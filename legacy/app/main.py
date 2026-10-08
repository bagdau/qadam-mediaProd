import hashlib
import hmac
import secrets
from pathlib import Path

import httpx
from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import storage, tiktok
from app.config import ROOT, settings


app = FastAPI(title="Qadam Media Integration Lab")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.on_event("startup")
def startup() -> None:
    storage.initialize()


def session_value() -> str:
    return hmac.new(settings.app_secret.encode(), settings.lab_access_key.encode(), hashlib.sha256).hexdigest()


def require_lab(lab_session: str | None = Cookie(default=None)) -> None:
    if not lab_session or not hmac.compare_digest(lab_session, session_value()):
        raise HTTPException(status_code=401, detail="Введите пароль тестового стенда")


@app.get("/")
def home() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/terms")
def terms() -> FileResponse:
    return FileResponse(ROOT / "static" / "terms.html")


@app.get("/privacy")
def privacy() -> FileResponse:
    return FileResponse(ROOT / "static" / "privacy.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "qadam-integration-lab"}


@app.post("/api/session")
async def login(request: Request, response: Response) -> dict:
    payload = await request.json()
    if not hmac.compare_digest(str(payload.get("access_key", "")), settings.lab_access_key):
        raise HTTPException(status_code=401, detail="Неверный пароль стенда")
    response.set_cookie("lab_session", session_value(), httponly=True, secure=settings.cookie_secure, samesite="lax", max_age=86400)
    return {"authenticated": True}


@app.get("/api/status", dependencies=[Depends(require_lab)])
def status() -> dict:
    token = storage.load_token()
    return {
        "configured": bool(settings.tiktok_client_key and settings.tiktok_client_secret),
        "redirect_uri": settings.tiktok_redirect_uri,
        "scopes": settings.tiktok_scopes.split(","),
        "connected": token is not None,
        "open_id": token.get("open_id") if token else None,
        "events": storage.recent_events(),
    }


@app.get("/oauth/tiktok/start", dependencies=[Depends(require_lab)])
def oauth_start(response: Response) -> RedirectResponse:
    if not settings.tiktok_client_key or not settings.tiktok_client_secret:
        raise HTTPException(status_code=409, detail="Сначала заполните TIKTOK_CLIENT_KEY и TIKTOK_CLIENT_SECRET")
    state = secrets.token_urlsafe(32)
    redirect = RedirectResponse(tiktok.authorization_url(state))
    redirect.set_cookie("tiktok_oauth_state", state, httponly=True, secure=settings.cookie_secure, samesite="lax", max_age=600)
    return redirect


@app.get("/oauth/tiktok/callback")
async def oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None, error_description: str | None = None, tiktok_oauth_state: str | None = Cookie(default=None)) -> RedirectResponse:
    if error:
        storage.log_event("oauth", "error", {"error": error, "description": error_description or ""})
        return RedirectResponse("/?oauth=error")
    if not state or not tiktok_oauth_state or not hmac.compare_digest(state, tiktok_oauth_state):
        raise HTTPException(status_code=400, detail="OAuth state validation failed")
    if not code:
        raise HTTPException(status_code=400, detail="TikTok did not return an authorization code")
    try:
        token = await tiktok.exchange_code(code)
        storage.save_token(token)
        storage.log_event("oauth", "success", {"open_id": token.get("open_id"), "scope": token.get("scope")})
    except (httpx.HTTPError, RuntimeError) as exc:
        storage.log_event("oauth", "error", {"message": str(exc)})
        return RedirectResponse("/?oauth=error")
    redirect = RedirectResponse("/?oauth=success")
    redirect.delete_cookie("tiktok_oauth_state")
    return redirect


@app.post("/api/tiktok/test", dependencies=[Depends(require_lab)])
async def test_connection() -> dict:
    token = storage.load_token()
    if not token:
        raise HTTPException(status_code=409, detail="TikTok account is not connected")
    try:
        result = await tiktok.user_info(token["access_token"])
        storage.log_event("connection_test", "success", {"display_name": result.get("data", {}).get("user", {}).get("display_name")})
        return result
    except httpx.HTTPError as exc:
        storage.log_event("connection_test", "error", {"message": str(exc)})
        raise HTTPException(status_code=502, detail="TikTok API rejected the connection test") from exc


