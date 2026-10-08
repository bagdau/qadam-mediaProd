from dataclasses import dataclass


@dataclass(frozen=True)
class RateWindow:
    limit: int
    seconds: int

    def __post_init__(self) -> None:
        if self.limit < 1 or self.seconds < 1:
            raise ValueError("rate window values must be positive")

    def remaining(self, used: int) -> int:
        return max(0, self.limit - max(0, used))
