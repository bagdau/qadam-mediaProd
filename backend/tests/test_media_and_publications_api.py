from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import MediaAsset, Publication, PublicationEvent
from tests.conftest import login, make_account, make_media, make_user
from tests.helpers import make_mp4, make_webm

API = "/api/v1"


def upload_files(content: bytes, name: str = "clip.mp4", mime: str = "video/mp4"):
    return {"video": (name, content, mime)}


# ------------------------------------------------------------------- media
async def test_upload_valid_mp4(authed, media_dir):
    r = await authed.post(f"{API}/media", files=upload_files(make_mp4(42.0, 10_000)))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["content_type"] == "video/mp4" and body["duration_seconds"] == 42.0
    assert body["size_bytes"] > 10_000 and len(body["sha256"]) == 64
    stored = list(media_dir.glob("*.mp4"))
    assert len(stored) == 1 and stored[0].stat().st_size == body["size_bytes"]
    assert not list(media_dir.glob(".upload-*"))  # no temp leftovers


async def test_upload_webm_uses_client_duration(authed):
    r = await authed.post(f"{API}/media", files=upload_files(make_webm(), "a.webm", "video/webm"),
                          data={"duration_seconds": "9.5"})
    assert r.status_code == 201 and r.json()["content_type"] == "video/webm" and r.json()["duration_seconds"] == 9.5


async def test_declared_type_is_ignored_content_is_inspected(authed, media_dir):
    r = await authed.post(f"{API}/media", files=upload_files(b"MZ\x90\x00" + b"\x00" * 600, "evil.mp4", "video/mp4"))
    assert r.status_code == 415
    assert not [p for p in media_dir.glob("*") if p.name != ".tmp"]  # nothing left behind (the spool dir is permanent)


async def test_html_and_empty_uploads_rejected(authed):
    assert (await authed.post(f"{API}/media", files=upload_files(b"<script>1</script>", "x.mp4"))).status_code == 415
    assert (await authed.post(f"{API}/media", files=upload_files(b"", "x.mp4"))).status_code == 422


async def test_oversized_upload_rejected_and_cleaned(authed, media_dir):
    big = make_mp4(5, payload_size=9 * 1024 * 1024)  # MAX_VIDEO_MB=8 in tests
    r = await authed.post(f"{API}/media", files=upload_files(big))
    assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"
    assert not [p for p in media_dir.glob("*") if p.name != ".tmp"]  # nothing left behind (the spool dir is permanent)


async def test_hostile_filename_cannot_escape_media_dir(authed, media_dir, sessions):
    r = await authed.post(f"{API}/media", files=upload_files(make_mp4(), "../../../../etc/passwd.mp4"))
    assert r.status_code == 201
    assert r.json()["original_filename"] == "passwd.mp4"
    async with sessions() as db:
        asset = (await db.execute(select(MediaAsset))).scalar_one()
    assert (media_dir / asset.storage_name).exists() and ".." not in asset.storage_name


async def test_upload_requires_auth_and_csrf(client, user):
    assert (await client.post(f"{API}/media", files=upload_files(make_mp4()))).status_code == 401
    await login(client)
    client.csrf = None
    assert (await client.post(f"{API}/media", files=upload_files(make_mp4()))).status_code == 403


async def test_media_isolated_between_users(authed, sessions, settings):
    other = await make_user(sessions, "o@example.com")
    foreign = await make_media(sessions, settings, other.id)
    assert (await authed.get(f"{API}/media/{foreign.id}")).status_code == 404
    assert (await authed.delete(f"{API}/media/{foreign.id}")).status_code == 404
    assert (await authed.get(f"{API}/media")).json() == []


async def test_delete_removes_file(authed, user, sessions, settings):
    m = await make_media(sessions, settings, user.id)
    path = settings.media_dir / m.storage_name
    assert path.exists()
    assert (await authed.delete(f"{API}/media/{m.id}")).status_code == 204
    assert not path.exists()
    assert (await authed.get(f"{API}/media/{m.id}")).status_code == 404


# ------------------------------------------------------------ publications
def body(account, media, **kw):
    data = dict(account_id=str(account.id), media_id=str(media.id), title="Hello #qadam", privacy_level="SELF_ONLY",
                music_usage_confirmed=True)
    data.update(kw)
    return data


def key() -> dict:
    return {"Idempotency-Key": f"test-{uuid.uuid4()}"}


async def setup_ready(authed, sessions, crypto, settings, user, **media_kw):
    account = await make_account(sessions, crypto, user.id)
    media = await make_media(sessions, settings, user.id, **media_kw)
    return account, media


