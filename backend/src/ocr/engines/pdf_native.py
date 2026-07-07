"""PDF con texto nativo: extracción directa sin OCR (capa 2 del plan, coste 0)."""
from __future__ import annotations

import io
import time
from decimal import Decimal

from ocr.engines.parsing import parse_text_to_fields
from ocr.schema import ExtractionResult, InvoiceFields


class PdfNativeEngine:
    name = "pdf_native"

    async def extract(self, content: bytes, mime: str) -> ExtractionResult:
        if mime != "application/pdf":
            return ExtractionResult(engine=self.name, fields=InvoiceFields(), error="no aplica")
        t0 = time.monotonic()
        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(content)) as pdf:
                text = "\n".join((page.extract_text() or "") for page in pdf.pages)
        except Exception as exc:  # PDF corrupto/escaneado sin texto
            return ExtractionResult(engine=self.name, fields=InvoiceFields(), error=str(exc)[:200])
        if len(text.strip()) < 40:
            return ExtractionResult(
                engine=self.name, fields=InvoiceFields(), error="PDF sin capa de texto"
            )
        fields = parse_text_to_fields(text)
        conf = {k: 0.98 for k, v in fields.model_dump().items() if v not in (None, [])}
        return ExtractionResult(
            engine=self.name,
            fields=fields,
            confidences=conf,
            raw={"chars": len(text)},
            duration_ms=int((time.monotonic() - t0) * 1000),
            cost_eur=Decimal("0"),
        )
