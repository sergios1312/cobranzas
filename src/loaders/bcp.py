"""Loader del extracto bancario BCP.

Validado contra muestra abril 2026 (hoja 'BCP 94' del libro consolidado).

Estructura observada:
- Filas 0-2: metadatos (Cuenta, Moneda, Tipo de Cuenta).
- Fila 3: cabecera (Fecha, Fecha valuta, Descripcion operacion, Monto, Saldo, ...).
- Como BBVA: 'Monto' es un solo numero con signo (positivo abono, negativo cargo).
- Fechas en 'DD/MM/YYYY'.

TODO: el filtro de descripcion para identificar depositos MC/AMEX/Diners en BCP
no esta documentado en el PDF (el PDF usa Interbank/BBVA). Para v1 el loader
solo carga; la conciliacion con BCP requiere validar los patrones contra
archivos con depositos MC/AMEX/Diners reales en BCP.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd

from ..modelos import MovimientoBancario


def _parse_decimal(v) -> Decimal:
    if pd.isna(v) or v == "":
        return Decimal("0")
    return Decimal(str(v).replace(",", ""))


def _parse_fecha(v):
    """BCP exporta fechas como string 'DD/MM/YYYY'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if hasattr(v, "date"):
        return v.date() if hasattr(v, "hour") else v
    return pd.to_datetime(str(v).strip(), format="%d/%m/%Y", errors="coerce").date()


def cargar(path: str | Path, cuenta: str = "", *, sheet_name: str = "BCP 94") -> list[MovimientoBancario]:
    """Lee el Excel de movimientos BCP. Detecta la fila de cabecera buscando
    'Fecha' como primera columna no vacia con sus pares 'Monto' y 'Saldo'.
    """
    df_raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
    fila_cabecera = None
    for i in range(min(15, len(df_raw))):
        valores = [str(v).strip() for v in df_raw.iloc[i].fillna("").tolist()]
        if "Fecha" in valores and "Monto" in valores and "Saldo" in valores:
            fila_cabecera = i
            break

    if fila_cabecera is None:
        raise ValueError(f"No se encontró fila de cabecera en hoja '{sheet_name}'")

    df = pd.read_excel(path, sheet_name=sheet_name, header=fila_cabecera)
    df.columns = [str(c).strip() for c in df.columns]

    movimientos: list[MovimientoBancario] = []
    for _, fila in df.iterrows():
        fecha = _parse_fecha(fila.get("Fecha"))
        if fecha is None:
            continue

        importe = _parse_decimal(fila.get("Monto"))
        abono = importe if importe > 0 else Decimal("0")
        cargo = -importe if importe < 0 else Decimal("0")

        movimientos.append(MovimientoBancario(
            fecha_operacion=fecha,
            fecha_proceso=_parse_fecha(fila.get("Fecha valuta")) or fecha,
            banco="BCP",
            cuenta=cuenta,
            nro_operacion=str(fila.get("Operación - Número", "")).strip(),
            descripcion=str(fila.get("Descripción operación", "")).strip(),
            abono=abono,
            cargo=cargo,
        ))

    return movimientos
