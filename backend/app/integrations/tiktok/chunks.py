"""Chunk planning for FILE_UPLOAD (TikTok Media Transfer Guide).

* each chunk is 5-64 MB, the *final* chunk may be up to 128 MB;
* ``total_chunk_count = floor(video_size / chunk_size)``;
* files smaller than 5 MB (and any file up to 64 MB here) go in a single request
  with ``chunk_size == video_size``;
* 1..1000 chunks, uploaded strictly sequentially.
"""

from __future__ import annotations

from dataclasses import dataclass

MIB = 1024 * 1024
MIN_CHUNK = 5 * MIB
MAX_CHUNK = 64 * MIB
MAX_FINAL_CHUNK = 128 * MIB
MAX_CHUNKS = 1000
MAX_VIDEO_SIZE = 4 * 1024 * MIB  # 4 GB
SINGLE_REQUEST_LIMIT = 64 * MIB
DEFAULT_CHUNK = 32 * MIB


@dataclass(frozen=True)
class ChunkPlan:
    video_size: int
    chunk_size: int
    total_chunks: int

    def ranges(self) -> list[tuple[int, int]]:
        """Inclusive byte ranges ``(first, last)`` in upload order."""
        out: list[tuple[int, int]] = []
        for index in range(self.total_chunks):
            first = index * self.chunk_size
            last = self.video_size - 1 if index == self.total_chunks - 1 else first + self.chunk_size - 1
            out.append((first, last))
        return out

    def range_at(self, offset: int) -> tuple[int, int] | None:
        """The chunk range that starts exactly at ``offset`` (None when upload is complete)."""
        for first, last in self.ranges():
            if first == offset:
                return first, last
        return None


def plan_chunks(video_size: int) -> ChunkPlan:
    if video_size <= 0:
        raise ValueError("video_size must be positive")
    if video_size > MAX_VIDEO_SIZE:
        raise ValueError("video exceeds the 4 GB TikTok limit")
    if video_size <= SINGLE_REQUEST_LIMIT:
        return ChunkPlan(video_size, video_size, 1)
    chunk = DEFAULT_CHUNK
    total = video_size // chunk
    last = video_size - (total - 1) * chunk
    while last > MAX_FINAL_CHUNK or total > MAX_CHUNKS:  # pragma: no cover - only for >4 GB
        chunk = min(chunk * 2, MAX_CHUNK)
        total = video_size // chunk
        last = video_size - (total - 1) * chunk
        if chunk == MAX_CHUNK:
            break
    return ChunkPlan(video_size, chunk, total)
