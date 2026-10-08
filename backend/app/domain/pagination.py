from dataclasses import dataclass


@dataclass(frozen=True)
class PageRequest:
    limit: int = 50
    offset: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if self.offset < 0:
            raise ValueError("offset must be non-negative")

    @property
    def next_offset(self) -> int:
        return self.offset + self.limit
