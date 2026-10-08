# ruff: noqa: S101

import hashlib
import hmac
from datetime import UTC, datetime

from app.integrations.tiktok.captions import caption_entities
from app.integrations.tiktok.retry_headers import retry_after_seconds
from app.integrations.tiktok.signatures import verify_signature
from app.integrations.tiktok.status import classify_publish_status
from app.integrations.tiktok.urls import validate_upload_url


def test_caption_entities_and_status_mapping() -> None:
    assert caption_entities("Hi @qadam.media #Qadam") == {"mentions": ["@qadam.media"], "hashtags": ["#Qadam"]}
    assert classify_publish_status("PUBLISH_COMPLETE") == "success"
    assert classify_publish_status("SOMETHING_NEW") == "unknown"


def test_retry_after_supports_seconds_and_http_dates() -> None:
    now = datetime(2026, 10, 9, 0, 0, tzinfo=UTC)
    assert retry_after_seconds("15", now=now) == 15
    assert retry_after_seconds("Fri, 09 Oct 2026 00:01:00 GMT", now=now) == 60


def test_upload_url_and_signature_validation() -> None:
    assert validate_upload_url("https://upload.example/video", allowed_hosts=frozenset({"upload.example"}))
    payload, secret = b"{}", "secret"
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert verify_signature(payload, f"sha256={signature}", secret)
