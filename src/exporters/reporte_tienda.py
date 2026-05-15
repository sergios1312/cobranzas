"""Exporter del reporte de conciliacion por tienda.

Genera un Excel multi-hoja con la misma informacion que el asistente contable
arma a mano. Plantilla canonica basada en el ejemplo del PDF (tienda Schell)
pero saneada: sin typos, columnas de diferencia siempre presentes, hoja Bancos
siempre incluida.

Hojas generadas:
  - CIERRE       Cierre Caja Resumen de la tienda + columnas DIFERENCIA por medio
  - MASTERCARD   Transacciones MC de la tienda + tabla resumen por fecha
  - AMEX         Transacciones AMEX de la tienda + tabla resumen por fecha
  - DINERS       Transacciones Diners ventas de la tienda
  - Diners Pagos Pagos Diners de la tienda
  - Bancos       Movimientos bancarios filtrados (todos los bancos involucrados)
"""

from __future__ import annotations

from dataclasses import asdict, fields, is_dataclass
from decimal import Decimal
from pathlib import Path

import pandas as pd

from ..modelos import (
    DiferenciaConciliacion, LineaCierreCaja, MatchDeposito, MedioPago,
    MovimientoBancario, PagoDiners, Tienda, TipoTransaccion, TransaccionMedioPago,
)


def _dataclass_a_dict(obj) -> dict:
    """Convierte un dataclass a dict aplanando enums y dates a su repr str."""
    d = {}
    for f in fields(obj):
        v = getattr(obj, f.name)
        if hasattr(v, "value") and hasattr(type(v), "__members__"):
            v = v.value
        d[f.name] = v
    return d


def _df_transacciones(transacciones: list[TransaccionMedioPago]) -> pd.DataFrame:
    if not transacciones:
        return pd.DataFrame(columns=[
            "fecha_proceso", "fecha_abono", "codigo_comercio", "tipo",
            "importe_bruto", "comision", "igv", "importe_neto",
            "voucher", "autorizacion",
        ])
    rows = [_dataclass_a_dict(t) for t in transacciones]
    df = pd.DataFrame(rows)
    return df[[
        "fecha_proceso", "fecha_abono", "codigo_comercio", "tipo",
        "importe_bruto", "comision", "igv", "importe_neto",
        "voucher", "autorizacion",
    ]]


def _df_resumen_por_fecha(transacciones: list[TransaccionMedioPago]) -> pd.DataFrame:
    """Suma importe_bruto por fecha_proceso, separando compras de extornos."""
    if not transacciones:
        return pd.DataFrame(columns=["fecha", "compras", "extornos", "neto"])
    rows = []
    for t in transacciones:
        rows.append({
            "fecha": t.fecha_proceso,
            "compras": t.importe_bruto if t.tipo == TipoTransaccion.COMPRA else Decimal("0"),
            "extornos": t.importe_bruto if t.tipo == TipoTransaccion.EXTORNO else Decimal("0"),
        })
    df = pd.DataFrame(rows)
    g = df.groupby("fecha", as_index=False).agg({"compras": "sum", "extornos": "sum"})
    g["neto"] = g["compras"] - g["extornos"]
    return g.sort_values("fecha")


def _df_cierre_con_diferencias(
    lineas_cierre: list[LineaCierreCaja],
    diferencias: list[DiferenciaConciliacion],
    id_tienda: str,
) -> pd.DataFrame:
    """Cierre Caja para la tienda con columnas DIFERENCIA por medio."""
    lineas_t = [l for l in lineas_cierre if l.id_tienda == id_tienda]
    if not lineas_t:
        return pd.DataFrame()

    # Indice de diferencias por (fecha, medio)
    idx_dif: dict[tuple, Decimal] = {
        (d.fecha, d.medio_pago): d.diferencia for d in diferencias
    }

    rows = []
    for l in sorted(lineas_t, key=lambda x: x.fecha):
        row = {
            "FECHA": l.fecha,
            "ID TIENDA": l.id_tienda,
            "NOMBRE": l.nombre_tienda,
            "MASTERCARD": l.importe(MedioPago.MASTERCARD),
            "DIFERENCIA MC": idx_dif.get((l.fecha, MedioPago.MASTERCARD), Decimal("0")),
            "AMERICAN EXPRESS": l.importe(MedioPago.AMEX),
            "DIFERENCIA AMEX": idx_dif.get((l.fecha, MedioPago.AMEX), Decimal("0")),
            "DINERS": l.importe(MedioPago.DINERS),
            "DIFERENCIA DINERS": idx_dif.get((l.fecha, MedioPago.DINERS), Decimal("0")),
            "VISA": l.importe(MedioPago.VISA),
            "EFECTIVO": l.importe(MedioPago.EFECTIVO),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def _df_pagos_diners(pagos: list[PagoDiners]) -> pd.DataFrame:
    if not pagos:
        return pd.DataFrame()
    return pd.DataFrame([_dataclass_a_dict(p) for p in pagos])


def _df_movimientos_bancarios(matches: list[MatchDeposito]) -> pd.DataFrame:
    """Aplana todos los movimientos bancarios de los matches, indicando a qué
    (fecha esperada × medio) corresponde cada uno."""
    rows = []
    for m in matches:
        for mov in m.movimientos:
            d = _dataclass_a_dict(mov)
            d["medio_pago_origen"] = m.medio_pago.value
            d["fecha_esperada"] = m.fecha_esperada
            d["importe_esperado"] = m.importe_esperado
            d["cuadra"] = m.cuadra()
            rows.append(d)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df


def exportar(
    *,
    path: str | Path,
    tienda: Tienda,
    lineas_cierre: list[LineaCierreCaja],
    diferencias: list[DiferenciaConciliacion],
    txn_mc: list[TransaccionMedioPago],
    txn_amex: list[TransaccionMedioPago],
    txn_diners: list[TransaccionMedioPago],
    pagos_diners: list[PagoDiners],
    matches_por_medio: dict[MedioPago, list[MatchDeposito]],
) -> Path:
    """Escribe el reporte multi-hoja para una tienda."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Aplanamos todos los matches en un solo dataframe para la hoja Bancos
    matches_planos: list[MatchDeposito] = []
    for ms in matches_por_medio.values():
        matches_planos.extend(ms)

    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        _df_cierre_con_diferencias(lineas_cierre, diferencias, tienda.id_sap).to_excel(
            xl, sheet_name="CIERRE", index=False,
        )

        # Las tablas resumen se vuelcan en una hoja separada para evitar el
        # quirk de pandas que rellena filas vacias entre tabla principal y
        # tabla "al lado". Quien revise el Excel ve dos hojas claras.
        if txn_mc:
            _df_transacciones(txn_mc).to_excel(xl, sheet_name="MASTERCARD", index=False)
            _df_resumen_por_fecha(txn_mc).to_excel(
                xl, sheet_name="MC_RESUMEN", index=False,
            )

        if txn_amex:
            _df_transacciones(txn_amex).to_excel(xl, sheet_name="AMEX", index=False)
            _df_resumen_por_fecha(txn_amex).to_excel(
                xl, sheet_name="AMEX_RESUMEN", index=False,
            )

        if txn_diners:
            _df_transacciones(txn_diners).to_excel(xl, sheet_name="DINERS", index=False)

        if pagos_diners:
            _df_pagos_diners(pagos_diners).to_excel(
                xl, sheet_name="Diners Pagos", index=False,
            )

        df_bancos = _df_movimientos_bancarios(matches_planos)
        if not df_bancos.empty:
            df_bancos.to_excel(xl, sheet_name="Bancos", index=False)

    return path
