"""Generador UUIDv7 (RFC 9562) puro, sin dependencias.

Decisión BD-4 de la auditoría: UUIDv7 combina la no-enumerabilidad de UUIDv4
(mitiga IDOR) con la ordenación temporal (índices B-tree compactos).
"""
from __future__ import annotations

import os
import time
import uuid

_last_ts_ms = 0
_seq = 0


def uuid7() -> uuid.UUID:
    """UUIDv7: 48 bits de epoch-ms + versión + aleatorio.

    Monotónico dentro del mismo milisegundo mediante contador en rand_a.
    """
    global _last_ts_ms, _seq
    ts_ms = time.time_ns() // 1_000_000
    if ts_ms == _last_ts_ms:
        _seq = (_seq + 1) & 0x0FFF
    else:
        _last_ts_ms = ts_ms
        _seq = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFF_FFFF_FFFF_FFFF
    value = (ts_ms & 0xFFFF_FFFF_FFFF) << 80
    value |= 0x7 << 76
    value |= _seq << 64
    value |= 0b10 << 62
    value |= rand_b
    return uuid.UUID(int=value)
