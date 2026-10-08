"""Local stand-in for TikTok (development only - never part of the production stack).

It lets you click through the complete OAuth + Direct Post flow without a TikTok Developer App
(which needs HTTPS redirect URIs and app review). The backend refuses TikTok endpoint overrides when
ENVIRONMENT=production, so this cannot be wired into a production deployment by accident.

Run:  uvicorn devtools.mock_tiktok:app --port 9000
Env:  QADAM_BACKEND_CALLBACK (default http://localhost:8080/oauth/tiktok/callback)
"""

from __future__ import annotations

import html
import re
import secrets
import time
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

app = FastAPI(title="Mock TikTok (dev only)", docs_url="/docs")

OPEN_ID = "mock-open-id-0001"
STATE = {"codes": {}, "access": set(), "refresh": {}, "posts": {}, "uploads": {}}


def ok(data: dict | None = None) -> JSONResponse:
    body: dict = {"error": {"code": "ok", "message": "", "log_id": secrets.token_hex(6)}}
    if data is not None:
        body["data"] = data
    return JSONResponse(body)


def err(code: str, status: int = 400, message: str = "") -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message or code, "log_id": secrets.token_hex(6)}}, status_code=status)


def bearer(request: Request) -> str:
    return request.headers.get("authorization", "").removeprefix("Bearer ").strip()


def authed(request: Request) -> bool:
    return bearer(request) in STATE["access"]


# ------------------------------------------------------------------ consent page
@app.get("/authorize", response_class=HTMLResponse)
@app.get("/v2/auth/authorize/", response_class=HTMLResponse)
def authorize(client_key: str = "", redirect_uri: str = "", state: str = "", scope: str = "", response_type: str = "code"):
    safe = {k: html.escape(v) for k, v in dict(redirect_uri=redirect_uri, state=state, scope=scope).items()}
    return f"""<!doctype html><meta charset=utf-8><title>Mock TikTok</title>
<body style="font-family:system-ui;max-width:420px;margin:12vh auto;padding:0 16px">
<h1>Mock TikTok</h1><p>Приложение <b>{html.escape(client_key)}</b> запрашивает доступ:</p>
<ul>{''.join(f'<li>{html.escape(s)}</li>' for s in scope.split(',') if s)}</ul>
<form method=post action="">
<input type=hidden name=redirect_uri value="{safe['redirect_uri']}"><input type=hidden name=state value="{safe['state']}">
<input type=hidden name=scope value="{safe['scope']}">
<button name=decision value=allow style="padding:10px 18px">Разрешить</button>
<button name=decision value=deny style="padding:10px 18px">Отклонить</button></form>
<p style="color:#666;font-size:13px">Это локальная имитация. Реальный TikTok не используется.</p></body>"""


@app.post("/authorize")
@app.post("/v2/auth/authorize/")
def authorize_post(redirect_uri: str = Form(...), state: str = Form(""), scope: str = Form(""), decision: str = Form(...)):
    if decision != "allow":
        return RedirectResponse(f"{redirect_uri}?{urlencode({'error': 'access_denied', 'error_description': 'User denied', 'state': state})}", 303)
    code = secrets.token_urlsafe(16)
    STATE["codes"][code] = scope
    return RedirectResponse(f"{redirect_uri}?{urlencode({'code': code, 'scopes': scope, 'state': state})}", 303)


# ------------------------------------------------------------------------ OAuth
def issue(scope: str) -> dict:
    access, refresh = f"act.{secrets.token_urlsafe(24)}", f"rft.{secrets.token_urlsafe(24)}"
    STATE["access"].add(access)
    STATE["refresh"][refresh] = scope
    return {"access_token": access, "expires_in": 86400, "open_id": OPEN_ID, "refresh_expires_in": 31536000,
            "refresh_token": refresh, "scope": scope, "token_type": "Bearer"}


