"""Loader del extracto bancario Interbank."""

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


def _parse_fecha(v):
    """Interbank exporta fechas como string 'DD/MM/YYYY' (europeo)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    # Si ya es datetime/date (algunas exportaciones), lo devolvemos tal cual
    if hasattr(v, "date"):
        return v.date() if hasattr(v, "hour") else v
    return pd.to_datetime(str(v).strip(), format="%d/%m/%Y", errors="coerce").date()


def cargar(path: str | Path, cuenta: str = "", *,
           sheet_name: str = "INTERBANK") -> list[MovimientoBancario]:
    """Lee el Excel de movimientos Interbank.

    El archivo real tiene 4 filas de metadatos antes de la cabecera (cuenta,
    empresa, etc.). Se detecta la fila de cabecera buscando 'Fecha de operación'.
    Para el libro consolidado de bancos, se especifica `sheet_name='INTERBANK'`.
    """
    df_raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
    fila_cabecera = None
    for i in range(min(15, len(df_raw))):
        valores = [str(v).strip() for v in df_raw.iloc[i].fillna("").tolist()]
        if any("Fecha de operación" in v for v in valores):
            fila_cabecera = i
            break

    if fila_cabecera is None:
        raise ValueError(f"No se encontró fila de cabecera en hoja '{sheet_name}'")

    df = pd.read_excel(path, sheet_name=sheet_name, header=fila_cabecera)
    df.columns = [str(c).strip() for c in df.columns]

    movimientos: list[MovimientoBancario] = []
    for _, fila in df.iterrows():
        if pd.isna(fila.get("Fecha de operación")):
            continue
        fecha_op = _parse_fecha(fila["Fecha de operación"])
        movimientos.append(MovimientoBancario(
            fecha_operacion=fecha_op,
            fecha_proceso=_parse_fecha(fila.get("Fecha de proceso")) or fecha_op,
            banco="INTERBANK",
            cuenta=cuenta,
            nro_operacion=texto_id(fila.get("Nro. de operación")),
            descripcion=str(fila.get("Descripción", "")).strip(),
            cargo=_parse_decimal(fila.get("Cargo")),
            abono=_parse_decimal(fila.get("Abono")),
        ))

    return movimientos
