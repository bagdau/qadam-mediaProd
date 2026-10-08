from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.models import AuditLog, Session, User
from tests.conftest import PASSWORD, login, make_user

API = "/api/v1"


async def test_login_sets_httponly_session_cookie_and_returns_csrf(client, user):
    response = await client.post(f"{API}/auth/login", json={"email": "Owner@Example.com", "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "owner@example.com"
    assert "password" not in response.text
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith("qm_session="))
    csrf_cookie = next(c for c in cookies if c.startswith("qm_csrf="))
    assert "HttpOnly" in session_cookie and "SameSite=lax" in session_cookie
    assert "HttpOnly" not in csrf_cookie
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_session_token_is_not_stored_in_clear(client, user, sessions):
    await login(client)
    token = client.cookies.get("qm_session")
    async with sessions() as db:
        row = (await db.execute(select(Session))).scalar_one()
    assert row.token_hash != token and len(row.token_hash) == 64


async def test_wrong_password_and_unknown_user_look_identical(client, user):
    bad = await client.post(f"{API}/auth/login", json={"email": "owner@example.com", "password": "nope-nope-nope"})
    unknown = await client.post(f"{API}/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-nope"})
    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json()


async def test_account_lockout_after_repeated_failures(client, user, sessions):
    for _ in range(5):
        r = await client.post(f"{API}/auth/login", json={"email": "owner@example.com", "password": "wrong-password-1"})
        assert r.status_code == 401
    locked = await client.post(f"{API}/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "account_locked"
    assert int(locked.headers["retry-after"]) > 0
    async with sessions() as db:
        await db.execute(update(User).values(locked_until=datetime.now(UTC) - timedelta(seconds=1)))
        await db.commit()
    assert (await client.post(f"{API}/auth/login", json={"email": "owner@example.com", "password": PASSWORD})).status_code == 200


async def test_login_is_rate_limited_per_ip(client, user):
    statuses = [
        (await client.post(f"{API}/auth/login", json={"email": f"u{i}@example.com", "password": "x" * 12})).status_code
        for i in range(25)
    ]
    assert statuses[:20] == [401] * 20
    assert set(statuses[20:]) == {429}


async def test_me_requires_session(client, user):
    assert (await client.get(f"{API}/auth/me")).status_code == 401
    await login(client)
    me = await client.get(f"{API}/auth/me")
    assert me.status_code == 200 and me.json()["user"]["email"] == "owner@example.com"


async def test_state_changing_requests_need_csrf_token(client, user):
    await login(client)
    token = client.csrf
    client.csrf = None
    assert (await client.post(f"{API}/auth/logout")).status_code == 403
    assert (await client.post(f"{API}/auth/logout", headers={"X-CSRF-Token": "forged"})).status_code == 403
    assert (await client.post(f"{API}/auth/logout", headers={"X-CSRF-Token": token})).status_code == 204


async def test_csrf_token_of_another_session_is_rejected(app, user):
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as a, \
            httpx.AsyncClient(transport=transport, base_url="http://testserver") as b:
        csrf_a = (await a.post(f"{API}/auth/login", json={"email": "owner@example.com", "password": PASSWORD})).json()["csrf_token"]
        await b.post(f"{API}/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
        # B's cookie pair is valid, but A's token is bound to A's session
        b.cookies.set("qm_csrf", csrf_a)
        r = await b.post(f"{API}/auth/logout", headers={"X-CSRF-Token": csrf_a})
        assert r.status_code == 403


async def test_foreign_origin_is_rejected(client, user):
    r = await client.post(f"{API}/auth/login", json={"email": "owner@example.com", "password": PASSWORD},
                          headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "bad_origin"
    ok = await client.post(f"{API}/auth/login", json={"email": "owner@example.com", "password": PASSWORD},
                           headers={"Origin": "http://testserver"})
    assert ok.status_code == 200


async def test_logout_revokes_session_server_side(client, user):
    await login(client)
    stolen = client.cookies.get("qm_session")
    assert (await client.post(f"{API}/auth/logout")).status_code == 204
    client.cookies.set("qm_session", stolen)
    assert (await client.get(f"{API}/auth/me")).status_code == 401


async def test_expired_and_idle_sessions_are_rejected(client, user, sessions):
    await login(client)
    async with sessions() as db:
        await db.execute(update(Session).values(last_seen_at=datetime.now(UTC) - timedelta(hours=25)))
        await db.commit()
    assert (await client.get(f"{API}/auth/me")).status_code == 401


async def test_change_password_revokes_other_sessions(app, user, sessions):
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as a, \
            httpx.AsyncClient(transport=transport, base_url="http://testserver") as b:
        csrf = (await a.post(f"{API}/auth/login", json={"email": "owner@example.com", "password": PASSWORD})).json()["csrf_token"]
        await b.post(f"{API}/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
        weak = await a.post(f"{API}/auth/password", headers={"X-CSRF-Token": csrf},
                            json={"current_password": PASSWORD, "new_password": "short"})
        assert weak.status_code == 422
        wrong = await a.post(f"{API}/auth/password", headers={"X-CSRF-Token": csrf},
                             json={"current_password": "not-the-password", "new_password": "A-Brand-New-Passw0rd"})
        assert wrong.status_code == 403
        ok = await a.post(f"{API}/auth/password", headers={"X-CSRF-Token": csrf},
                          json={"current_password": PASSWORD, "new_password": "A-Brand-New-Passw0rd"})
        assert ok.status_code == 204
        assert (await a.get(f"{API}/auth/me")).status_code == 200
        assert (await b.get(f"{API}/auth/me")).status_code == 401


async def test_sessions_listing_and_revocation(client, user):
    await login(client)
    listing = (await client.get(f"{API}/auth/sessions")).json()
    assert len(listing) == 1 and listing[0]["current"] is True
    assert (await client.delete(f"{API}/auth/sessions/00000000-0000-0000-0000-000000000000")).status_code == 404


async def test_registration_disabled_by_default(client):
    r = await client.post(f"{API}/auth/register", json={"email": "new@example.com", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "registration_disabled"


async def test_validation_errors_do_not_echo_secrets(client):
    r = await client.post(f"{API}/auth/login", json={"email": "not-an-email", "password": "SuperSecret-12345"})
    assert r.status_code == 422
    assert "SuperSecret-12345" not in r.text


async def test_login_is_audited(client, user, sessions):
    await client.post(f"{API}/auth/login", json={"email": "owner@example.com", "password": "bad-password-123"})
    await login(client)
    async with sessions() as db:
        actions = [a for (a,) in (await db.execute(select(AuditLog.action).order_by(AuditLog.created_at))).all()]
    assert "auth.login_failed" in actions and "auth.login" in actions


async def test_other_user_cannot_see_data(client, sessions):
    await make_user(sessions, "a@example.com")
    await make_user(sessions, "b@example.com")
    await login(client, "a@example.com")
    assert (await client.get(f"{API}/accounts")).json() == []
