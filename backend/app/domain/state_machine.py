TERMINAL = frozenset({"PUBLISHED", "INBOX_DELIVERED", "FAILED", "NEEDS_REVIEW", "CANCELLED"})
TRANSITIONS: dict[str, frozenset[str]] = {
    "QUEUED": frozenset({"INITIATING", "CANCELLED"}),
    "INITIATING": frozenset({"UPLOADING", "FAILED", "NEEDS_REVIEW"}),
    "UPLOADING": frozenset({"PROCESSING", "FAILED", "NEEDS_REVIEW"}),
    "PROCESSING": frozenset({"PUBLISHED", "INBOX_DELIVERED", "FAILED", "NEEDS_REVIEW"}),
    "FAILED": frozenset({"QUEUED"}),
}


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, frozenset())


def require_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        raise ValueError(f"invalid publication transition: {current} -> {target}")
