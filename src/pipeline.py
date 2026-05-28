"""Pipeline completo de cobranzas — pasos 2 a 5 del proceso del PDF.

Esta es la lógica compartida entre la CLI (`main.py`) y la interfaz gráfica
(`conciliar_gui.py`): consolidación, conciliación de ventas, conciliación de
depósitos y generación del asiento SAP. No imprime ni decide formato de
salida; recibe un callback `log` para los mensajes de progreso y devuelve
estructuras de datos que el llamador presenta o exporta.

Lo único fuera de alcance son el paso 1 (descarga de reportes) y la
importación final del asiento a SAP, que siguen siendo manuales.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from .asiento.generador import construir_asiento
from .conciliacion import depositos as concil_depositos
from .conciliacion import ventas as concil_ventas
from .config import ConfiguracionCuentas
from .exporters import reporte_tienda as exporter_reporte
from .exporters import sap_b1 as exporter_sap_b1
from .loaders import bbva, bcp, cierre_caja, diners, interbank, izipay
from .modelos import (
    Asiento,
    DiferenciaConciliacion,
    LineaCierreCaja,
    MatchDeposito,
    MedioPago,
    MovimientoBancario,
    PagoDiners,
    Tienda,
    TransaccionMedioPago,
)

# Bancos con loader implementado y validado. Cualquier otro banco asignado a
# una tienda se reporta como conciliación omitida.
BANCOS_SOPORTADOS = {"INTERBANK", "BBVA", "BCP"}

MEDIOS = (MedioPago.MASTERCARD, MedioPago.AMEX, MedioPago.DINERS)

# Callback de progreso. La CLI le pasa `print`; la GUI, un volcado a su panel.
Log = Callable[[str], None]


def _sin_log(_mensaje: str) -> None:
    """Log por defecto: descarta el mensaje."""


# ---------------------------------------------------------------------------
# Estructuras de datos
# ---------------------------------------------------------------------------

@dataclass
class Insumos:
    """Los seis insumos crudos del proceso, ya cargados al modelo canónico."""
    lineas_cierre: list[LineaCierreCaja]
    txn_mc: list[TransaccionMedioPago]
    txn_amex: list[TransaccionMedioPago]
    txn_diners: list[TransaccionMedioPago]
    pagos_diners: list[PagoDiners]
    movs_por_banco: dict[str, list[MovimientoBancario]]


@dataclass
class ResultadoTienda:
    """Todo lo producido para una tienda: conciliación, matches y asientos."""
    tienda: Tienda
    diferencias: list[DiferenciaConciliacion]
    txn_mc: list[TransaccionMedioPago]
    txn_amex: list[TransaccionMedioPago]
    txn_diners: list[TransaccionMedioPago]
    pagos_diners: list[PagoDiners]
    matches_por_medio: dict[MedioPago, list[MatchDeposito]] = field(default_factory=dict)
    asientos: list[Asiento] = field(default_factory=list)

    def diferencias_significativas(self, tolerancia: Decimal) -> list[DiferenciaConciliacion]:
        return [d for d in self.diferencias if d.es_significativa(tolerancia)]


@dataclass
class ResultadoPipeline:
    """Resultado completo del pipeline para un período."""
    desde: date
    hasta: date
    lineas_cierre: list[LineaCierreCaja] = field(default_factory=list)
    resultados: list[ResultadoTienda] = field(default_factory=list)
    skip_por_banco: list[tuple[str, MedioPago, str]] = field(default_factory=list)

    @property
    def asientos(self) -> list[Asiento]:
        return [a for r in self.resultados for a in r.asientos]

    @property
    def asientos_con_advertencia(self) -> list[Asiento]:
        return [a for a in self.asientos if a.advertencias]

    def resumen_skip_por_banco(self) -> dict[str, int]:
        return dict(Counter(banco for _, _, banco in self.skip_por_banco))


# ---------------------------------------------------------------------------
# Carga de insumos
# ---------------------------------------------------------------------------

def _unico_archivo(carpeta: Path, patron: str) -> Path:
    """Devuelve el único archivo de `carpeta` que matchea `patron`. Ignora los
    temporales de Excel ('~$...'). Falla si no hay ninguno, o si hay más de uno
    (ambigüedad: no se adivina cuál del período usar)."""
    candidatos = [p for p in sorted(carpeta.glob(patron))
                  if not p.name.startswith("~$")]
    if not candidatos:
        raise FileNotFoundError(
            f"No se encontró archivo con patrón '{patron}' en {carpeta}")
    if len(candidatos) > 1:
        nombres = ", ".join(p.name for p in candidatos)
        raise ValueError(
            f"Hay {len(candidatos)} archivos que matchean '{patron}' en "
            f"{carpeta}: {nombres}. Deja solo el del período a procesar.")
    return candidatos[0]


def descubrir_archivos(inputs: Path) -> dict[str, Path]:
    """Localiza los 6 insumos por glob en la estructura de carpetas estándar."""
    inputs = Path(inputs)
    return {
        "cierre": _unico_archivo(inputs / "Reporte SAP", "*.xlsx"),
        "mc": _unico_archivo(inputs / "Reportes CSV", "mc_*.csv"),
        "amex": _unico_archivo(inputs / "Reportes CSV", "movi_amex*.csv"),
        "diners_ventas": _unico_archivo(inputs / "Reportes CSV", "ventas-*.xlsx"),
        "diners_pagos": _unico_archivo(inputs / "Reportes CSV", "pagos-*.xlsx"),
        "bancos": _unico_archivo(inputs / "Extractos bancarios", "*.xlsx"),
    }


def cargar_insumos(
    *,
    cierre: str | Path,
    mc: str | Path,
    amex: str | Path,
    diners_ventas: str | Path,
    diners_pagos: str | Path,
    bancos: str | Path,
) -> Insumos:
    """Carga los 6 insumos crudos al modelo canónico desde rutas explícitas.

    El libro de bancos es un único Excel con una hoja por banco; se cargan las
    tres hojas soportadas (Interbank, BBVA, BCP)."""
    return Insumos(
        lineas_cierre=cierre_caja.cargar(cierre),
        txn_mc=izipay.cargar(mc, MedioPago.MASTERCARD),
        txn_amex=izipay.cargar(amex, MedioPago.AMEX),
        txn_diners=diners.cargar_ventas(diners_ventas),
        pagos_diners=diners.cargar_pagos(diners_pagos),
        movs_por_banco={
            "INTERBANK": interbank.cargar(bancos),
            "BBVA": bbva.cargar(bancos),
            "BCP": bcp.cargar(bancos),
        },
    )


# ---------------------------------------------------------------------------
# Ejecución del pipeline
# ---------------------------------------------------------------------------

def _filtrar_periodo(insumos: Insumos, desde: date, hasta: date) -> Insumos:
    """Filtra Cierre y pasarelas al período [desde, hasta]. Los movimientos
    bancarios NO se filtran: el abono de una venta del período puede
    acreditarse en el banco después de `hasta`."""
    def en_periodo(d: date | None) -> bool:
        return d is not None and desde <= d <= hasta

    return Insumos(
        lineas_cierre=[l for l in insumos.lineas_cierre if en_periodo(l.fecha)],
        txn_mc=[t for t in insumos.txn_mc if en_periodo(t.fecha_proceso)],
        txn_amex=[t for t in insumos.txn_amex if en_periodo(t.fecha_proceso)],
        txn_diners=[t for t in insumos.txn_diners if en_periodo(t.fecha_proceso)],
        pagos_diners=insumos.pagos_diners,
        movs_por_banco=insumos.movs_por_banco,
    )


def _asiento_de_tienda(
    res: ResultadoTienda,
    medio: MedioPago,
    insumos: Insumos,
    cuentas: ConfiguracionCuentas,
    hasta: date,
    log: Log,
) -> None:
    """Concilia depósitos y genera el asiento de un (tienda, medio). Anexa el
    resultado a `res`. No lanza: los errores se reportan vía `log`."""
    tienda = res.tienda
    banco_nombre = tienda.banco_para(medio)
    if banco_nombre is None or banco_nombre == "PENDIENTE":
        return  # la tienda no usa este medio o el banco está sin asignar
    if banco_nombre not in BANCOS_SOPORTADOS:
        return  # el llamador ya registró el skip por banco sin loader

    movs = insumos.movs_por_banco[banco_nombre]
    reportes = {
        MedioPago.MASTERCARD: res.txn_mc,
        MedioPago.AMEX: res.txn_amex,
        MedioPago.DINERS: res.txn_diners,
    }

    if medio == MedioPago.DINERS:
        # Para Diners filtramos a pagos cuya orden corresponde a una venta del
        # período (excluye depósitos de ventas de meses anteriores).
        esperados = concil_depositos.depositos_esperados_diners(
            res.pagos_diners, ventas=res.txn_diners)
        transacciones_asiento = concil_depositos.ventas_diners_a_cancelar(
            res.txn_diners, res.pagos_diners)
    else:
        esperados = concil_depositos.depositos_esperados_izipay(reportes[medio])
        transacciones_asiento = reportes[medio]

    mov_filt = concil_depositos.filtrar_movimientos(
        movs, medio, tienda, banco_nombre, cuentas.filtros_bancos)
    matches = concil_depositos.emparejar(esperados, mov_filt, medio)
    res.matches_por_medio[medio] = matches

    cuadran = [m for m in matches if m.cuadra(cuentas.tolerancia_conciliacion)]
    if not cuadran:
        return

    if medio == MedioPago.DINERS:
        total_a_cancelar = sum(
            (v.importe_bruto for v in transacciones_asiento), Decimal("0"))
    else:
        total_a_cancelar = sum(
            (d.total_medio_pago for d in res.diferencias
             if d.medio_pago == medio), Decimal("0"))
    if total_a_cancelar <= 0:
        return

    try:
        asiento = construir_asiento(
            tienda=tienda, medio=medio, total_a_cancelar=total_a_cancelar,
            matches=cuadran, transacciones=transacciones_asiento,
            fecha_corte=hasta, cuentas=cuentas)
    except (ValueError, KeyError) as e:
        log(f"  [!] No se pudo generar asiento {medio.value}: {e}")
        return

    if not asiento.balanceado():
        diff = asiento.total_debito() - asiento.total_credito()
        log(f"  [!] Asiento {medio.value} NO balancea (diff={diff})")
    res.asientos.append(asiento)
    log(f"  [ok] Asiento {medio.value}: {len(asiento.lineas)} líneas, "
        f"haber={asiento.total_credito()}")
    for adv in asiento.advertencias:
        log(f"  [!] {adv}")


def ejecutar(
    *,
    insumos: Insumos,
    tiendas: list[Tienda],
    cuentas: ConfiguracionCuentas,
    desde: date,
    hasta: date,
    log: Log = _sin_log,
) -> ResultadoPipeline:
    """Ejecuta los pasos 2-5 del proceso para cada tienda del período."""
    insumos = _filtrar_periodo(insumos, desde, hasta)
    resultado = ResultadoPipeline(
        desde=desde, hasta=hasta, lineas_cierre=insumos.lineas_cierre)

    for tienda in tiendas:
        if (tienda.codigo_comercio_mc_amex is None
                and tienda.codigo_comercio_diners is None):
            continue  # tienda sin POS

        log(f"Tienda {tienda.id_sap} - {tienda.nombre}")
        mc_t = [t for t in insumos.txn_mc
                if t.codigo_comercio == tienda.codigo_comercio_mc_amex]
        amex_t = [t for t in insumos.txn_amex
                  if t.codigo_comercio == tienda.codigo_comercio_mc_amex]
        diners_t = [t for t in insumos.txn_diners
                    if t.codigo_comercio == tienda.codigo_comercio_diners]
        pagos_t = [p for p in insumos.pagos_diners
                   if p.codigo_comercio == tienda.codigo_comercio_diners]

        diferencias = concil_ventas.conciliar_ventas_tienda(
            insumos.lineas_cierre,
            {MedioPago.MASTERCARD: mc_t, MedioPago.AMEX: amex_t,
             MedioPago.DINERS: diners_t},
            tienda.id_sap)
        res = ResultadoTienda(
            tienda=tienda, diferencias=diferencias, txn_mc=mc_t, txn_amex=amex_t,
            txn_diners=diners_t, pagos_diners=pagos_t)

        sig = res.diferencias_significativas(cuentas.tolerancia_conciliacion)
        if sig:
            log(f"  [!] {len(sig)} diferencia(s) significativa(s) en ventas")

        for medio in MEDIOS:
            banco = tienda.banco_para(medio)
            if (banco is not None and banco != "PENDIENTE"
                    and banco not in BANCOS_SOPORTADOS):
                resultado.skip_por_banco.append((tienda.id_sap, medio, banco))
                continue
            _asiento_de_tienda(res, medio, insumos, cuentas, hasta, log)

        resultado.resultados.append(res)

    return resultado


# ---------------------------------------------------------------------------
# Exportación de entregables
# ---------------------------------------------------------------------------

def exportar(
    resultado: ResultadoPipeline,
    outputs: str | Path,
    log: Log = _sin_log,
) -> list[Path]:
    """Escribe en `outputs` el reporte multi-hoja por tienda y un Excel de
    asiento SAP B1 por cada asiento generado. Devuelve las rutas escritas."""
    outputs = Path(outputs)
    outputs.mkdir(parents=True, exist_ok=True)
    sufijo = f"{resultado.desde.isoformat()}_{resultado.hasta.isoformat()}"
    escritos: list[Path] = []

    for res in resultado.resultados:
        for asiento in res.asientos:
            # Los asientos con advertencias o que no balancean van a un subdir
            # aparte para que el contador no los importe junto con los buenos.
            carpeta = outputs / "_revisar" if asiento.requiere_revision() else outputs
            ruta = carpeta / (f"asiento_{res.tienda.id_sap}_"
                              f"{asiento.medio_pago.value}_{sufijo}.xlsx")
            exporter_sap_b1.exportar(asiento, ruta)
            escritos.append(ruta)

        ruta_reporte = outputs / f"reporte_{res.tienda.id_sap}_{sufijo}.xlsx"
        exporter_reporte.exportar(
            path=ruta_reporte,
            tienda=res.tienda,
            lineas_cierre=resultado.lineas_cierre,
            diferencias=res.diferencias,
            txn_mc=res.txn_mc,
            txn_amex=res.txn_amex,
            txn_diners=res.txn_diners,
            pagos_diners=res.pagos_diners,
            matches_por_medio=res.matches_por_medio,
        )
        escritos.append(ruta_reporte)

    log(f"{len(escritos)} archivo(s) escritos en {outputs}")
    return escritos
