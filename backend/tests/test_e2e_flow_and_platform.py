"""Full backend scenarios (API -> queue -> worker -> TikTok mock) plus platform-level checks."""

from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import SecretStr
import pytest
from sqlalchemy import select

from app import cli
from app.main import create_app
from app.models import Publication
from app.services.publishing import PublishingWorkflow, RetryLater
from app.workers import tasks
from tests.conftest import login, make_user
from tests.fake_tiktok import GOOD_CODE
from tests.helpers import make_mp4

API = "/api/v1"


async def test_full_journey_register_connect_upload_publish_status(
    authed, workflow, sessions, dispatcher, tiktok_mock, media_dir
):
    # 1. connect a TikTok account through the OAuth flow
    url = (await authed.post(f"{API}/tiktok/oauth/start")).json()["authorization_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    cb = await authed.get("/oauth/tiktok/callback", params={"code": GOOD_CODE, "state": state})
    assert "connected=" in cb.headers["location"]
    account = (await authed.get(f"{API}/accounts")).json()[0]
    assert account["status"] == "active" and account["display_name"] == "Test Creator"

    # 2. creator info drives the form
    creator = (await authed.get(f"{API}/accounts/{account['id']}/creator-info")).json()
    assert creator["nickname"] == "Test Creator"

    # 3. upload a video
    media = (await authed.post(f"{API}/media", files={"video": ("promo.mp4", make_mp4(20.0, 6000), "video/mp4")})).json()

    # 4. publish with an idempotency key (the second click returns the same row)
    key = {"Idempotency-Key": f"e2e-{uuid.uuid4()}"}
    payload = {"account_id": account["id"], "media_id": media["id"], "title": "Launch day #qadam",
               "privacy_level": "SELF_ONLY", "music_usage_confirmed": True, "allow_comment": True}
    created = await authed.post(f"{API}/publications", json=payload, headers=key)
    again = await authed.post(f"{API}/publications", json=payload, headers=key)
    assert (created.status_code, again.status_code) == (201, 200)
    pub_id = uuid.UUID(created.json()["id"])
    assert dispatcher.calls[0][:2] == ("publish", pub_id) and len(dispatcher.calls) == 1

    # 5. the worker picks it up (what Celery does), then polls until TikTok finishes
    assert await workflow.run_publish(pub_id) == "uploaded"
    mid = (await authed.get(f"{API}/publications/{pub_id}")).json()
    assert mid["status"] == "PROCESSING" and mid["uploaded_bytes"] == media["size_bytes"]
    await workflow.poll_status(pub_id)
    await workflow.poll_status(pub_id)

    # 6. the user sees the outcome and the full timeline
    final = (await authed.get(f"{API}/publications/{pub_id}")).json()
    assert final["status"] == "PUBLISHED" and final["tiktok_post_ids"] == ["7300000000000000001"]
    steps = [e["to_status"] for e in final["events"] if e["type"] == "status_changed"]
    assert steps == ["INITIATING", "UPLOADING", "PROCESSING", "PUBLISHED"]
    assert tiktok_mock.init_count == 1
    dash = (await authed.get(f"{API}/dashboard")).json()
    assert dash["publications_by_status"] == {"PUBLISHED": 1} and dash["published_last_7_days"] == 1

    # 7. a repeated submit of the same video is refused
    dup = await authed.post(f"{API}/publications", json=payload, headers={"Idempotency-Key": f"e2e-{uuid.uuid4()}"})
    assert dup.status_code == 409

    # 8. disconnecting revokes access at TikTok and clears credentials
    assert (await authed.delete(f"{API}/accounts/{account['id']}")).status_code == 204
    assert tiktok_mock.count("revoke") == 1
    assert (await authed.get(f"{API}/accounts/{account['id']}")).json()["status"] == "revoked"


async def test_failed_publication_can_be_retried_by_the_user(authed, workflow, sessions, dispatcher, tiktok_mock, crypto,
                                                             settings, user):
    from tests.conftest import make_account, make_media
    from tests.fake_tiktok import api_error

    account = await make_account(sessions, crypto, user.id)
    media = await make_media(sessions, settings, user.id)
    payload = {"account_id": str(account.id), "media_id": str(media.id), "privacy_level": "SELF_ONLY",
               "music_usage_confirmed": True}
    pid = uuid.UUID((await authed.post(f"{API}/publications", json=payload,
                                       headers={"Idempotency-Key": "first-attempt-1"})).json()["id"])
    tiktok_mock.push("video_init", api_error("spam_risk_too_many_posts", 403))
    assert await workflow.run_publish(pid) == "failed"
    shown = (await authed.get(f"{API}/publications/{pid}")).json()
    assert shown["status"] == "FAILED" and "лимит" in shown["fail_message"]
    assert (await authed.post(f"{API}/publications/{pid}/retry")).status_code == 200
    assert await workflow.run_publish(pid) == "uploaded"
    assert (await authed.get(f"{API}/publications/{pid}")).json()["attempts"] == 2


# ------------------------------------------------------------ platform
async def test_health_endpoints(client):
    assert (await client.get("/health/live")).json()["status"] == "ok"
    assert (await client.get("/health")).status_code == 200
    ready = await client.get("/health/ready")
    assert ready.status_code == 200 and ready.json()["checks"] == {"postgres": "ok", "redis": "ok"}


async def test_readiness_reports_dependency_failure(app, client):
    class Broken:
        async def ping(self):
            raise ConnectionError("down")

    original = app.state.redis
    app.state.redis = Broken()
    try:
        r = await client.get("/health/ready")
    finally:
        app.state.redis = original
    assert r.status_code == 503 and r.json()["checks"]["redis"] == "error"


async def test_security_headers_and_no_server_leak(client):
    r = await client.get("/health/live")
    for header in ("x-content-type-options", "x-frame-options", "referrer-policy", "content-security-policy",
                   "cross-origin-opener-policy", "permissions-policy"):
        assert header in r.headers
    assert "server" not in r.headers or "uvicorn" not in r.headers["server"].lower()
    assert r.headers["x-request-id"]


async def test_unknown_route_and_method_use_json_errors(client):
    r = await client.get("/api/v1/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "http_404"
    r = await client.put("/api/v1/auth/login")
    assert r.status_code == 405


async def test_unhandled_errors_do_not_leak_internals(app, user):
    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret internal detail: password=hunter2")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get("/boom")
    assert r.status_code == 500 and "hunter2" not in r.text and r.json()["error"]["code"] == "internal_error"


async def test_docs_hidden_in_production(sessions, redis, tiktok_client, dispatcher, settings):
    prod = settings.model_copy(update={"environment": "production"})
    application = create_app(settings=prod, redis=redis, sessions=sessions, tiktok_client=tiktok_client,
                             dispatcher=dispatcher)
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://testserver") as c:
            assert (await c.get("/api/docs")).status_code == 404
            assert (await c.get("/api/openapi.json")).status_code == 404


async def test_cors_is_strict(sessions, redis, tiktok_client, dispatcher, settings):
    cfg = settings.model_copy(update={"cors_origins": ["https://app.qadam.test"]})
    application = create_app(settings=cfg, redis=redis, sessions=sessions, tiktok_client=tiktok_client,
                             dispatcher=dispatcher)
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://testserver") as c:
            good = await c.options("/api/v1/auth/login", headers={"Origin": "https://app.qadam.test",
                                                                  "Access-Control-Request-Method": "POST"})
            bad = await c.options("/api/v1/auth/login", headers={"Origin": "https://evil.test",
                                                                 "Access-Control-Request-Method": "POST"})
    assert good.headers["access-control-allow-origin"] == "https://app.qadam.test"
    assert good.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in bad.headers


async def test_bootstrap_admin_is_created_once(sessions, redis, tiktok_client, dispatcher, settings):
    cfg = settings.model_copy(update={"bootstrap_admin_email": "Admin@Example.com",
                                      "bootstrap_admin_password": SecretStr("Bootstrap-Passw0rd-1")})
    for _ in range(2):
        application = create_app(settings=cfg, redis=redis, sessions=sessions, tiktok_client=tiktok_client,
                                 dispatcher=dispatcher)
        async with application.router.lifespan_context(application):
            pass
    from app.models import User

    async with sessions() as db:
        admins = (await db.execute(select(User).where(User.role == "admin"))).scalars().all()
    assert [a.email for a in admins] == ["admin@example.com"]


# ----------------------------------------------------------- Celery tasks
class FakeTask:
    name = "fake"

    def __init__(self, retries: int = 0) -> None:
        self.request = type("R", (), {"retries": retries})()
        self.retried: dict | None = None

    def retry(self, **kw):
        self.retried = kw
        return RuntimeError("retry-scheduled")


def test_task_retries_with_requested_countdown(monkeypatch):
    async def step(_wf, _pid):
        raise RetryLater(42, "rate_limited")

    monkeypatch.setattr(tasks, "run", lambda factory: (_ for _ in ()).throw(RetryLater(42, "rate_limited")))
    task = FakeTask(retries=1)
    with pytest.raises(RuntimeError, match="retry-scheduled"):
        tasks._handle(task, str(uuid.uuid4()), step, max_retries=5)
    assert task.retried["countdown"] == 42


def test_task_gives_up_and_fails_the_publication_after_max_retries(monkeypatch):
    calls: list[str] = []

    def fake_run(factory):
        if not calls:
            calls.append("step")
            raise RetryLater(1, "TikTok недоступен")
        calls.append("fail_exhausted")
        return None

    monkeypatch.setattr(tasks, "run", fake_run)
    result = tasks._handle(FakeTask(retries=5), str(uuid.uuid4()), lambda w, p: None, max_retries=5)
    assert result == "exhausted" and calls == ["step", "fail_exhausted"]


def test_task_unexpected_exception_is_retried_not_lost(monkeypatch):
    def boom(factory):
        raise ValueError("unexpected")

    monkeypatch.setattr(tasks, "run", boom)
    task = FakeTask(retries=0)
    with pytest.raises(RuntimeError, match="retry-scheduled"):
        tasks._handle(task, str(uuid.uuid4()), lambda w, p: None, max_retries=3)
    assert task.retried["countdown"] > 0


def test_celery_is_configured_for_reliable_delivery():
    from app.workers.celery_app import celery_app

    conf = celery_app.conf
    assert conf.task_acks_late and conf.task_reject_on_worker_lost and conf.worker_prefetch_multiplier == 1
    assert conf.broker_transport_options["visibility_timeout"] >= 3600
    scheduled = {v["task"] for v in conf.beat_schedule.values()}
    assert {"app.workers.tasks.sweep_publications", "app.workers.tasks.refresh_tokens",
            "app.workers.tasks.cleanup_media", "app.workers.tasks.cleanup_auth"} <= scheduled
    registered = set(celery_app.tasks.keys())
    assert {"app.workers.tasks.publish_video", "app.workers.tasks.poll_publication"} <= registered


# -------------------------------------------------------------------- CLI
def test_cli_generate_key_and_check_config(capsys):
    assert cli.main(["generate-key"]) == 0
    key = capsys.readouterr().out.strip()
    assert len(key) == 44
    assert cli.main(["check-config"]) == 0
    assert "environment=test" in capsys.readouterr().out
