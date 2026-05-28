"""Tests del pipeline: detección de revisión, validación de insumos y ruteo."""
from datetime import date
from decimal import Decimal

import pytest

from src import pipeline
from src.modelos import Asiento, LineaAsiento, MedioPago, Tienda


def _asiento(advertencias=None, balanceado=True) -> Asiento:
    debito = Decimal("100") if balanceado else Decimal("90")
    return Asiento(
        fecha_contabilizacion=date(2026, 4, 30),
        fecha_vencimiento=date(2026, 4, 30),
        fecha_documento=date(2026, 4, 30),
        glosa="g", proyecto="MIS.X", medio_pago=MedioPago.MASTERCARD,
        id_tienda="MIS.X",
        lineas=[
            LineaAsiento("121206", "P", "121206", credito=Decimal("100")),
            LineaAsiento("104107", "B", "104107", debito=debito),
        ],
        advertencias=advertencias or [],
    )


# --- Asiento.requiere_revision ---

def test_requiere_revision_asiento_limpio_es_falso():
    assert _asiento().requiere_revision() is False


def test_requiere_revision_con_advertencias():
    assert _asiento(advertencias=["x"]).requiere_revision() is True


def test_requiere_revision_si_no_balancea():
    assert _asiento(balanceado=False).requiere_revision() is True


# --- _unico_archivo ---

def test_unico_archivo_devuelve_el_unico(tmp_path):
    (tmp_path / "mc_1.csv").write_text("x")
    assert pipeline._unico_archivo(tmp_path, "mc_*.csv").name == "mc_1.csv"


def test_unico_archivo_ignora_temporales_de_excel(tmp_path):
    (tmp_path / "rep.xlsx").write_text("x")
    (tmp_path / "~$rep.xlsx").write_text("x")
    assert pipeline._unico_archivo(tmp_path, "*.xlsx").name == "rep.xlsx"


def test_unico_archivo_falla_si_hay_varios(tmp_path):
    (tmp_path / "mc_1.csv").write_text("x")
    (tmp_path / "mc_2.csv").write_text("x")
    with pytest.raises(ValueError, match="Hay 2 archivos"):
        pipeline._unico_archivo(tmp_path, "mc_*.csv")


def test_unico_archivo_falla_si_no_hay(tmp_path):
    with pytest.raises(FileNotFoundError):
        pipeline._unico_archivo(tmp_path, "mc_*.csv")


# --- exportar: separación a _revisar/ ---

def test_exportar_separa_asientos_a_revisar(tmp_path):
    tienda = Tienda(id_sap="MIS.X", nombre="X", codigo_proyecto="MIS.X")
    res = pipeline.ResultadoTienda(
        tienda=tienda, diferencias=[], txn_mc=[], txn_amex=[], txn_diners=[],
        pagos_diners=[])
    res.asientos = [_asiento(), _asiento(advertencias=["revisar"])]
    rp = pipeline.ResultadoPipeline(
        desde=date(2026, 4, 1), hasta=date(2026, 4, 30), resultados=[res])

    escritos = pipeline.exportar(rp, tmp_path)

    asientos = [p for p in escritos if p.name.startswith("asiento")]
    en_revisar = [p for p in asientos if "_revisar" in p.parts]
    normales = [p for p in asientos if "_revisar" not in p.parts]
    assert len(en_revisar) == 1
    assert len(normales) == 1
    assert en_revisar[0].exists()
