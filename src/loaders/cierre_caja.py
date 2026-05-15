"""Loader del Cierre Caja Resumen exportado de SAP Query Manager.

Validado contra muestra abril 2026:
- CIERRE DE TIENDAS.xlsx: 6,060 filas, 27 columnas, hoja 'Hoja1'.
- Cubre 202 IDs de tienda × 30 dias.

El reporte real tiene 13+ medios de pago. Para v1 sólo nos importan MC, AMEX,
DINERS (los que se concilian con asiento). Las columnas no contempladas se
ignoran silenciosamente — si en el futuro se agregan medios al enum se mapean
agregando entradas a COLUMNAS_MEDIO_PAGO.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd

from ..modelos import LineaCierreCaja, MedioPago


# Mapeo de nombre de columna del Excel (UPPER) → MedioPago canonico.
# Solo se incluyen medios para los que el enum tiene valor.
COLUMNAS_MEDIO_PAGO = {
    "VISA": MedioPago.VISA,
    "EFECTIVO": MedioPago.EFECTIVO,
    "MASTERCARD": MedioPago.MASTERCARD,
    "AMERICAN EXPRESS": MedioPago.AMEX,
    "DINERS": MedioPago.DINERS,
    "LUKITA (BBVA)": MedioPago.LUKITA,
    "TUNKY (INTERBANK)": MedioPago.TUNKY,
    "WALI (INTERBANK)": MedioPago.WALI,
    "YAPE (BCP)": MedioPago.YAPE,
}

# Columnas que NO son medios de pago (totales, notas, etc) que se ignoran
# explicitamente para que su presencia no cause sorpresas.
COLUMNAS_IGNORADAS = {
    "TOTAL VENTA", "TOTAL", "NOTA CREDITO", "ADELANTO (PRE-VENTA)",
    "TRANSFERENCIA MALVITEC", "RAPPI", "MILLAS INTERBANK", "PUNTOS VIDA (BBVA)",
    "YAPE (BCP) - 2", "YAPE (BCP) - 3", "SANTANDER", "MIS CUOTAS", "CUOTEALO",
    "POWERPAY", "CÁLIDDA",
}


def cargar(path: str | Path) -> list[LineaCierreCaja]:
    """Lee el Cierre Caja Resumen y devuelve una lista de LineaCierreCaja.

    Las filas con FECHA o ID TIENDA vacios se descartan.
    """
    df = pd.read_excel(path)
    df.columns = [str(c).strip().upper() for c in df.columns]

    lineas: list[LineaCierreCaja] = []
    for _, fila in df.iterrows():
        if pd.isna(fila.get("FECHA")) or pd.isna(fila.get("ID TIENDA")):
            continue

        importes: dict[MedioPago, Decimal] = {}
        for col_excel, medio in COLUMNAS_MEDIO_PAGO.items():
            if col_excel not in df.columns:
                continue
            valor = fila[col_excel]
            if pd.notna(valor) and valor != 0:
                importes[medio] = Decimal(str(valor))

        lineas.append(LineaCierreCaja(
            fecha=pd.to_datetime(fila["FECHA"]).date(),
            id_tienda=str(fila["ID TIENDA"]).strip(),
            nombre_tienda=str(fila["NOMBRE"]).strip() if pd.notna(fila.get("NOMBRE")) else "",
            importes=importes,
        ))

    return lineas
