"""Rate limiting mínimo en memoria (ventana deslizante).

En Reserved VM de Replit hay un único proceso ⇒ suficiente para proteger
login/registro sin infra adicional. Si algún día hay N réplicas, migrar a
un limitador respaldado por Postgres/Redis (documentado en ADR-0012).
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request

from shared.exceptions import DomainError


class RateLimitExceeded(DomainError):
    status_code = 429


_buckets: dict[str, deque[float]] = defaultdict(deque)


def limit(key_prefix: str, max_calls: int, window_seconds: int):
    async def dependency(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        key = f"{key_prefix}:{ip}"
        now = time.monotonic()
        bucket = _buckets[key]
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        if len(bucket) >= max_calls:
            raise RateLimitExceeded("Demasiados intentos: espera un momento")
        bucket.append(now)

    return dependency
