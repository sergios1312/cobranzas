"""Script standalone para los pasos 2 y 3 del PDF:

  PASO 2  Consolida los reportes de MC, AMEX y Diners por tienda.
  PASO 3  Coteja la consolidacion contra el Cierre Caja Resumen y reporta
          que coincide y que no.

NO toca bancos ni genera asientos contables — eso esta en `main.py`. Este
script es la "demo de conciliacion de ventas" pura, util para mostrar el
flujo del PDF a un asistente contable.

Uso minimo:

    py conciliar_ventas.py --inputs "Muestra al 30.04/" --outputs ./resultados/

Flags utiles:
    --tiendas MIS.MI01,MIS.SA01    # filtrar a tiendas especificas
    --solo-discrepancias           # solo imprimir filas con diferencia > tolerancia

Output:
    resultados/conciliacion_ventas_<periodo>.xlsx con 3 hojas:
      - Resumen        una fila por (tienda, medio) con totales del periodo
      - Detalle        una fila por (tienda, fecha, medio) con cierre vs pasarela
      - Discrepancias  subset del Detalle con diferencia > tolerancia
    Tabla resumida en consola.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.conciliacion import ventas as concil_ventas
from src.config import cargar_cuentas, cargar_tiendas
from src.loaders import cierre_caja, diners, izipay
from src.modelos import (
    MedioPago,
    TipoTransaccion,
)

MEDIOS = (MedioPago.MASTERCARD, MedioPago.AMEX, MedioPago.DINERS)


def resource_path(rel: str) -> Path:
    """Resuelve la ruta de un recurso. Funciona tanto corriendo como script
    (.py) como dentro de un .exe de PyInstaller (donde los datos embebidos se
    extraen a sys._MEIPASS en tiempo de ejecucion)."""
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return Path(base) / rel


def parse_args():
    p = argparse.ArgumentParser(
        description="Conciliacion de ventas (pasos 2-3 del PDF).",
    )
    p.add_argument("--inputs", type=Path, required=True,
                   help="Carpeta con los archivos crudos del periodo")
    p.add_argument("--outputs", type=Path, required=True,
                   help="Carpeta donde escribir el Excel de resultados")
    p.add_argument("--desde", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                   help="Fecha desde (YYYY-MM-DD). Si se omite usa el rango completo del cierre.")
    p.add_argument("--hasta", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                   help="Fecha hasta (YYYY-MM-DD). Si se omite usa el rango completo del cierre.")
    p.add_argument("--tiendas", type=str, default="",
                   help="IDs de tienda separados por coma; vacio = todas las del catalogo")
    p.add_argument("--solo-discrepancias", action="store_true",
                   help="En la salida de consola solo mostrar diferencias > tolerancia")
    p.add_argument("--config-cuentas", type=Path, default=Path("config/cuentas.yaml"))
    p.add_argument("--config-tiendas", type=Path, default=Path("config/tiendas.yaml"))
    return p.parse_args()


def _primer_archivo(carpeta: Path, patron: str) -> Path:
    matches = sorted(carpeta.glob(patron))
    if not matches:
        raise FileNotFoundError(
            f"No se encontro archivo con patron '{patron}' en {carpeta}",
        )
    return matches[0]


def cargar_inputs_archivos(
    cierre_path: Path,
    mc_path: Path,
    amex_path: Path,
    diners_v_path: Path,
    diners_p_path: Path,
) -> dict:
    """Carga los 5 insumos desde rutas de archivo explicitas. Esta es la
    funcion que usa la GUI (donde el usuario elige cada archivo)."""
    return {
        "cierre": cierre_caja.cargar(cierre_path),
        "txn_mc": izipay.cargar(mc_path, MedioPago.MASTERCARD),
        "txn_amex": izipay.cargar(amex_path, MedioPago.AMEX),
        "txn_diners": diners.cargar_ventas(diners_v_path),
        "pagos_diners": diners.cargar_pagos(diners_p_path),
        "_paths": {
            "cierre": Path(cierre_path),
            "mc": Path(mc_path),
            "amex": Path(amex_path),
            "diners_ventas": Path(diners_v_path),
            "diners_pagos": Path(diners_p_path),
        },
    }


def cargar_inputs(inputs: Path) -> dict:
    """Descubre los 5 insumos por glob en las subcarpetas estandar y delega
    a `cargar_inputs_archivos`. Esta es la ruta que usa el CLI."""
    return cargar_inputs_archivos(
        cierre_path=_primer_archivo(inputs / "Reporte SAP", "*.xlsx"),
        mc_path=_primer_archivo(inputs / "Reportes CSV", "mc_*.csv"),
        amex_path=_primer_archivo(inputs / "Reportes CSV", "movi_amex*.csv"),
        diners_v_path=_primer_archivo(inputs / "Reportes CSV", "ventas-*.xlsx"),
        diners_p_path=_primer_archivo(inputs / "Reportes CSV", "pagos-*.xlsx"),
    )


def filtrar_por_periodo(insumos: dict, desde, hasta) -> dict:
    """Aplica filtro de fecha si --desde/--hasta fueron especificados."""
    if desde is None and hasta is None:
        return insumos
    fmin = desde or min(l.fecha for l in insumos["cierre"])
    fmax = hasta or max(l.fecha for l in insumos["cierre"])

    def en_rango(d):
        return d is not None and fmin <= d <= fmax

    return {
        **insumos,
        "cierre": [l for l in insumos["cierre"] if en_rango(l.fecha)],
        "txn_mc": [t for t in insumos["txn_mc"] if en_rango(t.fecha_proceso)],
        "txn_amex": [t for t in insumos["txn_amex"] if en_rango(t.fecha_proceso)],
        "txn_diners": [t for t in insumos["txn_diners"] if en_rango(t.fecha_proceso)],
    }


def conciliar_tienda(
    tienda,
    insumos: dict,
    tolerancia: Decimal,
) -> list[dict]:
    """Genera filas de detalle para una tienda: una fila por (fecha, medio)
    presente en cierre o pasarela."""
    if tienda.codigo_comercio_mc_amex is None and tienda.codigo_comercio_diners is None:
        return []

    reportes = {
        MedioPago.MASTERCARD: [
            t for t in insumos["txn_mc"]
            if t.codigo_comercio == tienda.codigo_comercio_mc_amex
        ],
        MedioPago.AMEX: [
            t for t in insumos["txn_amex"]
            if t.codigo_comercio == tienda.codigo_comercio_mc_amex
        ],
        MedioPago.DINERS: [
            t for t in insumos["txn_diners"]
            if t.codigo_comercio == tienda.codigo_comercio_diners
        ],
    }

    difs = concil_ventas.conciliar_ventas_tienda(insumos["cierre"], reportes, tienda.id_sap)

    filas = []
    for d in difs:
        # Conteos auxiliares de la pasarela
        txns = reportes[d.medio_pago]
        n_compras = sum(1 for t in txns if t.fecha_proceso == d.fecha
                        and t.tipo == TipoTransaccion.COMPRA)
        n_extornos = sum(1 for t in txns if t.fecha_proceso == d.fecha
                         and t.tipo == TipoTransaccion.EXTORNO)

        filas.append({
            "id_tienda": tienda.id_sap,
            "nombre": tienda.nombre,
            "fecha": d.fecha,
            "medio": d.medio_pago.value,
            "cierre_sap": d.total_cierre,
            "pasarela": d.total_medio_pago,
            "diferencia": d.diferencia,
            "estado": "OK" if not d.es_significativa(tolerancia) else "DISCREPANCIA",
            "txn_compras": n_compras,
            "txn_extornos": n_extornos,
        })
    return filas


def resumir(detalle: list[dict], tolerancia: Decimal) -> list[dict]:
    """Resumen por (tienda, medio): totales del periodo y conteo de discrepancias."""
    acc = defaultdict(lambda: {
        "cierre_sap": Decimal("0"),
        "pasarela": Decimal("0"),
        "fechas_total": 0,
        "fechas_con_diff": 0,
        "monto_neto_diff": Decimal("0"),
    })

    for fila in detalle:
        # Solo cuento fechas donde haya actividad (cierre o pasarela > 0)
        if fila["cierre_sap"] == 0 and fila["pasarela"] == 0:
            continue
        k = (fila["id_tienda"], fila["nombre"], fila["medio"])
        a = acc[k]
        a["cierre_sap"] += fila["cierre_sap"]
        a["pasarela"] += fila["pasarela"]
        a["fechas_total"] += 1
        if fila["estado"] == "DISCREPANCIA":
            a["fechas_con_diff"] += 1
            a["monto_neto_diff"] += fila["diferencia"]

    out = []
    for (id_t, nombre, medio), v in sorted(acc.items()):
        out.append({
            "id_tienda": id_t,
            "nombre": nombre,
            "medio": medio,
            "cierre_sap": round(v["cierre_sap"], 2),
            "pasarela": round(v["pasarela"], 2),
            "diferencia_total": round(v["cierre_sap"] - v["pasarela"], 2),
            "fechas_activas": v["fechas_total"],
            "fechas_con_diff": v["fechas_con_diff"],
            "monto_neto_diff": round(v["monto_neto_diff"], 2),
        })
    return out


def procesar(
    insumos: dict,
    tiendas: list,
    tolerancia: Decimal,
    desde=None,
    hasta=None,
) -> dict:
    """Ejecuta la conciliacion completa. Devuelve dict con detalle, resumen,
    discrepancias y la cadena de periodo. Reutilizable desde CLI y GUI."""
    if desde is not None or hasta is not None:
        insumos = filtrar_por_periodo(insumos, desde, hasta)

    detalle: list[dict] = []
    for t in tiendas:
        detalle.extend(conciliar_tienda(t, insumos, tolerancia))

    resumen = resumir(detalle, tolerancia)
    discrepancias = [f for f in detalle if f["estado"] == "DISCREPANCIA"]

    if insumos["cierre"]:
        fmin = min(l.fecha for l in insumos["cierre"])
        fmax = max(l.fecha for l in insumos["cierre"])
        periodo = f"{fmin.isoformat()}_{fmax.isoformat()}"
    else:
        periodo = "vacio"

    return {
        "detalle": detalle,
        "resumen": resumen,
        "discrepancias": discrepancias,
        "periodo": periodo,
    }


def imprimir_consola(resumen: list[dict], discrepancias: list[dict], solo_discrepancias: bool):
    """Imprime un resumen ejecutivo y la tabla de discrepancias en stdout."""
    print()
    print("=" * 90)
    print("CONCILIACION DE VENTAS — Resumen ejecutivo")
    print("=" * 90)

    # Aggregados globales
    n_tiendas = len({r["id_tienda"] for r in resumen})
    n_filas_resumen = len(resumen)
    n_discrep = len(discrepancias)
    suma_cierre = sum(r["cierre_sap"] for r in resumen)
    suma_pasarela = sum(r["pasarela"] for r in resumen)
    monto_neto = suma_cierre - suma_pasarela

    print(f"Tiendas analizadas:         {n_tiendas}")
    print(f"Filas (tienda x medio):     {n_filas_resumen}")
    print(f"Total cierre SAP:           S/ {suma_cierre:>15,.2f}")
    print(f"Total reportado pasarelas:  S/ {suma_pasarela:>15,.2f}")
    print(f"Diferencia neta:            S/ {monto_neto:>+15,.2f}")
    print(f"Discrepancias detectadas:   {n_discrep}")

    # Top 10 tiendas con mayor monto absoluto de discrepancia
    if resumen:
        top = sorted(resumen, key=lambda r: -abs(r["monto_neto_diff"]))[:10]
        print()
        print("-" * 90)
        print("Top 10 (tienda, medio) por monto absoluto de discrepancia")
        print("-" * 90)
        print(f"{'TIENDA':<12} {'MEDIO':<11} {'CIERRE':>14} "
              f"{'PASARELA':>14} {'DIF TOTAL':>12} {'#DIFFS':>7}")
        for r in top:
            if r["monto_neto_diff"] == 0:
                continue
            print(f"{r['id_tienda']:<12} {r['medio']:<11} "
                  f"{r['cierre_sap']:>14,.2f} {r['pasarela']:>14,.2f} "
                  f"{r['monto_neto_diff']:>+12,.2f} {r['fechas_con_diff']:>7}")

    # Detalle de discrepancias si se pidio
    if solo_discrepancias and discrepancias:
        print()
        print("-" * 90)
        print(f"Detalle de las {len(discrepancias)} discrepancias")
        print("-" * 90)
        print(f"{'TIENDA':<12} {'FECHA':<12} {'MEDIO':<11} "
              f"{'CIERRE':>12} {'PASARELA':>12} {'DIFF':>10}")
        for d in discrepancias[:60]:
            print(f"{d['id_tienda']:<12} {str(d['fecha']):<12} {d['medio']:<11} "
                  f"{d['cierre_sap']:>12,.2f} {d['pasarela']:>12,.2f} {d['diferencia']:>+10,.2f}")
        if len(discrepancias) > 60:
            print(f"... y {len(discrepancias) - 60} mas (ver Excel)")


def exportar_excel(
    path: Path,
    detalle: list[dict],
    resumen: list[dict],
    discrepancias: list[dict],
):
    """Exporta 3 hojas: Resumen, Detalle, Discrepancias."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        pd.DataFrame(resumen).to_excel(xl, sheet_name="Resumen", index=False)
        pd.DataFrame(detalle).to_excel(xl, sheet_name="Detalle", index=False)
        pd.DataFrame(discrepancias).to_excel(xl, sheet_name="Discrepancias", index=False)


