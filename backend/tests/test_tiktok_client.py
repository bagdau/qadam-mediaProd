from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.integrations.tiktok.chunks import plan_chunks
from app.integrations.tiktok.client import PostInfo
from app.integrations.tiktok.errors import (
    TikTokApiError,
    TikTokAuthError,
    TikTokOAuthError,
    TikTokRateLimited,
    TikTokScopeError,
    TikTokTransient,
    UploadOffsetMismatch,
    UploadUrlExpired,
)
from tests.fake_tiktok import API, GOOD_CODE, OPEN_ID, UPLOAD_URL, api_error, ok

POST = PostInfo(title="hi #tag", privacy_level="SELF_ONLY", disable_comment=True, disable_duet=True,
                disable_stitch=True)


def test_authorization_url_matches_login_kit_contract(tiktok_client):
    url = tiktok_client.authorization_url("STATE123")
    parsed = urlparse(url)
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://www.tiktok.com/v2/auth/authorize/"
    assert q["client_key"] == "test-client-key" and q["response_type"] == "code" and q["state"] == "STATE123"
    assert q["scope"] == "user.info.basic,video.publish,video.upload"
    assert q["redirect_uri"] == "https://qadam.test/oauth/tiktok/callback"
    assert "client_secret" not in url


async def test_exchange_code_returns_token_set(tiktok_client, tiktok_mock):
    tokens = await tiktok_client.exchange_code(GOOD_CODE)
    assert tokens.open_id == OPEN_ID and tokens.access_token == "acc-0"
    assert tokens.scopes == ["user.info.basic", "video.publish"]
    assert (tokens.access_expires_at - tokens.refresh_expires_at).days < 0
    assert "acc-0" not in repr(tokens)  # tokens must not leak through repr()


async def test_exchange_code_sends_form_with_server_side_secret(tiktok_client, tiktok_mock):
    await tiktok_client.exchange_code(GOOD_CODE)
    request = tiktok_mock.router.calls.last.request
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    form = parse_qs(request.content.decode())
    assert form["client_secret"] == ["test-client-secret-value"] and form["grant_type"] == ["authorization_code"]


async def test_invalid_code_raises_oauth_error_requiring_reauth(tiktok_client, tiktok_mock):
    with pytest.raises(TikTokOAuthError) as exc:
        await tiktok_client.exchange_code("expired")
    assert exc.value.code == "invalid_grant" and exc.value.requires_reauth


async def test_refresh_returns_rotated_tokens(tiktok_client, tiktok_mock):
    tokens = await tiktok_client.refresh("ref-0")
    assert tokens.access_token == "acc-1" and tokens.refresh_token == "ref-1"


async def test_revoke_accepts_empty_body(tiktok_client, tiktok_mock):
    await tiktok_client.revoke("acc-0")
    assert tiktok_mock.count("revoke") == 1


async def test_user_info(tiktok_client, tiktok_mock):
    info = await tiktok_client.user_info("acc-0")
    assert info["display_name"] == "Test Creator"


async def test_creator_info_parsed(tiktok_client, tiktok_mock):
    info = await tiktok_client.creator_info("acc-0")
    assert info.nickname == "Test Creator" and info.max_video_post_duration_sec == 600
    assert "SELF_ONLY" in info.privacy_level_options and not info.comment_disabled


async def test_invalid_access_token_maps_to_auth_error(tiktok_client, tiktok_mock):
    with pytest.raises(TikTokAuthError):
        await tiktok_client.creator_info("stale-token")


async def test_missing_scope(tiktok_client, tiktok_mock):
    tiktok_mock.push("creator_info", api_error("scope_not_authorized", 401))
    with pytest.raises(TikTokScopeError):
        await tiktok_client.creator_info("acc-0")


@pytest.mark.parametrize("response", [
    api_error("rate_limit_exceeded", 429, headers={"Retry-After": "42"}),
    httpx.Response(429, json={}, headers={"Retry-After": "42"}),
])
async def test_rate_limit_carries_retry_after(tiktok_client, tiktok_mock, response):
    tiktok_mock.push("creator_info", response)
    with pytest.raises(TikTokRateLimited) as exc:
        await tiktok_client.creator_info("acc-0")
    assert exc.value.retry_after == 42


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_5xx_is_transient(tiktok_client, tiktok_mock, status):
    tiktok_mock.push("creator_info", httpx.Response(status, text="boom"))
    with pytest.raises(TikTokTransient):
        await tiktok_client.creator_info("acc-0")


async def test_network_errors_are_transient_and_flag_whether_request_was_sent(tiktok_client, tiktok_mock):
    tiktok_mock.push("video_init", httpx.ConnectError("refused"), httpx.ReadTimeout("slow"))
    plan = plan_chunks(1000)
    with pytest.raises(TikTokTransient) as not_sent:
        await tiktok_client.init_direct_post("acc-0", POST, plan)
    assert not_sent.value.maybe_sent is False
    with pytest.raises(TikTokTransient) as maybe:
        await tiktok_client.init_direct_post("acc-0", POST, plan)
    assert maybe.value.maybe_sent is True


@pytest.mark.parametrize("code,message_part", [
    ("unaudited_client_can_only_post_to_private_accounts", "аудит"),
    ("spam_risk_too_many_posts", "лимит"),
    ("privacy_level_option_mismatch", "приватности"),
    ("invalid_param", "параметры"),
])
async def test_permanent_api_errors_have_friendly_messages(tiktok_client, tiktok_mock, code, message_part):
    tiktok_mock.push("video_init", api_error(code, 403))
    with pytest.raises(TikTokApiError) as exc:
        await tiktok_client.init_direct_post("acc-0", POST, plan_chunks(1000))
    assert exc.value.code == code and message_part in exc.value.message


