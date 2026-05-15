"""Exporter del asiento contable en formato 'Importar de Excel' de SAP B1.

ESTADO: formato TENTATIVO. La plantilla oficial de SAP B1 no esta disponible
todavia; este formato se basa en los nombres de campo que muestra la pantalla
'Registro en el diario' del PDF (paginas 20-22). Validar contra un asiento
ya importado por contabilidad antes de usar en produccion.

Estructura generada:
  - Hoja 'Cabecera': una fila con datos del asiento (fechas, glosa, proyecto).
  - Hoja 'Lineas':   una fila por LineaAsiento, con codigo de socio, cuenta,
                     debito, credito, referencias y fecha de vencimiento.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..modelos import Asiento


def exportar(asiento: Asiento, path: str | Path) -> Path:
    """Escribe el asiento a Excel en formato 'Importar de Excel' tentativo."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    cabecera = pd.DataFrame([{
        "Fecha contabilizacion": asiento.fecha_contabilizacion,
        "Fecha vencimiento": asiento.fecha_vencimiento,
        "Fecha documento": asiento.fecha_documento,
        "Comentarios": asiento.glosa,
        "Proyecto": asiento.proyecto,
        "ID tienda": asiento.id_tienda,
        "Medio de pago": asiento.medio_pago.value,
        "Total debito": asiento.total_debito(),
        "Total credito": asiento.total_credito(),
        "Balanceado": asiento.balanceado(),
    }])

    lineas = pd.DataFrame([{
        "Cuenta de mayor / Codigo SN": l.cuenta_mayor,
        "Nombre cuenta": l.nombre_cuenta,
        "Cuenta asociada": l.cuenta_asociada or "",
        "Debito": l.debito,
        "Credito": l.credito,
        "Referencia 1": l.referencia_1,
        "Referencia 2": l.referencia_2,
        "Fecha vencimiento": l.fecha_vencimiento,
        "Proyecto": l.proyecto,
    } for l in asiento.lineas])

    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        cabecera.to_excel(xl, sheet_name="Cabecera", index=False)
        lineas.to_excel(xl, sheet_name="Lineas", index=False)

    return path
