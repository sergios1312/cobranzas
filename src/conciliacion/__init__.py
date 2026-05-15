"""Lógica de conciliación: comparación de totales (ventas) y matching de
depósitos contra extractos bancarios.

Estos módulos operan exclusivamente sobre el esquema canónico de
`modelos.py`. No conocen formatos de archivo, lo que permite testearlos
con datos sintéticos y reutilizarlos si cambian los formatos de origen.
"""