async def test_create_publication_queues_work(authed, sessions, crypto, settings, user, dispatcher, tiktok_mock):
    account, media = await setup_ready(authed, sessions, crypto, settings, user)
    r = await authed.post(f"{API}/publications", json=body(account, media, allow_comment=True), headers=key())
    assert r.status_code == 201, r.text
    pub = r.json()
    assert pub["status"] == "QUEUED" and pub["disable_comment"] is False
    assert pub["disable_duet"] is True and pub["disable_stitch"] is True  # off unless explicitly enabled
    assert dispatcher.calls == [("publish", uuid.UUID(pub["id"]), 0)]
    async with sessions() as db:
        events = (await db.execute(select(PublicationEvent))).scalars().all()
    assert [e.type for e in events] == ["created"]


async def test_same_idempotency_key_returns_original(authed, sessions, crypto, settings, user, dispatcher, tiktok_mock):
    account, media = await setup_ready(authed, sessions, crypto, settings, user)
    headers = key()
    first = await authed.post(f"{API}/publications", json=body(account, media), headers=headers)
    second = await authed.post(f"{API}/publications", json=body(account, media), headers=headers)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    assert len(dispatcher.calls) == 1
    async with sessions() as db:
        assert len((await db.execute(select(Publication))).scalars().all()) == 1


async def test_concurrent_double_submit_creates_one_publication(authed, sessions, crypto, settings, user, dispatcher, tiktok_mock):
    import asyncio

    account, media = await setup_ready(authed, sessions, crypto, settings, user)
    headers = key()
    results = await asyncio.gather(*[authed.post(f"{API}/publications", json=body(account, media), headers=headers) for _ in range(5)])
    assert {r.status_code for r in results} <= {200, 201, 409}
    async with sessions() as db:
        assert len((await db.execute(select(Publication))).scalars().all()) == 1


async def test_idempotency_key_is_required(authed, sessions, crypto, settings, user, tiktok_mock):
    account, media = await setup_ready(authed, sessions, crypto, settings, user)
    r = await authed.post(f"{API}/publications", json=body(account, media))
    assert r.status_code == 422 and r.json()["error"]["code"] == "idempotency_key_required"
    r = await authed.post(f"{API}/publications", json=body(account, media), headers={"Idempotency-Key": "x"})
    assert r.status_code == 422


async def test_duplicate_publication_of_same_video_is_blocked(authed, sessions, crypto, settings, user, tiktok_mock):
    account, media = await setup_ready(authed, sessions, crypto, settings, user)
    assert (await authed.post(f"{API}/publications", json=body(account, media), headers=key())).status_code == 201
    dup = await authed.post(f"{API}/publications", json=body(account, media), headers=key())
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "duplicate_publication"
    allowed = await authed.post(f"{API}/publications", json=body(account, media, allow_duplicate=True), headers=key())
    assert allowed.status_code == 201


async def test_privacy_must_be_offered_by_creator_info(authed, sessions, crypto, settings, user, tiktok_mock):
    account, media = await setup_ready(authed, sessions, crypto, settings, user)
    tiktok_mock.creator["privacy_level_options"] = ["SELF_ONLY"]
    r = await authed.post(f"{API}/publications", json=body(account, media, privacy_level="PUBLIC_TO_EVERYONE"), headers=key())
    assert r.status_code == 422 and r.json()["error"]["code"] == "privacy_not_allowed"


async def test_unaudited_app_is_limited_to_self_only(authed, sessions, crypto, settings, user, tiktok_mock):
    account, media = await setup_ready(authed, sessions, crypto, settings, user)
    r = await authed.post(f"{API}/publications", json=body(account, media, privacy_level="PUBLIC_TO_EVERYONE"), headers=key())
    assert r.status_code == 422 and r.json()["error"]["code"] == "unaudited_private_only"


async def test_audited_app_may_publish_publicly(authed, sessions, crypto, settings, user, tiktok_mock, monkeypatch):
    monkeypatch.setattr(settings, "tiktok_client_audited", True)
    account, media = await setup_ready(authed, sessions, crypto, settings, user)
    r = await authed.post(f"{API}/publications", json=body(account, media, privacy_level="PUBLIC_TO_EVERYONE"), headers=key())
    assert r.status_code == 201


async def test_branded_content_cannot_be_private(authed, sessions, crypto, settings, user, tiktok_mock):
    account, media = await setup_ready(authed, sessions, crypto, settings, user)
    r = await authed.post(f"{API}/publications", json=body(account, media, brand_content_toggle=True), headers=key())
    assert r.status_code == 422 and r.json()["error"]["code"] == "branded_private"


