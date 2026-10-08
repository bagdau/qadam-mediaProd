# ruff: noqa: S101

from datetime import UTC, datetime, time, timedelta

from app.domain.audit_policy import sanitize_audit_details
from app.domain.leases import lease_deadline, lease_expired
from app.domain.locale import choose_locale
from app.domain.maintenance import in_maintenance_window
from app.domain.uploads import content_range, uploaded_percent


def test_nested_audit_secrets_are_redacted() -> None:
    details = {"access_token": "secret", "nested": [{"password": "hidden"}, {"safe": 1}]}
    assert sanitize_audit_details(details) == {
        "access_token": "[REDACTED]",
        "nested": [{"password": "[REDACTED]"}, {"safe": 1}],
    }


def test_time_and_upload_helpers_cover_boundaries() -> None:
    now = datetime(2026, 10, 9, 23, tzinfo=UTC)
    deadline = lease_deadline(now, seconds=30)
    assert not lease_expired(now, deadline)
    assert in_maintenance_window(now, start=time(22), end=time(2))
    assert content_range(0, 9, 10) == "bytes 0-9/10"
    assert uploaded_percent(3, 4) == 75
    assert deadline - now == timedelta(seconds=30)


def test_locale_negotiation_uses_supported_language() -> None:
    assert choose_locale("de;q=0.9, kk-KZ;q=0.8") == "kk"
