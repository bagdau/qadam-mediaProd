from dataclasses import dataclass


@dataclass(frozen=True)
class VideoLimits:
    minimum_seconds: float
    maximum_seconds: float
    maximum_bytes: int

    def validate(self, *, duration_seconds: float, size_bytes: int) -> None:
        if not self.minimum_seconds <= duration_seconds <= self.maximum_seconds:
            raise ValueError("video duration is outside TikTok limits")
        if not 0 < size_bytes <= self.maximum_bytes:
            raise ValueError("video size is outside TikTok limits")
