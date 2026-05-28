"""Loader de reportes Diners Club (ventas y pagos por separado).

Validado contra la muestra de abril 2026:
- ventas-20260504-1123.xlsx → 345 transacciones, hoja 'data', 26 columnas
- pagos-20260504-1123.xlsx  → 274 pagos, hoja 'data', 21 columnas

Convenciones del archivo real:
- Fechas en formato 'DD-MM-YYYY' como string.
- Codigos de comercio son enteros (los convertimos a string).
- En 'ventas': 'Tipo de transaccion' = CONSUMO (compra) | AJUSTE DE DEBITO (extorno).
- En 'pagos': la columna 'Pago efectivo' es una FECHA, no un importe; el monto
  del deposito esta en 'Importe total de abono'.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd

from ..modelos import (
    MedioPago,
    PagoDiners,
    TipoTransaccion,
    TransaccionMedioPago,
)


def _parse_decimal(v) -> Decimal:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return Decimal("0")
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return Decimal("0")
    return Decimal(s.replace(",", ""))


def _parse_fecha(v):
    """Diners exporta fechas como 'DD-MM-YYYY' string."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return pd.to_datetime(str(v).strip(), format="%d-%m-%Y", errors="coerce").date()


def cargar_ventas(path: str | Path) -> list[TransaccionMedioPago]:
    """Lee el reporte de Ventas Diners.

    Distingue CONSUMO (compra) de AJUSTE DE DEBITO (extorno).
    """
    df = pd.read_excel(path, sheet_name="data")

    transacciones: list[TransaccionMedioPago] = []
    for _, fila in df.iterrows():
        tipo_raw = str(fila.get("Tipo de transacción", "")).strip().upper()
        es_extorno = "AJUSTE" in tipo_raw or "DEBITO" in tipo_raw or "DÉBITO" in tipo_raw
        tipo = TipoTransaccion.EXTORNO if es_extorno else TipoTransaccion.COMPRA

        # Convencion: importes en valor absoluto. El signo se infiere de `tipo`.
        importe_bruto = abs(_parse_decimal(fila.get("Importe del consumo")))
        importe_neto = abs(_parse_decimal(fila.get("Importe neto de pago")))

        # IMPORTANTE: para Diners, el cierre SAP se registra por la 'Fecha de
        # ticket' (dia fisico de la venta), no por la 'Fecha de proceso' del
        # CSV (que Diners pone 1 dia despues cuando procesa el ticket).
        # Usar Fecha de ticket aqui evita 14+ diferencias fantasma por tienda.
        # Si Fecha de ticket no esta, fallback a Fecha de recepcion.
        fecha_venta = (
            _parse_fecha(fila.get("Fecha de ticket"))
            or _parse_fecha(fila.get("Fecha de recepción"))
            or _parse_fecha(fila.get("Fecha de proceso"))
        )
        transacciones.append(TransaccionMedioPago(
            medio_pago=MedioPago.DINERS,
            codigo_comercio=str(fila["Código de comercio"]).strip(),
            fecha_proceso=fecha_venta,
            fecha_abono=_parse_fecha(fila.get("Fecha de pago")),
            importe_bruto=importe_bruto,
            comision=_parse_decimal(fila.get("Comisión del consumo")),
            igv=_parse_decimal(fila.get("IGV del consumo")),
            importe_neto=importe_neto,
            autorizacion=str(fila.get("Código de autorización", "")).strip() or None,
            tipo=tipo,
            orden_pago=str(fila.get("Orden de pago", "")).strip() or None,
        ))

    return transacciones


def cargar_pagos(path: str | Path) -> list[PagoDiners]:
    """Lee el reporte de Pagos Diners. Cada fila representa un deposito
    consolidado a buscar en el extracto bancario."""
    df = pd.read_excel(path, sheet_name="data")

    pagos: list[PagoDiners] = []
    for _, fila in df.iterrows():
        pagos.append(PagoDiners(
            codigo_comercio=str(fila["Codigo de comercio"]).strip(),
            fecha_pago=_parse_fecha(fila.get("Fecha de pago efectivo")),
            importe_total_abono=_parse_decimal(fila.get("Importe total de abono")),
            comision=_parse_decimal(fila.get("Comisiones cobradas")),
            igv=_parse_decimal(fila.get("IGV")),
            estado=str(fila.get("Estado del pago", "")).strip().upper(),
            orden_pago=str(fila.get("Orden de pago", "")).strip() or None,
            importe_total_consumos=_parse_decimal(fila.get("Importe total de consumos")),
        ))

    return pagos
