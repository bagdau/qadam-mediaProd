import uuid


def new_id() -> uuid.UUID:
    """Return a sortable-agnostic, collision-resistant domain identifier."""
    return uuid.uuid4()


def parse_id(value: str, *, field: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{field} must be a valid UUID") from exc
