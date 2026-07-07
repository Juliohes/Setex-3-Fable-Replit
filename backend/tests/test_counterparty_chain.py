"""Cadena L1→L4 con dobles de las fuentes externas (sin red, S2.8)."""
import pytest

from ocr.counterparty.chain import _name_similar
from ocr.counterparty.outcome import CifStatus, NameMatch
from ocr.counterparty.resolvers.base import Resolution, TimeoutResolver


class _SlowResolver:
    source = "slow"

    async def resolve(self, cif):
        import asyncio

        await asyncio.sleep(5)
        return Resolution(resolved=True, exists=True)


class _BoomResolver:
    source = "boom"

    async def resolve(self, cif):
        raise RuntimeError("caída del tercero")


@pytest.mark.asyncio
async def test_timeout_no_bloquea():  # ARQ-6
    r = TimeoutResolver(_SlowResolver(), timeout_seconds=0.05)
    res = await r.resolve("A58818501")
    assert res.resolved is False


@pytest.mark.asyncio
async def test_excepcion_no_bloquea():
    r = TimeoutResolver(_BoomResolver(), timeout_seconds=1)
    res = await r.resolve("A58818501")
    assert res.resolved is False


def test_similitud_nombres():
    assert _name_similar("ENDESA ENERGIA S.A.U.", "ENDESA ENERGIA SAU") is NameMatch.match
    assert _name_similar("FERRETERIA PACO SL", "ENDESA ENERGIA SAU") is NameMatch.mismatch
    assert _name_similar(None, "ENDESA") is NameMatch.unknown


def test_outcome_enums_estables():
    assert CifStatus.invalid.value == "invalid"
    assert CifStatus.not_found.value == "not_found"
