"""Servicio de audit log append-only con cadena de hashes por tenant (BD-7).

`chain_hash_n = SHA256(payload_hash_n ‖ chain_hash_{n-1})`: alterar o borrar
una fila rompe la verificación de toda la cadena posterior.
"""
from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from security.models import AuditLog

GENESIS = "0" * 64


def _sha(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


async def write_audit(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID | None,
    actor_type: str,
    actor_id: uuid.UUID | None,
    action: str,
    entity: str,
    entity_id: str | None = None,
    payload: dict | None = None,
) -> None:
    payload = payload or {}
    payload_hash = _sha(json.dumps(payload, sort_keys=True, default=str))
    last = await session.execute(
        select(AuditLog.chain_hash)
        .where(AuditLog.tenant_id == tenant_id)
        .order_by(AuditLog.seq.desc())
        .limit(1)
        .with_for_update()
    )
    prev = last.scalar_one_or_none() or GENESIS
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity=entity,
            entity_id=entity_id,
            payload=payload,
            payload_hash=payload_hash,
            prev_hash=prev,
            chain_hash=_sha(payload_hash + prev),
        )
    )
