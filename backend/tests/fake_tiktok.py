"""In-process fake of the TikTok HTTP API (respx) used by the test-suite.

It follows the documented request/response shapes and can be told to misbehave per endpoint.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any
from urllib.parse import parse_qs

import httpx
import respx

API = "https://open.tiktokapis.com/v2"
UPLOAD_URL = "https://upload.tiktokapis.test/video/upload?upload_id=u1&secret=s3cr3t-signature"
GOOD_CODE = "good-code"
OPEN_ID = "open-id-123"


def ok(data: dict | None = None) -> httpx.Response:
    body: dict[str, Any] = {"error": {"code": "ok", "message": "", "log_id": "log-1"}}
    if data is not None:
        body["data"] = data
    return httpx.Response(200, json=body)


def api_error(code: str, status: int = 400, message: str = "", headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": message or code, "log_id": "log-err"}},
                          headers=headers)


class FakeTikTok:
    def __init__(self, router: respx.MockRouter) -> None:
        self.router = router
        self.calls: list[tuple[str, Any]] = []
        self.overrides: dict[str, list[Any]] = defaultdict(list)  # endpoint -> queue of responses/exceptions
        self.refresh_count = 0
        self.reject_all = False  # every bearer token is refused, even freshly refreshed ones
        self.valid_access: set[str] = {"acc-0"}
        self.initial_scope = "user.info.basic,video.publish"
        self.creator: dict[str, Any] = {
            "creator_username": "tester",
            "creator_nickname": "Test Creator",
            "creator_avatar_url": "https://example.test/a.jpg",
            "privacy_level_options": ["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"],
            "comment_disabled": False,
            "duet_disabled": False,
            "stitch_disabled": False,
            "max_video_post_duration_sec": 600,
        }
        self.status_sequence: list[dict[str, Any]] = [
            {"status": "PROCESSING_UPLOAD"},
            {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [7300000000000000001]},
        ]
        self.status_calls = 0
        self.uploaded: list[tuple[int, int, int, dict]] = []  # first, last, total, headers
        self.init_count = 0
        self.last_init_body: dict | None = None
        self._install()

    # ------------------------------------------------------------- helpers
    def push(self, endpoint: str, *responses: Any) -> None:
        self.overrides[endpoint].extend(responses)

    def _next(self, endpoint: str) -> Any | None:
        queue = self.overrides[endpoint]
        if not queue:
            return None
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def count(self, endpoint: str) -> int:
        return sum(1 for name, _ in self.calls if name == endpoint)

    def _bearer(self, request: httpx.Request) -> str:
        return request.headers.get("authorization", "").removeprefix("Bearer ").strip()

    def _auth_failure(self, request: httpx.Request) -> httpx.Response | None:
        if self.reject_all or self._bearer(request) not in self.valid_access:
            return api_error("access_token_invalid", 401, "The access token is invalid or not found in the request.")
        return None

    # -------------------------------------------------------------- routes
    def _install(self) -> None:
        r = self.router
        r.post(f"{API}/oauth/token/").mock(side_effect=self._token)
        r.post(f"{API}/oauth/revoke/").mock(side_effect=self._revoke)
        r.get(f"{API}/user/info/").mock(side_effect=self._user_info)
        r.post(f"{API}/post/publish/creator_info/query/").mock(side_effect=self._creator_info)
        r.post(f"{API}/post/publish/video/init/").mock(side_effect=lambda req: self._init("video_init", req))
        r.post(f"{API}/post/publish/inbox/video/init/").mock(side_effect=lambda req: self._init("inbox_init", req))
        r.post(f"{API}/post/publish/status/fetch/").mock(side_effect=self._status)
        r.put(re.compile(r"^https://upload\.tiktokapis\.test/.*")).mock(side_effect=self._upload)

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.calls.append(("token", {k: v for k, v in form.items() if k != "client_secret"}))
        forced = self._next("token")
        if forced is not None:
            return forced
        if form.get("grant_type") == "authorization_code":
            if form.get("code") != GOOD_CODE:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Authorization code is expired or invalid.", "log_id": "l"})
            self.valid_access.add("acc-0")
            return httpx.Response(200, json={
                "access_token": "acc-0", "expires_in": 86400, "open_id": OPEN_ID, "refresh_expires_in": 31536000,
                "refresh_token": "ref-0", "scope": self.initial_scope, "token_type": "Bearer"})
        if form.get("grant_type") == "refresh_token":
            self.refresh_count += 1
            access = f"acc-{self.refresh_count}"
            self.valid_access = {access}
            return httpx.Response(200, json={
                "access_token": access, "expires_in": 86400, "open_id": OPEN_ID,
                "refresh_expires_in": 31536000, "refresh_token": f"ref-{self.refresh_count}",
                "scope": self.initial_scope, "token_type": "Bearer"})
        return httpx.Response(400, json={"error": "invalid_request", "error_description": "bad grant"})

    def _revoke(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(("revoke", None))
        return self._next("revoke") or httpx.Response(200, json={})

    def _user_info(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(("user_info", None))
        forced = self._next("user_info")
        if forced is not None:
            return forced
        return self._auth_failure(request) or ok({"user": {"open_id": OPEN_ID, "union_id": "u", "display_name": "Test Creator",
                                                           "avatar_url": "https://example.test/a.jpg"}})

    def _creator_info(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(("creator_info", None))
        forced = self._next("creator_info")
        if forced is not None:
            return forced
        return self._auth_failure(request) or ok(dict(self.creator))

    def _init(self, name: str, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append((name, body))
        self.last_init_body = body
        forced = self._next(name)
        if forced is not None:
            return forced
        failure = self._auth_failure(request)
        if failure:
            return failure
        self.init_count += 1
        return ok({"publish_id": f"v_pub_file~v2-1.{1000 + self.init_count}", "upload_url": UPLOAD_URL})

    def _upload(self, request: httpx.Request) -> httpx.Response:
        match = re.match(r"bytes (\d+)-(\d+)/(\d+)", request.headers.get("content-range", ""))
        assert match, "Content-Range header is required"
        first, last, total = map(int, match.groups())
        length = int(request.headers["content-length"])
        assert length == last - first + 1, "Content-Length must equal the chunk size"
        self.calls.append(("upload", (first, last, total)))
        forced = self._next("upload")
        if forced is not None:
            return forced
        body = request.read()
        assert len(body) == length
        self.uploaded.append((first, last, total, dict(request.headers)))
        return httpx.Response(201 if last + 1 == total else 206)

    def _status(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append(("status", body))
        forced = self._next("status")
        if forced is not None:
            return forced
        failure = self._auth_failure(request)
        if failure:
            return failure
        index = min(self.status_calls, len(self.status_sequence) - 1)
        self.status_calls += 1
        return ok(dict(self.status_sequence[index]))
