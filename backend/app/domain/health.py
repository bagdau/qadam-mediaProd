from collections.abc import Mapping


def aggregate_health(checks: Mapping[str, bool]) -> tuple[str, dict[str, str]]:
    details = {name: "up" if healthy else "down" for name, healthy in sorted(checks.items())}
    return ("ready" if all(checks.values()) else "degraded", details)
