"""Loader del extracto bancario BBVA."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd

from ..modelos import MovimientoBancario
from ._comun import texto_id


def _parse_decimal(v) -> Decimal:
    if pd.isna(v) or v == "":
        return Decimal("0")
    return Decimal(str(v).replace(",", ""))


def cargar(path: str | Path, cuenta: str = "", *,
           sheet_name: str = "BBVA") -> list[MovimientoBancario]:
    """Lee el Excel de movimientos BBVA.

    El extracto BBVA presenta el importe como una única columna 'Importe'
    (positivo abono, negativo cargo). Se separa en abono/cargo al mapear.
    Para el libro consolidado de bancos, se especifica `sheet_name='BBVA'`.
    """
    df_raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
    fila_cabecera = None
    for i in range(min(15, len(df_raw))):
        valores = [str(v).strip() for v in df_raw.iloc[i].fillna("").tolist()]
        if any("F. Operación" in v or "F. Operacion" in v for v in valores):
            fila_cabecera = i
            break

    if fila_cabecera is None:
        raise ValueError(f"No se encontró fila de cabecera en hoja '{sheet_name}'")

    df = pd.read_excel(path, sheet_name=sheet_name, header=fila_cabecera)
    df.columns = [str(c).strip() for c in df.columns]

    movimientos: list[MovimientoBancario] = []
    for _, fila in df.iterrows():
        fecha_op = fila.get("F. Operación") or fila.get("F. Operacion")
        if pd.isna(fecha_op):
            continue

        importe = _parse_decimal(fila.get("Importe"))
        abono = importe if importe > 0 else Decimal("0")
        cargo = -importe if importe < 0 else Decimal("0")

        movimientos.append(MovimientoBancario(
            fecha_operacion=pd.to_datetime(fecha_op).date(),
            fecha_proceso=pd.to_datetime(fila.get("F. Valor") or fecha_op).date(),
            banco="BBVA",
            cuenta=cuenta,
            nro_operacion=texto_id(fila.get("Nº. Doc.")),
            descripcion=str(fila.get("Concepto", "")).strip(),
            abono=abono,
            cargo=cargo,
        ))

    return movimientos
