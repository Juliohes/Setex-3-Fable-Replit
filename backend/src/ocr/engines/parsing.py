"""Parsing determinista de texto de factura a campos canónicos.

Compartido por el motor PDF-nativo y como red de los motores cloud cuando
devuelven texto plano. Conservador a propósito: ante ambigüedad ⇒ None.
"""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, InvalidOperation

from ocr.schema import InvoiceFields, TaxLineFields

_TAX_ID_RE = re.compile(r"\b([ABCDEFGHJNPQRSUVW]\s?[\d.\s]{7,9}[0-9A-J]|[XYZ]?\d{7,8}\s?[A-Z])\b")
_DATE_RES = [
    (re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})\b"), "ymd"),
]
_TOTAL_RE = re.compile(
    r"(?:TOTAL(?:\s+FACTURA)?|IMPORTE\s+TOTAL|TOTAL\s+A\s+PAGAR)\D{0,12}([\d.,]+)", re.IGNORECASE
)
_IVA_LINE_RE = re.compile(
    r"(?:IVA|I\.V\.A\.?)\s*(?:AL\s*)?(\d{1,2}(?:[.,]\d{1,2})?)\s*%\D{0,20}?([\d.,]+)\D{1,20}?([\d.,]+)",
    re.IGNORECASE,
)
_IRPF_RE = re.compile(r"IRPF\s*\(?-?\s*(\d{1,2}(?:[.,]\d{1,2})?)\s*%\)?\D{0,12}([\d.,]+)", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?:FACTURA|FRA\.?|N[ºO°]|NUM\.?)\s*[:.\-]?\s*([A-Z0-9][A-Z0-9\-/]{1,30})",
                        re.IGNORECASE)


def parse_amount(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    s = raw.strip().replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def parse_date(text: str) -> dt.date | None:
    for rx, order in _DATE_RES:
        m = rx.search(text)
        if not m:
            continue
        try:
            if order == "dmy":
                return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
    return None


def parse_text_to_fields(text: str, own_cif: str | None = None) -> InvoiceFields:
    upper = text.upper()
    ids = ["".join(t.split()).replace(".", "") for t in _TAX_ID_RE.findall(upper)]
    own = "".join((own_cif or "").split()).upper()
    counterparty_cif = next((i for i in ids if i != own), None)
    own_read = own if own and own in ids else None

    m_total = _TOTAL_RE.search(upper)
    total = parse_amount(m_total.group(1)) if m_total else None

    lines: list[TaxLineFields] = []
    for pct, base, cuota in _IVA_LINE_RE.findall(upper):
        lines.append(
            TaxLineFields(iva_pct=parse_amount(pct), base=parse_amount(base), cuota=parse_amount(cuota))
        )

    irpf = _IRPF_RE.search(upper)
    m_num = _NUMBER_RE.search(upper)

    return InvoiceFields(
        invoice_number=m_num.group(1) if m_num else None,
        issue_date=parse_date(upper),
        counterparty_cif=counterparty_cif,
        counterparty_name=None,  # nombre: solo lo aportan motores con layout; aquí nunca se inventa
        own_cif_as_read=own_read,
        total=total,
        tax_lines=lines,
        irpf_pct=parse_amount(irpf.group(1)) if irpf else None,
        irpf_cuota=parse_amount(irpf.group(2)) if irpf else None,
    )
