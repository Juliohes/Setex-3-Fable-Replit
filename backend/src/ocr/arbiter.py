"""Árbitro por campo (ARQ-7): función pura y testeable, sin red ni estado.

Regla: coinciden ⇒ aceptar · discrepan ⇒ gana quien pase la validación
determinista · nadie la pasa ⇒ None + marca "revisar" (anti-alucinación).
Añadir un motor = añadir un ExtractionResult a la lista; el árbitro no cambia.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from ocr.schema import ExtractionResult, InvoiceFields, TaxLineFields
from ocr.verification import check_plausible_date, validate_tax_id

REVIEW_CONFIDENCE_THRESHOLD = 0.85


@dataclass(frozen=True)
class ArbitrationResult:
    fields: InvoiceFields
    flags: dict[str, str] = field(default_factory=dict)  # campo → 'ok'|'review'|'missing'
    winners: dict[str, str] = field(default_factory=dict)  # campo → motor ganador


def _norm(v: object) -> object:
    if isinstance(v, str):
        return " ".join(v.split()).upper()
    return v


def _pick(
    name: str,
    values: list[tuple[str, object, float]],
    validator=None,
) -> tuple[object, str, str]:
    """Devuelve (valor, flag, motor). Solo valores no-None compiten."""
    present = [(eng, v, conf) for eng, v, conf in values if v is not None]
    if not present:
        return None, "missing", ""
    normed = {repr(_norm(v)) for _, v, _ in present}
    if len(normed) == 1:
        eng, v, conf = max(present, key=lambda t: t[2])
        flag = "ok" if conf >= REVIEW_CONFIDENCE_THRESHOLD else "review"
        if validator is not None and not validator(v):
            return None, "review", ""
        return v, flag, eng
    # Discrepancia: gana el que pase la validación determinista.
    if validator is not None:
        passing = [(eng, v, conf) for eng, v, conf in present if validator(v)]
        if len({repr(_norm(v)) for _, v, _ in passing}) == 1:
            eng, v, conf = max(passing, key=lambda t: t[2])
            return v, "review", eng
    return None, "review", ""


def _valid_cif(v: object) -> bool:
    return isinstance(v, str) and validate_tax_id(v).valid


def _valid_date(v: object) -> bool:
    return isinstance(v, dt.date) and check_plausible_date(v).valid


def _valid_amount(v: object) -> bool:
    try:
        return v is not None and Decimal(str(v)) >= 0
    except Exception:
        return False


def arbitrate(results: list[ExtractionResult]) -> ArbitrationResult:
    ok = [r for r in results if r.error is None]
    if not ok:
        return ArbitrationResult(fields=InvoiceFields(), flags={"_all": "missing"})

    def collect(attr: str) -> list[tuple[str, object, float]]:
        return [(r.engine, getattr(r.fields, attr), r.confidences.get(attr, 0.5)) for r in ok]

    flags: dict[str, str] = {}
    winners: dict[str, str] = {}
    out: dict[str, object] = {}

    spec = [
        ("invoice_number", None),
        ("issue_date", _valid_date),
        ("counterparty_name", None),
        ("counterparty_cif", _valid_cif),
        ("own_cif_as_read", None),
        ("total", _valid_amount),
        ("irpf_pct", _valid_amount),
        ("irpf_cuota", _valid_amount),
    ]
    for name, validator in spec:
        value, flag, eng = _pick(name, collect(name), validator)
        out[name] = value
        flags[name] = flag
        if eng:
            winners[name] = eng

    # Tramos de IVA: gana el conjunto del motor con mayor confianza media que
    # tenga tramos; si ninguno tiene, lista vacía + missing.
    with_lines = [r for r in ok if r.fields.tax_lines]
    if with_lines:
        best = max(
            with_lines,
            key=lambda r: sum(r.confidences.get(k, 0.5) for k in ("total", "counterparty_cif")),
        )
        out["tax_lines"] = [TaxLineFields(**tl.model_dump()) for tl in best.fields.tax_lines]
        flags["tax_lines"] = "ok" if len(with_lines) > 1 else "review"
        winners["tax_lines"] = best.engine
    else:
        out["tax_lines"] = []
        flags["tax_lines"] = "missing"

    return ArbitrationResult(fields=InvoiceFields(**out), flags=flags, winners=winners)
