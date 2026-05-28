"""Interfaz gráfica para los pasos 2 y 3 del proceso de cobranzas.

El usuario carga los 5 reportes del período (Cierre SAP, Mastercard y AMEX
de Izipay, y los dos de Diners), ajusta el rango de fechas si quiere acotar
el período y presiona Procesar. La app consolida los reportes por tienda y
los coteja contra el Cierre Caja Resumen, mostrando qué cuadra y dónde hay
diferencias, y exportando un Excel con Resumen, Detalle y Discrepancias.

NO toca depósitos bancarios ni genera asientos contables — eso es el pipeline
completo (`main.py`). Esta GUI cubre solo los pasos 2-3 del PDF.

Los catálogos (`config/tiendas.yaml`, `config/cuentas.yaml`) van embebidos en
el .exe (ver `resource_path`).

Para correr como script:   py conciliar_gui.py
Para empaquetar:           ver build_exe.py
"""

from __future__ import annotations

import calendar
import os
import sys
import threading
import tkinter as tk
import traceback
from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

import conciliar_ventas as cv
from src.config import cargar_cuentas, cargar_tiendas
from src.loaders import cierre_caja

# (clave, etiqueta visible, tipos de archivo para el filedialog).
# La clave coincide con los parámetros de cv.cargar_inputs_archivos.
ARCHIVOS = [
    ("cierre", "Cierre Caja (SAP)", [("Excel", "*.xlsx *.xls")]),
    ("mc", "Mastercard (Izipay)", [("CSV", "*.csv")]),
    ("amex", "AMEX (Izipay)", [("CSV", "*.csv")]),
    ("diners_v", "Diners — Ventas", [("Excel", "*.xlsx *.xls")]),
    ("diners_p", "Diners — Pagos", [("Excel", "*.xlsx *.xls")]),
]


def resource_path(rel: str) -> Path:
    """Resuelve un recurso embebido. Funciona como script y dentro del .exe."""
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return Path(base) / rel


