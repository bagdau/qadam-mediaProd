from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
from sqlalchemy import select, text, update

from app.integrations.tiktok.errors import TikTokTransient
from app.models import AuditLog, ConnectedAccount, OAuthState, Publication
from app.services.tiktok_accounts import ReauthRequired
from tests.conftest import login, make_account, make_media, make_user
from tests.fake_tiktok import GOOD_CODE, OPEN_ID, api_error

API = "/api/v1"


async def start(client) -> str:
    r = await client.post(f"{API}/tiktok/oauth/start")
    assert r.status_code == 200, r.text
    url = r.json()["authorization_url"]
    return parse_qs(urlparse(url).query)["state"][0]


async def callback(client, **params):
    return await client.get("/oauth/tiktok/callback", params=params)


# ---------------------------------------------------------------- authorise
async def test_start_requires_auth_and_csrf(client, user):
    assert (await client.post(f"{API}/tiktok/oauth/start")).status_code == 401
    await login(client)
    client.csrf = None
    assert (await client.post(f"{API}/tiktok/oauth/start")).status_code == 403


async def test_state_is_random_hashed_and_expiring(authed, sessions):
    s1, s2 = await start(authed), await start(authed)
    assert s1 != s2 and len(s1) >= 40
    async with sessions() as db:
        rows = (await db.execute(select(OAuthState))).scalars().all()
    assert len(rows) == 2
    assert all(s not in r.state_hash for r in rows for s in (s1, s2))
    assert all(timedelta(minutes=9) < r.expires_at - datetime.now(UTC) <= timedelta(minutes=10) for r in rows)


async def test_start_fails_cleanly_when_not_configured(authed, monkeypatch, settings):
    monkeypatch.setattr(settings, "tiktok_client_key", "")
    r = await authed.post(f"{API}/tiktok/oauth/start")
    assert r.status_code == 409 and r.json()["error"]["code"] == "tiktok_not_configured"


# ----------------------------------------------------------------- callback
async def test_successful_callback_stores_only_encrypted_tokens(authed, sessions, tiktok_mock, crypto):
    state = await start(authed)
    r = await callback(authed, code=GOOD_CODE, state=state, scopes="user.info.basic,video.publish")
    assert r.status_code == 303
    assert r.headers["location"].startswith("http://testserver/accounts?connected=")
    async with sessions() as db:
        account = (await db.execute(select(ConnectedAccount))).scalar_one()
        raw = (await db.execute(text("SELECT row_to_json(c)::text FROM connected_accounts c"))).scalar_one()
    assert account.provider_account_id == OPEN_ID and account.display_name == "Test Creator"
    assert account.scopes == ["user.info.basic", "video.publish"]
    assert "acc-0" not in raw and "ref-0" not in raw  # no plaintext tokens anywhere in the row
    assert crypto.decrypt(account.access_token_enc) == "acc-0"
    assert crypto.decrypt(account.refresh_token_enc) == "ref-0"
    assert account.access_expires_at > datetime.now(UTC) + timedelta(hours=23)
    assert account.refresh_expires_at > datetime.now(UTC) + timedelta(days=360)


async def test_api_never_exposes_tokens(authed, sessions, tiktok_mock):
    state = await start(authed)
    await callback(authed, code=GOOD_CODE, state=state)
    listing = (await authed.get(f"{API}/accounts")).text
    assert "acc-0" not in listing and "ref-0" not in listing and "token" not in listing.lower().replace("expires", "")
    assert "test-client-secret-value" not in listing


async def test_state_is_single_use(authed, tiktok_mock):
    state = await start(authed)
    assert (await callback(authed, code=GOOD_CODE, state=state)).headers["location"].find("connected=") != -1
    replay = await callback(authed, code=GOOD_CODE, state=state)
    assert "oauth_error=oauth_state_invalid" in replay.headers["location"]
    assert tiktok_mock.count("token") == 1  # the replay never reached TikTok


