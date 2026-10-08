from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, text, update

from app.integrations.tiktok import chunks
from app.models import AuditLog, ConnectedAccount, Publication, PublicationEvent
from app.services.publishing import RetryLater
from tests.conftest import make_account, make_media
from tests.fake_tiktok import UPLOAD_URL, api_error, ok


@pytest.fixture
async def ctx(sessions, crypto, settings, user, media_dir):
    account = await make_account(sessions, crypto, user.id)
    media = await make_media(sessions, settings, user.id, size_payload=3000)
    return account, media


async def new_pub(sessions, user, account, media, **kw) -> Publication:
    values = dict(user_id=user.id, account_id=account.id, media_id=media.id, idempotency_key=f"k-{uuid.uuid4()}",
                  privacy_level="SELF_ONLY", title="Hi #qadam", mode="DIRECT_POST", status="QUEUED")
    values.update(kw)
    async with sessions() as db:
        pub = Publication(**values)
        db.add(pub)
        await db.commit()
        return pub


async def reload(sessions, pub_id) -> Publication:
    async with sessions() as db:
        return (await db.execute(select(Publication).where(Publication.id == pub_id)
                                 .execution_options(populate_existing=True))).scalar_one()


async def events(sessions, pub_id) -> list[PublicationEvent]:
    async with sessions() as db:
        return list((await db.execute(select(PublicationEvent).where(PublicationEvent.publication_id == pub_id)
                                      .order_by(PublicationEvent.created_at))).scalars())


# ------------------------------------------------------------- happy path
async def test_direct_post_end_to_end(workflow, sessions, user, ctx, tiktok_mock, dispatcher, crypto):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media, disable_comment=False, cover_timestamp_ms=500)
    assert await workflow.run_publish(pub.id) == "uploaded"

    row = await reload(sessions, pub.id)
    assert row.status == "PROCESSING" and row.tiktok_publish_id.startswith("v_pub_file")
    assert row.uploaded_bytes == media.size_bytes and row.attempts == 1 and row.started_at
    assert crypto.decrypt(row.upload_url_enc) == UPLOAD_URL and "s3cr3t" not in row.upload_url_enc
    post_info = tiktok_mock.last_init_body["post_info"]
    assert post_info["title"] == "Hi #qadam" and post_info["privacy_level"] == "SELF_ONLY"
    assert post_info["disable_comment"] is False and post_info["video_cover_timestamp_ms"] == 500
    assert tiktok_mock.uploaded[0][:3] == (0, media.size_bytes - 1, media.size_bytes)
    assert dispatcher.calls[-1][0] == "poll"

    assert await workflow.poll_status(pub.id) == "processing"      # PROCESSING_UPLOAD
    assert dispatcher.calls[-1][0] == "poll" and dispatcher.calls[-1][2] >= 10
    assert await workflow.poll_status(pub.id) == "published"       # PUBLISH_COMPLETE
    done = await reload(sessions, pub.id)
    assert done.status == "PUBLISHED" and done.tiktok_post_ids == ["7300000000000000001"] and done.finished_at
    path = [(e.from_status, e.to_status) for e in await events(sessions, pub.id) if e.type == "status_changed"]
    assert path == [("QUEUED", "INITIATING"), ("INITIATING", "UPLOADING"), ("UPLOADING", "PROCESSING"),
                    ("PROCESSING", "PUBLISHED")]
    assert tiktok_mock.init_count == 1


