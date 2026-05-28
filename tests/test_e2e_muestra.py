"""Test end-to-end contra la muestra real (Muestra al 30.04/).

Reproduce el ejemplo del PDF: la conciliacion de ventas Mastercard de la
tienda Schell (MIS.MI01) para el periodo 01-09 de abril. El total de la
pasarela debe ser 168,769.84 (PDF pag. 19-20) y el 06/04 debe arrojar la
diferencia de 586.00 que el PDF identifica explicitamente.

El modulo se omite si la carpeta de muestra no esta disponible.
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from src.conciliacion import ventas as cv
from src.config import cargar_tiendas
from src.loaders import cierre_caja, izipay
from src.modelos import MedioPago

MUESTRA = Path("Muestra al 30.04")

pytestmark = pytest.mark.skipif(
    not MUESTRA.exists(), reason="carpeta 'Muestra al 30.04/' no disponible")


def _primer_archivo(subcarpeta: str, patron: str) -> Path:
    return sorted((MUESTRA / subcarpeta).glob(patron))[0]


@pytest.fixture(scope="module")
def schell_difs():
    """Conciliacion de ventas MC de la tienda Schell para el periodo 01-09."""
    schell = next(t for t in cargar_tiendas("config/tiendas.yaml")
                  if t.id_sap == "MIS.MI01")
    lineas = cierre_caja.cargar(_primer_archivo("Reporte SAP", "*.xlsx"))
    txn_mc = izipay.cargar(_primer_archivo("Reportes CSV", "mc_*.csv"),
                           MedioPago.MASTERCARD)

    desde, hasta = date(2026, 4, 1), date(2026, 4, 9)

    def en_periodo(d):
        return d is not None and desde <= d <= hasta

    lineas = [l for l in lineas if en_periodo(l.fecha)]
    txn_mc = [t for t in txn_mc if en_periodo(t.fecha_proceso)
              and t.codigo_comercio == schell.codigo_comercio_mc_amex]
    return cv.conciliar_ventas_tienda(lineas, {MedioPago.MASTERCARD: txn_mc},
                                      schell.id_sap)


def test_schell_mc_total_pasarela_01_09(schell_difs):
    """El total a cancelar MC de Schell 01-09 es 168,769.84 (HABER del PDF)."""
    total = sum((d.total_medio_pago for d in schell_difs), Decimal("0"))
    assert total == Decimal("168769.84")


def test_schell_mc_diferencia_06_04_es_586(schell_difs):
    """El PDF identifica una diferencia de 586.00 el 06/04 en Schell MC."""
    dif = next(d for d in schell_difs if d.fecha == date(2026, 4, 6))
    assert dif.diferencia == Decimal("586.00")
