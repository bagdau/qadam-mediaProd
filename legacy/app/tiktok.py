from urllib.parse import urlencode

import httpx

from app.config import settings


AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
API_ROOT = "https://open.tiktokapis.com/v2"


def authorization_url(state: str) -> str:
    return f"{AUTHORIZE_URL}?{urlencode({'client_key': settings.tiktok_client_key, 'response_type': 'code', 'scope': settings.tiktok_scopes, 'redirect_uri': settings.tiktok_redirect_uri, 'state': state})}"


async def exchange_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(TOKEN_URL, data={
            "client_key": settings.tiktok_client_key,
            "client_secret": settings.tiktok_client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": settings.tiktok_redirect_uri,
        })
    response.raise_for_status()
    return response.json()


async def refresh_token(refresh: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(TOKEN_URL, data={
            "client_key": settings.tiktok_client_key,
            "client_secret": settings.tiktok_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh,
        })
    response.raise_for_status()
    return response.json()


async def user_info(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{API_ROOT}/user/info/",
            params={"fields": "open_id,union_id,avatar_url,display_name"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    response.raise_for_status()
    return response.json()


async def creator_info(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{API_ROOT}/post/publish/creator_info/query/",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"},
        )
    response.raise_for_status()
    result = response.json()
    if result.get("error", {}).get("code") not in {None, "ok"}:
        raise RuntimeError(result["error"].get("message") or result["error"]["code"])
    return result


async def upload_draft(access_token: str, content: bytes, content_type: str) -> dict:
    size = len(content)
    init_payload = {"source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}}
    async with httpx.AsyncClient(timeout=120) as client:
        init = await client.post(
            f"{API_ROOT}/post/publish/inbox/video/init/",
            json=init_payload,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"},
        )
        init.raise_for_status()
        result = init.json()
        if result.get("error", {}).get("code") not in {None, "ok"}:
            raise RuntimeError(result["error"].get("message") or result["error"]["code"])
        upload_url = result["data"]["upload_url"]
        uploaded = await client.put(upload_url, content=content, headers={
            "Content-Type": content_type,
            "Content-Length": str(size),
            "Content-Range": f"bytes 0-{size - 1}/{size}",
        })
        uploaded.raise_for_status()
    return {"publish_id": result["data"]["publish_id"], "upload_status": uploaded.status_code}


async def direct_post(access_token: str, content: bytes, content_type: str, description: str, privacy_level: str, disable_comment: bool, disable_duet: bool, disable_stitch: bool) -> dict:
    size = len(content)
    payload = {
        "post_info": {"title": description, "privacy_level": privacy_level, "disable_comment": disable_comment, "disable_duet": disable_duet, "disable_stitch": disable_stitch, "video_cover_timestamp_ms": 1000},
        "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1},
    }
    async with httpx.AsyncClient(timeout=180) as client:
        init = await client.post(f"{API_ROOT}/post/publish/video/init/", json=payload, headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"})
        init.raise_for_status()
        result = init.json()
        if result.get("error", {}).get("code") not in {None, "ok"}:
            raise RuntimeError(result["error"].get("message") or result["error"]["code"])
        upload_url = result["data"]["upload_url"]
        uploaded = await client.put(upload_url, content=content, headers={"Content-Type": content_type, "Content-Length": str(size), "Content-Range": f"bytes 0-{size - 1}/{size}"})
        uploaded.raise_for_status()
    return {"publish_id": result["data"]["publish_id"], "upload_status": uploaded.status_code}


async def post_status(access_token: str, publish_id: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{API_ROOT}/post/publish/status/fetch/",
            json={"publish_id": publish_id},
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"},
        )
    response.raise_for_status()
    return response.json()

