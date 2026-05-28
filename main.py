"""Orquestador CLI del pipeline de cobranzas.

Ejecuta los pasos 2-5 del proceso (consolidación, conciliación de ventas,
conciliación de depósitos y generación del asiento SAP). La lógica vive en
`src/pipeline.py`, compartida con la interfaz gráfica.

Uso:

    python main.py --inputs ./entradas --outputs ./salidas \\
                   --desde 2026-04-01 --hasta 2026-04-30 \\
                   [--tiendas MIS.MI01,MIS.SA01]

Estructura esperada en --inputs:
    Reporte SAP/CIERRE DE TIENDAS.xlsx
    Reportes CSV/mc_*.csv
    Reportes CSV/movi_amex*.csv
    Reportes CSV/ventas-*.xlsx        (Diners ventas)
    Reportes CSV/pagos-*.xlsx         (Diners pagos)
    Extractos bancarios/*.xlsx        (libro consolidado de bancos)
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from src import pipeline
from src.config import cargar_cuentas, cargar_tiendas


def parse_args():
    p = argparse.ArgumentParser(
        description="Pipeline de conciliación de cobranzas de tiendas físicas.")
    p.add_argument("--inputs", type=Path, required=True,
                   help="Carpeta con los archivos crudos del período")
    p.add_argument("--outputs", type=Path, required=True,
                   help="Carpeta donde escribir los entregables")
    p.add_argument("--desde", required=True,
                   type=lambda s: datetime.strptime(s, "%Y-%m-%d").date())
    p.add_argument("--hasta", required=True,
                   type=lambda s: datetime.strptime(s, "%Y-%m-%d").date())
    p.add_argument("--tiendas", type=str, default="",
                   help="IDs de tienda separados por coma; vacío = todas")
    p.add_argument("--config-cuentas", type=Path,
                   default=Path("config/cuentas.yaml"))
    p.add_argument("--config-tiendas", type=Path,
                   default=Path("config/tiendas.yaml"))
    return p.parse_args()


def main():
    args = parse_args()

    cuentas = cargar_cuentas(args.config_cuentas)
    pendientes = cuentas.placeholders_pendientes()
    if pendientes:
        print(f"[!] {len(pendientes)} código(s) contable(s) pendiente(s) en "
              f"{args.config_cuentas}; los asientos que los requieran se omitirán:")
        for p in pendientes:
            print(f"    - {p}")

    tiendas = cargar_tiendas(args.config_tiendas)
    if args.tiendas:
        ids = {t.strip() for t in args.tiendas.split(",")}
        tiendas = [t for t in tiendas if t.id_sap in ids]

    print("[1/3] Cargando archivos crudos...")
    insumos = pipeline.cargar_insumos(**pipeline.descubrir_archivos(args.inputs))

    print(f"[2/3] Procesando {len(tiendas)} tienda(s), período "
          f"{args.desde.isoformat()} -> {args.hasta.isoformat()}...")
    resultado = pipeline.ejecutar(
        insumos=insumos, tiendas=tiendas, cuentas=cuentas,
        desde=args.desde, hasta=args.hasta, log=print,
    )

    print("[3/3] Exportando entregables...")
    escritos = pipeline.exportar(resultado, args.outputs, log=print)

    print(f"\n[ok] {len(resultado.asientos)} asiento(s) generado(s), "
          f"{len(escritos)} archivo(s) en {args.outputs}")
    con_adv = resultado.asientos_con_advertencia
    if con_adv:
        print(f"[!] {len(con_adv)} asiento(s) marcados para revisión contable")
    if resultado.skip_por_banco:
        print(f"[!] {len(resultado.skip_por_banco)} conciliación(es) omitida(s) "
              f"(banco sin loader):")
        for banco, n in resultado.resumen_skip_por_banco().items():
            print(f"    {banco}: {n} caso(s)")


if __name__ == "__main__":
    main()
