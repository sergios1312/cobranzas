"""Esquema canónico en memoria.

Los loaders convierten archivos crudos (SAP, Izipay, Diners, bancos) a estas
estructuras. Toda la lógica de conciliación, matching y generación de asientos
opera exclusivamente sobre estos tipos, lo que aísla la lógica de negocio del
formato específico de cada archivo de entrada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional


class MedioPago(str, Enum):
    MASTERCARD = "MASTERCARD"
    AMEX = "AMEX"
    DINERS = "DINERS"
    VISA = "VISA"
    EFECTIVO = "EFECTIVO"
    YAPE = "YAPE"
    LUKITA = "LUKITA"
    TUNKY = "TUNKY"
    WALI = "WALI"


class TipoTransaccion(str, Enum):
    COMPRA = "COMPRA"
    EXTORNO = "EXTORNO"


# ---------------------------------------------------------------------------
# Insumos
# ---------------------------------------------------------------------------

@dataclass
class LineaCierreCaja:
    """Una fila del Cierre Caja Resumen — totales de venta por
    tienda × fecha, con un importe por cada medio de pago."""
    fecha: date
    id_tienda: str
    nombre_tienda: str
    importes: dict[MedioPago, Decimal]

    def importe(self, medio: MedioPago) -> Decimal:
        return self.importes.get(medio, Decimal("0"))


@dataclass
class TransaccionMedioPago:
    """Una transacción individual reportada por Izipay (MC/AMEX) o Diners
    Ventas. Granularidad: una transacción por fila del CSV/XLS."""
    medio_pago: MedioPago
    codigo_comercio: str
    fecha_proceso: date
    fecha_abono: Optional[date]
    importe_bruto: Decimal
    comision: Decimal
    igv: Decimal
    importe_neto: Decimal
    voucher: Optional[str] = None
    autorizacion: Optional[str] = None
    tipo: TipoTransaccion = TipoTransaccion.COMPRA
    orden_pago: Optional[str] = None  # solo aplica a Diners (cruza con PagoDiners)


@dataclass
class PagoDiners:
    """Diners liquida en bloque — esta es una línea del reporte de Pagos
    (distinto del de Ventas). Cada línea ya representa un depósito
    individual a buscar en banco."""
    codigo_comercio: str
    fecha_pago: date              # 'Fecha de pago efectivo' del reporte
    importe_total_abono: Decimal  # 'Importe total de abono' — monto del deposito a buscar en banco
    comision: Decimal
    igv: Decimal
    estado: str                   # 'PAGADO' | otros
    orden_pago: Optional[str] = None  # cruza 1-a-1 con TransaccionMedioPago.orden_pago de ventas Diners
    importe_total_consumos: Decimal = Decimal("0")  # bruto total que el pago dice cubrir; sirve para detectar pagos multi-periodo


@dataclass
class MovimientoBancario:
    fecha_operacion: date
    fecha_proceso: date
    banco: str           # 'INTERBANK' | 'BBVA'
    cuenta: str
    nro_operacion: str
    descripcion: str     # contiene patrón a filtrar (cod_comercio o AMEX)
    abono: Decimal = Decimal("0")
    cargo: Decimal = Decimal("0")


@dataclass
class Tienda:
    id_sap: str
    nombre: str
    codigo_proyecto: str
    codigo_comercio_mc_amex: Optional[str] = None
    codigo_comercio_diners: Optional[str] = None
    banco_mc: Optional[str] = None
    banco_amex: Optional[str] = None
    banco_diners: Optional[str] = None
    banco_efectivo: Optional[str] = None
    banco_visa_puntos: Optional[str] = None
    encargado: Optional[str] = None

    @property
    def prefijo_descripcion_mc(self) -> Optional[str]:
        if self.codigo_comercio_mc_amex is None or self.codigo_comercio_mc_amex == "PENDIENTE":
            return None
        return "00" + self.codigo_comercio_mc_amex

    def banco_para(self, medio: "MedioPago") -> Optional[str]:
        if medio == MedioPago.MASTERCARD:
            return self.banco_mc
        if medio == MedioPago.AMEX:
            return self.banco_amex
        if medio == MedioPago.DINERS:
            return self.banco_diners
        return None


# ---------------------------------------------------------------------------
# Resultados de conciliación
# ---------------------------------------------------------------------------

@dataclass
class DiferenciaConciliacion:
    """Resultado del paso de conciliación de ventas: diferencia por fecha
    entre lo declarado en Cierre Caja Resumen y lo reportado por la
    pasarela del medio de pago."""
    fecha: date
    id_tienda: str
    medio_pago: MedioPago
    total_cierre: Decimal
    total_medio_pago: Decimal

    @property
    def diferencia(self) -> Decimal:
        return self.total_cierre - self.total_medio_pago

    def es_significativa(self, tolerancia: Decimal = Decimal("0.01")) -> bool:
        return abs(self.diferencia) > tolerancia


@dataclass
class MatchDeposito:
    """Empareja un deposito esperado con N movimientos bancarios.

    Para MC/AMEX: 1 fecha de abono = suma de transacciones del dia, que en el
    banco aparece distribuida en multiples movs (uno por transaccion). El match
    es la coleccion completa de movs de ese (tienda, fecha) en el banco.

    Para Diners: 1 pago = 1 mov en banco. La lista contendra 0 o 1 movimiento.

    La validacion 'cuadra' compara la suma esperada vs la suma de movs.
    El generador del asiento itera sobre `movimientos` (no sobre el match)
    para crear una linea DEBE por cada movimiento individual.
    """
    fecha_esperada: date
    importe_esperado: Decimal
    medio_pago: MedioPago
    movimientos: list[MovimientoBancario] = field(default_factory=list)

    @property
    def encontrado(self) -> bool:
        return len(self.movimientos) > 0

    @property
    def suma_movimientos(self) -> Decimal:
        return sum((m.abono for m in self.movimientos), Decimal("0"))

    @property
    def diferencia(self) -> Decimal:
        return self.importe_esperado - self.suma_movimientos

    def cuadra(self, tolerancia: Decimal = Decimal("0.01")) -> bool:
        return self.encontrado and abs(self.diferencia) <= tolerancia


# ---------------------------------------------------------------------------
# Asiento contable de salida
# ---------------------------------------------------------------------------

@dataclass
class LineaAsiento:
    cuenta_mayor: str           # cuenta contable o código de Socio de Negocio
    nombre_cuenta: str
    cuenta_asociada: Optional[str] = None
    debito: Decimal = Decimal("0")
    credito: Decimal = Decimal("0")
    referencia_1: str = ""
    referencia_2: str = ""
    fecha_vencimiento: Optional[date] = None
    proyecto: str = ""


@dataclass
class Asiento:
    fecha_contabilizacion: date
    fecha_vencimiento: date
    fecha_documento: date
    glosa: str
    proyecto: str
    medio_pago: MedioPago
    id_tienda: str
    lineas: list[LineaAsiento] = field(default_factory=list)

    def total_debito(self) -> Decimal:
        return sum((l.debito for l in self.lineas), Decimal("0"))

    def total_credito(self) -> Decimal:
        return sum((l.credito for l in self.lineas), Decimal("0"))

    def balanceado(self, tolerancia: Decimal = Decimal("0.01")) -> bool:
        return abs(self.total_debito() - self.total_credito()) <= tolerancia
