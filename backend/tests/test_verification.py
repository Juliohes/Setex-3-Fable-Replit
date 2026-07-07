"""Cierra TST-1..4 de la auditoría: ramas del CIF, dispatcher basura, fronteras
de tolerancia 0,02/0,03 y aserciones sobre `.reason` (contrato de UI)."""
import datetime as dt
from decimal import Decimal

import pytest

from ocr.verification import (
    check_invoice_totals,
    check_plausible_date,
    check_tax_line,
    validate_cif,
    validate_iban,
    validate_nie,
    validate_nif,
    validate_tax_id,
)


class TestNifNie:
    def test_nif_valido(self):
        assert validate_nif("12345678Z").valid

    def test_nif_letra_incorrecta_con_reason(self):
        res = validate_nif("12345678A")
        assert not res.valid
        assert "esperada Z" in res.reason

    def test_nie_valido(self):
        assert validate_nie("X1234567L").valid

    def test_none_no_explota(self):  # BP-4
        for fn in (validate_nif, validate_nie, validate_cif, validate_tax_id, validate_iban):
            res = fn(None)
            assert not res.valid
            assert res.reason


class TestCifRamas:
    """TST-1: ramas letra-vs-dígito, incluidas las de mismatch."""

    def test_abeh_exige_digito(self):
        assert validate_cif("A58818501").valid          # control dígito correcto
        res = validate_cif("A5881850A")                  # letra donde va dígito
        assert not res.valid
        assert "dígito" in res.reason

    def test_pqs_exige_letra(self):
        assert validate_cif("P2807900B").valid           # ayuntamiento (letra)
        res = validate_cif("P28079002")                  # dígito donde va letra
        assert not res.valid
        assert "letra" in res.reason

    def test_resto_acepta_ambos(self):  # BP-2: N/W/R y demás
        assert validate_cif("B65410011").valid
        res = validate_cif("B65410012")
        assert not res.valid
        assert "esperado" in res.reason


class TestDispatcher:
    def test_basura_ocr_no_reconocida(self):  # TST-2
        res = validate_tax_id("??-borroso-99")
        assert not res.valid
        assert "no reconocido" in res.reason

    def test_vacio(self):
        res = validate_tax_id("   ")
        assert not res.valid
        assert "no legible" in res.reason

    @pytest.mark.parametrize("value,ok", [("12345678Z", True), ("X1234567L", True), ("A58818501", True)])
    def test_despacha(self, value, ok):
        assert validate_tax_id(value).valid is ok


class TestIban:
    def test_es_valido(self):
        assert validate_iban("ES91 2100 0418 4502 0005 1332").valid

    def test_checksum_malo(self):
        res = validate_iban("ES9121000418450200051333")
        assert not res.valid
        assert "módulo 97" in res.reason

    def test_demasiado_largo_corta_antes(self):
        assert not validate_iban("ES" + "1" * 40, require_es=False).valid


class TestFronterasTolerancia:
    """TST-3: 0,02 pasa / 0,03 falla. Un cambio de > a >= rompería estos tests."""

    def test_tramo_diff_002_valido(self):
        assert check_tax_line(Decimal("100"), Decimal("21"), Decimal("21.02")).valid

    def test_tramo_diff_003_invalido(self):
        res = check_tax_line(Decimal("100"), Decimal("21"), Decimal("21.03"))
        assert not res.valid
        assert "no cuadra" in res.reason

    def test_total_diff_002_valido(self):
        lines = [(Decimal("100"), Decimal("21"), Decimal("21"))]
        assert check_invoice_totals(lines, None, Decimal("121.02")).valid

    def test_total_diff_003_invalido(self):
        lines = [(Decimal("100"), Decimal("21"), Decimal("21"))]
        res = check_invoice_totals(lines, None, Decimal("121.03"))
        assert not res.valid
        assert "Descuadre" in res.reason


class TestCuadre:
    def test_bp1_cada_tramo_se_valida(self):
        """BP-1 cerrado: una cuota de tramo incoherente falla aunque el total cuadre."""
        lines = [(Decimal("100"), Decimal("21"), Decimal("30"))]  # 21% de 100 NO es 30
        res = check_invoice_totals(lines, None, Decimal("130"))
        assert not res.valid
        assert "21" in res.reason

    def test_con_irpf(self):
        lines = [(Decimal("1000"), Decimal("21"), Decimal("210"))]
        assert check_invoice_totals(lines, Decimal("150"), Decimal("1060")).valid

    def test_tramo_ilegible(self):
        res = check_invoice_totals([(None, Decimal("21"), Decimal("21"))], None, Decimal("121"))
        assert not res.valid
        assert "incompleto" in res.reason


class TestFecha:
    def test_plausible(self):
        assert check_plausible_date(dt.date.today()).valid

    def test_fuera_de_rango(self):
        res = check_plausible_date(dt.date(2019, 1, 1), today=dt.date(2026, 7, 3))
        assert not res.valid
        assert "implausible" in res.reason

    def test_none(self):
        assert not check_plausible_date(None).valid
