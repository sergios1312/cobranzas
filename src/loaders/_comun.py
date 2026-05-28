"""Utilidades compartidas por los loaders de archivos crudos."""

from __future__ import annotations

import pandas as pd


def texto_id(valor) -> str:
    """Devuelve un identificador (nro de operación, documento) como string
    limpio. pandas lee las celdas numéricas como float, así que un número de
    operación como 8224818 llega como 8224818.0; esta función quita ese '.0'
    espurio para que la referencia del asiento sea exacta. Las celdas vacías
    devuelven cadena vacía."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    s = str(valor).strip()
    return s[:-2] if s.endswith(".0") and s[:-2].isdigit() else s
