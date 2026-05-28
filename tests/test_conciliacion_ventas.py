"""Tests de conciliacion/ventas.py — reglas de negocio del BLUEPRINT §5.1."""
from datetime import date
from decimal import Decimal

from src.conciliacion.ventas import conciliar_ventas_tienda, resumen_por_fecha
from src.modelos import MedioPago, TipoTransaccion


def test_v01_cierre_igual_a_pasarela_no_produce_diferencia(make_cierre, make_txn):
    """V01: cuando cierre == pasarela, la diferencia es 0 y no es significativa."""
    cierre = [make_cierre(importes={MedioPago.MASTERCARD: Decimal("100.00")})]
    txns = [make_txn(bruto="100.00")]
    difs = conciliar_ventas_tienda(cierre, {MedioPago.MASTERCARD: txns}, "MIS.TST")
    assert len(difs) == 1
    assert difs[0].diferencia == Decimal("0")
    assert not difs[0].es_significativa(Decimal("0.01"))


def test_v02_diferencia_menor_a_tolerancia_no_es_significativa(make_cierre, make_txn):
    """V02: diferencia de 0.005 (< tolerancia 0.01) → no significativa."""
    cierre = [make_cierre(importes={MedioPago.MASTERCARD: Decimal("100.005")})]
    txns = [make_txn(bruto="100.00")]
    difs = conciliar_ventas_tienda(cierre, {MedioPago.MASTERCARD: txns}, "MIS.TST")
    assert not difs[0].es_significativa(Decimal("0.01"))


def test_v03_diferencia_mayor_a_tolerancia_es_significativa(make_cierre, make_txn):
    """V03: diferencia de 0.50 (> tolerancia) → significativa."""
    cierre = [make_cierre(importes={MedioPago.MASTERCARD: Decimal("100.50")})]
    txns = [make_txn(bruto="100.00")]
    difs = conciliar_ventas_tienda(cierre, {MedioPago.MASTERCARD: txns}, "MIS.TST")
    assert difs[0].diferencia == Decimal("0.50")
    assert difs[0].es_significativa(Decimal("0.01"))


def test_v04_fecha_solo_en_cierre(make_cierre):
    """V04: fecha presente solo en el cierre → pasarela = 0."""
    cierre = [make_cierre(fecha=date(2026, 4, 2),
                          importes={MedioPago.MASTERCARD: Decimal("80.00")})]
    difs = conciliar_ventas_tienda(cierre, {MedioPago.MASTERCARD: []}, "MIS.TST")
    assert len(difs) == 1
    assert difs[0].total_medio_pago == Decimal("0")
    assert difs[0].diferencia == Decimal("80.00")


def test_v05_fecha_solo_en_pasarela(make_txn):
    """V05: fecha presente solo en la pasarela → cierre = 0, diferencia negativa."""
    txns = [make_txn(fecha_proceso=date(2026, 4, 3), bruto="60.00")]
    difs = conciliar_ventas_tienda([], {MedioPago.MASTERCARD: txns}, "MIS.TST")
    assert len(difs) == 1
    assert difs[0].total_cierre == Decimal("0")
    assert difs[0].diferencia == Decimal("-60.00")


def test_v06_resumen_por_fecha_excluye_extornos(make_txn):
    """V06: resumen_por_fecha suma compras y omite extornos."""
    txns = [
        make_txn(bruto="100", tipo=TipoTransaccion.COMPRA),
        make_txn(bruto="50", tipo=TipoTransaccion.COMPRA),
        make_txn(bruto="30", tipo=TipoTransaccion.EXTORNO),
    ]
    resumen = resumen_por_fecha(txns)
    assert resumen[date(2026, 4, 1)] == Decimal("150")


def test_v07_filtrado_por_tienda_es_estricto(make_cierre, make_txn):
    """V07: el cierre de otra tienda no contamina las diferencias."""
    cierre = [
        make_cierre(id_tienda="MIS.TST",
                    importes={MedioPago.MASTERCARD: Decimal("100")}),
        make_cierre(id_tienda="OTRA",
                    importes={MedioPago.MASTERCARD: Decimal("999")}),
    ]
    txns = [make_txn(bruto="100")]
    difs = conciliar_ventas_tienda(cierre, {MedioPago.MASTERCARD: txns}, "MIS.TST")
    assert len(difs) == 1
    assert all(d.id_tienda == "MIS.TST" for d in difs)


def test_v08_un_registro_por_fecha_y_medio(make_cierre, make_txn):
    """V08: con varios medios hay un DiferenciaConciliacion por (fecha, medio)."""
    cierre = [make_cierre(importes={
        MedioPago.MASTERCARD: Decimal("100"),
        MedioPago.AMEX: Decimal("40"),
    })]
    reportes = {
        MedioPago.MASTERCARD: [make_txn(medio=MedioPago.MASTERCARD, bruto="100")],
        MedioPago.AMEX: [make_txn(medio=MedioPago.AMEX, bruto="40")],
    }
    difs = conciliar_ventas_tienda(cierre, reportes, "MIS.TST")
    assert len(difs) == 2
    assert {d.medio_pago for d in difs} == {MedioPago.MASTERCARD, MedioPago.AMEX}
