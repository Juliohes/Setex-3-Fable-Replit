"""Árbitro por campo (ARQ-7): coinciden / discrepan / nadie pasa."""
import datetime as dt
from decimal import Decimal

from ocr.arbiter import arbitrate
from ocr.schema import ExtractionResult, InvoiceFields


def _res(engine, conf=0.95, **fields):
    return ExtractionResult(
        engine=engine, fields=InvoiceFields(**fields),
        confidences={k: conf for k in fields},
    )


def test_coinciden_acepta():
    a = _res("m1", counterparty_cif="A58818501", total=Decimal("121.00"))
    b = _res("m2", counterparty_cif="A58818501", total=Decimal("121.00"))
    out = arbitrate([a, b])
    assert out.fields.counterparty_cif == "A58818501"
    assert out.flags["counterparty_cif"] == "ok"


def test_discrepan_gana_el_que_valida():
    a = _res("m1", counterparty_cif="A58818501")   # CIF válido
    b = _res("m2", counterparty_cif="A58818502")   # control incorrecto
    out = arbitrate([a, b])
    assert out.fields.counterparty_cif == "A58818501"
    assert out.flags["counterparty_cif"] == "review"
    assert out.winners["counterparty_cif"] == "m1"


def test_nadie_pasa_devuelve_null():
    a = _res("m1", counterparty_cif="A58818502")
    b = _res("m2", counterparty_cif="B65410013")
    out = arbitrate([a, b])
    assert out.fields.counterparty_cif is None      # anti-alucinación
    assert out.flags["counterparty_cif"] == "review"


def test_confianza_baja_marca_review():
    a = _res("m1", conf=0.4, issue_date=dt.date(2026, 6, 1))
    out = arbitrate([a])
    assert out.fields.issue_date == dt.date(2026, 6, 1)
    assert out.flags["issue_date"] == "review"


def test_campo_ausente_missing():
    out = arbitrate([_res("m1")])
    assert out.fields.total is None
    assert out.flags["total"] == "missing"


def test_motores_con_error_se_ignoran():
    err = ExtractionResult(engine="caido", fields=InvoiceFields(), error="timeout")
    ok = _res("m1", total=Decimal("50.00"))
    out = arbitrate([err, ok])
    assert out.fields.total == Decimal("50.00")
