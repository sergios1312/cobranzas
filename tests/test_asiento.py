"""Tests de asiento/generador.py — reglas de negocio del BLUEPRINT §5.3."""
from datetime import date
from decimal import Decimal

import pytest

from src.asiento.generador import construir_asiento
from src.config import Banco
from src.modelos import MatchDeposito, MedioPago, TipoTransaccion


def _match(fecha, medio, movs):
    """Construye un MatchDeposito a partir de movimientos bancarios."""
    return MatchDeposito(
        fecha_esperada=fecha,
        importe_esperado=sum((m.abono for m in movs), Decimal("0")),
        medio_pago=medio,
        movimientos=list(movs),
    )


def test_a01_asiento_sin_extornos_sin_residuo(tienda, cuentas, make_mov):
    """A01: 3 depositos, sin extornos ni residuo → 1 haber puente + 3 debe banco."""
    movs = [make_mov(fecha=date(2026, 4, 5), abono="40", nro_operacion="1"),
            make_mov(fecha=date(2026, 4, 6), abono="35", nro_operacion="2"),
            make_mov(fecha=date(2026, 4, 7), abono="25", nro_operacion="3")]
    matches = [_match(m.fecha_operacion, MedioPago.MASTERCARD, [m]) for m in movs]
    asiento = construir_asiento(
        tienda=tienda, medio=MedioPago.MASTERCARD, total_a_cancelar=Decimal("100"),
        matches=matches, transacciones=[], fecha_corte=date(2026, 4, 9),
        cuentas=cuentas,
    )
    assert len(asiento.lineas) == 4
    assert asiento.balanceado()


def test_a02_extornos_generan_linea_cliente_generico(tienda, cuentas, make_mov,
                                                     make_txn):
    """A02: con extornos aparece la linea del cliente generico C00000000."""
    matches = [_match(date(2026, 4, 5), MedioPago.MASTERCARD,
                      [make_mov(abono="80")])]
    extorno = make_txn(bruto="20", tipo=TipoTransaccion.EXTORNO)
    asiento = construir_asiento(
        tienda=tienda, medio=MedioPago.MASTERCARD, total_a_cancelar=Decimal("100"),
        matches=matches, transacciones=[extorno], fecha_corte=date(2026, 4, 9),
        cuentas=cuentas,
    )
    cli = [l for l in asiento.lineas if l.cuenta_mayor == "C00000000"]
    assert len(cli) == 1
    assert cli[0].debito == Decimal("20")
    assert asiento.balanceado()


def test_a03_comision_positiva_genera_linea_proveedor(tienda, cuentas, make_mov):
    """A03: si queda residuo positivo aparece la linea del proveedor de comision."""
    matches = [_match(date(2026, 4, 5), MedioPago.MASTERCARD,
                      [make_mov(abono="90")])]
    asiento = construir_asiento(
        tienda=tienda, medio=MedioPago.MASTERCARD, total_a_cancelar=Decimal("100"),
        matches=matches, transacciones=[], fecha_corte=date(2026, 4, 9),
        cuentas=cuentas,
    )
    prov = [l for l in asiento.lineas if l.cuenta_mayor == "P20432405525"]
    assert len(prov) == 1
    assert prov[0].debito == Decimal("10")


def test_a04_comision_cero_no_genera_linea_proveedor(tienda, cuentas, make_mov):
    """A04: si el residuo es exactamente 0, no hay linea de proveedor."""
    matches = [_match(date(2026, 4, 5), MedioPago.MASTERCARD,
                      [make_mov(abono="100")])]
    asiento = construir_asiento(
        tienda=tienda, medio=MedioPago.MASTERCARD, total_a_cancelar=Decimal("100"),
        matches=matches, transacciones=[], fecha_corte=date(2026, 4, 9),
        cuentas=cuentas,
    )
    assert all(l.cuenta_mayor != "P20432405525" for l in asiento.lineas)


def test_a05_a06_balanceado(tienda, cuentas, make_mov):
    """A05/A06: balanceado() es True para un asiento correcto y False si se altera."""
    matches = [_match(date(2026, 4, 5), MedioPago.MASTERCARD,
                      [make_mov(abono="90")])]
    asiento = construir_asiento(
        tienda=tienda, medio=MedioPago.MASTERCARD, total_a_cancelar=Decimal("100"),
        matches=matches, transacciones=[], fecha_corte=date(2026, 4, 9),
        cuentas=cuentas,
    )
    assert asiento.balanceado()
    asiento.lineas[0].credito += Decimal("5")
    assert not asiento.balanceado()