async def test_spam_risk_returned_with_http_200_is_still_an_error(tiktok_client, tiktok_mock):
    tiktok_mock.push("creator_info", httpx.Response(200, json={"error": {"code": "spam_risk_too_many_posts", "message": "", "log_id": "x"}}))
    with pytest.raises(TikTokApiError):
        await tiktok_client.creator_info("acc-0")


async def test_direct_post_request_body_follows_documented_shape(tiktok_client, tiktok_mock):
    plan = plan_chunks(5000)
    result = await tiktok_client.init_direct_post("acc-0", POST, plan)
    body = tiktok_mock.last_init_body
    assert body["source_info"] == {"source": "FILE_UPLOAD", "video_size": 5000, "chunk_size": 5000, "total_chunk_count": 1}
    assert body["post_info"]["privacy_level"] == "SELF_ONLY" and body["post_info"]["title"] == "hi #tag"
    assert body["post_info"]["disable_comment"] is True
    assert {"brand_content_toggle", "brand_organic_toggle", "is_aigc", "video_cover_timestamp_ms"} <= set(body["post_info"])
    assert result.publish_id.startswith("v_pub_file") and result.upload_url == UPLOAD_URL
    assert "UPLOAD_URL" not in repr(result) and "s3cr3t" not in repr(result)


async def test_inbox_init_has_no_post_info(tiktok_client, tiktok_mock):
    await tiktok_client.init_inbox_upload("acc-0", plan_chunks(5000))
    assert "post_info" not in tiktok_mock.last_init_body


async def test_init_without_publish_id_is_rejected(tiktok_client, tiktok_mock):
    tiktok_mock.push("video_init", ok({"upload_url": UPLOAD_URL}))
    with pytest.raises(TikTokApiError):
        await tiktok_client.init_direct_post("acc-0", POST, plan_chunks(10))


async def test_upload_chunk_sends_range_headers_and_streams_file(tiktok_client, tiktok_mock, tmp_path):
    f = tmp_path / "v.bin"
    data = bytes(range(256)) * 40
    f.write_bytes(data)
    assert await tiktok_client.upload_chunk(UPLOAD_URL, f, 0, 4999, len(data), "video/mp4") == 206
    assert await tiktok_client.upload_chunk(UPLOAD_URL, f, 5000, len(data) - 1, len(data), "video/mp4") == 201
    first, last, total, headers = tiktok_mock.uploaded[0]
    assert (first, last, total) == (0, 4999, len(data))
    assert headers["content-range"] == f"bytes 0-4999/{len(data)}" and headers["content-type"] == "video/mp4"


@pytest.mark.parametrize("status,exc_type", [(403, UploadUrlExpired), (404, UploadUrlExpired),
                                              (500, TikTokTransient), (503, TikTokTransient),
                                              (400, TikTokApiError), (429, TikTokRateLimited)])
async def test_upload_error_mapping(tiktok_client, tiktok_mock, tmp_path, status, exc_type):
    f = tmp_path / "v.bin"
    f.write_bytes(b"x" * 100)
    tiktok_mock.push("upload", httpx.Response(status))
    with pytest.raises(exc_type):
        await tiktok_client.upload_chunk(UPLOAD_URL, f, 0, 99, 100, "video/mp4")


async def test_upload_416_reports_server_side_progress(tiktok_client, tiktok_mock, tmp_path):
    f = tmp_path / "v.bin"
    f.write_bytes(b"x" * 100)
    tiktok_mock.push("upload", httpx.Response(416, headers={"Content-Range": "bytes 0-49/100"}))
    with pytest.raises(UploadOffsetMismatch) as exc:
        await tiktok_client.upload_chunk(UPLOAD_URL, f, 50, 99, 100, "video/mp4")
    assert exc.value.uploaded_bytes == 50


async def test_fetch_status(tiktok_client, tiktok_mock):
    tiktok_mock.push("status", ok({"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [123]}))
    status = await tiktok_client.fetch_status("acc-0", "pub-1")
    assert status.status == "PUBLISH_COMPLETE" and status.post_ids == ["123"]
    tiktok_mock.push("status", ok({"status": "FAILED", "fail_reason": "file_format_check_failed"}))
    failed = await tiktok_client.fetch_status("acc-0", "pub-1")
    assert failed.fail_reason == "file_format_check_failed"
    assert tiktok_mock.calls[0][1] == {"publish_id": "pub-1"}


async def test_client_does_not_log_tokens(tiktok_client, tiktok_mock, caplog):
    caplog.set_level("DEBUG")
    await tiktok_client.exchange_code(GOOD_CODE)
    await tiktok_client.creator_info("acc-0")
    assert "acc-0" not in caplog.text and "ref-0" not in caplog.text and "test-client-secret-value" not in caplog.text
    assert API.startswith("https://")


async def test_http_upload_url_is_refused_in_production(settings, tiktok_mock):
    from app.integrations.tiktok.client import TikTokClient

    tiktok_mock.push("video_init", ok({"publish_id": "p1", "upload_url": "http://upload.tiktokapis.test/x"}))
    prod = settings.model_copy(update={"environment": "production"})
    async with TikTokClient(prod) as client:
        with pytest.raises(TikTokApiError) as exc:
            await client.init_direct_post("acc-0", POST, plan_chunks(10))
    assert exc.value.code == "insecure_upload_url"
