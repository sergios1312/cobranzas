"""Construye el asiento contable a partir de:
  - los matches de depósito validados (debe banco)
  - los extornos identificados en el período (debe cliente genérico)
  - el total a cancelar de la cuenta puente (haber)
  - el residuo, que se imputa como comisión a la pasarela

Patrón documentado en el PDF (ejemplo Mastercard tienda Schell):
  - Línea 1 [haber]: Cuenta puente 121206 — total a cancelar
  - Líneas 2..N [debe]: Banco Interbank (104107) — un débito por depósito
  - Línea N+1 [debe]: Cliente genérico (C00000000 / 461101) — extornos
  - Línea final [debe]: Proveedor comisión (P20432405525 / 421201) — residuo
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from ..config import ConfiguracionCuentas, es_placeholder
from ..modelos import (
    Asiento,
    LineaAsiento,
    MatchDeposito,
    MedioPago,
    Tienda,
    TipoTransaccion,
    TransaccionMedioPago,
)


def _total_extornos(transacciones: Iterable[TransaccionMedioPago]) -> Decimal:
    return sum(
        (t.importe_bruto for t in transacciones
         if t.tipo == TipoTransaccion.EXTORNO),
        Decimal("0"),
    )


def construir_asiento(
    *,
    tienda: Tienda,
    medio: MedioPago,
    total_a_cancelar: Decimal,
    matches: list[MatchDeposito],
    transacciones: list[TransaccionMedioPago],
    fecha_corte: date,
    cuentas: ConfiguracionCuentas,
) -> Asiento:
    """Arma el asiento. `total_a_cancelar` es la suma de las operaciones
    seleccionadas en SAP para reconciliar (equivale a lo que el operador
    elige en la pantalla 'Reconciliación Interna' del PDF, excluyendo las
    diferencias)."""

    banco_nombre = tienda.banco_para(medio)
    if banco_nombre is None or banco_nombre == "PENDIENTE":
        raise ValueError(
            f"Tienda {tienda.id_sap} no tiene banco asignado para {medio.value}"
        )
    banco_cfg = cuentas.bancos[banco_nombre]
    cuenta_socio_banco = banco_cfg.codigo_socio_sap
    nombre_banco_largo = f"{banco_cfg.nombre_largo} CTA. {banco_cfg.cuenta_corriente}"

    # Aplanar todos los movimientos bancarios de los matches encontrados.
    # Para MC/AMEX cada match agrupa varios movs del dia; para Diners es 0 o 1.
    movimientos_banco = [
        mov
        for m in matches if m.encontrado
        for mov in m.movimientos
    ]
    total_debitos = sum((mov.abono for mov in movimientos_banco), Decimal("0"))
    total_extornos = _total_extornos(transacciones)
    comision = total_a_cancelar - total_debitos - total_extornos

    # Un asiento con un codigo placeholder (XXX/PENDIENTE) no es importable a
    # SAP. Se valida solo lo que este asiento realmente usa y se aborta con un
    # mensaje claro; el llamador lo omite y continua con el resto.
    faltantes: list[str] = []
    if es_placeholder(cuenta_socio_banco):
        faltantes.append(f"banco {banco_nombre} (codigo_socio_sap)")
    if total_extornos > 0 and es_placeholder(cuentas.cliente_generico_codigo):
        faltantes.append("cliente generico (codigo_socio)")
    if comision != 0:
        _prov = cuentas.proveedores_comision[medio]
        if es_placeholder(_prov.codigo_socio) or es_placeholder(_prov.cuenta_asociada):
            faltantes.append(f"proveedor comision {medio.value}")
    if faltantes:
        raise ValueError(
            "codigos contables pendientes en cuentas.yaml: " + ", ".join(faltantes)
        )

    # Rango de fechas para la glosa
    fechas = [mov.fecha_operacion for mov in movimientos_banco]
    if fechas:
        rango = f"{min(fechas).strftime('%d')}-{max(fechas).strftime('%d')}"
    else:
        rango = fecha_corte.strftime("%d")
    glosa = f"INGRESOS {medio.value} {rango}"

    # ---- Línea 1: HABER cuenta puente ----
    lineas: list[LineaAsiento] = [
        LineaAsiento(
            cuenta_mayor=cuentas.cuentas_puente[medio],
            nombre_cuenta=cuentas.nombres_cuenta_puente[medio],
            cuenta_asociada=cuentas.cuentas_puente[medio],
            credito=total_a_cancelar,
            proyecto=tienda.codigo_proyecto,
            fecha_vencimiento=fecha_corte,
        )
    ]

    # ---- Líneas N: DEBE banco (uno por movimiento bancario individual) ----
    for mov in movimientos_banco:
        lineas.append(LineaAsiento(
            cuenta_mayor=cuenta_socio_banco,
            nombre_cuenta=nombre_banco_largo,
            cuenta_asociada=cuenta_socio_banco,
            debito=mov.abono,
            referencia_1=mov.nro_operacion,
            fecha_vencimiento=mov.fecha_operacion,
            proyecto=tienda.codigo_proyecto,
        ))

    # ---- Línea extorno (si aplica): DEBE cliente genérico ----
    if total_extornos > 0:
        lineas.append(LineaAsiento(
            cuenta_mayor=cuentas.cliente_generico_codigo,
            nombre_cuenta=cuentas.cliente_generico_nombre,
            cuenta_asociada=cuentas.cliente_generico_cuenta_asociada,
            debito=total_extornos,
            proyecto=tienda.codigo_proyecto,
            fecha_vencimiento=fecha_corte,
        ))

    # ---- Línea comisión: residuo del asiento, va al proveedor ----
    # Normalmente el residuo es la comisión bancaria (DEBE). Si los depósitos
    # más los extornos superan el total a cancelar, el residuo es negativo: se
    # registra como CRÉDITO (un DEBE negativo sería un asiento inválido) y se
    # marca el asiento para revisión contable.
    advertencias: list[str] = []
    if comision != 0:
        prov = cuentas.proveedores_comision[medio]
        lineas.append(LineaAsiento(
            cuenta_mayor=prov.codigo_socio,
            nombre_cuenta=prov.nombre,
            cuenta_asociada=prov.cuenta_asociada,
            debito=comision if comision > 0 else Decimal("0"),
            credito=-comision if comision < 0 else Decimal("0"),
            proyecto=tienda.codigo_proyecto,
            fecha_vencimiento=fecha_corte,
        ))
        if comision < 0:
            advertencias.append(
                f"Residuo de comisión negativo ({comision}): los depósitos y "
                f"extornos superan el total a cancelar; revisar (posibles "
                f"extornos de un período anterior)."
            )

    return Asiento(
        fecha_contabilizacion=fecha_corte,
        fecha_vencimiento=fecha_corte,
        fecha_documento=fecha_corte,
        glosa=glosa,
        proyecto=tienda.codigo_proyecto,
        medio_pago=medio,
        id_tienda=tienda.id_sap,
        lineas=lineas,
        advertencias=advertencias,
    )
