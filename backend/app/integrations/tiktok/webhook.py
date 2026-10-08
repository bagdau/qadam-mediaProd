from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WebhookEvent:
    event: str
    user_open_id: str | None
    content: dict[str, Any]


def parse_webhook(payload: dict[str, Any]) -> WebhookEvent:
    event = payload.get("event")
    if not isinstance(event, str) or not event:
        raise ValueError("webhook event is required")
    content = payload.get("content")
    if not isinstance(content, dict):
        content = {}
    open_id = payload.get("user_open_id")
    return WebhookEvent(event, open_id if isinstance(open_id, str) else None, content)
