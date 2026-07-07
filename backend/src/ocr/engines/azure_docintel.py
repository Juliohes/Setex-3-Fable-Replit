"""Adapter Azure Document Intelligence `prebuilt-invoice` (West Europe)."""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from decimal import Decimal

import httpx

from ocr.engines.parsing import parse_amount
from ocr.schema import ExtractionResult, InvoiceFields, TaxLineFields

_API_VERSION = "2024-11-30"


def _field(doc_fields: dict, name: str) -> dict:
    return doc_fields.get(name) or {}


class AzureDocIntelEngine:
    name = "azure_docintel"

    def __init__(self, endpoint: str, key: str) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._key = key

    async def extract(self, content: bytes, mime: str) -> ExtractionResult:
        t0 = time.monotonic()
        url = (
            f"{self._endpoint}/documentintelligence/documentModels/prebuilt-invoice:analyze"
            f"?api-version={_API_VERSION}"
        )
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                resp = await client.post(
                    url,
                    headers={"Ocp-Apim-Subscription-Key": self._key, "Content-Type": mime},
                    content=content,
                )
                resp.raise_for_status()
                op_url = resp.headers["operation-location"]
                for _ in range(60):
                    await asyncio.sleep(1.5)
                    poll = await client.get(op_url, headers={"Ocp-Apim-Subscription-Key": self._key})
                    poll.raise_for_status()
                    body = poll.json()
                    if body.get("status") in ("succeeded", "failed"):
                        break
                if body.get("status") != "succeeded":
                    return ExtractionResult(
                        engine=self.name, fields=InvoiceFields(), error="analyze no completado"
                    )
            doc = (body.get("analyzeResult", {}).get("documents") or [{}])[0]
            f = doc.get("fields", {})
            confs: dict[str, float] = {}

            def take(name: str, canon: str) -> str | None:
                fd = _field(f, name)
                if fd.get("content") is None:
                    return None
                confs[canon] = float(fd.get("confidence", 0.5))
                return str(fd["content"])

            date_raw = _field(f, "InvoiceDate").get("valueDate")
            issue_date = dt.date.fromisoformat(date_raw) if date_raw else None
            if issue_date:
                confs["issue_date"] = float(_field(f, "InvoiceDate").get("confidence", 0.5))

            total_raw = _field(f, "InvoiceTotal").get("valueCurrency", {}).get("amount")
            total = Decimal(str(total_raw)).quantize(Decimal("0.01")) if total_raw is not None else None
            if total is not None:
                confs["total"] = float(_field(f, "InvoiceTotal").get("confidence", 0.5))

            lines: list[TaxLineFields] = []
            for item in _field(f, "TaxDetails").get("valueArray", []) or []:
                obj = item.get("valueObject", {})
                rate = obj.get("Rate", {}).get("content")
                amount = obj.get("Amount", {}).get("valueCurrency", {}).get("amount")
                base = obj.get("NetAmount", {}).get("valueCurrency", {}).get("amount")
                lines.append(
                    TaxLineFields(
                        iva_pct=parse_amount(str(rate).replace("%", "")) if rate else None,
                        base=Decimal(str(base)).quantize(Decimal("0.01")) if base is not None else None,
                        cuota=Decimal(str(amount)).quantize(Decimal("0.01")) if amount is not None else None,
                    )
                )

            fields = InvoiceFields(
                invoice_number=take("InvoiceId", "invoice_number"),
                issue_date=issue_date,
                counterparty_name=take("VendorName", "counterparty_name"),
                counterparty_cif=take("VendorTaxId", "counterparty_cif"),
                own_cif_as_read=take("CustomerTaxId", "own_cif_as_read"),
                total=total,
                tax_lines=lines,
            )
            pages = len(body.get("analyzeResult", {}).get("pages", [])) or 1
            return ExtractionResult(
                engine=self.name,
                fields=fields,
                confidences=confs,
                raw={"pages": pages},
                duration_ms=int((time.monotonic() - t0) * 1000),
                cost_eur=Decimal("0.009") * pages,
            )
        except Exception as exc:
            return ExtractionResult(engine=self.name, fields=InvoiceFields(), error=str(exc)[:300])
