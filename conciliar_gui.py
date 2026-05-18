"""Interfaz grafica para la conciliacion de ventas (pasos 2-3 del PDF).

El usuario selecciona los 5 archivos crudos del periodo, elige donde guardar
el resultado y la app consolida MC/AMEX/Diners y los coteja contra el Cierre
Caja Resumen, mostrando un resumen en pantalla y exportando un Excel.

Los catalogos (config/tiendas.yaml, config/cuentas.yaml) van embebidos en el
.exe — ver `resource_path` en conciliar_ventas.py.

Para correr como script:   py conciliar_gui.py
Para empaquetar:           ver build_exe.py
"""

from __future__ import annotations

import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from conciliar_ventas import (
    cargar_inputs_archivos, exportar_excel, procesar, resource_path,
)
from src.config import cargar_cuentas, cargar_tiendas


# Definicion de los 5 archivos de entrada: (clave, etiqueta, tipos de archivo)
ARCHIVOS = [
    ("cierre", "Cierre Caja Resumen (SAP)", [("Excel", "*.xlsx *.xls")]),
    ("mc", "Reporte Mastercard (Izipay)", [("CSV", "*.csv")]),
    ("amex", "Reporte AMEX (Izipay)", [("CSV", "*.csv")]),
    ("diners_v", "Diners — Ventas", [("Excel", "*.xlsx *.xls")]),
    ("diners_p", "Diners — Pagos", [("Excel", "*.xlsx *.xls")]),
]