def app_dir() -> Path:
    """Carpeta donde vive el .exe (o el script en modo desarrollo)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def _bordes_del_mes(d: date) -> tuple[date, date]:
    """Primer y último día del mes al que pertenece `d`."""
    _, ultimo = calendar.monthrange(d.year, d.month)
    return d.replace(day=1), date(d.year, d.month, ultimo)


def _parse_fecha(s: str) -> date | None:
    """'YYYY-MM-DD' → date; vacío → None. ValueError si el formato es inválido."""
    s = s.strip()
    return datetime.strptime(s, "%Y-%m-%d").date() if s else None


class ConciliadorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Conciliación de ventas — Pasos 2 y 3")
        root.geometry("840x680")
        root.minsize(720, 580)

        self.vars: dict[str, tk.StringVar] = {k: tk.StringVar() for k, _, _ in ARCHIVOS}
        self.var_desde = tk.StringVar()
        self.var_hasta = tk.StringVar()
        self.var_salida = tk.StringVar(value=str(app_dir() / "resultados"))
        self.procesando = False

        self._construir_ui()

    def _construir_ui(self):
        cont = ttk.Frame(self.root, padding=14)
        cont.pack(fill="both", expand=True)

        ttk.Label(
            cont, text="Conciliación de ventas (pasos 2-3 del proceso)",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", pady=(0, 4))
        ttk.Label(
            cont, foreground="#555",
            text="Carga los 5 reportes del período. Las fechas se llenan "
                 "solas al elegir el Cierre; puedes editarlas para acotar.",
        ).pack(anchor="w", pady=(0, 12))

        # --- Botones de carga + ruta ---
        grid = ttk.Frame(cont)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        for fila, (clave, etiqueta, tipos) in enumerate(ARCHIVOS):
            ttk.Button(
                grid, text=f"Cargar {etiqueta}", width=30,
                command=lambda k=clave, t=tipos: self._elegir_archivo(k, t),
            ).grid(row=fila, column=0, sticky="w", pady=3, padx=(0, 8))
            ttk.Entry(
                grid, textvariable=self.vars[clave], state="readonly",
            ).grid(row=fila, column=1, sticky="ew", pady=3)

        # --- Rango de fechas ---
        fechas = ttk.Frame(cont)
        fechas.pack(fill="x", pady=(14, 0))
        ttk.Label(fechas, text="Desde (YYYY-MM-DD):").grid(
            row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(fechas, textvariable=self.var_desde, width=14).grid(
            row=0, column=1)
        ttk.Label(fechas, text="   Hasta:").grid(row=0, column=2, padx=(12, 6))
        ttk.Entry(fechas, textvariable=self.var_hasta, width=14).grid(
            row=0, column=3)
        ttk.Label(
            fechas, foreground="#888",
            text="   (se autollenan al cargar el Cierre — edita si quieres "
                 "excluir días)",
        ).grid(row=0, column=4, sticky="w", padx=(8, 0))

        # --- Carpeta de salida ---
        sal = ttk.Frame(cont)
        sal.pack(fill="x", pady=(12, 0))
        sal.columnconfigure(1, weight=1)
        ttk.Label(sal, text="Carpeta de resultados").grid(
            row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(sal, textvariable=self.var_salida).grid(
            row=0, column=1, sticky="ew")
        ttk.Button(sal, text="Examinar...", width=12,
                   command=self._elegir_salida).grid(row=0, column=2, padx=(8, 0))

        # --- Acción ---
        self.btn = ttk.Button(cont, text="PROCESAR", command=self._on_procesar)
        self.btn.pack(fill="x", pady=(14, 6), ipady=6)

        self.estado = ttk.Label(cont, text="Listo.", foreground="#0a7")
        self.estado.pack(anchor="w")

        ttk.Label(cont, text="Resultados:", font=("Segoe UI", 9, "bold")).pack(
            anchor="w", pady=(8, 2))
        self.salida = scrolledtext.ScrolledText(
            cont, height=14, font=("Consolas", 9), wrap="none")
        self.salida.pack(fill="both", expand=True)
        self.salida.configure(state="disabled")

    # --------------------------------------------------------------- acciones
    def _elegir_archivo(self, clave: str, tipos: list):
        ruta = filedialog.askopenfilename(
            title="Seleccionar archivo", filetypes=tipos + [("Todos", "*.*")])
        if not ruta:
            return
        self.vars[clave].set(ruta)
        # Al elegir el Cierre, autollenamos las fechas (en otro hilo: la carga
        # puede tardar uno o dos segundos).
        if clave == "cierre":
            threading.Thread(
                target=self._detectar_fechas_cierre, args=(ruta,),
                daemon=True).start()

    def _elegir_salida(self):
        carpeta = filedialog.askdirectory(title="Carpeta de resultados")
        if carpeta:
            self.var_salida.set(carpeta)

    def _detectar_fechas_cierre(self, path: str):
        """Carga el Cierre y autollena Desde/Hasta con el primer y último día
        del mes que cubre. Si el usuario ya tipeó fechas, no las pisa."""
        if self.var_desde.get().strip() or self.var_hasta.get().strip():
            return
        try:
            fechas = [l.fecha for l in cierre_caja.cargar(path) if l.fecha]
        except Exception:
            return  # no se pudo leer; el usuario puede tipear a mano
        if not fechas:
            return
        primero, _ = _bordes_del_mes(min(fechas))
        _, ultimo = _bordes_del_mes(max(fechas))
        self.root.after(0, self.var_desde.set, primero.isoformat())
        self.root.after(0, self.var_hasta.set, ultimo.isoformat())

    def _on_procesar(self):
        if self.procesando:
            return
        faltantes = []
        for clave, etiqueta, _ in ARCHIVOS:
            ruta = self.vars[clave].get().strip()
            if not ruta:
                faltantes.append(etiqueta)
            elif not Path(ruta).is_file():
                messagebox.showerror("Archivo no encontrado", f"No existe:\n{ruta}")
                return
        if faltantes:
            messagebox.showwarning(
                "Faltan archivos",
                "Falta cargar:\n\n- " + "\n- ".join(faltantes))
            return
        try:
            desde = _parse_fecha(self.var_desde.get())
            hasta = _parse_fecha(self.var_hasta.get())
        except ValueError:
            messagebox.showerror(
                "Fecha inválida",
                "Las fechas deben tener formato YYYY-MM-DD (o vacías).")
            return
        if desde and hasta and desde > hasta:
            messagebox.showerror(
                "Rango inválido", "La fecha 'Desde' es posterior a 'Hasta'.")
            return

        self.procesando = True
        self.btn.configure(state="disabled")
        self._set_estado("Procesando, puede tardar unos segundos...", "#c70")
        self._escribir("", limpiar=True)
        threading.Thread(
            target=self._run, args=(desde, hasta), daemon=True).start()

    # ---------------------------------------------------------------- proceso
    def _run(self, desde: date | None, hasta: date | None):
        try:
            cuentas = cargar_cuentas(resource_path("config/cuentas.yaml"))
            tiendas = cargar_tiendas(resource_path("config/tiendas.yaml"))

            insumos = cv.cargar_inputs_archivos(
                cierre_path=Path(self.vars["cierre"].get()),
                mc_path=Path(self.vars["mc"].get()),
                amex_path=Path(self.vars["amex"].get()),
                diners_v_path=Path(self.vars["diners_v"].get()),
                diners_p_path=Path(self.vars["diners_p"].get()),
            )
            insumos = cv.filtrar_por_periodo(insumos, desde, hasta)

            tol = cuentas.tolerancia_conciliacion
            detalle: list[dict] = []
            for t in tiendas:
                detalle.extend(cv.conciliar_tienda(t, insumos, tol))
            resumen = cv.resumir(detalle, tol)
            discrepancias = [f for f in detalle if f["estado"] == "DISCREPANCIA"]

            if insumos["cierre"]:
                fmin = min(l.fecha for l in insumos["cierre"])
                fmax = max(l.fecha for l in insumos["cierre"])
                periodo = f"{fmin.isoformat()}_{fmax.isoformat()}"
            else:
                periodo = "vacio"
            salida_dir = Path(self.var_salida.get().strip()
                              or (app_dir() / "resultados"))
            salida_dir.mkdir(parents=True, exist_ok=True)
            ruta_excel = salida_dir / f"conciliacion_ventas_{periodo}.xlsx"
            cv.exportar_excel(ruta_excel, detalle, resumen, discrepancias)

            texto = self._formatear(resumen, discrepancias, periodo, ruta_excel)
            self.root.after(0, self._exito, texto, salida_dir)
        except Exception as e:  # noqa: BLE001 — el detalle se muestra al usuario
            self.root.after(0, self._error, str(e), traceback.format_exc())

    def _formatear(self, resumen: list[dict], discrepancias: list[dict],
                   periodo: str, ruta_excel: Path) -> str:
        n_tiendas = len({r["id_tienda"] for r in resumen})
        n_filas = len(resumen)
        n_discrep = len(discrepancias)
        suma_cierre = sum((r["cierre_sap"] for r in resumen), 0)
        suma_pasarela = sum((r["pasarela"] for r in resumen), 0)
        monto_neto = suma_cierre - suma_pasarela

        lin = [
            "=" * 78,
            "  CONCILIACIÓN DE VENTAS — Resumen ejecutivo",
            "=" * 78,
            f"  Período:                      {periodo.replace('_', ' → ')}",
            f"  Tiendas analizadas:           {n_tiendas}",
            f"  Filas (tienda × medio):       {n_filas}",
            f"  Total cierre SAP:             S/ {suma_cierre:>15,.2f}",
            f"  Total reportado pasarelas:    S/ {suma_pasarela:>15,.2f}",
            f"  Diferencia neta:              S/ {monto_neto:>+15,.2f}",
            f"  Discrepancias detectadas:     {n_discrep}",
            "",
        ]
        top = [r for r in sorted(resumen, key=lambda r: -abs(r["monto_neto_diff"]))[:10]
               if r["monto_neto_diff"] != 0]
        if top:
            lin += [
                "-" * 78,
                "  Top 10 (tienda, medio) por monto absoluto de discrepancia",
                "-" * 78,
                f"  {'TIENDA':<12} {'MEDIO':<11} {'CIERRE':>14} "
                f"{'PASARELA':>14} {'DIF TOTAL':>12} {'#DIFFS':>7}",
            ]
            for r in top:
                lin.append(
                    f"  {r['id_tienda']:<12} {r['medio']:<11} "
                    f"{r['cierre_sap']:>14,.2f} {r['pasarela']:>14,.2f} "
                    f"{r['monto_neto_diff']:>+12,.2f} "
                    f"{r['fechas_con_diff']:>7}")
        lin += [
            "", "=" * 78,
            f"  Excel exportado: {ruta_excel.name}",
            f"  Carpeta:         {ruta_excel.parent}",
            "=" * 78,
        ]
        return "\n".join(lin)

    # --------------------------------------------------------------- callbacks
    def _exito(self, texto: str, carpeta: Path):
        self._escribir(texto, limpiar=True)
        self._set_estado(f"Listo. Resultados en: {carpeta}", "#0a7")
        self.procesando = False
        self.btn.configure(state="normal")
        if messagebox.askyesno(
                "Proceso completado",
                f"Resultados guardados en:\n{carpeta}\n\n¿Abrir la carpeta?"):
            try:
                os.startfile(carpeta)  # type: ignore[attr-defined]
            except Exception:
                pass

    def _error(self, mensaje: str, detalle: str):
        self._escribir(f"ERROR:\n{mensaje}\n\n{detalle}", limpiar=True)
        self._set_estado("Error al procesar.", "#c00")
        self.procesando = False
        self.btn.configure(state="normal")
        messagebox.showerror("Error", f"No se pudo procesar:\n\n{mensaje}")

    def _set_estado(self, texto: str, color: str):
        self.estado.configure(text=texto, foreground=color)

    def _escribir(self, texto: str, limpiar: bool = False):
        self.salida.configure(state="normal")
        if limpiar:
            self.salida.delete("1.0", "end")
        self.salida.insert("end", texto)
        self.salida.configure(state="disabled")


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    ConciliadorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
