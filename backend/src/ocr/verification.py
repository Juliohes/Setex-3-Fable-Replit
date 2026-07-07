"""Verificación determinista "tipo DNI" (ADR-0010). Módulo PURO: sin red, sin I/O.

Cierra los hallazgos de auditoría:
- BP-1: `check_invoice_totals` valida cada tramo con `check_tax_line` (ya no hay
  código muerto ni cuadre laxo: base×IVA% ≈ cuota POR TRAMO + total global).
- BP-2: claves de CIF N/W/R aceptan dígito O letra (decisión 2026-06-29, fuentes
  contradictorias; `python-stdnum` hace lo mismo). P/Q/S exigen letra; A/B/E/H dígito.
- BP-4: todos los validadores aceptan `str | None` (la regla anti-alucinación
  produce null; null ⇒ veredicto "no válido", nunca AttributeError).
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

TOLERANCE = Decimal("0.02")  # tolerancia de redondeo por importe

_NIF_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
_CIF_LETTER_ONLY = frozenset("PQS")
_CIF_DIGIT_ONLY = frozenset("ABEH")
_CIF_CONTROL_LETTERS = "JABCDEFGHI"
_NIF_RE = re.compile(r"^\d{8}[A-Z]$")
_NIE_RE = re.compile(r"^[XYZ]\d{7}[A-Z]$")
_CIF_RE = re.compile(r"^[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]$")


@dataclass(frozen=True)
class CheckResult:
    valid: bool
    reason: str


def _normalize(value: str | None) -> str:
    """Punto único de normalización. `None` ⇒ cadena vacía (BP-4)."""
    if value is None:
        return ""
    return re.sub(r"[\s.\-]", "", value).upper()


def validate_nif(value: str | None) -> CheckResult:
    v = _normalize(value)
    if not _NIF_RE.match(v):
        return CheckResult(False, "NIF con formato incorrecto (8 dígitos + letra)")
    expected = _NIF_LETTERS[int(v[:8]) % 23]
    if v[8] != expected:
        return CheckResult(False, f"Letra de control del NIF incorrecta (esperada {expected})")
    return CheckResult(True, "NIF válido")


def validate_nie(value: str | None) -> CheckResult:
    v = _normalize(value)
    if not _NIE_RE.match(v):
        return CheckResult(False, "NIE con formato incorrecto (X/Y/Z + 7 dígitos + letra)")
    digit = {"X": "0", "Y": "1", "Z": "2"}[v[0]]
    expected = _NIF_LETTERS[int(digit + v[1:8]) % 23]
    if v[8] != expected:
        return CheckResult(False, f"Letra de control del NIE incorrecta (esperada {expected})")
    return CheckResult(True, "NIE válido")


def validate_cif(value: str | None) -> CheckResult:
    v = _normalize(value)
    if not _CIF_RE.match(v):
        return CheckResult(False, "CIF con formato incorrecto (letra + 7 dígitos + control)")
    kind, digits, control = v[0], v[1:8], v[8]
    total = 0
    for i, ch in enumerate(digits):
        n = int(ch)
        if i % 2 == 0:  # posiciones impares (1ª, 3ª…): duplicar y sumar cifras
            n *= 2
            n = n // 10 + n % 10
        total += n
    control_digit = (10 - (total % 10)) % 10
    control_letter = _CIF_CONTROL_LETTERS[control_digit]

    if kind in _CIF_LETTER_ONLY:
        if control != control_letter:
            return CheckResult(False, f"Control del CIF incorrecto (esperada letra {control_letter})")
    elif kind in _CIF_DIGIT_ONLY:
        if control != str(control_digit):
            return CheckResult(False, f"Control del CIF incorrecto (esperado dígito {control_digit})")
    else:  # BP-2: resto de claves (incluye N/W/R): dígito o letra
        if control not in (str(control_digit), control_letter):
            return CheckResult(
                False,
                f"Control del CIF incorrecto (esperado {control_digit} o {control_letter})",
            )
    return CheckResult(True, "CIF válido")


def validate_tax_id(value: str | None) -> CheckResult:
    """Dispatcher NIF / NIE / CIF. Basura del OCR ⇒ 'no reconocido' (TST-2)."""
    v = _normalize(value)
    if not v:
        return CheckResult(False, "Identificador fiscal no legible")
    if _NIF_RE.match(v):
        return validate_nif(v)
    if _NIE_RE.match(v):
        return validate_nie(v)
    if _CIF_RE.match(v):
        return validate_cif(v)
    return CheckResult(False, "Identificador fiscal no reconocido (no es NIF, NIE ni CIF)")


def validate_iban(value: str | None, require_es: bool = True) -> CheckResult:
    v = _normalize(value)
    if not v:
        return CheckResult(False, "IBAN no legible")
    if len(v) > 34:
        return CheckResult(False, "IBAN demasiado largo")
    if require_es and (not v.startswith("ES") or len(v) != 24):
        return CheckResult(False, "IBAN español con formato incorrecto (ES + 22 dígitos)")
    if not re.match(r"^[A-Z]{2}\d{2}[A-Z0-9]+$", v):
        return CheckResult(False, "IBAN con caracteres inválidos")
    rearranged = v[4:] + v[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    if int(numeric) % 97 != 1:
        return CheckResult(False, "Checksum del IBAN incorrecto (módulo 97)")
    return CheckResult(True, "IBAN válido")


def _to_decimal(value: Decimal | str | float | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def check_tax_line(base: Decimal | None, iva_pct: Decimal | None, cuota: Decimal | None) -> CheckResult:
    """base × IVA% ≈ cuota (tolerancia 0,02 €)."""
    b, p, c = _to_decimal(base), _to_decimal(iva_pct), _to_decimal(cuota)
    if b is None or p is None or c is None:
        return CheckResult(False, "Tramo de IVA incompleto o no legible")
    expected = (b * p / Decimal(100)).quantize(Decimal("0.01"))
    if abs(expected - c) > TOLERANCE:
        return CheckResult(
            False, f"La cuota del tramo {p}% no cuadra: {b} × {p}% = {expected}, leída {c}"
        )
    return CheckResult(True, "Tramo de IVA cuadrado")


def check_invoice_totals(
    lines: list[tuple[Decimal | None, Decimal | None, Decimal | None]],
    irpf_cuota: Decimal | None,
    total: Decimal | None,
) -> CheckResult:
    """Cuadre global. BP-1: valida CADA tramo (base, iva_pct, cuota) y después
    Σbases + Σcuotas − IRPF ≈ total."""
    if not lines:
        return CheckResult(False, "Sin tramos de IVA legibles")
    t = _to_decimal(total)
    if t is None:
        return CheckResult(False, "Importe total no legible")
    sum_base = Decimal("0")
    sum_cuota = Decimal("0")
    for base, pct, cuota in lines:
        line_check = check_tax_line(base, pct, cuota)
        if not line_check.valid:
            return line_check
        sum_base += _to_decimal(base) or Decimal("0")
        sum_cuota += _to_decimal(cuota) or Decimal("0")
    irpf = _to_decimal(irpf_cuota) or Decimal("0")
    expected = (sum_base + sum_cuota - irpf).quantize(Decimal("0.01"))
    if abs(expected - t) > TOLERANCE:
        return CheckResult(
            False,
            f"Descuadre: bases {sum_base} + IVA {sum_cuota} − IRPF {irpf} = {expected}, total leído {t}",
        )
    return CheckResult(True, "Factura cuadrada")


def check_plausible_date(value: dt.date | None, today: dt.date | None = None) -> CheckResult:
    if value is None:
        return CheckResult(False, "Fecha no legible")
    today = today or dt.date.today()
    if abs((today - value).days) > 730:
        return CheckResult(False, f"Fecha implausible ({value.isoformat()}, fuera de ±2 años)")
    return CheckResult(True, "Fecha plausible")