async def test_interactions_disabled_by_creator_cannot_be_enabled(authed, sessions, crypto, settings, user, tiktok_mock):
    account, media = await setup_ready(authed, sessions, crypto, settings, user)
    tiktok_mock.creator.update(comment_disabled=True, duet_disabled=True, stitch_disabled=True)
    for flag, code in (("allow_comment", "comment_disabled"), ("allow_duet", "duet_disabled"), ("allow_stitch", "stitch_disabled")):
        r = await authed.post(f"{API}/publications", json=body(account, media, **{flag: True}), headers=key())
        assert r.status_code == 422 and r.json()["error"]["code"] == code
    assert (await authed.post(f"{API}/publications", json=body(account, media), headers=key())).status_code == 201


async def test_video_longer_than_creator_limit_rejected(authed, sessions, crypto, settings, user, tiktok_mock):
    account, media = await setup_ready(authed, sessions, crypto, settings, user, duration=700.0)
    r = await authed.post(f"{API}/publications", json=body(account, media), headers=key())
    assert r.status_code == 422 and r.json()["error"]["code"] == "video_too_long"


async def test_music_usage_confirmation_is_mandatory_for_direct_post(authed, sessions, crypto, settings, user, tiktok_mock):
    account, media = await setup_ready(authed, sessions, crypto, settings, user)
    r = await authed.post(f"{API}/publications", json=body(account, media, music_usage_confirmed=False), headers=key())
    assert r.status_code == 422


async def test_privacy_has_no_default(authed, sessions, crypto, settings, user, tiktok_mock):
    account, media = await setup_ready(authed, sessions, crypto, settings, user)
    payload = body(account, media)
    del payload["privacy_level"]
    assert (await authed.post(f"{API}/publications", json=payload, headers=key())).status_code == 422


async def test_title_limit_counts_utf16_units(authed, sessions, crypto, settings, user, tiktok_mock):
    account, media = await setup_ready(authed, sessions, crypto, settings, user)
    r = await authed.post(f"{API}/publications", json=body(account, media, title="😀" * 1200), headers=key())
    assert r.status_code == 422  # 1200 code points = 2400 UTF-16 units
    assert (await authed.post(f"{API}/publications", json=body(account, media, title="😀" * 1000), headers=key())).status_code == 201


async def test_missing_scope_is_reported(authed, sessions, crypto, settings, user, tiktok_mock):
    account = await make_account(sessions, crypto, user.id, scopes=["user.info.basic"])
    media = await make_media(sessions, settings, user.id)
    r = await authed.post(f"{API}/publications", json=body(account, media), headers=key())
    assert r.status_code == 422 and r.json()["error"]["code"] == "scope_missing"


async def test_needs_reauth_account_cannot_publish(authed, sessions, crypto, settings, user, tiktok_mock):
    account = await make_account(sessions, crypto, user.id, status="needs_reauth")
    media = await make_media(sessions, settings, user.id)
    r = await authed.post(f"{API}/publications", json=body(account, media), headers=key())
    assert r.status_code == 409 and r.json()["error"]["code"] == "account_inactive"


async def test_cannot_publish_foreign_account_or_media(authed, sessions, crypto, settings, user, tiktok_mock):
    other = await make_user(sessions, "o@example.com")
    foreign_acc = await make_account(sessions, crypto, other.id)
    foreign_media = await make_media(sessions, settings, other.id)
    own_acc, own_media = await setup_ready(authed, sessions, crypto, settings, user)
    assert (await authed.post(f"{API}/publications", json=body(foreign_acc, own_media), headers=key())).status_code == 404
    assert (await authed.post(f"{API}/publications", json=body(own_acc, foreign_media), headers=key())).status_code == 404


async def test_tiktok_unavailable_during_create(authed, sessions, crypto, settings, user, tiktok_mock):
    import httpx

    account, media = await setup_ready(authed, sessions, crypto, settings, user)
    tiktok_mock.push("creator_info", httpx.Response(503))
    r = await authed.post(f"{API}/publications", json=body(account, media), headers=key())
    assert r.status_code == 503
    async with sessions() as db:
        assert (await db.execute(select(Publication))).first() is None


async def test_list_filter_and_pagination(authed, sessions, crypto, settings, user, tiktok_mock):
    account = await make_account(sessions, crypto, user.id)
    for i in range(3):
        media = await make_media(sessions, settings, user.id, size_payload=1000 + i)
        assert (await authed.post(f"{API}/publications", json=body(account, media), headers=key())).status_code == 201
    page = (await authed.get(f"{API}/publications", params={"limit": 2})).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    page2 = (await authed.get(f"{API}/publications", params={"limit": 2, "offset": 2})).json()
    assert len(page2["items"]) == 1
    assert (await authed.get(f"{API}/publications", params={"status": "PUBLISHED"})).json()["total"] == 0
    assert (await authed.get(f"{API}/publications", params={"status": "BOGUS"})).status_code == 422