def app_dir() -> Path:
    """Carpeta donde vive el .exe (o el script en modo desarrollo)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


class ConciliadorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Conciliacion de Ventas — Tiendas Fisicas")
        root.geometry("780x620")
        root.minsize(680, 540)

        self.vars: dict[str, tk.StringVar] = {k: tk.StringVar() for k, _, _ in ARCHIVOS}
        self.var_salida = tk.StringVar(value=str(app_dir() / "resultados"))
        self.procesando = False

        self._construir_ui()

    # ------------------------------------------------------------------ UI
    def _construir_ui(self):
        cont = ttk.Frame(self.root, padding=14)
        cont.pack(fill="both", expand=True)

        titulo = ttk.Label(
            cont, text="Conciliacion de ventas: MC · AMEX · Diners vs Cierre SAP",
            font=("Segoe UI", 12, "bold"),
        )
        titulo.pack(anchor="w", pady=(0, 4))
        ttk.Label(
            cont, foreground="#555",
            text="Selecciona los 5 archivos crudos del periodo y presiona Procesar.",
        ).pack(anchor="w", pady=(0, 12))

        # --- Selectores de archivo ---
        grid = ttk.Frame(cont)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)

        for fila, (clave, etiqueta, tipos) in enumerate(ARCHIVOS):
            ttk.Label(grid, text=etiqueta).grid(row=fila, column=0, sticky="w", pady=3, padx=(0, 8))
            entry = ttk.Entry(grid, textvariable=self.vars[clave])
            entry.grid(row=fila, column=1, sticky="ew", pady=3)
            ttk.Button(
                grid, text="Examinar...", width=12,
                command=lambda k=clave, t=tipos: self._elegir_archivo(k, t),
            ).grid(row=fila, column=2, padx=(8, 0), pady=3)

        # --- Carpeta de salida ---
        sal = ttk.Frame(cont)
        sal.pack(fill="x", pady=(12, 0))
        sal.columnconfigure(1, weight=1)
        ttk.Label(sal, text="Carpeta de resultados").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(sal, textvariable=self.var_salida).grid(row=0, column=1, sticky="ew")
        ttk.Button(
            sal, text="Examinar...", width=12, command=self._elegir_salida,
        ).grid(row=0, column=2, padx=(8, 0))

        # --- Boton procesar ---
        self.btn = ttk.Button(cont, text="PROCESAR", command=self._on_procesar)
        self.btn.pack(fill="x", pady=(14, 6), ipady=6)

        # --- Estado ---
        self.estado = ttk.Label(cont, text="Listo.", foreground="#0a7")
        self.estado.pack(anchor="w")

        # --- Resultados ---
        ttk.Label(cont, text="Resultados:", font=("Segoe UI", 9, "bold")).pack(
            anchor="w", pady=(8, 2),
        )
        self.salida = scrolledtext.ScrolledText(
            cont, height=14, font=("Consolas", 9), wrap="none",
        )
        self.salida.pack(fill="both", expand=True)
        self.salida.configure(state="disabled")

    # ------------------------------------------------------------- acciones
    def _elegir_archivo(self, clave: str, tipos: list):
        ruta = filedialog.askopenfilename(
            title="Seleccionar archivo", filetypes=tipos + [("Todos", "*.*")],
        )
        if ruta:
            self.vars[clave].set(ruta)

    def _elegir_salida(self):
        carpeta = filedialog.askdirectory(title="Carpeta de resultados")
        if carpeta:
            self.var_salida.set(carpeta)

    def _on_procesar(self):
        if self.procesando:
            return
        # Validar que los 5 archivos esten seleccionados y existan
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
                "Selecciona estos archivos:\n\n- " + "\n- ".join(faltantes),
            )
            return

        self.procesando = True
        self.btn.configure(state="disabled")
        self._set_estado("Procesando, espera unos segundos...", "#c70")
        self._escribir("", limpiar=True)
        # Correr en thread para no congelar la ventana
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            cuentas = cargar_cuentas(resource_path("config/cuentas.yaml"))
            tiendas = cargar_tiendas(resource_path("config/tiendas.yaml"))

            insumos = cargar_inputs_archivos(
                cierre_path=self.vars["cierre"].get(),
                mc_path=self.vars["mc"].get(),
                amex_path=self.vars["amex"].get(),
                diners_v_path=self.vars["diners_v"].get(),
                diners_p_path=self.vars["diners_p"].get(),
            )
            res = procesar(insumos, tiendas, cuentas.tolerancia_conciliacion)

            salida = Path(self.var_salida.get().strip() or (app_dir() / "resultados"))
            salida.mkdir(parents=True, exist_ok=True)
            ruta_excel = salida / f"conciliacion_ventas_{res['periodo']}.xlsx"
            exportar_excel(ruta_excel, res["detalle"], res["resumen"], res["discrepancias"])

            texto = self._formatear_resumen(res, ruta_excel)
            self.root.after(0, self._exito, texto, ruta_excel)
        except Exception as e:  # noqa: BLE001 — se muestra al usuario
            detalle = traceback.format_exc()
            self.root.after(0, self._error, str(e), detalle)

    # -------------------------------------------------------------- helpers
    def _formatear_resumen(self, res: dict, ruta_excel: Path) -> str:
        resumen = res["resumen"]
        discrepancias = res["discrepancias"]
        n_tiendas = len({r["id_tienda"] for r in resumen})
        suma_cierre = sum(r["cierre_sap"] for r in resumen)
        suma_pasar = sum(r["pasarela"] for r in resumen)

        lineas = [
            "=" * 78,
            "  RESUMEN EJECUTIVO",
            "=" * 78,
            f"  Tiendas analizadas:        {n_tiendas}",
            f"  Filas (tienda x medio):    {len(resumen)}",
            f"  Total cierre SAP:          S/ {suma_cierre:>16,.2f}",
            f"  Total reportado pasarelas: S/ {suma_pasar:>16,.2f}",
            f"  Diferencia neta:           S/ {suma_cierre - suma_pasar:>+16,.2f}",
            f"  Discrepancias detectadas:  {len(discrepancias)}",
            "",
            "-" * 78,
            "  TOP 15 (tienda, medio) POR MONTO DE DISCREPANCIA",
            "-" * 78,
            f"  {'TIENDA':<11}{'MEDIO':<11}{'CIERRE':>14}{'PASARELA':>14}{'DIF TOTAL':>13}",
        ]
        top = sorted(resumen, key=lambda r: -abs(r["monto_neto_diff"]))
        for r in top[:15]:
            if r["monto_neto_diff"] == 0:
                continue
            lineas.append(
                f"  {r['id_tienda']:<11}{r['medio']:<11}"
                f"{r['cierre_sap']:>14,.2f}{r['pasarela']:>14,.2f}"
                f"{r['monto_neto_diff']:>+13,.2f}"
            )
        lineas += [
            "",
            "=" * 78,
            f"  Excel generado: {ruta_excel}",
            "  Hojas: Resumen | Detalle | Discrepancias",
            "=" * 78,
        ]
        return "\n".join(lineas)

    def _exito(self, texto: str, ruta_excel: Path):
        self._escribir(texto, limpiar=True)
        self._set_estado(f"Listo. Excel en: {ruta_excel}", "#0a7")
        self.procesando = False
        self.btn.configure(state="normal")
        if messagebox.askyesno(
            "Conciliacion completada",
            f"Resultado guardado en:\n{ruta_excel}\n\nAbrir la carpeta?",
        ):
            try:
                import os
                os.startfile(ruta_excel.parent)  # type: ignore[attr-defined]
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
