"""Minimal container inspection without external binaries.

For MP4/MOV the duration is read from the ``moov/mvhd`` atom. For other
containers (WebM) the duration is unknown server-side and the caller falls
back to the (untrusted) client-reported value; TikTok validates the file again.
"""

from __future__ import annotations

import struct
from pathlib import Path

ALLOWED_TYPES: dict[str, str] = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
}


def detect_content_type(head: bytes) -> str | None:
    import filetype

    kind = filetype.guess(head)
    if kind and kind.mime in ALLOWED_TYPES:
        return kind.mime
    return None


def mp4_duration_seconds(path: Path) -> float | None:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            return _find_mvhd(fh, 0, size, depth=0)
    except (OSError, struct.error, ValueError):
        return None


def _find_mvhd(fh, start: int, end: int, depth: int) -> float | None:
    pos = start
    while pos + 8 <= end:
        fh.seek(pos)
        header = fh.read(8)
        if len(header) < 8:
            return None
        box_size, box_type = struct.unpack(">I4s", header)
        header_len = 8
        if box_size == 1:
            box_size = struct.unpack(">Q", fh.read(8))[0]
            header_len = 16
        elif box_size == 0:
            box_size = end - pos
        if box_size < header_len:
            return None
        box_end = min(pos + box_size, end)
        if box_type == b"moov" and depth == 0:
            found = _find_mvhd(fh, pos + header_len, box_end, depth + 1)
            if found is not None:
                return found
        elif box_type == b"mvhd" and depth == 1:
            body = fh.read(min(box_end - pos - header_len, 32))
            version = body[0]
            if version == 1:
                timescale, duration = struct.unpack(">IQ", body[20:32])
            else:
                timescale, duration = struct.unpack(">II", body[12:20])
            return duration / timescale if timescale else None
        pos = box_end
    return None
