"""Loaders: cada módulo toma un archivo crudo de su fuente y devuelve
estructuras canónicas del esquema (`modelos.py`).

⚠️ ESTADO: stubs. Los nombres exactos de columnas, formatos de fecha y
codificación se cierran cuando se reciban archivos reales de muestra.
Abajo se documenta el esquema esperado por loader según el análisis visual
del PDF.

────────────────────────────────────────────────────────────────────────────
CIERRE CAJA RESUMEN  (SAP Query Manager → Excel)
────────────────────────────────────────────────────────────────────────────
Columnas observadas en PDF:
  FECHA, ID TIENDA, NOMBRE, TOTAL VENTA, VISA, EFECTIVO, MASTERCARD,
  AMERICAN EXPRESS, DINERS, LUKITA (BBVA), TUNKY (INTERBANK), WALI, YAPE...
Notas:
  - Hay un registro por (FECHA × ID TIENDA).
  - Las columnas de medios de pago varían; el loader debe soportar columnas
    nuevas/faltantes con tolerancia.

────────────────────────────────────────────────────────────────────────────
IZIPAY MASTERCARD / AMEX  (mc.com.pe → CSV)
────────────────────────────────────────────────────────────────────────────
Nombre archivo:
  mc_MMAAAACODIGO.csv         (Mastercard)
  movi_amexMMAAAACODIGO.csv   (AMEX)
Columnas observadas en PDF:
  Codigo, Producto, Tipo_Mov, Fecha_Proceso, Fecha_Lote, Lote_Manual,
  Lote_Pos, Terminal, Voucher, Autorizacion, Cuotas, Tarjeta, Origen,
  Transaccion, Fecha_Consumo, Importe, Comision, Comision_IGV, IGV,
  Neto_Parcial, Neto_Total, Fecha_Abono, Observaciones
Notas:
  - 'Tipo_Mov' aparenta ser 'A' = compra y 'C' = extorno (a confirmar).
  - 'Neto_Total' es el importe que llega al banco — clave para matching.
  - 'Fecha_Abono' es la fecha esperada del depósito en banco.

────────────────────────────────────────────────────────────────────────────
DINERS VENTAS  (comerciosdinersclub.pe → XLS)
────────────────────────────────────────────────────────────────────────────
Columnas observadas en PDF:
  Código de comercio, Nombre del comercio, Red, Origen, Tipo de tarjeta,
  Fecha de proceso, Fecha de pago, Marca, Nº de tarjeta, Tipo de tarjeta,
  Código de autorización, Orden de pago, Moneda, Importe total,
  Comisión, IGV...

────────────────────────────────────────────────────────────────────────────
DINERS PAGOS  (comerciosdinersclub.pe → XLS)
────────────────────────────────────────────────────────────────────────────
Columnas observadas en PDF:
  Código de comercio, Nombre del comercio, Red, Moneda, F. Programada,
  Importe total, Comisión c/IGV, Cargo, Ajustes, Importe neto de pago,
  Retención, Importe total de abono, Estado del pago, Pago efectivo,
  Documento auto Banco, Banco, ...
Notas:
  - Estado del pago: 'PAGADO' | 'PENDIENTE'. Solo PAGADO se concilia.
  - 'Pago efectivo' es el importe que llega al banco — clave para matching.
  - Cada fila ES un depósito (a diferencia de MC/AMEX que agregan en banco).

────────────────────────────────────────────────────────────────────────────
EXTRACTO INTERBANK  (XLSX)
────────────────────────────────────────────────────────────────────────────
Columnas observadas en PDF:
  Fecha de operación, Fecha de proceso, Nro. de operación, Movimiento,
  Descripción, Canal, Cargo, Abono
Notas:
  - Filtro para MC: Descripción contiene prefijo_descripcion_mc de la tienda
    (ej. '001023366').
  - Filtro para AMEX: Descripción contiene 'AMEX'.

────────────────────────────────────────────────────────────────────────────
EXTRACTO BBVA  (XLSX)
────────────────────────────────────────────────────────────────────────────
Columnas observadas en PDF:
  F. Operación, F. Valor, Código, Nº Doc., Concepto, Importe, Oficina
Notas:
  - Filtro para Diners: Concepto contiene codigo_filtro_diners_bancos de la
    tienda (ej. 'R20100118760').
  - 'Importe' es positivo para abonos, negativo para cargos (a confirmar).
"""
