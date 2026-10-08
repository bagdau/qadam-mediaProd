PRIVACY_LEVELS = (
    "PUBLIC_TO_EVERYONE",
    "MUTUAL_FOLLOW_FRIENDS",
    "FOLLOWER_OF_CREATOR",
    "SELF_ONLY",
)


def ordered_privacy_options(values: list[str]) -> list[str]:
    allowed = set(values)
    return [value for value in PRIVACY_LEVELS if value in allowed]
