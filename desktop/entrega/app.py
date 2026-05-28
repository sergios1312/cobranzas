"""
Conciliación de Ventas — Tiendas Físicas
Interfaz PySide6 · Variación A (Clásico refinado)
------------------------------------------------------------
- Tema grafito neutro (QSS) + IBM Plex Sans/Mono
- Campos con indicador de "cargado" (✓ verde)
- Consola de resultados a color (OK / REV)
- Procesamiento en hilo aparte (la ventana no se congela)

Reemplaza el contenido de Worker.run() con tu lógica real de conciliación.
"""

import sys
import time
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFontDatabase, QPalette, QColor


# ──────────────────────────────────────────────────────────────
#  Fuentes — coloca los .ttf en una carpeta ./fonts (opcional pero
#  recomendado para que el look sea idéntico en cualquier PC).
# ──────────────────────────────────────────────────────────────
def cargar_fuentes():
    for f in ["IBMPlexSans-Regular.ttf", "IBMPlexSans-Medium.ttf",
              "IBMPlexSans-SemiBold.ttf", "IBMPlexSans-Bold.ttf",
              "IBMPlexMono-Regular.ttf", "IBMPlexMono-Medium.ttf"]:
        QFontDatabase.addApplicationFont(f"fonts/{f}")


# ──────────────────────────────────────────────────────────────
#  Hoja de estilos (el "CSS de Qt"). Esto es lo que cambia el look.
# ──────────────────────────────────────────────────────────────
QSS = """
* { font-family: "IBM Plex Sans"; font-size: 14px; color: #1c1e22; }
QWidget#root { background: #ffffff; }

QLabel#h1    { font-size: 21px; font-weight: 600; }
QLabel#sub   { color: #6c7077; font-size: 13px; }
QLabel#grupo { color: #a0a3a9; font-size: 11px; font-weight: 600; letter-spacing: 1px; }
QLabel#campo { font-weight: 500; }

/* Campo (contenedor con borde) */
QFrame#field            { background: #ffffff; border: 1px solid #d8dade; border-radius: 7px; }
QFrame#field[focus="true"] { border: 1px solid #26282c; }
QFrame#field QLineEdit  { background: transparent; border: none; font-family: "IBM Plex Mono";
                          font-size: 12px; }
QLabel#check { color: #2f8c5f; font-weight: 700; font-size: 13px; }

/* Botón secundario (Examinar) */
QPushButton {
    background: #ffffff; border: 1px solid #d8dade; border-radius: 7px;
    padding: 9px 16px; font-weight: 500; font-size: 13px;
}
QPushButton:hover   { background: #f2f2f4; }
QPushButton:pressed { background: #e9e9ec; }

/* Botón primario (Procesar) */
QPushButton#primary {
    background: #26282c; border: 1px solid #26282c; color: #ffffff;
    font-weight: 600; padding: 13px; font-size: 14px;
}
QPushButton#primary:hover    { background: #373a3f; border-color: #373a3f; }
QPushButton#primary:disabled { background: #c9cace; border-color: #c9cace; color: #ffffff; }

/* Estado */
QLabel#status            { color: #6c7077; font-size: 13px; }
QLabel#status[ok="true"] { color: #2f8c5f; }

/* Consola */
QTextEdit {
    background: #fbfbfc; border: 1px solid #e7e8ea; border-radius: 9px;
    padding: 12px 14px; color: #1c1e22;
}

/* Scrollbar discreta */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #d8dade; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #c2c4c9; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
"""

# Colores para la consola (HTML)
COL = {"t": "#a0a3a9", "ok": "#2f8c5f", "rev": "#bb853c", "hr": "#d8dade"}

ARCHIVOS = [
    "Cierre Caja Resumen (SAP)",
    "Reporte Mastercard (Izipay)",
    "Reporte AMEX (Izipay)",
    "Diners — Ventas",
    "Diners — Pagos",
]


