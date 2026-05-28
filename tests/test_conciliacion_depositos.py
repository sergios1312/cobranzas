"""Tests de conciliacion/depositos.py — reglas de negocio del BLUEPRINT §5.2."""
from datetime import date
from decimal import Decimal

from src.conciliacion.depositos import (
    depositos_esperados_diners,
    depositos_esperados_izipay,
    emparejar,
    filtrar_movimientos,
    ventas_diners_a_cancelar,
)
from src.modelos import MedioPago, TipoTransaccion


def test_esperados_izipay_una_tupla_por_transaccion(make_txn):
    """Cada transaccion con fecha_abono y neto>0 produce un deposito esperado."""
    txns = [
        make_txn(fecha_abono=date(2026, 4, 6), neto="100"),
        make_txn(fecha_abono=date(2026, 4, 6), neto="50"),
        make_txn(fecha_abono=date(2026, 4, 7), neto="30"),
    ]
    assert len(depositos_esperados_izipay(txns)) == 3


def test_esperados_izipay_ignora_abono_nulo(make_txn):
    """Transacciones sin fecha_abono no producen deposito esperado."""
    txns = [
        make_txn(fecha_abono=None, neto="100"),
        make_txn(fecha_abono=date(2026, 4, 6), neto="50"),
    ]
    assert depositos_esperados_izipay(txns) == [(date(2026, 4, 6), Decimal("50"))]


def test_esperados_izipay_ignora_extornos_y_neto_cero(make_txn):
    """Extornos y transacciones con neto=0 no producen deposito esperado."""
    txns = [
        make_txn(fecha_abono=date(2026, 4, 6), neto="0"),
        make_txn(fecha_abono=date(2026, 4, 6), neto="80",
                 tipo=TipoTransaccion.EXTORNO),
        make_txn(fecha_abono=date(2026, 4, 6), neto="40"),
    ]
    assert depositos_esperados_izipay(txns) == [(date(2026, 4, 6), Decimal("40"))]


def test_esperados_diners_solo_pagados(make_pago_diners):
    """Sin ventas de referencia, solo cuentan los pagos en estado PAGADO."""
    pagos = [
        make_pago_diners(estado="PAGADO", abono="100", fecha_pago=date(2026, 4, 9)),
        make_pago_diners(estado="PENDIENTE", abono="200"),
    ]
    assert depositos_esperados_diners(pagos) == [(date(2026, 4, 9), Decimal("100"))]


def test_esperados_diners_excluye_pago_multiperiodo(make_pago_diners, make_txn):
    """Un pago cuyo total de consumos no cuadra con las ventas del periodo
    (pago multi-periodo) se excluye."""
    venta = make_txn(medio=MedioPago.DINERS, bruto="100", orden_pago="OP1")
    pago_ok = make_pago_diners(orden_pago="OP1", abono="95", consumos="100")
    pago_multi = make_pago_diners(orden_pago="OP1", abono="280", consumos="300")
    assert depositos_esperados_diners([pago_ok], ventas=[venta]) == [
        (pago_ok.fecha_pago, Decimal("95"))]
    assert depositos_esperados_diners([pago_multi], ventas=[venta]) == []


def test_ventas_diners_a_cancelar_solo_ordenes_pagadas(make_txn, make_pago_diners):
    """Solo se cancelan las ventas cuya orden de pago tiene un pago efectivo."""
    v1 = make_txn(medio=MedioPago.DINERS, bruto="100", orden_pago="OP1")
    v2 = make_txn(medio=MedioPago.DINERS, bruto="50", orden_pago="OP2")
    pago = make_pago_diners(orden_pago="OP1", abono="95", consumos="100")
    assert ventas_diners_a_cancelar([v1, v2], [pago]) == [v1]


def test_filtro_mc_por_prefijo_de_descripcion(make_mov, tienda):
    """MC: solo los movimientos cuya descripcion contiene el prefijo de la tienda."""
    movs = [
        make_mov(descripcion="PAGO PMP 001023366", abono="100"),
        make_mov(descripcion="PAGO PMP 009999999", abono="200"),
    ]
    filtrados = filtrar_movimientos(movs, MedioPago.MASTERCARD, tienda,
                                    "INTERBANK", {})
    assert [m.abono for m in filtrados] == [Decimal("100")]


def test_filtro_amex_es_case_insensitive(make_mov, tienda):
    """AMEX: el patron 'AMEX' matchea sin importar mayusculas/minusculas."""
    filtros = {"INTERBANK": {MedioPago.AMEX: "AMEX"}}
    movs = [
        make_mov(descripcion="abono amex pago", abono="10"),
        make_mov(descripcion="PAGO AMEX", abono="20"),
        make_mov(descripcion="transferencia interna", abono="30"),
    ]
    filtrados = filtrar_movimientos(movs, MedioPago.AMEX, tienda,
                                    "INTERBANK", filtros)
    assert {m.abono for m in filtrados} == {Decimal("10"), Decimal("20")}


def test_match_exacto(make_mov):
    """Un esperado con un movimiento de igual fecha e importe → encontrado."""
    matches = emparejar([(date(2026, 4, 6), Decimal("100"))],
                        [make_mov(fecha=date(2026, 4, 6), abono="100")],
                        MedioPago.MASTERCARD)
    assert matches[0].encontrado
    assert matches[0].cuadra(Decimal("0.01"))


def test_match_con_duplicados(make_mov):
    """Dos esperados iguales con dos movimientos iguales → ambos encontrados."""
    esperados = [(date(2026, 4, 6), Decimal("100"))] * 2
    movs = [
        make_mov(fecha=date(2026, 4, 6), abono="100", nro_operacion="A"),
        make_mov(fecha=date(2026, 4, 6), abono="100", nro_operacion="B"),
    ]
    matches = emparejar(esperados, movs, MedioPago.MASTERCARD)
    assert all(m.encontrado for m in matches)
    assert {m.movimientos[0].nro_operacion for m in matches} == {"A", "B"}


def test_match_con_duplicados_desbalanceados(make_mov):
    """Dos esperados pero un solo movimiento → uno encontrado, uno no."""
    esperados = [(date(2026, 4, 6), Decimal("100"))] * 2
    movs = [make_mov(fecha=date(2026, 4, 6), abono="100")]
    matches = emparejar(esperados, movs, MedioPago.MASTERCARD)
    assert len([m for m in matches if m.encontrado]) == 1
    assert len([m for m in matches if not m.encontrado]) == 1


def test_match_sin_movimiento_bancario(make_mov):
    """Un esperado sin movimiento que matchee → no encontrado."""
    matches = emparejar([(date(2026, 4, 6), Decimal("100"))],
                        [make_mov(fecha=date(2026, 4, 7), abono="100")],
                        MedioPago.MASTERCARD)
    assert not matches[0].encontrado
    assert matches[0].movimientos == []
