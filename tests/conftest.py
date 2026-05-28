"""Fixtures y factories compartidos para los tests del dominio.

Las factories construyen las dataclasses de src/modelos.py en memoria, sin
tocar archivos. Los importes se pasan como str y se convierten a Decimal,
nunca float (regla del proyecto: el dinero siempre es Decimal).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.config import Banco, ConfiguracionCuentas, ProveedorComision
from src.modelos import (
    LineaCierreCaja,
    MedioPago,
    MovimientoBancario,
    PagoDiners,
    Tienda,
    TipoTransaccion,
    TransaccionMedioPago,
)


@pytest.fixture
def cuentas() -> ConfiguracionCuentas:
    """Plan de cuentas completo (sin placeholders) para generar asientos."""
    return ConfiguracionCuentas(
        cuentas_puente={
            MedioPago.MASTERCARD: "121206",
            MedioPago.AMEX: "121207",
            MedioPago.DINERS: "121208",
        },
        nombres_cuenta_puente={
            MedioPago.MASTERCARD: "CTA POR COBR MASTERCARD",
            MedioPago.AMEX: "CTA POR COBR AMERICAN EXPRESS",
            MedioPago.DINERS: "CTA POR COBR DINERS",
        },
        bancos={
            "INTERBANK": Banco("104107", "108-3002238284", "BANCO INTERBANK"),
            "BBVA": Banco("104200", "0011-0616-0501000126", "BANCO BBVA CONTINENTAL"),
        },
        filtros_bancos={"INTERBANK": {MedioPago.AMEX: "AMEX"}},
        cliente_generico_codigo="C00000000",
        cliente_generico_nombre="CLIENTE GENERICO",
        cliente_generico_cuenta_asociada="461101",
        proveedores_comision={
            MedioPago.MASTERCARD: ProveedorComision(
                "P20432405525", "PROCESOS DE MEDIOS DE PAGO S.A.", "421201"),
            MedioPago.AMEX: ProveedorComision(
                "P20100000001", "PROVEEDOR AMEX", "421202"),
            MedioPago.DINERS: ProveedorComision(
                "P20100000002", "PROVEEDOR DINERS", "421203"),
        },
        tolerancia_conciliacion=Decimal("0.01"),
    )


@pytest.fixture
def tienda() -> Tienda:
    """Tienda tipica: MC y AMEX en Interbank, Diners en BBVA."""
    return Tienda(
        id_sap="MIS.TST",
        nombre="TIENDA DE PRUEBA",
        codigo_proyecto="MIS.TST",
        codigo_comercio_mc_amex="1023366",
        codigo_comercio_diners="1001299773",
        banco_mc="INTERBANK",
        banco_amex="INTERBANK",
        banco_diners="BBVA",
    )


@pytest.fixture
def make_txn():
    """Factory de TransaccionMedioPago."""
    def _make(
        *,
        medio: MedioPago = MedioPago.MASTERCARD,
        codigo: str = "1023366",
        fecha_proceso: date = date(2026, 4, 1),
        fecha_abono: date | None = None,
        bruto: str = "0",
        comision: str = "0",
        igv: str = "0",
        neto: str = "0",
        tipo: TipoTransaccion = TipoTransaccion.COMPRA,
        orden_pago: str | None = None,
    ) -> TransaccionMedioPago:
        return TransaccionMedioPago(
            medio_pago=medio,
            codigo_comercio=codigo,
            fecha_proceso=fecha_proceso,
            fecha_abono=fecha_abono,
            importe_bruto=Decimal(bruto),
            comision=Decimal(comision),
            igv=Decimal(igv),
            importe_neto=Decimal(neto),
            tipo=tipo,
            orden_pago=orden_pago,
        )
    return _make


@pytest.fixture
def make_cierre():
    """Factory de LineaCierreCaja."""
    def _make(
        *,
        fecha: date = date(2026, 4, 1),
        id_tienda: str = "MIS.TST",
        importes: dict[MedioPago, Decimal] | None = None,
    ) -> LineaCierreCaja:
        return LineaCierreCaja(
            fecha=fecha,
            id_tienda=id_tienda,
            nombre_tienda="TIENDA DE PRUEBA",
            importes=importes or {},
        )
    return _make


@pytest.fixture
def make_mov():
    """Factory de MovimientoBancario."""
    def _make(
        *,
        fecha: date = date(2026, 4, 1),
        banco: str = "INTERBANK",
        nro_operacion: str = "1",
        descripcion: str = "",
        abono: str = "0",
        cargo: str = "0",
    ) -> MovimientoBancario:
        return MovimientoBancario(
            fecha_operacion=fecha,
            fecha_proceso=fecha,
            banco=banco,
            cuenta="",
            nro_operacion=nro_operacion,
            descripcion=descripcion,
            abono=Decimal(abono),
            cargo=Decimal(cargo),
        )
    return _make


@pytest.fixture
def make_pago_diners():
    """Factory de PagoDiners."""
    def _make(
        *,
        codigo: str = "1001299773",
        fecha_pago: date = date(2026, 4, 1),
        abono: str = "0",
        comision: str = "0",
        igv: str = "0",
        estado: str = "PAGADO",
        orden_pago: str | None = None,
        consumos: str = "0",
    ) -> PagoDiners:
        return PagoDiners(
            codigo_comercio=codigo,
            fecha_pago=fecha_pago,
            importe_total_abono=Decimal(abono),
            comision=Decimal(comision),
            igv=Decimal(igv),
            estado=estado,
            orden_pago=orden_pago,
            importe_total_consumos=Decimal(consumos),
        )
    return _make
