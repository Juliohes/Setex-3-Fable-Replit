"""Cadena de verificación del CIF de contraparte (§11.8, ADR-0011, PAT-4).

Orden por coste con early-exit:
  L1 estructura (puro)  →  L2 supplier master del tenant  →  L4 caché global
  →  L3 resolución externa (VIES / AEAT según feature flags del tenant).

Veredictos (regla 11-12 del plan):
  · L1 inválido            ⇒ invalid  (BLOQUEA)
  · Fuente dice "no existe"⇒ not_found (BLOQUEA)
  · Existe, nombre ≠ leído ⇒ valid + mismatch (AVISO con razón social oficial)
  · Nadie resuelve         ⇒ unverified (NO bloquea: "Revisar manual", ARQ-6)
"""
from __future__ import annotations

import datetime as dt
import difflib
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ocr.counterparty.outcome import CifStatus, NameMatch, VerificationOutcome
from ocr.counterparty.resolvers.base import CifResolver, Resolution, TimeoutResolver
from ocr.models import CifLookup, Counterparty
from ocr.verification import validate_tax_id
from shared.config import Settings

_NOT_FOUND_TTL = 60 * 60 * 24 * 3  # BD-10: TTL corto para "no existe"


def _name_similar(read: str | None, official: str | None) -> NameMatch:
    if not read or not official:
        return NameMatch.unknown
    a = " ".join(read.upper().split())
    b = " ".join(official.upper().split())
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    return NameMatch.match if ratio >= 0.72 or a in b or b in a else NameMatch.mismatch


def build_resolvers(settings: Settings, tenant_features: dict) -> list[CifResolver]:
    """Adapters activos según config global + feature flags del tenant (§11.8.3)."""
    resolvers: list[CifResolver] = []
    if settings.aeat_censal_enabled and tenant_features.get("cif_aeat", True):
        from ocr.counterparty.resolvers.aeat import AeatCensalResolver

        resolvers.append(AeatCensalResolver(settings.aeat_cert_path, settings.aeat_key_path))
    if settings.vies_enabled and tenant_features.get("cif_vies", True):
        from ocr.counterparty.resolvers.vies import ViesResolver

        resolvers.append(ViesResolver())
    return [TimeoutResolver(r, settings.external_resolver_timeout_seconds) for r in resolvers]


async def verify_counterparty_cif(
    tenant_session: AsyncSession,
    infra_session: AsyncSession,
    cif: str | None,
    name_read: str | None,
    resolvers: list[CifResolver],
) -> VerificationOutcome:
    # L1 · Estructura (barato, puro, ya bloqueante)
    l1 = validate_tax_id(cif)
    if not l1.valid:
        return VerificationOutcome(
            status=CifStatus.invalid,
            name_match=NameMatch.unknown,
            source="structure",
            blocking=True,
            official_name=None,
            reason=l1.reason,
        )
    clean = "".join((cif or "").split()).upper()

    # L2 · Supplier master del tenant (gratis; mejora con el uso)
    row = await tenant_session.execute(select(Counterparty).where(Counterparty.cif == clean))
    master = row.scalar_one_or_none()
    if master is not None:
        match = _name_similar(name_read, master.name)
        return VerificationOutcome(
            status=CifStatus.valid,
            name_match=match,
            source="supplier_master",
            blocking=False,
            official_name=master.name,
            reason="CIF ya confirmado anteriormente en esta asesoría",
        )

    # L4 · Caché global (BD-2: jamás expuesta al tenant; solo aquí)
    now = dt.datetime.now(dt.UTC)
    cached = await infra_session.execute(select(CifLookup).where(CifLookup.cif == clean))
    for lk in cached.scalars():
        if lk.fetched_at and (now - lk.fetched_at).total_seconds() < lk.ttl_seconds:
            if lk.exists:
                match = _name_similar(name_read, lk.official_name)
                return VerificationOutcome(
                    status=CifStatus.valid,
                    name_match=match,
                    source=f"cache:{lk.source}",
                    blocking=False,
                    official_name=lk.official_name,
                    reason="CIF verificado (caché de resoluciones)",
                )

    # L3 · Resolución externa, en orden de autoridad
    for resolver in resolvers:
        res: Resolution = await resolver.resolve(clean)
        if not res.resolved:
            continue
        stmt = (
            pg_insert(CifLookup)
            .values(
                cif=clean,
                source=resolver.source,
                exists=res.exists,
                official_name=res.official_name,
                raw_json=res.raw or {},
                fetched_at=now,
                ttl_seconds=(60 * 60 * 24 * 30) if res.exists else _NOT_FOUND_TTL,
            )
            .on_conflict_do_update(
                index_elements=[CifLookup.cif, CifLookup.source],
                set_={
                    "exists": res.exists,
                    "official_name": res.official_name,
                    "fetched_at": now,
                },
            )
        )
        await infra_session.execute(stmt)
        if res.exists:
            match = _name_similar(name_read, res.official_name)
            return VerificationOutcome(
                status=CifStatus.valid,
                name_match=match,
                source=resolver.source,
                blocking=False,
                official_name=res.official_name,
                reason=f"CIF verificado en {resolver.source.upper()}",
            )
        if resolver.source == "aeat":
            # Solo la fuente autoritativa puede afirmar inexistencia (VIES no cubre nacional).
            return VerificationOutcome(
                status=CifStatus.not_found,
                name_match=NameMatch.unknown,
                source=resolver.source,
                blocking=True,
                official_name=None,
                reason="El CIF no consta en el censo de la AEAT",
            )

    # Nadie resolvió (fuentes caídas / cobertura): NO bloquear (ARQ-6)
    return VerificationOutcome(
        status=CifStatus.unverified,
        name_match=NameMatch.unknown,
        source="none",
        blocking=False,
        official_name=None,
        reason="No se pudo verificar el CIF en fuentes externas: revisar manualmente",
    )


async def upsert_supplier_master(
    tenant_session: AsyncSession,
    tenant_id: uuid.UUID,
    cif: str,
    name: str,
    source: str = "human",
) -> None:
    """Cada confirmación humana alimenta el supplier master (regla 13).
    BD-13: times_seen con UPDATE atómico, no read-modify-write."""
    clean = "".join(cif.split()).upper()
    stmt = (
        pg_insert(Counterparty)
        .values(tenant_id=tenant_id, cif=clean, name=name, name_source=source, times_seen=1)
        .on_conflict_do_update(
            index_elements=[Counterparty.tenant_id, Counterparty.cif],
            set_={"times_seen": Counterparty.times_seen + 1, "name": name},
        )
    )
    await tenant_session.execute(stmt)