@app.post("/v2/oauth/token/")
async def token(request: Request):
    form = {k: v for k, v in (await request.form()).items()}
    if form.get("grant_type") == "authorization_code":
        scope = STATE["codes"].pop(form.get("code", ""), None)
        if scope is None:
            return JSONResponse({"error": "invalid_grant", "error_description": "Authorization code is invalid or expired.", "log_id": "mock"}, status_code=400)
        return issue(scope)
    if form.get("grant_type") == "refresh_token":
        scope = STATE["refresh"].pop(form.get("refresh_token", ""), None)
        if scope is None:
            return JSONResponse({"error": "invalid_grant", "error_description": "Refresh token is invalid.", "log_id": "mock"}, status_code=400)
        return issue(scope)
    return JSONResponse({"error": "invalid_request", "error_description": "unsupported grant_type"}, status_code=400)


@app.post("/v2/oauth/revoke/")
async def revoke(request: Request):
    STATE["access"].discard((await request.form()).get("token", ""))
    return Response(status_code=200, content="{}", media_type="application/json")


@app.get("/v2/user/info/")
def user_info(request: Request):
    if not authed(request):
        return err("access_token_invalid", 401)
    return ok({"user": {"open_id": OPEN_ID, "union_id": "mock-union", "display_name": "Mock Creator", "avatar_url": ""}})


# ------------------------------------------------------------------ Content Posting
@app.post("/v2/post/publish/creator_info/query/")
def creator_info(request: Request):
    if not authed(request):
        return err("access_token_invalid", 401)
    return ok({"creator_username": "mock_creator", "creator_nickname": "Mock Creator", "creator_avatar_url": "",
               "privacy_level_options": ["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"],
               "comment_disabled": False, "duet_disabled": False, "stitch_disabled": False,
               "max_video_post_duration_sec": 600})


@app.post("/v2/post/publish/video/init/")
@app.post("/v2/post/publish/inbox/video/init/")
async def init(request: Request):
    if not authed(request):
        return err("access_token_invalid", 401)
    body = await request.json()
    publish_id = f"v_pub_file~v2-1.{secrets.token_hex(8)}"
    upload_id = secrets.token_urlsafe(10)
    inbox = "inbox" in request.url.path
    privacy = (body.get("post_info") or {}).get("privacy_level")
    if not inbox and privacy and privacy != "SELF_ONLY":
        return err("unaudited_client_can_only_post_to_private_accounts", 403)
    size = body["source_info"]["video_size"]
    STATE["posts"][publish_id] = {"started": time.time(), "size": size, "received": 0, "inbox": inbox}
    STATE["uploads"][upload_id] = publish_id
    base = str(request.base_url).rstrip("/")
    return ok({"publish_id": publish_id, "upload_url": f"{base}/upload/{upload_id}"})


@app.put("/upload/{upload_id}")
async def upload(upload_id: str, request: Request):
    publish_id = STATE["uploads"].get(upload_id)
    if not publish_id:
        return Response(status_code=404)
    post = STATE["posts"][publish_id]
    match = re.match(r"bytes (\d+)-(\d+)/(\d+)", request.headers.get("content-range", ""))
    if not match:
        return Response(status_code=400)
    first, last, total = map(int, match.groups())
    if first != post["received"]:
        return Response(status_code=416, headers={"Content-Range": f"bytes 0-{post['received'] - 1}/{total}"})
    data = await request.body()
    if len(data) != last - first + 1:
        return Response(status_code=400)
    post["received"] = last + 1
    if post["received"] >= total:
        post["done_at"] = time.time()
        return Response(status_code=201)
    return Response(status_code=206)


@app.post("/v2/post/publish/status/fetch/")
async def status(request: Request):
    if not authed(request):
        return err("access_token_invalid", 401)
    post = STATE["posts"].get((await request.json()).get("publish_id"))
    if not post:
        return err("invalid_publish_id", 400)
    if "done_at" not in post:
        return ok({"status": "PROCESSING_UPLOAD", "uploaded_bytes": post["received"]})
    if time.time() - post["done_at"] < 8:  # pretend TikTok is busy for a few seconds
        return ok({"status": "PROCESSING_UPLOAD"})
    if post["inbox"]:
        return ok({"status": "SEND_TO_USER_INBOX"})
    return ok({"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [int(time.time() * 1000)]})
