PRIVACY_LEVELS = frozenset(
    {"PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"}
)


def select_privacy(requested: str, allowed: list[str], *, client_audited: bool) -> str:
    if requested not in PRIVACY_LEVELS or requested not in allowed:
        raise ValueError("privacy level is unavailable")
    if not client_audited and requested != "SELF_ONLY":
        raise ValueError("unaudited clients must use SELF_ONLY")
    return requested