def main():
    args = parse_args()
    args.outputs.mkdir(parents=True, exist_ok=True)

    cuentas = cargar_cuentas(args.config_cuentas)
    todas = cargar_tiendas(args.config_tiendas)
    if args.tiendas:
        ids = {t.strip() for t in args.tiendas.split(",")}
        tiendas = [t for t in todas if t.id_sap in ids]
    else:
        tiendas = todas

    print(f"[1/4] Cargando archivos crudos desde {args.inputs}...")
    insumos = cargar_inputs(args.inputs)
    for nombre, ruta in insumos["_paths"].items():
        print(f"      {nombre:>14}: {ruta.name}")

    if args.desde or args.hasta:
        print(f"[2/4] Filtrando al periodo {args.desde or '...'} -> {args.hasta or '...'}")

    print(f"[3/4] Conciliando {len(tiendas)} tienda(s)...")
    res = procesar(
        insumos, tiendas, cuentas.tolerancia_conciliacion,
        desde=args.desde, hasta=args.hasta,
    )

    ruta_excel = args.outputs / f"conciliacion_ventas_{res['periodo']}.xlsx"
    print(f"[4/4] Exportando a {ruta_excel}...")
    exportar_excel(ruta_excel, res["detalle"], res["resumen"], res["discrepancias"])

    imprimir_consola(res["resumen"], res["discrepancias"], args.solo_discrepancias)
    print(f"\n[ok] Excel generado: {ruta_excel}")


if __name__ == "__main__":
    main()