async def test_large_video_is_uploaded_in_sequential_chunks(workflow, sessions, user, crypto, settings, tiktok_mock, monkeypatch):
    monkeypatch.setattr(chunks, "SINGLE_REQUEST_LIMIT", 10_000)
    monkeypatch.setattr(chunks, "DEFAULT_CHUNK", 8_000)
    account = await make_account(sessions, crypto, user.id)
    media = await make_media(sessions, settings, user.id, size_payload=30_000)
    pub = await new_pub(sessions, user, account, media)
    await workflow.run_publish(pub.id)

    size = media.size_bytes
    plan = chunks.plan_chunks(size)
    assert plan.total_chunks == size // 8_000 >= 3
    body = tiktok_mock.last_init_body["source_info"]
    assert body == {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": 8_000, "total_chunk_count": plan.total_chunks}
    sent = [(f, l) for f, l, _t, _h in tiktok_mock.uploaded]
    assert sent == plan.ranges()  # in order, contiguous, last chunk absorbs the remainder
    assert (await reload(sessions, pub.id)).uploaded_bytes == size


async def test_inbox_mode_uses_inbox_endpoint_and_ends_in_inbox(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media, mode="UPLOAD_TO_INBOX")
    tiktok_mock.status_sequence = [{"status": "SEND_TO_USER_INBOX"}]
    await workflow.run_publish(pub.id)
    assert tiktok_mock.count("inbox_init") == 1 and tiktok_mock.count("video_init") == 0
    assert tiktok_mock.count("creator_info") == 0  # not needed for inbox uploads
    assert await workflow.poll_status(pub.id) == "inbox"
    assert (await reload(sessions, pub.id)).status == "INBOX_DELIVERED"


# --------------------------------------------------- duplicate protection
async def test_parallel_duplicate_tasks_call_init_once(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media)
    results = await asyncio.gather(*[workflow.run_publish(pub.id) for _ in range(5)])
    assert tiktok_mock.init_count == 1
    assert results.count("uploaded") == 1
    assert len(tiktok_mock.uploaded) == 1


async def test_redelivered_task_after_success_is_a_noop(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media)
    await workflow.run_publish(pub.id)
    assert await workflow.run_publish(pub.id) == "noop"           # PROCESSING
    await workflow.poll_status(pub.id)
    await workflow.poll_status(pub.id)
    assert await workflow.run_publish(pub.id) == "noop"           # PUBLISHED
    assert tiktok_mock.init_count == 1 and len(tiktok_mock.uploaded) == 1


async def test_worker_crash_during_init_never_causes_a_second_post(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    # simulates a worker that died right after marking INITIATING (lease expired, no publish_id stored)
    pub = await new_pub(sessions, user, account, media, status="INITIATING",
                        lease_until=datetime.now(UTC) - timedelta(minutes=1))
    assert await workflow.run_publish(pub.id) == "needs_review"
    row = await reload(sessions, pub.id)
    assert row.status == "NEEDS_REVIEW" and row.fail_reason == "init_uncertain"
    assert tiktok_mock.init_count == 0


async def test_live_lease_makes_concurrent_task_back_off(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media, status="INITIATING",
                        lease_until=datetime.now(UTC) + timedelta(minutes=2))
    assert await workflow.run_publish(pub.id) == "busy"
    assert (await reload(sessions, pub.id)).status == "INITIATING" and tiktok_mock.init_count == 0


async def test_cancelled_publication_is_never_sent(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media, status="CANCELLED")
    assert await workflow.run_publish(pub.id) == "noop" and not tiktok_mock.calls


async def test_unknown_publication_is_ignored(workflow, tiktok_mock):
    assert await workflow.run_publish(uuid.uuid4()) == "missing"
    assert await workflow.poll_status(uuid.uuid4()) == "missing"


# ----------------------------------------------------- transient failures
async def test_connection_refused_on_init_is_retried_without_duplicate(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media)
    tiktok_mock.push("video_init", httpx.ConnectError("refused"))
    with pytest.raises(RetryLater):
        await workflow.run_publish(pub.id)
    row = await reload(sessions, pub.id)
    assert row.status == "QUEUED" and row.lease_until is None
    assert await workflow.run_publish(pub.id) == "uploaded"
    assert tiktok_mock.init_count == 1


async def test_ambiguous_timeout_on_init_requires_manual_review(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media)
    tiktok_mock.push("video_init", httpx.ReadTimeout("no response"))
    assert await workflow.run_publish(pub.id) == "needs_review"
    row = await reload(sessions, pub.id)
    assert row.status == "NEEDS_REVIEW" and row.fail_reason == "init_uncertain"
    assert await workflow.run_publish(pub.id) == "noop"           # a redelivery must not re-init
    assert tiktok_mock.count("video_init") == 1


async def test_5xx_on_init_is_retried(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media)
    tiktok_mock.push("video_init", httpx.Response(503))
    with pytest.raises(RetryLater) as exc:
        await workflow.run_publish(pub.id)
    assert exc.value.countdown > 0
    assert (await reload(sessions, pub.id)).status == "QUEUED"
    assert await workflow.run_publish(pub.id) == "uploaded"


async def test_rate_limit_on_init_honours_retry_after(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media)
    tiktok_mock.push("video_init", api_error("rate_limit_exceeded", 429, headers={"Retry-After": "37"}))
    with pytest.raises(RetryLater) as exc:
        await workflow.run_publish(pub.id)
    assert exc.value.countdown == 37
    assert (await reload(sessions, pub.id)).status == "QUEUED"


async def test_local_rate_budget_defers_instead_of_calling_tiktok(workflow, sessions, user, ctx, tiktok_mock, redis):
    account, media = ctx
    import time
    window = int(time.time() // 60)
    await redis.set(f"tt:rl:video_init:{account.id}:{window}", 99)
    pub = await new_pub(sessions, user, account, media)
    with pytest.raises(RetryLater) as exc:
        await workflow.run_publish(pub.id)
    assert 1 <= exc.value.countdown <= 61 and tiktok_mock.count("video_init") == 0


async def test_upload_resumes_from_last_confirmed_chunk(workflow, sessions, user, crypto, settings, tiktok_mock, monkeypatch):
    monkeypatch.setattr(chunks, "SINGLE_REQUEST_LIMIT", 10_000)
    monkeypatch.setattr(chunks, "DEFAULT_CHUNK", 8_000)
    account = await make_account(sessions, crypto, user.id)
    media = await make_media(sessions, settings, user.id, size_payload=30_000)
    pub = await new_pub(sessions, user, account, media)
    # chunk 1 succeeds, chunk 2 fails three times in a row (all in-task attempts)
    tiktok_mock.push("upload", httpx.Response(206), *[httpx.Response(502)] * 3)
    with pytest.raises(RetryLater):
        await workflow.run_publish(pub.id)
    row = await reload(sessions, pub.id)
    assert row.status == "UPLOADING" and row.uploaded_bytes == 8_000 and row.lease_until is None
    assert await workflow.run_publish(pub.id) == "uploaded"       # redelivery resumes, no new init
    assert tiktok_mock.init_count == 1
    starts = [f for f, _l, _t, _h in tiktok_mock.uploaded]
    assert starts[0] == 8_000  # chunk 1 was never re-sent after resume


async def test_single_chunk_5xx_is_retried_in_place(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media)
    tiktok_mock.push("upload", httpx.Response(500))
    assert await workflow.run_publish(pub.id) == "uploaded"
    assert tiktok_mock.count("upload") == 2


async def test_range_mismatch_resyncs_to_server_progress(workflow, sessions, user, crypto, settings, tiktok_mock, monkeypatch):
    """Chunk 2 reached TikTok but its response was lost: the retry gets 416 and must skip ahead, not loop."""
    monkeypatch.setattr(chunks, "SINGLE_REQUEST_LIMIT", 10_000)
    monkeypatch.setattr(chunks, "DEFAULT_CHUNK", 8_000)
    account = await make_account(sessions, crypto, user.id)
    media = await make_media(sessions, settings, user.id, size_payload=30_000)
    pub = await new_pub(sessions, user, account, media)
    tiktok_mock.push("upload", httpx.Response(206), httpx.Response(416, headers={"Content-Range": "bytes 0-15999/31000"}))
    assert await workflow.run_publish(pub.id) == "uploaded"
    sent = [f for f, _l, _t, _h in tiktok_mock.uploaded]
    assert sent == [16_000]  # forced 206 for chunk 1 and the 416 for chunk 2 are not recorded; 8_000 never re-sent
    assert (await reload(sessions, pub.id)).status == "PROCESSING"


async def test_unexplained_range_mismatch_fails_instead_of_looping(workflow, sessions, user, crypto, settings, tiktok_mock, monkeypatch):
    monkeypatch.setattr(chunks, "SINGLE_REQUEST_LIMIT", 10_000)
    monkeypatch.setattr(chunks, "DEFAULT_CHUNK", 8_000)
    account = await make_account(sessions, crypto, user.id)
    media = await make_media(sessions, settings, user.id, size_payload=30_000)
    pub = await new_pub(sessions, user, account, media)
    tiktok_mock.push("upload", httpx.Response(206), httpx.Response(416, headers={"Content-Range": "bytes 0-7999/31000"}))
    assert await workflow.run_publish(pub.id) == "failed"
    assert (await reload(sessions, pub.id)).fail_reason == "upload_offset_mismatch"


async def test_expired_upload_url_fails_with_clear_reason(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media)
    tiktok_mock.push("upload", httpx.Response(403))
    assert await workflow.run_publish(pub.id) == "failed"
    row = await reload(sessions, pub.id)
    assert row.fail_reason == "upload_url_expired" and "истекла" in row.fail_message


# ----------------------------------------------------- permanent failures
async def test_unaudited_client_error_is_surfaced(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media)
    tiktok_mock.push("video_init", api_error("unaudited_client_can_only_post_to_private_accounts", 403))
    assert await workflow.run_publish(pub.id) == "failed"
    row = await reload(sessions, pub.id)
    assert row.status == "FAILED" and "аудит" in row.fail_message
    assert row.fail_reason == "unaudited_client_can_only_post_to_private_accounts"


async def test_privacy_option_removed_after_queueing_fails_before_init(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media)
    tiktok_mock.creator["privacy_level_options"] = ["FOLLOWER_OF_CREATOR"]
    assert await workflow.run_publish(pub.id) == "failed"
    assert (await reload(sessions, pub.id)).fail_reason == "privacy_not_allowed" and tiktok_mock.init_count == 0


async def test_daily_post_cap_from_creator_info(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media)
    tiktok_mock.push("creator_info", httpx.Response(200, json={"error": {"code": "spam_risk_too_many_posts", "message": "", "log_id": "x"}}))
    assert await workflow.run_publish(pub.id) == "failed"
    assert "лимит" in (await reload(sessions, pub.id)).fail_message


async def test_revoked_account_fails_without_calling_tiktok(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    async with sessions() as db:
        await db.execute(update(ConnectedAccount).values(status="needs_reauth"))
        await db.commit()
    pub = await new_pub(sessions, user, account, media)
    assert await workflow.run_publish(pub.id) == "failed"
    assert (await reload(sessions, pub.id)).fail_reason == "account_inactive" and not tiktok_mock.calls


async def test_missing_scope_fails(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    async with sessions() as db:
        await db.execute(update(ConnectedAccount).values(scopes=["user.info.basic"]))
        await db.commit()
    pub = await new_pub(sessions, user, account, media)
    assert await workflow.run_publish(pub.id) == "failed"
    assert (await reload(sessions, pub.id)).fail_reason == "scope_missing"


async def test_missing_video_file_fails(workflow, sessions, user, ctx, settings, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media)
    tiktok_mock.push("upload", httpx.Response(206))  # unused; file vanishes after init
    (settings.media_dir / media.storage_name).unlink()
    assert await workflow.run_publish(pub.id) == "failed"
    assert (await reload(sessions, pub.id)).fail_reason == "media_missing"


async def test_expired_access_token_is_refreshed_before_publishing(workflow, sessions, user, ctx, tiktok_mock, crypto):
    account, media = ctx
    async with sessions() as db:
        await db.execute(update(ConnectedAccount).values(access_expires_at=datetime.now(UTC) + timedelta(seconds=30)))
        await db.commit()
    pub = await new_pub(sessions, user, account, media)
    assert await workflow.run_publish(pub.id) == "uploaded"
    assert tiktok_mock.refresh_count == 1


async def test_token_revoked_mid_flight_marks_reauth(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    tiktok_mock.reject_all = True
    pub = await new_pub(sessions, user, account, media)
    assert await workflow.run_publish(pub.id) == "failed"
    assert (await reload(sessions, pub.id)).fail_reason == "reauth_required"
    async with sessions() as db:
        assert (await db.get(ConnectedAccount, account.id)).status == "needs_reauth"


# --------------------------------------------------------------- polling
@pytest.mark.parametrize("reason,fragment", [
    ("file_format_check_failed", "Формат"), ("duration_check_failed", "Длительность"),
    ("frame_rate_check_failed", "кадров"), ("picture_size_check_failed", "Разрешение"),
    ("spam_risk_text", "спам"), ("auth_removed", "отозвал"), ("some_new_reason", "не смог"),
])
async def test_tiktok_failure_reasons_are_translated(workflow, sessions, user, ctx, tiktok_mock, reason, fragment):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media)
    tiktok_mock.status_sequence = [{"status": "FAILED", "fail_reason": reason}]
    await workflow.run_publish(pub.id)
    assert await workflow.poll_status(pub.id) == "failed"
    row = await reload(sessions, pub.id)
    assert row.status == "FAILED" and row.fail_reason == reason and fragment in row.fail_message


async def test_poll_backoff_grows(workflow, sessions, user, ctx, tiktok_mock, dispatcher):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media)
    tiktok_mock.status_sequence = [{"status": "PROCESSING_UPLOAD"}]
    await workflow.run_publish(pub.id)
    delays = []
    for _ in range(4):
        await workflow.poll_status(pub.id)
        delays.append(dispatcher.calls[-1][2])
    assert delays == sorted(delays) and delays[-1] > delays[0] and max(delays) <= 300


async def test_poll_transient_errors_ask_for_retry_and_keep_state(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media)
    await workflow.run_publish(pub.id)
    tiktok_mock.push("status", httpx.Response(500), api_error("rate_limit_exceeded", 429, headers={"Retry-After": "12"}))
    with pytest.raises(RetryLater):
        await workflow.poll_status(pub.id)
    with pytest.raises(RetryLater) as exc:
        await workflow.poll_status(pub.id)
    assert exc.value.countdown == 12
    assert (await reload(sessions, pub.id)).status == "PROCESSING"


async def test_poll_after_access_lost_needs_review(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media)
    await workflow.run_publish(pub.id)
    tiktok_mock.reject_all = True
    assert await workflow.poll_status(pub.id) == "needs_review"
    assert (await reload(sessions, pub.id)).fail_reason == "auth_lost"


async def test_poll_gives_up_after_deadline(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media)
    tiktok_mock.status_sequence = [{"status": "PROCESSING_UPLOAD"}]
    await workflow.run_publish(pub.id)
    async with sessions() as db:
        await db.execute(update(Publication).values(started_at=datetime.now(UTC) - timedelta(hours=7)))
        await db.commit()
    assert await workflow.poll_status(pub.id) == "needs_review"
    assert (await reload(sessions, pub.id)).fail_reason == "processing_timeout"


async def test_polling_a_finished_publication_does_nothing(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media, status="PUBLISHED")
    assert await workflow.poll_status(pub.id) == "noop" and not tiktok_mock.calls


# -------------------------------------------------- sweeper & exhaustion
async def test_sweeper_redispatches_lost_work(workflow, sessions, user, ctx, tiktok_mock, dispatcher):
    account, media = ctx
    old = datetime.now(UTC) - timedelta(minutes=10)
    queued = await new_pub(sessions, user, account, media)
    stale = await new_pub(sessions, user, account, media, status="UPLOADING", lease_until=old)
    polling = await new_pub(sessions, user, account, media, status="PROCESSING", next_poll_at=old,
                            tiktok_publish_id="v_pub_x")
    fresh = await new_pub(sessions, user, account, media)
    async with sessions() as db:
        await db.execute(update(Publication).where(Publication.id.in_([queued.id, stale.id, polling.id]))
                         .values(updated_at=old))
        await db.commit()
    counts = await workflow.sweep()
    assert counts == {"publish": 2, "poll": 1}
    assert {(k, pid) for k, pid, _ in dispatcher.calls} == {("publish", queued.id), ("publish", stale.id), ("poll", polling.id)}
    assert fresh.id not in {pid for _, pid, _ in dispatcher.calls}


async def test_retry_exhaustion_marks_failed_not_lost(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media)
    await workflow.fail_exhausted(pub.id, "TikTok недоступен")
    row = await reload(sessions, pub.id)
    assert row.status == "FAILED" and row.fail_reason == "retries_exhausted"
    processing = await new_pub(sessions, user, account, media, status="PROCESSING", tiktok_publish_id="x")
    await workflow.fail_exhausted(processing.id, "x")
    assert (await reload(sessions, processing.id)).status == "NEEDS_REVIEW"  # may still be live at TikTok


# ---------------------------------------------------------- secrecy
async def test_no_secret_is_persisted_in_events_or_audit(workflow, sessions, user, ctx, tiktok_mock):
    account, media = ctx
    pub = await new_pub(sessions, user, account, media)
    tiktok_mock.push("video_init", api_error("invalid_param", 400, "bad title"))
    await workflow.run_publish(pub.id)
    p2 = await new_pub(sessions, user, account, media)
    await workflow.run_publish(p2.id)
    await workflow.poll_status(p2.id)
    async with sessions() as db:
        blob = (await db.execute(text(
            "SELECT coalesce(string_agg(details::text || message, ' '), '') FROM publication_events"))).scalar_one()
        blob += (await db.execute(text("SELECT coalesce(string_agg(details::text, ' '), '') FROM audit_logs"))).scalar_one()
    for secret in ("s3cr3t", "acc-0", "ref-0", "test-client-secret-value", "upload_id=u1"):
        assert secret not in blob