async def test_detail_includes_events_and_is_private(authed, sessions, crypto, settings, user, tiktok_mock):
    account, media = await setup_ready(authed, sessions, crypto, settings, user)
    created = (await authed.post(f"{API}/publications", json=body(account, media), headers=key())).json()
    detail = (await authed.get(f"{API}/publications/{created['id']}")).json()
    assert detail["events"][0]["type"] == "created" and detail["media_filename"] == "clip.mp4"
    other = await make_user(sessions, "o@example.com")
    foreign_acc = await make_account(sessions, crypto, other.id)
    foreign_media = await make_media(sessions, settings, other.id)
    async with sessions() as db:
        foreign = Publication(user_id=other.id, account_id=foreign_acc.id, media_id=foreign_media.id,
                              idempotency_key="foreign-key-1", privacy_level="SELF_ONLY")
        db.add(foreign)
        await db.commit()
    assert (await authed.get(f"{API}/publications/{foreign.id}")).status_code == 404
    assert (await authed.post(f"{API}/publications/{foreign.id}/cancel")).status_code == 404


async def test_cancel_only_while_queued(authed, sessions, crypto, settings, user, tiktok_mock):
    account, media = await setup_ready(authed, sessions, crypto, settings, user)
    pid = (await authed.post(f"{API}/publications", json=body(account, media), headers=key())).json()["id"]
    assert (await authed.post(f"{API}/publications/{pid}/cancel")).json()["status"] == "CANCELLED"
    assert (await authed.post(f"{API}/publications/{pid}/cancel")).status_code == 409
    async with sessions() as db:
        busy = Publication(user_id=user.id, account_id=account.id, media_id=media.id, idempotency_key="busy-key-1",
                           privacy_level="SELF_ONLY", status="UPLOADING")
        db.add(busy)
        await db.commit()
    r = await authed.post(f"{API}/publications/{busy.id}/cancel")
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_cancellable"


async def test_retry_rules(authed, sessions, crypto, settings, user, dispatcher, tiktok_mock):
    account, media = await setup_ready(authed, sessions, crypto, settings, user)
    async with sessions() as db:
        failed = Publication(user_id=user.id, account_id=account.id, media_id=media.id, idempotency_key="failed-key-1",
                             privacy_level="SELF_ONLY", status="FAILED", fail_reason="x", tiktok_publish_id="old-id")
        review = Publication(user_id=user.id, account_id=account.id, media_id=media.id, idempotency_key="review-key-1",
                             privacy_level="SELF_ONLY", status="NEEDS_REVIEW", fail_reason="init_uncertain")
        done = Publication(user_id=user.id, account_id=account.id, media_id=media.id, idempotency_key="done-key-1",
                           privacy_level="SELF_ONLY", status="PUBLISHED")
        db.add_all([failed, review, done])
        await db.commit()
    assert (await authed.post(f"{API}/publications/{done.id}/retry")).json()["error"]["code"] == "not_retryable"
    risky = await authed.post(f"{API}/publications/{review.id}/retry")
    assert risky.status_code == 409 and risky.json()["error"]["code"] == "duplicate_risk"
    ok = await authed.post(f"{API}/publications/{review.id}/retry", json={"confirm_duplicate_risk": True})
    assert ok.status_code == 200 and ok.json()["status"] == "QUEUED"
    plain = await authed.post(f"{API}/publications/{failed.id}/retry")
    assert plain.status_code == 200 and plain.json()["tiktok_publish_id"] is None
    assert {c[1] for c in dispatcher.calls} == {review.id, failed.id}


async def test_dashboard_and_audit_endpoints(authed, sessions, crypto, settings, user, tiktok_mock):
    account, media = await setup_ready(authed, sessions, crypto, settings, user)
    await authed.post(f"{API}/publications", json=body(account, media), headers=key())
    dash = (await authed.get(f"{API}/dashboard")).json()
    assert dash["accounts_total"] == 1 and dash["publications_total"] == 1 and dash["in_progress"] == 1
    assert dash["recent"][0]["status"] == "QUEUED"
    logs = (await authed.get(f"{API}/audit-logs")).json()
    assert logs["total"] >= 2 and "publication.created" in {i["action"] for i in logs["items"]}
    meta = (await authed.get(f"{API}/meta")).json()
    assert meta["tiktok_client_audited"] is False and "video/mp4" in meta["allowed_content_types"]
