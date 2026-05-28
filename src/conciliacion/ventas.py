"""Conciliación de ventas.

Compara el total de venta declarado en el Cierre Caja Resumen contra el
total reportado por cada pasarela de medio de pago, agrupado por fecha.

Equivalente automatizado de las tablas dinámicas que se construyen a mano
en el archivo de Cierre por tienda.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from ..modelos import (
    DiferenciaConciliacion,
    LineaCierreCaja,
    MedioPago,
    TipoTransaccion,
    TransaccionMedioPago,
)


def resumen_por_fecha(
    transacciones: Iterable[TransaccionMedioPago],
    *,
    incluir_extornos: bool = False,
) -> dict[date, Decimal]:
    """Suma los importes brutos del medio de pago agrupados por fecha de
    proceso. Por defecto excluye extornos para que coincida con la columna
    del medio de pago en el Cierre Caja Resumen."""
    acc: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
    for t in transacciones:
        if not incluir_extornos and t.tipo == TipoTransaccion.EXTORNO:
            continue
        acc[t.fecha_proceso] += t.importe_bruto
    return dict(acc)


def conciliar_ventas_tienda(
    cierre: list[LineaCierreCaja],
    reportes: dict[MedioPago, list[TransaccionMedioPago]],
    id_tienda: str,
) -> list[DiferenciaConciliacion]:
    """Para una tienda dada, recorre cada (fecha × medio de pago) y produce
    un registro de diferencia comparando cierre contra reporte de pasarela.

    El llamador decide qué hacer con las diferencias significativas (ver
    `DiferenciaConciliacion.es_significativa`).
    """
    lineas_tienda = [l for l in cierre if l.id_tienda == id_tienda]
    diferencias: list[DiferenciaConciliacion] = []

    for medio, transacciones in reportes.items():
        resumen = resumen_por_fecha(transacciones)
        fechas = {l.fecha for l in lineas_tienda} | set(resumen.keys())

        for fecha in sorted(fechas):
            linea = next((l for l in lineas_tienda if l.fecha == fecha), None)
            total_cierre = linea.importe(medio) if linea else Decimal("0")
            total_mp = resumen.get(fecha, Decimal("0"))

            diferencias.append(DiferenciaConciliacion(
                fecha=fecha,
                id_tienda=id_tienda,
                medio_pago=medio,
                total_cierre=total_cierre,
                total_medio_pago=total_mp,
            ))

    return diferencias
