"""Contrato canónico entre motores, árbitro y persistencia (PAT-2: mínimo común)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, Field


class TaxLineFields(BaseModel):
    iva_pct: Decimal | None = None
    base: Decimal | None = None
    cuota: Decimal | None = None


class InvoiceFields(BaseModel):
    """Campos de oro (§3.6 regla 10): fecha, importes y CIF de la CONTRAPARTE.

    Regla anti-alucinación (Regla de Oro #4): campo no legible ⇒ None. Nunca
    se inventa ni se completa un valor parcialmente visible.
    """

    invoice_number: str | None = None
    issue_date: dt.date | None = None
    counterparty_name: str | None = None
    counterparty_cif: str | None = None
    own_cif_as_read: str | None = None   # solo anti-foto-equivocada; NUNCA rellena datos propios
    total: Decimal | None = None
    tax_lines: list[TaxLineFields] = Field(default_factory=list)
    irpf_pct: Decimal | None = None
    irpf_cuota: Decimal | None = None


class ExtractionResult(BaseModel):
    engine: str
    fields: InvoiceFields
    confidences: dict[str, float] = Field(default_factory=dict)  # 0..1 por campo
    raw: dict = Field(default_factory=dict)
    duration_ms: int = 0
    cost_eur: Decimal = Decimal("0")
    error: str | None = None