@app.get("/api/tiktok/creator-info", dependencies=[Depends(require_lab)])
async def creator_info() -> dict:
    token = storage.load_token()
    if not token:
        raise HTTPException(status_code=409, detail="Сначала подключите личный TikTok-аккаунт")
    try:
        result = await tiktok.creator_info(token["access_token"])
        storage.log_event("creator_info", "success", {"creator_username": result.get("data", {}).get("creator_username")})
        return result
    except (httpx.HTTPError, RuntimeError) as exc:
        storage.log_event("creator_info", "error", {"message": str(exc)})
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/tiktok/refresh", dependencies=[Depends(require_lab)])
async def refresh() -> dict:
    token = storage.load_token()
    if not token or not token.get("refresh_token"):
        raise HTTPException(status_code=409, detail="Refresh token is unavailable")
    updated = await tiktok.refresh_token(token["refresh_token"])
    storage.save_token(updated)
    storage.log_event("token_refresh", "success", {"scope": updated.get("scope")})
    return {"refreshed": True}


@app.post("/api/tiktok/upload-draft", dependencies=[Depends(require_lab)])
async def upload_draft(video: UploadFile = File(...)) -> dict:
    if video.content_type not in {"video/mp4", "video/quicktime", "video/webm"}:
        raise HTTPException(status_code=415, detail="Поддерживаются MP4, MOV и WebM")
    content = await video.read()
    if not content or len(content) > 64 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Для стенда используйте видео до 64 МБ")
    token = storage.load_token()
    if not token:
        raise HTTPException(status_code=409, detail="TikTok account is not connected")
    try:
        result = await tiktok.upload_draft(token["access_token"], content, video.content_type)
        storage.log_event("upload_draft", "success", result)
        return result
    except (httpx.HTTPError, RuntimeError) as exc:
        storage.log_event("upload_draft", "error", {"message": str(exc)})
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/tiktok/publish", dependencies=[Depends(require_lab)])
async def publish_video(video: UploadFile = File(...), description: str = Form(..., min_length=1, max_length=2200), privacy_level: str = Form(...), disable_comment: bool = Form(False), disable_duet: bool = Form(False), disable_stitch: bool = Form(False), duration_seconds: float = Form(...)) -> dict:
    if video.content_type not in {"video/mp4", "video/quicktime", "video/webm"}:
        raise HTTPException(status_code=415, detail="Поддерживаются MP4, MOV и WebM")
    content = await video.read()
    if not content or len(content) > 64 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Для стенда используйте видео до 64 МБ")
    token = storage.load_token()
    if not token:
        raise HTTPException(status_code=409, detail="Сначала подключите личный TikTok-аккаунт")
    try:
        creator = await tiktok.creator_info(token["access_token"])
        creator_data = creator.get("data", {})
        if privacy_level not in creator_data.get("privacy_level_options", []):
            raise HTTPException(status_code=400, detail="Выбранный уровень приватности недоступен этому аккаунту")
        maximum = creator_data.get("max_video_post_duration_sec")
        if maximum and duration_seconds > maximum:
            raise HTTPException(status_code=400, detail=f"TikTok разрешает этому аккаунту видео не длиннее {maximum} секунд")
        result = await tiktok.direct_post(token["access_token"], content, video.content_type, description, privacy_level, disable_comment, disable_duet, disable_stitch)
        storage.log_event("direct_publish", "success", {"publish_id": result["publish_id"], "privacy_level": privacy_level})
        return {**result, "message": "Видео принято TikTok и обрабатывается"}
    except HTTPException:
        raise
    except (httpx.HTTPError, RuntimeError) as exc:
        storage.log_event("direct_publish", "error", {"message": str(exc)})
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/tiktok/publish-status/{publish_id}", dependencies=[Depends(require_lab)])
async def publish_status(publish_id: str) -> dict:
    token = storage.load_token()
    if not token:
        raise HTTPException(status_code=409, detail="TikTok account is not connected")
    return await tiktok.post_status(token["access_token"], publish_id)


@app.delete("/api/tiktok/disconnect", dependencies=[Depends(require_lab)])
def disconnect() -> dict:
    storage.delete_token()
    storage.log_event("disconnect", "success", {})
    return {"disconnected": True}