# ──────────────────────────────────────────────────────────────
#  Campo de archivo: borde + nombre (mono) + ✓ verde al cargar
# ──────────────────────────────────────────────────────────────
class Campo(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("field")
        self.setFixedHeight(40)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(8)

        self.edit = QLineEdit()
        self.edit.setReadOnly(True)
        self.edit.setPlaceholderText("Ningún archivo seleccionado")
        pal = self.edit.palette()
        pal.setColor(QPalette.PlaceholderText, QColor("#a0a3a9"))
        self.edit.setPalette(pal)

        self.check = QLabel("✓")
        self.check.setObjectName("check")
        self.check.hide()

        lay.addWidget(self.edit, 1)
        lay.addWidget(self.check)

    def set_archivo(self, nombre):
        self.edit.setText(nombre)
        self.check.setVisible(bool(nombre))

    def text(self):
        return self.edit.text()


# ──────────────────────────────────────────────────────────────
#  Worker: corre la conciliación en un hilo aparte.
#  >>> REEMPLAZA el cuerpo de run() con tu lógica real. <<<
# ──────────────────────────────────────────────────────────────
class Worker(QThread):
    linea = Signal(str)       # una línea HTML para la consola
    progreso = Signal(int)    # 0..100
    terminado = Signal(int)   # nro de observaciones

    def __init__(self, rutas: dict, salida: str):
        super().__init__()
        self.rutas = rutas
        self.salida = salida

    def t(self, hora, texto, marca=None):
        html = f'<span style="color:{COL["t"]}">[{hora}]</span>&nbsp; {texto}'
        if marca:
            c = COL["ok"] if marca == "OK" else COL["rev"]
            html += f' &nbsp;<span style="color:{c};font-weight:600">{marca}</span>'
        self.linea.emit(html)

    def run(self):
        # ── DEMO (sustitúyelo por tu proceso real) ───────────────
        self.t("10:42:13", "Iniciando conciliación · periodo 2026-05")
        self.progreso.emit(10); time.sleep(0.4)
        self.t("10:42:14", "SAP ............ 1,284 registros&nbsp;&nbsp; S/ 842,510.40")
        self.progreso.emit(30); time.sleep(0.3)
        self.t("10:42:14", "Mastercard ..... 1,201 registros")
        self.progreso.emit(50); time.sleep(0.3)
        self.t("10:42:15", "AMEX ...........&nbsp;&nbsp;&nbsp; 64 registros")
        self.progreso.emit(70); time.sleep(0.3)
        self.t("10:42:15", "Diners ......... 19 ventas · 19 pagos")
        self.progreso.emit(85); time.sleep(0.3)
        self.linea.emit(f'<span style="color:{COL["hr"]}">'
                        f'────────────────────────────────────────────</span>')
        self.t("", "Mastercard&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; conciliado &nbsp;&nbsp; S/ 612,340.10", "OK")
        self.t("", "AMEX&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; conciliado &nbsp;&nbsp; S/&nbsp; 48,220.00", "OK")
        self.t("", "Diners&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; diferencia &nbsp;&nbsp; S/&nbsp;&nbsp;&nbsp;&nbsp; 180.50", "REV")
        self.linea.emit(f'<span style="color:{COL["hr"]}">'
                        f'────────────────────────────────────────────</span>')
        time.sleep(0.3)
        self.t("10:42:16", f"3 reportes generados en {self.salida}")
        self.progreso.emit(100)
        self.terminado.emit(1)   # 1 observación
        # ─────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────
#  Ventana principal
# ──────────────────────────────────────────────────────────────
class Ventana(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle("Conciliación de Ventas — Tiendas Físicas")
        self.resize(940, 880)
        self.campos = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(34, 30, 34, 30)
        root.setSpacing(22)

        # Encabezado
        h1 = QLabel("Conciliación de ventas"); h1.setObjectName("h1")
        sub = QLabel("Mastercard · AMEX · Diners contra el Cierre SAP. "
                     "Selecciona los archivos del periodo y procesa.")
        sub.setObjectName("sub"); sub.setWordWrap(True)
        root.addWidget(h1); root.addWidget(sub)

        # Grupo: archivos de origen
        root.addWidget(self._rotulo("Archivos de origen"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14); grid.setVerticalSpacing(9)
        grid.setColumnStretch(1, 1)
        for i, nombre in enumerate(ARCHIVOS):
            lbl = QLabel(nombre); lbl.setObjectName("campo"); lbl.setFixedWidth(218)
            campo = Campo()
            btn = QPushButton("Examinar")
            btn.clicked.connect(lambda _=False, c=campo: self.elegir_archivo(c))
            grid.addWidget(lbl, i, 0); grid.addWidget(campo, i, 1); grid.addWidget(btn, i, 2)
            self.campos[nombre] = campo
        root.addLayout(grid)

        # Grupo: carpeta de resultados
        root.addWidget(self._rotulo("Carpeta de resultados"))
        fila = QHBoxLayout(); fila.setSpacing(14)
        self.salida = QLineEdit(r"D:\proyectos\cobranzas\dist\resultados")
        self.salida.setStyleSheet("font-family:'IBM Plex Mono';font-size:12px;"
                                  "border:1px solid #d8dade;border-radius:7px;padding:8px 12px;")
        btn_out = QPushButton("Examinar"); btn_out.clicked.connect(self.elegir_carpeta)
        fila.addWidget(self.salida, 1); fila.addWidget(btn_out)
        root.addLayout(fila)

        # Botón primario + estado
        self.procesar_btn = QPushButton("Procesar conciliación")
        self.procesar_btn.setObjectName("primary")
        self.procesar_btn.clicked.connect(self.procesar)
        root.addWidget(self.procesar_btn)

        self.status = QLabel("● Listo")
        self.status.setObjectName("status")
        self.status.setProperty("ok", True)
        root.addWidget(self.status)

        # Consola
        root.addWidget(self._rotulo("Resultados"))
        self.consola = QTextEdit(); self.consola.setReadOnly(True)
        self.consola.setMinimumHeight(180)
        root.addWidget(self.consola, 1)

        self.refrescar_estado()

    # — helpers de UI —
    def _rotulo(self, texto):
        l = QLabel(texto.upper()); l.setObjectName("grupo"); return l

    def log_html(self, html):
        self.consola.append(
            f'<div style="white-space:pre;font-family:\'IBM Plex Mono\';font-size:12px">{html}</div>'
        )

    # — acciones —
    def elegir_archivo(self, campo):
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Selecciona archivo", "", "Datos (*.xlsx *.csv);;Todos (*.*)")
        if ruta:
            campo.set_archivo(ruta.split("/")[-1])
            campo._ruta = ruta
            self.refrescar_estado()

    def elegir_carpeta(self):
        d = QFileDialog.getExistingDirectory(self, "Carpeta de resultados")
        if d:
            self.salida.setText(d)

    def refrescar_estado(self):
        listos = sum(1 for c in self.campos.values() if c.text())
        total = len(self.campos)
        self.status.setText(f"● Listo · {listos} de {total} archivos seleccionados")
        self._set_ok(self.status, listos == total)

    def _set_ok(self, w, val):
        w.setProperty("ok", val)
        w.style().unpolish(w); w.style().polish(w)

    def procesar(self):
        rutas = {n: getattr(c, "_ruta", "") for n, c in self.campos.items()}
        self.consola.clear()
        self.procesar_btn.setEnabled(False)
        self.status.setText("● Procesando…")
        self._set_ok(self.status, False)

        self.worker = Worker(rutas, self.salida.text())
        self.worker.linea.connect(self.log_html)
        self.worker.terminado.connect(self._fin)
        self.worker.start()

    def _fin(self, observaciones):
        self.procesar_btn.setEnabled(True)
        if observaciones:
            self.status.setText(f"● Completado con {observaciones} observación(es)")
            self._set_ok(self.status, False)
        else:
            self.status.setText("● Conciliación completada sin diferencias")
            self._set_ok(self.status, True)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    cargar_fuentes()
    app.setStyleSheet(QSS)
    v = Ventana(); v.show()
    sys.exit(app.exec())