async def test_missing_unknown_or_expired_state_is_rejected(authed, sessions, tiktok_mock):
    assert "oauth_state_missing" in (await callback(authed, code=GOOD_CODE)).headers["location"]
    assert "oauth_state_invalid" in (await callback(authed, code=GOOD_CODE, state="forged")).headers["location"]
    state = await start(authed)
    async with sessions() as db:
        await db.execute(update(OAuthState).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        await db.commit()
    assert "oauth_state_invalid" in (await callback(authed, code=GOOD_CODE, state=state)).headers["location"]
    assert tiktok_mock.count("token") == 0


async def test_state_of_another_user_is_rejected(app, sessions, tiktok_mock):
    await make_user(sessions, "a@example.com")
    await make_user(sessions, "b@example.com")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as a, \
            httpx.AsyncClient(transport=transport, base_url="http://testserver") as b:
        csrf_a = (await a.post(f"{API}/auth/login", json={"email": "a@example.com", "password": "Correct-Horse-Battery-9"})).json()["csrf_token"]
        await b.post(f"{API}/auth/login", json={"email": "b@example.com", "password": "Correct-Horse-Battery-9"})
        url = (await a.post(f"{API}/tiktok/oauth/start", headers={"X-CSRF-Token": csrf_a})).json()["authorization_url"]
        state = parse_qs(urlparse(url).query)["state"][0]
        # attacker B is tricked into completing A's flow
        r = await b.get("/oauth/tiktok/callback", params={"code": GOOD_CODE, "state": state})
        assert "oauth_state_invalid" in r.headers["location"]
    async with sessions() as db:
        assert (await db.execute(select(ConnectedAccount))).first() is None


async def test_callback_without_session_redirects_to_login(client, user, tiktok_mock):
    r = await callback(client, code=GOOD_CODE, state="x")
    assert r.status_code == 303 and "/login?oauth_error=session_required" in r.headers["location"]
    assert tiktok_mock.count("token") == 0


async def test_user_denied_access_is_handled(authed, tiktok_mock, sessions):
    state = await start(authed)
    r = await callback(authed, error="access_denied", error_description="User denied", state=state)
    assert "oauth_error=oauth_denied" in r.headers["location"]
    assert tiktok_mock.count("token") == 0
    async with sessions() as db:
        actions = (await db.execute(select(AuditLog.action))).scalars().all()
    assert "tiktok.oauth_denied" in actions


async def test_code_exchange_failure_is_reported_without_leaking_details(authed, tiktok_mock):
    state = await start(authed)
    r = await callback(authed, code="bad-code", state=state)
    assert "oauth_error=oauth_exchange_failed" in r.headers["location"]
    assert "bad-code" not in r.headers["location"]


async def test_tiktok_outage_during_exchange(authed, tiktok_mock):
    tiktok_mock.push("token", httpx.Response(503, text="down"))
    state = await start(authed)
    r = await callback(authed, code=GOOD_CODE, state=state)
    assert "oauth_error=upstream_unavailable" in r.headers["location"]


async def test_reconnecting_same_creator_updates_existing_account(authed, tiktok_mock, sessions):
    for _ in range(2):
        state = await start(authed)
        await callback(authed, code=GOOD_CODE, state=state)
    async with sessions() as db:
        assert len((await db.execute(select(ConnectedAccount))).scalars().all()) == 1


# ------------------------------------------------------------- token upkeep
async def test_valid_token_is_used_without_refresh(account_service, sessions, crypto, user, tiktok_mock):
    acc = await make_account(sessions, crypto, user.id)
    assert await account_service.access_token(acc.id) == "acc-0"
    assert tiktok_mock.refresh_count == 0


async def test_expiring_token_is_refreshed_and_rotated(account_service, sessions, crypto, user, tiktok_mock):
    acc = await make_account(sessions, crypto, user.id, expires_in_seconds=60)
    assert await account_service.access_token(acc.id) == "acc-1"
    async with sessions() as db:
        row = await db.get(ConnectedAccount, acc.id)
    assert crypto.decrypt(row.access_token_enc) == "acc-1" and crypto.decrypt(row.refresh_token_enc) == "ref-1"
    assert row.access_expires_at > datetime.now(UTC) + timedelta(hours=23)


async def test_concurrent_callers_trigger_a_single_refresh(account_service, sessions, crypto, user, tiktok_mock):
    acc = await make_account(sessions, crypto, user.id, expires_in_seconds=10)
    tokens = await asyncio.gather(*[account_service.access_token(acc.id) for _ in range(6)])
    assert set(tokens) == {"acc-1"}
    assert tiktok_mock.refresh_count == 1  # row lock serialised the refreshes


async def test_invalid_grant_marks_account_for_reauth(account_service, sessions, crypto, user, tiktok_mock):
    acc = await make_account(sessions, crypto, user.id, expires_in_seconds=10)
    tiktok_mock.push("token", httpx.Response(400, json={"error": "invalid_grant", "error_description": "revoked"}))
    try:
        await account_service.access_token(acc.id)
        raise AssertionError("expected ReauthRequired")
    except ReauthRequired:
        pass
    async with sessions() as db:
        row = await db.get(ConnectedAccount, acc.id)
    assert row.status == "needs_reauth" and row.last_error == "invalid_grant"
    try:
        await account_service.access_token(acc.id)
        raise AssertionError("must stay blocked until reconnect")
    except ReauthRequired:
        pass


async def test_transient_refresh_failure_keeps_account_active(account_service, sessions, crypto, user, tiktok_mock):
    acc = await make_account(sessions, crypto, user.id, expires_in_seconds=10)
    tiktok_mock.push("token", httpx.Response(503))
    try:
        await account_service.access_token(acc.id)
        raise AssertionError("expected transient error")
    except TikTokTransient:
        pass
    async with sessions() as db:
        assert (await db.get(ConnectedAccount, acc.id)).status == "active"
    assert await account_service.access_token(acc.id) == "acc-1"  # lock was released, retry works


async def test_expired_refresh_token_requires_reauth(account_service, sessions, crypto, user, tiktok_mock):
    acc = await make_account(sessions, crypto, user.id, expires_in_seconds=10)
    async with sessions() as db:
        await db.execute(update(ConnectedAccount).values(refresh_expires_at=datetime.now(UTC) - timedelta(days=1)))
        await db.commit()
    try:
        await account_service.access_token(acc.id)
        raise AssertionError("expected ReauthRequired")
    except ReauthRequired:
        pass
    assert tiktok_mock.refresh_count == 0


async def test_server_side_token_rejection_triggers_one_transparent_refresh(account_service, sessions, crypto, user, tiktok_mock):
    acc = await make_account(sessions, crypto, user.id)
    tiktok_mock.valid_access = {"acc-1"}  # TikTok invalidated acc-0 early (e.g. user re-authorised elsewhere)
    info = await account_service.creator_info(acc.id)
    assert info.username == "tester" and tiktok_mock.refresh_count == 1


async def test_access_token_invalid_twice_marks_reauth(account_service, sessions, crypto, user, tiktok_mock):
    acc = await make_account(sessions, crypto, user.id)
    tiktok_mock.reject_all = True  # nothing is accepted any more, not even a refreshed token
    try:
        await account_service.creator_info(acc.id)
        raise AssertionError("expected ReauthRequired")
    except ReauthRequired:
        pass
    async with sessions() as db:
        assert (await db.get(ConnectedAccount, acc.id)).status == "needs_reauth"


async def test_token_budget_prevents_hammering_tiktok(account_service, sessions, crypto, user, tiktok_mock):
    from app.integrations.tiktok.errors import TikTokRateLimited

    acc = await make_account(sessions, crypto, user.id)
    for _ in range(18):
        await account_service.creator_info(acc.id)
    try:
        await account_service.creator_info(acc.id)
        raise AssertionError("expected local rate limit")
    except TikTokRateLimited as exc:
        assert 1 <= exc.retry_after <= 61
    assert tiktok_mock.count("creator_info") == 18  # the 19th call never left the process


async def test_refresh_expiring_job(account_service, sessions, crypto, user, tiktok_mock):
    soon = await make_account(sessions, crypto, user.id, expires_in_seconds=600)
    stats = await account_service.refresh_expiring()
    assert stats == {"refreshed": 1, "failed": 0, "reauth": 0}
    far_user = await make_user(sessions, "far@example.com")
    far = await make_account(sessions, crypto, far_user.id, expires_in_seconds=20 * 3600)
    assert (await account_service.refresh_expiring())["refreshed"] == 0
    async with sessions() as db:
        assert crypto.decrypt((await db.get(ConnectedAccount, soon.id)).access_token_enc) == "acc-1"
        assert crypto.decrypt((await db.get(ConnectedAccount, far.id)).access_token_enc) == "acc-0"


# ------------------------------------------------------------- disconnect
async def test_disconnect_revokes_remotely_and_wipes_tokens(authed, sessions, crypto, user, tiktok_mock):
    acc = await make_account(sessions, crypto, user.id)
    r = await authed.delete(f"{API}/accounts/{acc.id}")
    assert r.status_code == 204 and tiktok_mock.count("revoke") == 1
    async with sessions() as db:
        row = await db.get(ConnectedAccount, acc.id)
        audit = (await db.execute(select(AuditLog.action))).scalars().all()
    assert row.access_token_enc is None and row.refresh_token_enc is None and row.status == "revoked"
    assert "tiktok.account_disconnected" in audit


async def test_disconnect_succeeds_locally_even_if_revoke_fails(authed, sessions, crypto, user, tiktok_mock):
    acc = await make_account(sessions, crypto, user.id)
    tiktok_mock.push("revoke", httpx.Response(500))
    assert (await authed.delete(f"{API}/accounts/{acc.id}")).status_code == 204
    async with sessions() as db:
        assert (await db.get(ConnectedAccount, acc.id)).access_token_enc is None


async def test_disconnect_blocked_while_publications_are_running(authed, sessions, crypto, user, settings, tiktok_mock):
    acc = await make_account(sessions, crypto, user.id)
    media = await make_media(sessions, settings, user.id)
    async with sessions() as db:
        db.add(Publication(user_id=user.id, account_id=acc.id, media_id=media.id, idempotency_key="k-1" * 4,
                           privacy_level="SELF_ONLY", status="PROCESSING"))
        await db.commit()
    r = await authed.delete(f"{API}/accounts/{acc.id}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "account_busy"


async def test_accounts_are_isolated_between_users(authed, sessions, crypto, tiktok_mock):
    other = await make_user(sessions, "other@example.com")
    foreign = await make_account(sessions, crypto, other.id)
    assert (await authed.get(f"{API}/accounts/{foreign.id}")).status_code == 404
    assert (await authed.get(f"{API}/accounts/{foreign.id}/creator-info")).status_code == 404
    assert (await authed.delete(f"{API}/accounts/{foreign.id}")).status_code == 404
    assert (await authed.post(f"{API}/accounts/{foreign.id}/refresh")).status_code == 404


async def test_creator_info_endpoint(authed, sessions, crypto, user, tiktok_mock):
    acc = await make_account(sessions, crypto, user.id)
    body = (await authed.get(f"{API}/accounts/{acc.id}/creator-info")).json()
    assert body["nickname"] == "Test Creator" and "SELF_ONLY" in body["privacy_level_options"]
    tiktok_mock.push("creator_info", api_error("rate_limit_exceeded", 429))
    r = await authed.get(f"{API}/accounts/{acc.id}/creator-info")
    assert r.status_code == 429 and "retry-after" in r.headers


async def test_creator_info_when_tiktok_is_down(authed, sessions, crypto, user, tiktok_mock):
    acc = await make_account(sessions, crypto, user.id)
    tiktok_mock.push("creator_info", httpx.Response(502))
    r = await authed.get(f"{API}/accounts/{acc.id}/creator-info")
    assert r.status_code == 503 and r.json()["error"]["code"] == "upstream_unavailable"