@pytest.mark.parametrize("medio,cuenta_puente", [
    (MedioPago.MASTERCARD, "121206"),
    (MedioPago.AMEX, "121207"),
    (MedioPago.DINERS, "121208"),
])
def test_a07_haber_en_cuenta_puente_correcta(tienda, cuentas, make_mov,
                                             medio, cuenta_puente):
    """A07: el total a cancelar va al HABER de la cuenta puente del medio."""
    matches = [_match(date(2026, 4, 5), medio, [make_mov(abono="90")])]
    asiento = construir_asiento(
        tienda=tienda, medio=medio, total_a_cancelar=Decimal("100"),
        matches=matches, transacciones=[], fecha_corte=date(2026, 4, 9),
        cuentas=cuentas,
    )
    assert asiento.lineas[0].cuenta_mayor == cuenta_puente
    assert asiento.lineas[0].credito == Decimal("100")


def test_a08_glosa_contiene_rango_de_dias(tienda, cuentas, make_mov):
    """A08: la glosa lleva el rango dd-dd de las fechas de los depositos."""
    movs = [make_mov(fecha=date(2026, 4, 1), abono="50"),
            make_mov(fecha=date(2026, 4, 9), abono="50")]
    matches = [_match(m.fecha_operacion, MedioPago.MASTERCARD, [m]) for m in movs]
    asiento = construir_asiento(
        tienda=tienda, medio=MedioPago.MASTERCARD, total_a_cancelar=Decimal("100"),
        matches=matches, transacciones=[], fecha_corte=date(2026, 4, 9),
        cuentas=cuentas,
    )
    assert asiento.glosa == "INGRESOS MASTERCARD 01-09"


def test_a09_todas_las_lineas_llevan_proyecto(tienda, cuentas, make_mov, make_txn):
    """A09: cada linea del asiento lleva el codigo de proyecto de la tienda."""
    matches = [_match(date(2026, 4, 5), MedioPago.MASTERCARD,
                      [make_mov(abono="70")])]
    extorno = make_txn(bruto="10", tipo=TipoTransaccion.EXTORNO)
    asiento = construir_asiento(
        tienda=tienda, medio=MedioPago.MASTERCARD, total_a_cancelar=Decimal("100"),
        matches=matches, transacciones=[extorno], fecha_corte=date(2026, 4, 9),
        cuentas=cuentas,
    )
    assert all(l.proyecto == tienda.codigo_proyecto for l in asiento.lineas)


def test_a10_banco_segun_medio(tienda, cuentas, make_mov):
    """A10: MC usa banco_mc de la tienda; Diners usa banco_diners."""
    asiento_mc = construir_asiento(
        tienda=tienda, medio=MedioPago.MASTERCARD, total_a_cancelar=Decimal("100"),
        matches=[_match(date(2026, 4, 5), MedioPago.MASTERCARD,
                        [make_mov(abono="100")])],
        transacciones=[], fecha_corte=date(2026, 4, 9), cuentas=cuentas,
    )
    assert "INTERBANK" in asiento_mc.lineas[1].nombre_cuenta
    asiento_di = construir_asiento(
        tienda=tienda, medio=MedioPago.DINERS, total_a_cancelar=Decimal("100"),
        matches=[_match(date(2026, 4, 5), MedioPago.DINERS,
                        [make_mov(abono="100")])],
        transacciones=[], fecha_corte=date(2026, 4, 9), cuentas=cuentas,
    )
    assert "BBVA" in asiento_di.lineas[1].nombre_cuenta


def test_residuo_negativo_va_a_credito_y_marca_advertencia(tienda, cuentas,
                                                           make_mov, make_txn):
    """Si depositos + extornos superan el total a cancelar, el residuo se
    registra como CREDITO (no como DEBE negativo) y el asiento se marca."""
    matches = [_match(date(2026, 4, 5), MedioPago.MASTERCARD,
                      [make_mov(abono="100")])]
    extorno = make_txn(bruto="20", tipo=TipoTransaccion.EXTORNO)
    asiento = construir_asiento(
        tienda=tienda, medio=MedioPago.MASTERCARD, total_a_cancelar=Decimal("100"),
        matches=matches, transacciones=[extorno], fecha_corte=date(2026, 4, 9),
        cuentas=cuentas,
    )
    prov = [l for l in asiento.lineas if l.cuenta_mayor == "P20432405525"][0]
    assert prov.debito == Decimal("0")
    assert prov.credito == Decimal("20")
    assert asiento.advertencias
    assert asiento.balanceado()
    assert all(l.debito >= 0 and l.credito >= 0 for l in asiento.lineas)


def test_codigo_placeholder_aborta_el_asiento(tienda, cuentas, make_mov):
    """Un asiento que necesita un codigo placeholder lanza ValueError."""
    cuentas.bancos["INTERBANK"] = Banco("104XXX", "x", "BANCO INTERBANK")
    matches = [_match(date(2026, 4, 5), MedioPago.MASTERCARD,
                      [make_mov(abono="90")])]
    with pytest.raises(ValueError, match="pendientes"):
        construir_asiento(
            tienda=tienda, medio=MedioPago.MASTERCARD,
            total_a_cancelar=Decimal("100"), matches=matches, transacciones=[],
            fecha_corte=date(2026, 4, 9), cuentas=cuentas,
        )
