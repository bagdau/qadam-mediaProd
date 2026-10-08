from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    base_seconds: float = 2.0
    maximum_seconds: float = 300.0
    maximum_attempts: int = 6

    def delay(self, attempt: int) -> float:
        if attempt < 1:
            raise ValueError("attempt must be positive")
        return min(self.base_seconds * (2 ** (attempt - 1)), self.maximum_seconds)

    def allows(self, attempt: int) -> bool:
        return attempt < self.maximum_attempts
