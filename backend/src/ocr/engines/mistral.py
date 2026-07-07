"""Adapter Mistral OCR (La Plateforme, UE). Cabeza de serie del bench (§11.7).

Prompt de sistema estricto anti-alucinación: campo ilegible ⇒ null.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import time
from decimal import Decimal

import httpx

from ocr.engines.parsing import parse_amount
from ocr.schema import ExtractionResult, InvoiceFields, TaxLineFields

_SYSTEM = (
    "Eres un extractor de datos de facturas españolas. Las fechas en el documento están en "
    "formato español dd/mm/aaaa (el día va primero); conviértelas a YYYY-MM-DD sin cambiar el día "
    "por el mes. Devuelve SOLO un JSON con las claves: "
    "invoice_number, issue_date (YYYY-MM-DD), counterparty_name, counterparty_cif, "
    "own_cif_as_read, total, tax_lines (lista de {iva_pct, base, cuota}), irpf_pct, irpf_cuota, "
    "confidences (objeto campo->0..1). REGLA INNEGOCIABLE: si un campo no es legible con total "
    "certeza, devuelve null. PROHIBIDO inferir o completar CIFs, nombres o números parcialmente "
    "visibles. No añadas texto fuera del JSON."
)


def _to_fields(data: dict) -> tuple[InvoiceFields, dict[str, float]]:
    def dec(v: object) -> Decimal | None:
        return parse_amount(str(v)) if v is not None else None

    date = None
    if data.get("issue_date"):
        try:
            date = dt.date.fromisoformat(str(data["issue_date"])[:10])
        except ValueError:
            date = None
    lines = [
        TaxLineFields(iva_pct=dec(tl.get("iva_pct")), base=dec(tl.get("base")), cuota=dec(tl.get("cuota")))
        for tl in (data.get("tax_lines") or [])
        if isinstance(tl, dict)
    ]
    fields = InvoiceFields(
        invoice_number=data.get("invoice_number"),
        issue_date=date,
        counterparty_name=data.get("counterparty_name"),
        counterparty_cif=data.get("counterparty_cif"),
        own_cif_as_read=data.get("own_cif_as_read"),
        total=dec(data.get("total")),
        tax_lines=lines,
        irpf_pct=dec(data.get("irpf_pct")),
        irpf_cuota=dec(data.get("irpf_cuota")),
    )
    confs = {k: float(v) for k, v in (data.get("confidences") or {}).items() if isinstance(v, (int, float))}
    return fields, confs


class MistralOcrEngine:
    name = "mistral"

    def __init__(self, api_key: str, model: str = "mistral-small-latest") -> None:
        self._key = api_key
        self._model = model

    async def extract(self, content: bytes, mime: str) -> ExtractionResult:
        t0 = time.monotonic()
        b64 = base64.b64encode(content).decode()
        data_url = f"data:{mime};base64,{b64}"
        payload = {
            "model": self._model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extrae los campos de esta factura."},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.mistral.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self._key}"},
                    json=payload,
                )
                resp.raise_for_status()
                body = resp.json()
            raw_text = body["choices"][0]["message"]["content"]
            data = json.loads(raw_text)
            fields, confs = _to_fields(data)
            return ExtractionResult(
                engine=self.name,
                fields=fields,
                confidences=confs,
                raw={"usage": body.get("usage", {})},
                duration_ms=int((time.monotonic() - t0) * 1000),
                cost_eur=Decimal("0.004"),
            )
        except Exception as exc:
            return ExtractionResult(engine=self.name, fields=InvoiceFields(), error=str(exc)[:300])
