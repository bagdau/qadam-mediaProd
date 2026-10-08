# ruff: noqa: S101

import pytest

from app.domain.retry import RetryPolicy
from app.domain.state_machine import can_transition, require_transition


def test_publication_state_machine_allows_documented_path() -> None:
    assert can_transition("QUEUED", "INITIATING")
    assert can_transition("PROCESSING", "PUBLISHED")
    assert not can_transition("PUBLISHED", "QUEUED")


def test_invalid_transition_raises_clear_error() -> None:
    with pytest.raises(ValueError, match="PUBLISHED -> QUEUED"):
        require_transition("PUBLISHED", "QUEUED")


def test_retry_delay_is_capped() -> None:
    policy = RetryPolicy(base_seconds=2, maximum_seconds=10)
    assert [policy.delay(attempt) for attempt in range(1, 6)] == [2, 4, 8, 10, 10]
