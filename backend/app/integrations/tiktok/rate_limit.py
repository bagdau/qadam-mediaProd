"""Per-token request budgets for TikTok endpoints (fixed window in Redis).

Official limits per user access token: creator_info 20/min, video init 6/min,
status fetch 30/min. We stay slightly below them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Budget:
    name: str
    limit: int
    window: int = 60


CREATOR_INFO = Budget("creator_info", 18)
VIDEO_INIT = Budget("video_init", 5)
STATUS_FETCH = Budget("status_fetch", 25)


class TikTokRateLimiter:
    """``redis`` is a ``redis.asyncio.Redis`` (or fakeredis equivalent)."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    async def acquire(self, account_key: str, budget: Budget) -> float:
        """Take one slot. Returns 0 when allowed, else seconds to wait."""
        now = time.time()
        window_id = int(now // budget.window)
        key = f"tt:rl:{budget.name}:{account_key}:{window_id}"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, budget.window + 5)
        if count <= budget.limit:
            return 0.0
        return max(1.0, budget.window - (now % budget.window) + 1)
