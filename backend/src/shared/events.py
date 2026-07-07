"""Bus de eventos de dominio in-process (PAT-8: síncrono, sin Redis).

ARQ-8: `ocr` emite; `invoice_intake` reacciona. La dependencia fluye en una
sola dirección a través de este módulo compartido.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

Handler = Callable[[Any], Awaitable[None]]


@dataclass
class EventBus:
    _handlers: dict[type, list[Handler]] = field(default_factory=lambda: defaultdict(list))

    def subscribe(self, event_type: type, handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: Any) -> None:
        for handler in self._handlers[type(event)]:
            await handler(event)


bus = EventBus()


@dataclass(frozen=True)
class OcrCompleted:
    invoice_id: str
    tenant_id: str
