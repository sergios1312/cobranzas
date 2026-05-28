"""Tests del exporter de asiento SAP B1 (src/exporters/sap_b1.py)."""
from datetime import date
from decimal import Decimal

import pandas as pd

from src.exporters import reporte_tienda, sap_b1
from src.modelos import Asiento, LineaAsiento, MedioPago, Tienda


def _asiento(advertencias=None) -> Asiento:
    return Asiento(
        fecha_contabilizacion=date(2026, 4, 30),
        fecha_vencimiento=date(2026, 4, 30),
        fecha_documento=date(2026, 4, 30),
        glosa="INGRESOS MASTERCARD 01-09",
        proyecto="MIS.TST",
        medio_pago=MedioPago.MASTERCARD,
        id_tienda="MIS.TST",
        lineas=[
            LineaAsiento("121206", "CTA PUENTE", "121206", credito=Decimal("100")),
            LineaAsiento("104107", "BANCO", "104107", debito=Decimal("100"),
                         referencia_1="8224818"),
        ],
        advertencias=advertencias or [],
    )


def test_sap_b1_genera_cabecera_y_lineas(tmp_path):
    ruta = sap_b1.exportar(_asiento(), tmp_path / "a.xlsx")
    assert ruta.exists()
    assert pd.ExcelFile(ruta).sheet_names == ["Cabecera", "Lineas"]


def test_sap_b1_sin_advertencias_no_marca_revision(tmp_path):
    ruta = sap_b1.exportar(_asiento(), tmp_path / "a.xlsx")
    cab = pd.read_excel(ruta, sheet_name="Cabecera")
    assert bool(cab["Requiere revision"].iloc[0]) is False


def test_sap_b1_con_advertencias_marca_revision_en_cabecera(tmp_path):
    ruta = sap_b1.exportar(
        _asiento(advertencias=["Residuo de comisión negativo (-10)"]),
        tmp_path / "a.xlsx")
    cab = pd.read_excel(ruta, sheet_name="Cabecera")
    assert bool(cab["Requiere revision"].iloc[0]) is True
    assert "Residuo" in str(cab["Advertencias"].iloc[0])


def test_reporte_incluye_hoja_diners_resumen(tmp_path, make_txn):
    """El reporte por tienda incluye DINERS_RESUMEN cuando hay ventas Diners."""
    tienda = Tienda(id_sap="MIS.X", nombre="X", codigo_proyecto="MIS.X")
    ruta = reporte_tienda.exportar(
        path=tmp_path / "rep.xlsx", tienda=tienda, lineas_cierre=[],
        diferencias=[], txn_mc=[], txn_amex=[],
        txn_diners=[make_txn(medio=MedioPago.DINERS, bruto="100", neto="95")],
        pagos_diners=[], matches_por_medio={})
    hojas = pd.ExcelFile(ruta).sheet_names
    assert "DINERS" in hojas
    assert "DINERS_RESUMEN" in hojas

