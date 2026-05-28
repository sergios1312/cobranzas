"""Interfaz gráfica del ejecutable de conciliación de ventas (pasos 2-3).

Diseño PySide6 — Variación A "grafito" con IBM Plex (ver `desktop/entrega/`).
El usuario carga los 5 reportes del período, ajusta el rango de fechas
(autollenado al cargar el Cierre) y procesa la conciliación contra el
Cierre Caja Resumen.

NO toca depósitos bancarios ni genera asientos — esa parte es el pipeline
completo (`main.py`). Esta GUI cubre los pasos 2 y 3 del proceso del PDF.

Catálogos (`config/tiendas.yaml`, `config/cuentas.yaml`) embebidos en el
`.exe` vía `resource_path`. Las fuentes IBM Plex son opcionales: si la
carpeta `fonts/` con los `.ttf` no existe, Qt usa la fuente del sistema y
la app sigue luciendo limpia.
"""

from __future__ import annotations

import calendar
import os
import sys
import traceback
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QDate, QThread, Signal
from PySide6.QtGui import QColor, QFontDatabase, QPalette
from PySide6.QtWidgets import (
    QApplication, QDateEdit, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTextEdit, QVBoxLayout,
    QWidget,
)

import conciliar_ventas as cv
from src.config import cargar_cuentas, cargar_tiendas
from src.loaders import cierre_caja

# (clave que usa cv.cargar_inputs_archivos, etiqueta visible, filtro filedialog)
ARCHIVOS = [
    ("cierre",   "Cierre Caja Resumen (SAP)", "Excel (*.xlsx *.xls)"),
    ("mc",       "Reporte Mastercard (Izipay)", "CSV (*.csv)"),
    ("amex",     "Reporte AMEX (Izipay)", "CSV (*.csv)"),
    ("diners_v", "Diners — Ventas", "Excel (*.xlsx *.xls)"),
    ("diners_p", "Diners — Pagos", "Excel (*.xlsx *.xls)"),
]


# ──────────────────────────────────────────────────────────────────────────
#  Recursos: rutas que sirven tanto en script como dentro del .exe
# ──────────────────────────────────────────────────────────────────────────
def resource_path(rel: str) -> Path:
    """Resuelve un recurso embebido (config/*.yaml, fonts/*.ttf). Funciona
    como script y dentro del .exe de PyInstaller (sys._MEIPASS)."""
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return Path(base) / rel


def app_dir() -> Path:
    """Carpeta donde vive el .exe (o el script en modo desarrollo)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def cargar_fuentes() -> None:
    """Carga IBM Plex desde `fonts/` si los .ttf están presentes. No falla
    si la carpeta o los archivos no existen (Qt usa la fuente del sistema)."""
    base = resource_path("fonts")
    if not base.exists():
        return
    for nombre in ("IBMPlexSans-Regular.ttf", "IBMPlexSans-Medium.ttf",
                   "IBMPlexSans-SemiBold.ttf", "IBMPlexSans-Bold.ttf",
                   "IBMPlexMono-Regular.ttf", "IBMPlexMono-Medium.ttf"):
        p = base / nombre
        if p.exists():
            QFontDatabase.addApplicationFont(str(p))


def _bordes_del_mes(d: date) -> tuple[date, date]:
    """Primer y último día del mes al que pertenece `d`."""
    _, ultimo = calendar.monthrange(d.year, d.month)
    return d.replace(day=1), date(d.year, d.month, ultimo)


# ──────────────────────────────────────────────────────────────────────────
#  Estilo (paleta grafito + IBM Plex)
# ──────────────────────────────────────────────────────────────────────────
QSS = """
* { font-family: "IBM Plex Sans"; font-size: 13px; color: #1c1e22; }
QWidget#root { background: #ffffff; }

QLabel#h1    { font-size: 17px; font-weight: 600; }
QLabel#sub   { color: #6c7077; font-size: 13px; }
QLabel#grupo { color: #a0a3a9; font-size: 11px; font-weight: 600;
               letter-spacing: 1px; }
QLabel#campo { font-weight: 500; }
QLabel#hint  { color: #a0a3a9; font-size: 11px; }

/* Campo de archivo (frame con borde + ✓ verde) */
QFrame#field            { background: #ffffff; border: 1px solid #d8dade;
                          border-radius: 7px; }
