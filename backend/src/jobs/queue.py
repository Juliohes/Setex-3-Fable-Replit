"""Cola de jobs sobre PostgreSQL (sin Redis, modo Replit — ADR-0012).

Semántica at-least-once con `FOR UPDATE SKIP LOCKED`. La idempotencia real la
garantizan (a) `jobs.idempotency_key` UNIQUE y (b) `UNIQUE(invoice_id, engine)`
en `ocr_extractions` (ARQ-2): un reintento jamás duplica coste ni filas.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import uuid

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from security.models import Job
from shared.db import plain_session
from shared.logging import get_logger

log = get_logger(__name__)

_CLAIM = text(
    """
    UPDATE jobs SET status = 'running', locked_at = now(), attempts = attempts + 1
    WHERE id = (
        SELECT id FROM jobs
        WHERE status = 'queued' AND run_at <= now()
        ORDER BY run_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id, kind, payload, tenant_id, attempts, max_attempts
    """
)


async def enqueue(kind: str, idempotency_key: str, tenant_id: uuid.UUID, payload: dict) -> None:
    async with plain_session() as session:
        stmt = (
            pg_insert(Job)
            .values(kind=kind, idempotency_key=idempotency_key, tenant_id=tenant_id, payload=payload)
            .on_conflict_do_nothing(index_elements=[Job.idempotency_key])
        )
        await session.execute(stmt)


async def worker_loop(handlers: dict, poll_seconds: float = 2.0, stop: asyncio.Event | None = None) -> None:
    """Bucle del worker embebido (tarea asyncio dentro del proceso Reserved VM)."""
    stop = stop or asyncio.Event()
    while not stop.is_set():
        claimed = None
        try:
            async with plain_session() as session:
                row = (await session.execute(_CLAIM)).first()
                if row:
                    claimed = dict(row._mapping)
        except Exception as exc:
            log.error("jobs.claim_error", error=str(exc))
        if not claimed:
            try:
                await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
            except TimeoutError:
                pass
            continue
        handler = handlers.get(claimed["kind"])
        job_id = claimed["id"]
        try:
            if handler is None:
                raise RuntimeError(f"sin handler para {claimed['kind']}")
            await handler(claimed["tenant_id"], claimed["payload"])
            async with plain_session() as session:
                await session.execute(
                    text("UPDATE jobs SET status='done', locked_at=NULL WHERE id=:id"), {"id": job_id}
                )
        except Exception as exc:
            log.error("jobs.failed", job_id=str(job_id), error=str(exc))
            retry = claimed["attempts"] < claimed["max_attempts"]
            async with plain_session() as session:
                await session.execute(
                    text(
                        "UPDATE jobs SET status=:st, last_error=:err, locked_at=NULL, "
                        "run_at = now() + (interval '30 seconds' * attempts) WHERE id=:id"
                    ),
                    {"st": "queued" if retry else "failed", "err": str(exc)[:490], "id": job_id},
                )
