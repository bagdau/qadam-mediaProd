from __future__ import annotations

import struct


def make_mp4(duration_s: float = 12.0, payload_size: int = 2048, timescale: int = 1000) -> bytes:
    """Smallest structure that looks like an MP4 to ``filetype`` and carries a real mvhd duration."""
    ftyp = b"ftyp" + b"isom" + struct.pack(">I", 512) + b"isomiso2mp41"
    ftyp = struct.pack(">I", len(ftyp) + 4) + ftyp
    mvhd_body = (
        b"\x00\x00\x00\x00"  # version/flags
        + struct.pack(">IIII", 0, 0, timescale, int(duration_s * timescale))
        + b"\x00" * 80
    )
    mvhd = struct.pack(">I", len(mvhd_body) + 8) + b"mvhd" + mvhd_body
    moov = struct.pack(">I", len(mvhd) + 8) + b"moov" + mvhd
    mdat = struct.pack(">I", payload_size + 8) + b"mdat" + (b"\x5a" * payload_size)
    return ftyp + moov + mdat


def make_webm() -> bytes:
    return bytes.fromhex("1a45dfa3") + b"\x9f\x42\x86\x81\x01B\xf7\x81\x01B\xf2\x81\x04B\xf3\x81\x08B\x82\x84webm" + b"\x00" * 128
