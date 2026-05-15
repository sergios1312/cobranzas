"""Conciliación de depósitos contra extracto bancario.

Para cada depósito esperado (según el reporte de la pasarela), se busca el
movimiento correspondiente en el extracto del banco. La regla aceptada por
el usuario es:

    Dentro del filtro por tienda (por código de comercio o palabra clave),
    un match por (fecha, importe) es válido aun si hay duplicados, siempre
    que el conteo total cierre. No se necesita un campo de desempate.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from ..modelos import (
    MatchDeposito, MedioPago, MovimientoBancario, PagoDiners, Tienda,
    TipoTransaccion, TransaccionMedioPago,
)


# ---------------------------------------------------------------------------
# Construcción de "depósitos esperados" según medio de pago
# ---------------------------------------------------------------------------

def depositos_esperados_izipay(
    transacciones: Iterable[TransaccionMedioPago],
) -> list[tuple[date, Decimal]]:
    """Para MC y AMEX, retorna una entrada por transaccion con neto > 0 y
    fecha_abono asignada. Esto permite matching 1-a-1 contra movs bancarios
    individuales — robusto cuando el filtro bancario no distingue tienda
    (BCP, AMEX en Interbank)."""
    return [
        (t.fecha_abono, t.importe_neto)
        for t in transacciones
        if t.fecha_abono is not None
        and t.tipo == TipoTransaccion.COMPRA
        and t.importe_neto > 0
    ]


def _pagos_diners_del_periodo(
    pagos: Iterable[PagoDiners],
    ventas: Iterable[TransaccionMedioPago],
    tolerancia: Decimal = Decimal("0.01"),
) -> list[PagoDiners]:
    """Filtra los pagos Diners a solo aquellos que cubren EXACTAMENTE las
    ventas del período presentes en el CSV.

    Doble condición:
    - El `orden_pago` debe aparecer en al menos una venta del período.
    - El `importe_total_consumos` del pago debe coincidir con la suma de
      `importe_bruto` de las ventas con ese `orden_pago`. Si difiere, es un
      pago multi-período (incluye tickets de meses anteriores que no estan
      en el CSV de Ventas) y se excluye para evitar conciliaciones
      incorrectas.
    """
    bruto_por_orden: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for v in ventas:
        if v.orden_pago and v.tipo == TipoTransaccion.COMPRA:
            bruto_por_orden[v.orden_pago] += v.importe_bruto

    resultado: list[PagoDiners] = []
    for p in pagos:
        if p.estado.upper() != "PAGADO" or not p.orden_pago:
            continue
        if p.orden_pago not in bruto_por_orden:
            continue
        bruto_ventas = bruto_por_orden[p.orden_pago]
        # Solo aceptar si el pago dice cubrir exactamente lo del periodo.
        if abs(bruto_ventas - p.importe_total_consumos) > tolerancia:
            continue
        resultado.append(p)
    return resultado


def depositos_esperados_diners(
    pagos: Iterable[PagoDiners],
    ventas: Optional[Iterable[TransaccionMedioPago]] = None,
) -> list[tuple[date, Decimal]]:
    """Para Diners, cada línea del reporte de Pagos representa un depósito
    individual. Filtramos solo los PAGADO.

    Si se pasan las `ventas` del período:
    - Restringe a pagos cuya `orden_pago` aparece en alguna venta.
    - Excluye pagos multi-período (cuyo `importe_total_consumos` no cuadra
      con la suma de brutos de las ventas asociadas en el CSV).
    """
    if ventas is None:
        return [
            (p.fecha_pago, p.importe_total_abono)
            for p in pagos
            if p.estado.upper() == "PAGADO"
        ]
    pagos_validos = _pagos_diners_del_periodo(pagos, ventas)
    return [(p.fecha_pago, p.importe_total_abono) for p in pagos_validos]


def ventas_diners_a_cancelar(
    ventas: Iterable[TransaccionMedioPago],
    pagos: Iterable[PagoDiners],
) -> list[TransaccionMedioPago]:
    """Filtra las ventas Diners a solo aquellas cuya `orden_pago` corresponde
    a un pago efectivo COMPLETO del período (no multi-período). Las ventas
    cuyo pago abarca tickets de otros meses se excluyen para mantener la
    consistencia con `depositos_esperados_diners`."""
    ventas_list = list(ventas)
    pagos_validos = _pagos_diners_del_periodo(pagos, ventas_list)
    ordenes_pagadas = {p.orden_pago for p in pagos_validos}
    return [v for v in ventas_list if v.orden_pago in ordenes_pagadas]


# ---------------------------------------------------------------------------
# Filtrado de movimientos bancarios
# ---------------------------------------------------------------------------

def filtrar_movimientos(
    movimientos: Iterable[MovimientoBancario],
    medio: MedioPago,
    tienda: Tienda,
    banco: str,
    filtros: dict[str, dict[MedioPago, str]],
) -> list[MovimientoBancario]:
    """Filtra movs del banco que corresponden al (banco, medio, tienda).

    Estrategia:
    1. Si hay un patron explicito en `filtros[banco][medio]`, lo aplica
       case-insensitive sobre `descripcion` (ej. 'AMEX' en Interbank,
       'R20100118760' en BBVA, 'DE PROCESOS DE MEDIOS' en BCP).
    2. Si no hay patron y el medio es MASTERCARD, usa el prefijo de la
       tienda derivado del codigo de comercio (ej. '001023366').
    3. En otros casos, retorna lista vacia.

    Importante: este filtro puede traer movs de varias tiendas (cuando el
    patron es generico, como 'AMEX' o 'PROCESOS DE MEDIOS'). El matching
    1-a-1 por (fecha, importe) en `emparejar()` desambigua.
    """
    patron = filtros.get(banco, {}).get(medio)
    if patron is not None:
        patron_upper = patron.upper()
        return [m for m in movimientos if patron_upper in m.descripcion.upper()]

    if medio == MedioPago.MASTERCARD:
        clave = tienda.prefijo_descripcion_mc
        if clave is None:
            return []
        return [m for m in movimientos if clave in m.descripcion]

    return []


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def emparejar(
    esperados: list[tuple[date, Decimal]],
    movimientos: list[MovimientoBancario],
    medio: MedioPago,
) -> list[MatchDeposito]:
    """Empareja deposito esperado contra movs bancarios 1-a-1 por (fecha,
    importe). Misma estrategia para MC, AMEX y Diners porque tanto los
    esperados como los movs son ahora individuales:

    - MC / AMEX: cada esperado es 1 transaccion del CSV pasarela con su
      neto, no la suma del dia. Esto es robusto cuando el filtro bancario
      no distingue tienda (BCP, AMEX en Interbank).
    - DINERS: 1 pago = 1 deposito en banco.

    Duplicados de (fecha, importe) se asignan FIFO en orden de aparicion
    en `movimientos`.
    """
    indice: dict[tuple[date, Decimal], list[MovimientoBancario]] = defaultdict(list)
    for m in movimientos:
        indice[(m.fecha_operacion, m.abono)].append(m)

    matches: list[MatchDeposito] = []
    for fecha, importe in esperados:
        candidatos = indice.get((fecha, importe))
        movs = [candidatos.pop(0)] if candidatos else []
        matches.append(MatchDeposito(
            fecha_esperada=fecha,
            importe_esperado=importe,
            medio_pago=medio,
            movimientos=movs,
        ))
    return matches
