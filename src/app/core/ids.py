"""Identifier generation.

UUIDv7 (RFC 9562) is the default primary key: a 48-bit millisecond timestamp followed by
random bits. It is opaque like UUIDv4 but monotonic, so inserts land at the right edge of
the index instead of scattering across it.

``uuid.uuid7`` exists from CPython 3.14; this module uses it when present and falls back
to a spec-compliant implementation otherwise, so the project runs on 3.13 today and picks
up the stdlib version automatically later.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Final

_STDLIB_UUID7: Final = getattr(uuid, "uuid7", None)


def _uuid7_fallback() -> uuid.UUID:
    timestamp_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (timestamp_ms & 0xFFFFFFFFFFFF) << 80 | rand
    value &= ~(0xF000 << 64)  # clear version nibble
    value |= 0x7000 << 64  # version 7
    value &= ~(0xC000 << 48)  # clear variant bits
    value |= 0x8000 << 48  # RFC 4122 variant
    return uuid.UUID(int=value)


def uuid7() -> uuid.UUID:
    """Return a time-ordered UUIDv7."""
    if _STDLIB_UUID7 is not None:
        result: uuid.UUID = _STDLIB_UUID7()
        return result
    return _uuid7_fallback()
