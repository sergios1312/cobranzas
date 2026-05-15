"""Orquestador del pipeline de cobranzas.

Uso:

    python main.py \\
        --inputs ./entradas/ \\
        --outputs ./salidas/ \\
        --desde 2026-04-01 --hasta 2026-04-30

Estructura esperada en ./entradas/:
    Reporte SAP/CIERRE DE TIENDAS.xlsx
    Reportes CSV/mc_*.csv
    Reportes CSV/movi_amex*.csv
    Reportes CSV/ventas-*.xlsx        (Diners ventas)
    Reportes CSV/pagos-*.xlsx         (Diners pagos)
    Extractos bancarios/Movimientos bancos *.xlsx
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from src.config import cargar_cuentas, cargar_tiendas
from src.modelos import MedioPago, Tienda, MovimientoBancario
from src.loaders import cierre_caja, izipay, diners, interbank, bbva, bcp
from src.conciliacion import ventas as concil_ventas
from src.conciliacion import depositos as concil_depositos
from src.asiento.generador import construir_asiento
from src.exporters import reporte_tienda as exporter_reporte
from src.exporters import sap_b1 as exporter_sap_b1


# Bancos cuyos loaders están implementados y validados en v1.
# Cualquier otro banco asignado a una tienda se reporta como "no procesado".
BANCOS_SOPORTADOS = {"INTERBANK", "BBVA", "BCP"}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--inputs", type=Path, required=True,
                   help="Carpeta con los archivos crudos")
    p.add_argument("--outputs", type=Path, required=True,
                   help="Carpeta donde escribir los entregables")
    p.add_argument("--desde", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                   required=True)
    p.add_argument("--hasta", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                   required=True)
    p.add_argument("--tiendas", type=str, default="",
                   help="IDs de tienda separados por coma; vacío = todas")
    p.add_argument("--config-cuentas", type=Path, default=Path("config/cuentas.yaml"))
    p.add_argument("--config-tiendas", type=Path, default=Path("config/tiendas.yaml"))
    return p.parse_args()


def _primer_archivo(carpeta: Path, patron: str) -> Path:
    """Devuelve el primer archivo de la carpeta que matchea el patrón glob."""
    candidatos = sorted(carpeta.glob(patron))
    if not candidatos:
        raise FileNotFoundError(f"No se encontró archivo con patrón '{patron}' en {carpeta}")
    return candidatos[0]


def cargar_movimientos_bancos(libro_bancos: Path) -> dict[str, list[MovimientoBancario]]:
    """Carga los movimientos de todas las hojas del libro consolidado."""
    return {
        "INTERBANK": interbank.cargar(libro_bancos),
        "BBVA": bbva.cargar(libro_bancos),
        "BCP": bcp.cargar(libro_bancos),
    }


def main():
    args = parse_args()
    args.outputs.mkdir(parents=True, exist_ok=True)

    # ---------------------------- Configuración ----------------------------
    cuentas = cargar_cuentas(args.config_cuentas)
    todas_tiendas = cargar_tiendas(args.config_tiendas)
    if args.tiendas:
        ids = {t.strip() for t in args.tiendas.split(",")}
        tiendas = [t for t in todas_tiendas if t.id_sap in ids]
    else:
        tiendas = todas_tiendas

    filtros = cuentas.filtros_bancos

    # ----------------------------- Ingesta ---------------------------------
    print("[1/5] Cargando archivos crudos...")
    cierre_path = _primer_archivo(args.inputs / "Reporte SAP", "*.xlsx")
    mc_path = _primer_archivo(args.inputs / "Reportes CSV", "mc_*.csv")
    amex_path = _primer_archivo(args.inputs / "Reportes CSV", "movi_amex*.csv")
    diners_ventas_path = _primer_archivo(args.inputs / "Reportes CSV", "ventas-*.xlsx")
    diners_pagos_path = _primer_archivo(args.inputs / "Reportes CSV", "pagos-*.xlsx")
    bancos_path = _primer_archivo(args.inputs / "Extractos bancarios", "*.xlsx")

    lineas_cierre = cierre_caja.cargar(cierre_path)
    txn_mc = izipay.cargar(mc_path, MedioPago.MASTERCARD)
    txn_amex = izipay.cargar(amex_path, MedioPago.AMEX)
    txn_diners = diners.cargar_ventas(diners_ventas_path)
    pagos_diners = diners.cargar_pagos(diners_pagos_path)
    movs_por_banco = cargar_movimientos_bancos(bancos_path)

    print(f"      Cierre: {len(lineas_cierre)} lineas | "
          f"MC: {len(txn_mc)} | AMEX: {len(txn_amex)} | "
          f"Diners V/P: {len(txn_diners)}/{len(pagos_diners)} | "
          f"Bancos: " + ", ".join(f"{k}={len(v)}" for k, v in movs_por_banco.items()))

    # ---------------------- Procesamiento por tienda -----------------------
    asientos_generados: list = []
    skip_por_banco: list[tuple[str, MedioPago, str]] = []
    sufijo_periodo = f"{args.desde.isoformat()}_{args.hasta.isoformat()}"

    for tienda in tiendas:
        if tienda.codigo_comercio_mc_amex is None and tienda.codigo_comercio_diners is None:
            continue  # tienda sin POS

        print(f"\n[2/5] Tienda {tienda.id_sap} - {tienda.nombre}")

        # Filtrar transacciones por código de comercio
        mc_t = [t for t in txn_mc if t.codigo_comercio == tienda.codigo_comercio_mc_amex]
        amex_t = [t for t in txn_amex if t.codigo_comercio == tienda.codigo_comercio_mc_amex]
        diners_t = [t for t in txn_diners if t.codigo_comercio == tienda.codigo_comercio_diners]
        pagos_diners_t = [p for p in pagos_diners if p.codigo_comercio == tienda.codigo_comercio_diners]

        reportes = {
            MedioPago.MASTERCARD: mc_t,
            MedioPago.AMEX: amex_t,
            MedioPago.DINERS: diners_t,
        }

        # 1. Conciliación de ventas
        diferencias = concil_ventas.conciliar_ventas_tienda(
            lineas_cierre, reportes, tienda.id_sap,
        )
        significativas = [d for d in diferencias if d.es_significativa(cuentas.tolerancia_conciliacion)]
        if significativas:
            print(f"      [!] {len(significativas)} diferencia(s) significativa(s) en ventas")

        matches_por_medio: dict[MedioPago, list] = {}

        # 2. Conciliación de depósitos por medio de pago
        for medio in (MedioPago.MASTERCARD, MedioPago.AMEX, MedioPago.DINERS):
            banco_nombre = tienda.banco_para(medio)
            if banco_nombre is None or banco_nombre == "PENDIENTE":
                continue  # tienda no usa este medio o está pendiente
            if banco_nombre not in BANCOS_SOPORTADOS:
                # Bancos sin loader en v1 (Scotiabank, Pichincha, BCP/BBVA combinado)
                skip_por_banco.append((tienda.id_sap, medio, banco_nombre))
                continue

            movs = movs_por_banco[banco_nombre]

            if medio == MedioPago.DINERS:
                # Para Diners filtramos pagos a solo aquellos cuya orden_pago
                # corresponde a una venta del periodo (excluye depositos de
                # ventas anteriores que solo viven en el CSV de Pagos).
                esperados = concil_depositos.depositos_esperados_diners(
                    pagos_diners_t, ventas=diners_t,
                )
                # total_a_cancelar Diners = suma del bruto de ventas con pago
                # efectivo en el periodo (excluye ventas pendientes de pago).
                ventas_pagadas = concil_depositos.ventas_diners_a_cancelar(
                    diners_t, pagos_diners_t,
                )
                transacciones_asiento = ventas_pagadas
            else:
                esperados = concil_depositos.depositos_esperados_izipay(reportes[medio])
                transacciones_asiento = reportes[medio]

            mov_filt = concil_depositos.filtrar_movimientos(
                movs, medio, tienda, banco_nombre, filtros,
            )
            matches = concil_depositos.emparejar(esperados, mov_filt, medio)
            matches_por_medio[medio] = matches

            cuadran = [m for m in matches if m.cuadra(cuentas.tolerancia_conciliacion)]
            if not cuadran:
                continue

            # 3. Total a cancelar.
            if medio == MedioPago.DINERS:
                # Para Diners usamos el bruto de ventas con pago efectivo.
                total_a_cancelar = sum(
                    (v.importe_bruto for v in transacciones_asiento),
                    Decimal("0"),
                )
            else:
                # Para MC/AMEX usamos lo reportado por la pasarela en el periodo
                # (incluye todos los dias, incluso con diff significativa).
                total_a_cancelar = sum(
                    (d.total_medio_pago for d in diferencias if d.medio_pago == medio),
                    Decimal("0"),
                )
            if total_a_cancelar <= 0:
                continue

            try:
                asiento = construir_asiento(
                    tienda=tienda,
                    medio=medio,
                    total_a_cancelar=total_a_cancelar,
                    matches=cuadran,
                    transacciones=transacciones_asiento,
                    fecha_corte=args.hasta,
                    cuentas=cuentas,
                )
            except (ValueError, KeyError) as e:
                print(f"      [!] No se pudo generar asiento {medio.value}: {e}")
                continue

            if not asiento.balanceado():
                diff = asiento.total_debito() - asiento.total_credito()
                print(f"      [!] Asiento {medio.value} NO balancea (diff={diff})")

            asientos_generados.append(asiento)
            print(f"      [ok] Asiento {medio.value}: {len(asiento.lineas)} lineas, "
                  f"haber={asiento.total_credito()}")

            # Exportar asiento a Excel SAP B1
            ruta_asiento = args.outputs / f"asiento_{tienda.id_sap}_{medio.value}_{sufijo_periodo}.xlsx"
            exporter_sap_b1.exportar(asiento, ruta_asiento)

        # 4. Exportar reporte multi-hoja por tienda (siempre, aunque no haya asientos)
        ruta_reporte = args.outputs / f"reporte_{tienda.id_sap}_{sufijo_periodo}.xlsx"
        exporter_reporte.exportar(
            path=ruta_reporte,
            tienda=tienda,
            lineas_cierre=lineas_cierre,
            diferencias=diferencias,
            txn_mc=mc_t,
            txn_amex=amex_t,
            txn_diners=diners_t,
            pagos_diners=pagos_diners_t,
            matches_por_medio=matches_por_medio,
        )

    # ---------------------------- Resumen ----------------------------------
    print(f"\n[5/5] {len(asientos_generados)} asientos generados")
    if skip_por_banco:
        print(f"\n[!] {len(skip_por_banco)} conciliaciones omitidas (banco sin loader/filtros):")
        from collections import Counter
        por_banco = Counter(b for _, _, b in skip_por_banco)
        for banco, n in por_banco.most_common():
            print(f"   {banco}: {n} casos")
    print("[ok] Listo")


if __name__ == "__main__":
    main()