QFrame#field[focus="true"] { border: 1px solid #26282c; }
QLabel#check { color: #2f8c5f; font-weight: 700; font-size: 13px; }

/* Botón secundario (Examinar) */
QPushButton {
    background: #ffffff; border: 1px solid #d8dade; border-radius: 7px;
    padding: 6px 14px; font-weight: 500; font-size: 12px;
}
QPushButton:hover   { background: #f2f2f4; }
QPushButton:pressed { background: #e9e9ec; }

/* Botón primario (Procesar) */
QPushButton#primary {
    background: #26282c; border: 1px solid #26282c; color: #ffffff;
    font-weight: 600; padding: 9px; font-size: 13px;
}
QPushButton#primary:hover    { background: #373a3f; border-color: #373a3f; }
QPushButton#primary:disabled { background: #c9cace; border-color: #c9cace;
                               color: #ffffff; }

/* Estado */
QLabel#status            { color: #6c7077; font-size: 13px; }
QLabel#status[ok="true"] { color: #2f8c5f; }
QLabel#status[err="true"]{ color: #bb853c; }

/* Line edits genéricos (carpeta de salida) */
QLineEdit {
    background: #ffffff; border: 1px solid #d8dade; border-radius: 7px;
    padding: 8px 12px; font-family: "IBM Plex Mono"; font-size: 12px;
}
QLineEdit:focus { border: 1px solid #26282c; }

/* DateEdit */
QDateEdit {
    background: #ffffff; border: 1px solid #d8dade; border-radius: 7px;
    padding: 6px 10px; font-family: "IBM Plex Mono"; font-size: 12px;
    min-width: 130px;
}
QDateEdit:focus { border: 1px solid #26282c; }

/* Consola de resultados */
QTextEdit {
    background: #fbfbfc; border: 1px solid #e7e8ea; border-radius: 9px;
    padding: 12px 14px; color: #1c1e22;
}

/* Scrollbars discretas */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #d8dade; border-radius: 5px;
                              min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #c2c4c9; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
"""

# Colores para el HTML de la consola
COL = {"t": "#a0a3a9", "ok": "#2f8c5f", "rev": "#bb853c", "hr": "#d8dade",
       "err": "#c0392b"}


# ──────────────────────────────────────────────────────────────────────────
#  Campo de archivo: borde + nombre (mono) + ✓ verde al cargar
# ──────────────────────────────────────────────────────────────────────────
class Campo(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("field")
        self.setFixedHeight(32)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(8)

        self.edit = QLineEdit()
        self.edit.setReadOnly(True)
        self.edit.setPlaceholderText("Ningún archivo seleccionado")
        self.edit.setStyleSheet(
            "background:transparent;border:none;"
            "font-family:'IBM Plex Mono';font-size:12px;"
        )
        pal = self.edit.palette()
        pal.setColor(QPalette.PlaceholderText, QColor("#a0a3a9"))
        self.edit.setPalette(pal)

        self.check = QLabel("✓")
        self.check.setObjectName("check")
        self.check.hide()

        lay.addWidget(self.edit, 1)
        lay.addWidget(self.check)

        self._ruta = ""

    def set_ruta(self, ruta: str) -> None:
        self._ruta = ruta
        self.edit.setText(Path(ruta).name if ruta else "")
        self.check.setVisible(bool(ruta))

    def ruta(self) -> str:
        return self._ruta

    def hay(self) -> bool:
        return bool(self._ruta)


# ──────────────────────────────────────────────────────────────────────────
#  Detector de fechas: corre cierre_caja.cargar() en hilo aparte
# ──────────────────────────────────────────────────────────────────────────
class DetectarFechas(QThread):
    """Carga el Cierre y emite (primer_día_del_mes, último_día_del_mes) que
    cubre el reporte, para autollenar los QDateEdit sin congelar la UI."""
    detectado = Signal(object, object)  # (date, date) o (None, None)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        try:
            lineas = cierre_caja.cargar(self.path)
            fechas = [l.fecha for l in lineas if l.fecha]
            if not fechas:
                self.detectado.emit(None, None)
                return
            primero, _ = _bordes_del_mes(min(fechas))
            _, ultimo = _bordes_del_mes(max(fechas))
            self.detectado.emit(primero, ultimo)
        except Exception:
            self.detectado.emit(None, None)


# ──────────────────────────────────────────────────────────────────────────
#  Worker: corre la conciliación (pasos 2-3) en hilo aparte
# ──────────────────────────────────────────────────────────────────────────
class Worker(QThread):
    linea = Signal(str)        # una línea HTML para la consola
    terminado = Signal(int)    # número de discrepancias; -1 si hubo error

    def __init__(self, rutas: dict, desde: date, hasta: date, salida: Path):
        super().__init__()
        self.rutas = rutas
        self.desde = desde
        self.hasta = hasta
        self.salida = salida

    def _ts(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _log(self, texto: str, marca: str | None = None) -> None:
        html = (f'<span style="color:{COL["t"]}">[{self._ts()}]</span>'
                f'&nbsp;&nbsp;{texto}')
        if marca:
            color = COL["ok"] if marca == "OK" else (
                COL["rev"] if marca == "REV" else COL["err"])
            html += (f' &nbsp;<span style="color:{color};'
                     f'font-weight:600">{marca}</span>')
        self.linea.emit(html)

    def _hr(self) -> None:
        self.linea.emit(
            f'<span style="color:{COL["hr"]}">'
            f'─────────────────────────────────────────────────'
            f'</span>')

    def run(self) -> None:
        try:
            self._log(f"Iniciando conciliación · período "
                      f"{self.desde.isoformat()} → {self.hasta.isoformat()}")
            cuentas = cargar_cuentas(resource_path("config/cuentas.yaml"))
            tiendas = cargar_tiendas(resource_path("config/tiendas.yaml"))

            insumos = cv.cargar_inputs_archivos(
                cierre_path=Path(self.rutas["cierre"]),
                mc_path=Path(self.rutas["mc"]),
                amex_path=Path(self.rutas["amex"]),
                diners_v_path=Path(self.rutas["diners_v"]),
                diners_p_path=Path(self.rutas["diners_p"]),
            )
            insumos = cv.filtrar_por_periodo(insumos, self.desde, self.hasta)

            n_sap = len(insumos["cierre"])
            n_mc = len(insumos["txn_mc"])
            n_amex = len(insumos["txn_amex"])
            n_dv = len(insumos["txn_diners"])
            n_dp = len(insumos["pagos_diners"])
            self._log(f"SAP&nbsp;.............&nbsp;{n_sap:>6,}&nbsp;registros")
            self._log(f"Mastercard&nbsp;......&nbsp;{n_mc:>6,}&nbsp;registros")
            self._log(f"AMEX&nbsp;............&nbsp;{n_amex:>6,}&nbsp;registros")
            self._log(f"Diners&nbsp;..........&nbsp;{n_dv:>6,}&nbsp;ventas&nbsp;·&nbsp;"
                      f"{n_dp}&nbsp;pagos")

            tol = cuentas.tolerancia_conciliacion
            detalle: list[dict] = []
            for t in tiendas:
                detalle.extend(cv.conciliar_tienda(t, insumos, tol))
            resumen = cv.resumir(detalle, tol)
            discrepancias = [f for f in detalle
                             if f["estado"] == "DISCREPANCIA"]

            self._hr()
            # Resumen por medio (suma de cierre, pasarela y diferencia neta)
            por_medio: dict[str, dict[str, Decimal]] = {}
            for r in resumen:
                m = r["medio"]
                a = por_medio.setdefault(m, {
                    "cierre": Decimal("0"),
                    "pasarela": Decimal("0"),
                    "dif": Decimal("0"),
                })
                a["cierre"] += r["cierre_sap"]
                a["pasarela"] += r["pasarela"]
                a["dif"] += r["monto_neto_diff"]
            for m in ("MASTERCARD", "AMEX", "DINERS"):
                if m not in por_medio:
                    continue
                v = por_medio[m]
                marca = "OK" if abs(v["dif"]) <= tol else "REV"
                etiqueta = f"{m[:10]:<10}"
                self._log(
                    f"{etiqueta}&nbsp; cuadre&nbsp;&nbsp;"
                    f"S/&nbsp;{v['pasarela']:>14,.2f}&nbsp;&nbsp;"
                    f"dif&nbsp;S/&nbsp;{v['dif']:>+10,.2f}",
                    marca=marca,
                )
            self._hr()

            # Exportar Excel
            if insumos["cierre"]:
                fmin = min(l.fecha for l in insumos["cierre"])
                fmax = max(l.fecha for l in insumos["cierre"])
                periodo = f"{fmin.isoformat()}_{fmax.isoformat()}"
            else:
                periodo = "vacio"
            self.salida.mkdir(parents=True, exist_ok=True)
            # Sello de hora para evitar colision si el Excel anterior esta
            # abierto en Excel (Windows lo bloquea y daria PermissionError).
            sello = datetime.now().strftime("%H%M%S")
            ruta = self.salida / f"conciliacion_ventas_{periodo}_{sello}.xlsx"
            cv.exportar_excel(ruta, detalle, resumen, discrepancias)
            self._log(f"Excel generado:&nbsp;{ruta.name}")
            self._log(f"Carpeta:&nbsp;{self.salida}")

            self.terminado.emit(len(discrepancias))
        except Exception as e:  # noqa: BLE001 — el detalle va a la consola
            self._log(f"ERROR: {e}", marca="ERR")
            self.linea.emit(
                f'<pre style="color:{COL["err"]};font-family:\'IBM Plex Mono\';'
                f'font-size:11px">{traceback.format_exc()}</pre>')
            self.terminado.emit(-1)


# ──────────────────────────────────────────────────────────────────────────
#  Ventana principal
# ──────────────────────────────────────────────────────────────────────────
class Ventana(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle("Conciliación de Ventas — Tiendas Físicas")
        self.resize(720, 720)
        self.campos: dict[str, Campo] = {}
        self.detectador: DetectarFechas | None = None
        self.worker: Worker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(14)

        # — Encabezado —
        h1 = QLabel("Conciliación de ventas")
        h1.setObjectName("h1")
        sub = QLabel("Mastercard · AMEX · Diners contra el Cierre SAP. "
                     "Selecciona los archivos del período, ajusta las fechas "
                     "y procesa.")
        sub.setObjectName("sub")
        sub.setWordWrap(True)
        root.addWidget(h1)
        root.addWidget(sub)

        # — Archivos de origen —
        root.addWidget(self._rotulo("Archivos de origen"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        for i, (clave, etiqueta, tipos) in enumerate(ARCHIVOS):
            lbl = QLabel(etiqueta)
            lbl.setObjectName("campo")
            lbl.setFixedWidth(180)
            campo = Campo()
            btn = QPushButton("Examinar")
            btn.clicked.connect(
                lambda _=False, c=campo, k=clave, t=tipos:
                self._elegir_archivo(c, k, t))
            grid.addWidget(lbl, i, 0)
            grid.addWidget(campo, i, 1)
            grid.addWidget(btn, i, 2)
            self.campos[clave] = campo
        root.addLayout(grid)

        # — Período —
        root.addWidget(self._rotulo("Período"))
        fechas = QHBoxLayout()
        fechas.setSpacing(10)
        lbl_d = QLabel("Desde")
        lbl_d.setObjectName("campo")
        self.desde = QDateEdit()
        self.desde.setCalendarPopup(True)
        self.desde.setDisplayFormat("yyyy-MM-dd")
        self.desde.setDate(QDate.currentDate())
        lbl_h = QLabel("Hasta")
        lbl_h.setObjectName("campo")
        self.hasta = QDateEdit()
        self.hasta.setCalendarPopup(True)
        self.hasta.setDisplayFormat("yyyy-MM-dd")
        self.hasta.setDate(QDate.currentDate())
        hint = QLabel("se autollenan al cargar el Cierre")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        fechas.addWidget(lbl_d)
        fechas.addWidget(self.desde)
        fechas.addSpacing(14)
        fechas.addWidget(lbl_h)
        fechas.addWidget(self.hasta)
        fechas.addSpacing(14)
        fechas.addWidget(hint, 1)
        root.addLayout(fechas)

        # — Carpeta de resultados —
        root.addWidget(self._rotulo("Carpeta de resultados"))
        fila = QHBoxLayout()
        fila.setSpacing(14)
        self.salida = QLineEdit(str(app_dir() / "resultados"))
        btn_out = QPushButton("Examinar")
        btn_out.clicked.connect(self._elegir_carpeta)
        fila.addWidget(self.salida, 1)
        fila.addWidget(btn_out)
        root.addLayout(fila)

        # — Botón + estado —
        self.btn_procesar = QPushButton("Procesar conciliación")
        self.btn_procesar.setObjectName("primary")
        self.btn_procesar.clicked.connect(self._procesar)
        root.addWidget(self.btn_procesar)

        self.status = QLabel("● Listo")
        self.status.setObjectName("status")
        root.addWidget(self.status)

        # — Consola —
        root.addWidget(self._rotulo("Resultados"))
        self.consola = QTextEdit()
        self.consola.setReadOnly(True)
        self.consola.setMinimumHeight(260)
        root.addWidget(self.consola, 1)

        self._refrescar_estado()

    # — helpers de UI —
    def _rotulo(self, txt: str) -> QLabel:
        lbl = QLabel(txt.upper())
        lbl.setObjectName("grupo")
        return lbl

    def _set_prop(self, w: QWidget, name: str, val: bool) -> None:
        w.setProperty(name, val)
        w.style().unpolish(w)
        w.style().polish(w)

    # — acciones —
    def _elegir_archivo(self, campo: Campo, clave: str, tipos: str) -> None:
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Selecciona archivo", "", f"{tipos};;Todos (*.*)")
        if not ruta:
            return
        campo.set_ruta(ruta)
        self._refrescar_estado()
        if clave == "cierre":
            self.detectador = DetectarFechas(ruta)
            self.detectador.detectado.connect(self._aplicar_fechas)
            self.detectador.start()

    def _elegir_carpeta(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Carpeta de resultados")
        if d:
            self.salida.setText(d)

    def _aplicar_fechas(self, primero, ultimo) -> None:
        if primero and ultimo:
            self.desde.setDate(QDate(primero.year, primero.month, primero.day))
            self.hasta.setDate(QDate(ultimo.year, ultimo.month, ultimo.day))

    def _refrescar_estado(self) -> None:
        listos = sum(1 for c in self.campos.values() if c.hay())
        total = len(self.campos)
        self.status.setText(
            f"● Listo · {listos} de {total} archivos seleccionados")
        self._set_prop(self.status, "ok", listos == total)
        self._set_prop(self.status, "err", False)

    def _procesar(self) -> None:
        faltantes = [e for k, e, _ in ARCHIVOS if not self.campos[k].hay()]
        if faltantes:
            QMessageBox.warning(
                self, "Faltan archivos",
                "Falta cargar:\n\n• " + "\n• ".join(faltantes))
            return
        for clave, _, _ in ARCHIVOS:
            ruta = self.campos[clave].ruta()
            if not Path(ruta).is_file():
                QMessageBox.critical(
                    self, "Archivo no encontrado", f"No existe:\n{ruta}")
                return
        qd, qh = self.desde.date(), self.hasta.date()
        desde = date(qd.year(), qd.month(), qd.day())
        hasta = date(qh.year(), qh.month(), qh.day())
        if desde > hasta:
            QMessageBox.critical(
                self, "Rango inválido",
                "La fecha 'Desde' es posterior a 'Hasta'.")
            return

        rutas = {k: self.campos[k].ruta() for k, _, _ in ARCHIVOS}
        salida = Path(self.salida.text().strip()
                      or (app_dir() / "resultados"))

        self.consola.clear()
        self.btn_procesar.setEnabled(False)
        self.status.setText("● Procesando…")
        self._set_prop(self.status, "ok", False)
        self._set_prop(self.status, "err", False)

        self.worker = Worker(rutas, desde, hasta, salida)
        self.worker.linea.connect(self._log)
        self.worker.terminado.connect(self._fin)
        self.worker.start()

    def _log(self, html: str) -> None:
        self.consola.append(
            f'<div style="white-space:pre;'
            f'font-family:\'IBM Plex Mono\';font-size:12px">{html}</div>')

    def _fin(self, ndis: int) -> None:
        self.btn_procesar.setEnabled(True)
        if ndis < 0:
            self.status.setText("● Error durante el proceso")
            self._set_prop(self.status, "ok", False)
            self._set_prop(self.status, "err", True)
            return
        if ndis == 0:
            self.status.setText("● Conciliación completada sin diferencias")
            self._set_prop(self.status, "ok", True)
            self._set_prop(self.status, "err", False)
        else:
            self.status.setText(
                f"● Completado con {ndis} discrepancia(s)")
            self._set_prop(self.status, "ok", False)
            self._set_prop(self.status, "err", True)


def main():
    app = QApplication(sys.argv)
    cargar_fuentes()
    app.setStyleSheet(QSS)
    ventana = Ventana()
    ventana.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
