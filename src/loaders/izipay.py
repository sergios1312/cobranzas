"""Loader de CSVs de Izipay (Mastercard y American Express).

Validado contra muestra abril 2026:
- mc_042026009018628 (6).csv: 25,187 filas, 32 columnas, separador ';', UTF-8
- movi_amex042026009018628 (4).csv: 829 filas, 23 columnas, separador ';', UTF-8

Diferencias entre MC y AMEX:
- MC tiene columna `Status` ('Abonado' | 'Extorno' | 'Ret.Contracargo').
- AMEX no tiene `Status`; los extornos se identifican por `Tipo_Mov == 'C'`.
- `Fecha_Abono` viene como string `DD/MM/YYYY` en MC y como entero `YYYYMMDD`
  en AMEX. Tambien puede estar vacia.
- `Fecha_Proceso` viene como `D/MM/YYYY` (dia sin pad) en ambos.
- `Importe` puede ser negativo en extornos.
- `Neto_Total` es 0 cuando el abono aun no se ha procesado.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd

from ..modelos import MedioPago, TipoTransaccion, TransaccionMedioPago


_STATUS_EXTORNO = {"EXTORNO", "RET.CONTRACARGO"}


def _parse_decimal(v) -> Decimal:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return Decimal("0")
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return Decimal("0")
    return Decimal(s.replace(",", ""))


def _parse_fecha_proceso(v):
    """Formato 'D/MM/YYYY' (dia sin padding)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return pd.to_datetime(str(v).strip(), format="%d/%m/%Y", errors="coerce").date()


def _parse_fecha_abono(v):
    """Acepta string 'DD/MM/YYYY' (MC) o entero 'YYYYMMDD' (AMEX)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return None
    # Heuristica: si son 8 digitos puros y empieza con '20', es YYYYMMDD
    if s.isdigit() and len(s) == 8 and s.startswith("20"):
        return pd.to_datetime(s, format="%Y%m%d", errors="coerce").date()
    # En MC suele venir 'DD/MM/YYYY' o 'D/MM/YYYY'
    return pd.to_datetime(s, format="%d/%m/%Y", errors="coerce").date()


def _es_extorno(fila) -> bool:
    """Determina si una fila es extorno. MC usa 'Status', AMEX usa 'Tipo_Mov'."""
    status = str(fila.get("Status", "")).strip().upper()
    if status:
        return status in _STATUS_EXTORNO
    tipo_mov = str(fila.get("Tipo_Mov", "")).strip().upper()
    # En la muestra MC tiene tambien 'D' como anulacion (Status='Extorno'),
    # pero si no hay Status (AMEX) confiamos solo en 'C' como extorno conservador.
    return tipo_mov == "C"


def cargar(path: str | Path, medio: MedioPago) -> list[TransaccionMedioPago]:
    """Lee un CSV de Izipay. `medio` debe ser MedioPago.MASTERCARD o AMEX."""
    if medio not in (MedioPago.MASTERCARD, MedioPago.AMEX):
        raise ValueError(f"Medio de pago no valido para Izipay: {medio}")

    df = pd.read_csv(path, encoding="utf-8", sep=";", dtype=str)

    transacciones: list[TransaccionMedioPago] = []
    for _, fila in df.iterrows():
        tipo = TipoTransaccion.EXTORNO if _es_extorno(fila) else TipoTransaccion.COMPRA

        # Convencion: los importes siempre se guardan en valor absoluto.
        # El signo (compra vs extorno) se infiere de `tipo`. Asi se evita
        # confundir restas en sumas posteriores.
        importe_bruto = abs(_parse_decimal(fila.get("Importe")))
        importe_neto = abs(_parse_decimal(fila.get("Neto_Total")))

        transacciones.append(TransaccionMedioPago(
            medio_pago=medio,
            codigo_comercio=str(fila["Codigo"]).strip(),
            fecha_proceso=_parse_fecha_proceso(fila.get("Fecha_Proceso")),
            fecha_abono=_parse_fecha_abono(fila.get("Fecha_Abono")),
            importe_bruto=importe_bruto,
            comision=abs(_parse_decimal(fila.get("Comision"))),
            igv=abs(_parse_decimal(fila.get("IGV"))),
            importe_neto=importe_neto,
            voucher=str(fila.get("Voucher", "")).strip() or None,
            autorizacion=str(fila.get("Autorizacion", "")).strip() or None,
            tipo=tipo,
        ))

    return transacciones
