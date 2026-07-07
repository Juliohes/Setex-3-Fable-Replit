"""Parsing determinista texto→campos (conservador: ambigüedad ⇒ None)."""
from decimal import Decimal

from ocr.engines.parsing import parse_amount, parse_text_to_fields


def test_parse_amount_formatos_es_en():
    assert parse_amount("1.234,56") == Decimal("1234.56")
    assert parse_amount("1,234.56") == Decimal("1234.56")
    assert parse_amount("121,00") == Decimal("121.00")
    assert parse_amount("basura") is None
    assert parse_amount(None) is None


def test_factura_texto_simple():
    text = """FACTURA Nº: 2026-0042
    Fecha: 15/06/2026
    Proveedor CIF: A58818501
    Cliente: B65410011
    Base IVA 21% 100,00 cuota 21,00
    TOTAL FACTURA 121,00"""
    fields = parse_text_to_fields(text, own_cif="B65410011")
    assert fields.counterparty_cif == "A58818501"
    assert fields.own_cif_as_read == "B65410011"
    assert fields.total == Decimal("121.00")
    assert fields.issue_date is not None and fields.issue_date.year == 2026
    assert fields.tax_lines and fields.tax_lines[0].iva_pct == Decimal("21")


def test_sin_datos_devuelve_none():
    fields = parse_text_to_fields("texto sin nada relevante")
    assert fields.total is None
    assert fields.counterparty_cif is None
    assert fields.tax_lines == []
