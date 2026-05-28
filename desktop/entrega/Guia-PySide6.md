# Guía de implementación — PySide6 (Qt)

Cómo llevar el rediseño a tu `.exe` de Python. Tkinter “a secas” no llega a este nivel
de acabado; **PySide6** (los bindings oficiales de Qt) sí, y es lo que usa esta guía.
PyQt6 es casi idéntico — solo cambia el `import`.

> El truco está en **dos cosas**: (1) una **hoja de estilos QSS** (el “CSS de Qt”) con la
> paleta grafito, y (2) usar los widgets correctos. Con eso, botones, campos y consola
> dejan de verse “de serie”.

---

## 1. Instalación

```bash
pip install PySide6
```

Para empaquetar el `.exe`:

```bash
pip install pyinstaller
pyinstaller --noconsole --onefile --add-data "fonts;fonts" app.py
```

---

## 2. Fuentes (IBM Plex)

Descarga **IBM Plex Sans** e **IBM Plex Mono** (Google Fonts, gratis) y guarda los `.ttf`
en una carpeta `fonts/` junto a tu script. Se cargan en runtime — así el look es idéntico
aunque el usuario no las tenga instaladas:

```python
from PySide6.QtGui import QFontDatabase

def cargar_fuentes():
    for f in ["IBMPlexSans-Regular.ttf", "IBMPlexSans-Medium.ttf",
              "IBMPlexSans-SemiBold.ttf", "IBMPlexMono-Regular.ttf"]:
        QFontDatabase.addApplicationFont(f"fonts/{f}")
```

---

## 3. La paleta (tokens)

Los mismos colores del diseño, para reutilizar en el QSS:

| Token            | Valor       | Uso                         |
|------------------|-------------|-----------------------------|
| ink              | `#1c1e22`   | texto principal             |
| ink-2            | `#6c7077`   | texto secundario            |
| ink-3            | `#a0a3a9`   | texto tenue / placeholders  |
| surface          | `#ffffff`   | fondo de ventana            |
| canvas           | `#fbfbfc`   | fondos suaves / consola     |
| line             | `#e7e8ea`   | bordes finos                |
| line-2           | `#d8dade`   | bordes de campos / botones  |
| btn (grafito)    | `#26282c`   | botón primario              |
| ok (verde apag.) | `#2f8c5f`   | estado “Listo” / cargado    |
| warn (ámbar)     | `#bb853c`   | observación en consola      |

---

## 4. Hoja de estilos QSS

Esto es lo que cambia TODO el aspecto. Guárdalo como string y aplícalo con
`app.setStyleSheet(QSS)`:

```python
QSS = """
* { font-family: "IBM Plex Sans"; font-size: 14px; color: #1c1e22; }
QWidget#root { background: #ffffff; }

/* Títulos y rótulos */
QLabel#h1       { font-size: 21px; font-weight: 600; }
QLabel#sub      { color: #6c7077; font-size: 13px; }
QLabel#grupo    { color: #a0a3a9; font-size: 11px; font-weight: 600;
                  letter-spacing: 1px; }            /* usa .upper() en el texto */
QLabel#campo    { font-weight: 500; }

/* Campos de texto / rutas */
QLineEdit {
    background: #ffffff; border: 1px solid #d8dade; border-radius: 7px;
    padding: 8px 12px; selection-background-color: #d7e7df;
}
QLineEdit:focus      { border: 1px solid #26282c; }
QLineEdit[mono="true"] { font-family: "IBM Plex Mono"; font-size: 12px; }
QLineEdit:read-only  { background: #ffffff; }

/* Botón secundario (Examinar) */
QPushButton {
    background: #ffffff; border: 1px solid #d8dade; border-radius: 7px;
    padding: 9px 16px; font-weight: 500; font-size: 13px;
}
QPushButton:hover    { background: #f2f2f4; }
QPushButton:pressed  { background: #e9e9ec; }

/* Botón primario (Procesar) — objectName = "primary" */
QPushButton#primary {
    background: #26282c; border: 1px solid #26282c; color: #ffffff;
    font-weight: 600; padding: 13px; font-size: 14px;
}
QPushButton#primary:hover    { background: #373a3f; border-color: #373a3f; }
QPushButton#primary:disabled { background: #c9cace; border-color: #c9cace; color:#fff; }

/* Estado */
QLabel#status      { color: #6c7077; font-size: 13px; }
QLabel#status[ok="true"] { color: #2f8c5f; }

/* Consola de resultados */
QPlainTextEdit, QTextEdit {
    background: #fbfbfc; border: 1px solid #e7e8ea; border-radius: 9px;
    font-family: "IBM Plex Mono"; font-size: 12px; padding: 12px 14px;
    color: #1c1e22;
}

/* Scrollbars discretas */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #d8dade; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #c2c4c9; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
"""
```

> **Truco de la mayúscula:** QSS no tiene `text-transform`. Para los rótulos en
> mayúsculas (“ARCHIVOS DE ORIGEN”) escribe el texto ya en mayúsculas con
> `.upper()` y deja el `letter-spacing` al QSS.

---

## 5. Ejemplo completo — Variación A (Clásico refinado)

Archivo único y ejecutable. Reproduce la maqueta A:

```python
import sys
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QPlainTextEdit, QFileDialog, QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase

# --- pega aquí cargar_fuentes() y QSS de arriba ---

ARCHIVOS = [
    "Cierre Caja Resumen (SAP)",
    "Reporte Mastercard (Izipay)",
    "Reporte AMEX (Izipay)",
    "Diners — Ventas",
    "Diners — Pagos",
]

def rotulo_grupo(texto):
    l = QLabel(texto.upper()); l.setObjectName("grupo"); return l

class Ventana(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle("Conciliación de Ventas — Tiendas Físicas")
        self.resize(940, 860)
        self.campos = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(34, 30, 34, 30)
        root.setSpacing(24)

        # Encabezado
        h1 = QLabel("Conciliación de ventas"); h1.setObjectName("h1")
        sub = QLabel("Mastercard · AMEX · Diners contra el Cierre SAP. "
                     "Selecciona los archivos del periodo y procesa.")
        sub.setObjectName("sub"); sub.setWordWrap(True)
        root.addWidget(h1); root.addWidget(sub)

        # Grupo: archivos de origen
        root.addWidget(rotulo_grupo("Archivos de origen"))
        grid = QGridLayout(); grid.setHorizontalSpacing(14); grid.setVerticalSpacing(9)
        grid.setColumnStretch(1, 1)
        for i, nombre in enumerate(ARCHIVOS):
            lbl = QLabel(nombre); lbl.setObjectName("campo"); lbl.setFixedWidth(218)
            campo = QLineEdit(); campo.setReadOnly(True)
            campo.setPlaceholderText("Ningún archivo seleccionado")
            campo.setProperty("mono", True)
            btn = QPushButton("Examinar")
            btn.clicked.connect(lambda _=False, c=campo: self.elegir_archivo(c))
            grid.addWidget(lbl, i, 0); grid.addWidget(campo, i, 1); grid.addWidget(btn, i, 2)
            self.campos[nombre] = campo
        root.addLayout(grid)

        # Grupo: carpeta de resultados
        root.addWidget(rotulo_grupo("Carpeta de resultados"))
        fila = QHBoxLayout(); fila.setSpacing(14)
        self.salida = QLineEdit(r"D:\proyectos\cobranzas\dist\resultados")
        self.salida.setProperty("mono", True)
        btn_out = QPushButton("Examinar"); btn_out.clicked.connect(self.elegir_carpeta)
        fila.addWidget(self.salida, 1); fila.addWidget(btn_out)
        root.addLayout(fila)

        # Botón primario + estado
        procesar = QPushButton("Procesar conciliación"); procesar.setObjectName("primary")
        procesar.clicked.connect(self.procesar)
        root.addWidget(procesar)

        self.status = QLabel("● Listo"); self.status.setObjectName("status")
        self.status.setProperty("ok", True)
        root.addWidget(self.status)

        # Consola de resultados
        root.addWidget(rotulo_grupo("Resultados"))
        self.consola = QPlainTextEdit(); self.consola.setReadOnly(True)
        self.consola.setMinimumHeight(180)
        root.addWidget(self.consola, 1)

    # --- acciones ---
    def elegir_archivo(self, campo):
        ruta, _ = QFileDialog.getOpenFileName(self, "Selecciona archivo", "",
                                              "Datos (*.xlsx *.csv);;Todos (*.*)")
        if ruta:
            campo.setText(ruta.split("/")[-1])
            self.refrescar_estado()

    def elegir_carpeta(self):
        d = QFileDialog.getExistingDirectory(self, "Carpeta de resultados")
        if d: self.salida.setText(d)

    def refrescar_estado(self):
        listos = sum(1 for c in self.campos.values() if c.text())
        self.status.setText(f"● Listo · {listos} de {len(self.campos)} archivos seleccionados")

    def procesar(self):
        # Para la consola con color usa HTML en un QTextEdit (ver §6).
        self.consola.appendPlainText("[10:42:13]  Iniciando conciliación · periodo 2026-05")
        # ...tu lógica de conciliación aquí...

if __name__ == "__main__":
    app = QApplication(sys.argv)
    cargar_fuentes()
    app.setStyleSheet(QSS)
    v = Ventana(); v.show()
    sys.exit(app.exec())
```

---

## 6. Consola con color (OK / REV)

`QPlainTextEdit` es monocromo. Para los marcadores verdes/ámbar usa un **`QTextEdit`**
de solo lectura y escribe HTML:

```python
COL = {"t": "#a0a3a9", "ok": "#2f8c5f", "rev": "#bb853c"}

def log(self, hora, texto, marca=None):
    html = f'<span style="color:{COL["t"]}">[{hora}]</span>&nbsp; {texto}'
    if marca:
        c = COL["ok"] if marca == "OK" else COL["rev"]
        html += f' &nbsp;<span style="color:{c};font-weight:600">{marca}</span>'
    self.consola.append(html)   # QTextEdit.append() interpreta HTML
```

Para que respete los espacios en columnas, envuelve en `<pre>` o usa
`self.consola.setFontFamily("IBM Plex Mono")` + tabs.

---

## 7. Mapa de variaciones → widgets

| Variación              | Cómo se arma en Qt                                                            |
|------------------------|------------------------------------------------------------------------------|
| **A · Clásico**        | `QGridLayout` (rótulo / campo / botón). El ejemplo de arriba.                 |
| **B · Tarjetas**       | Cada tarjeta = `QFrame` con `border-radius` en QSS; filas con `QHBoxLayout`. El número/✓ es un `QLabel` redondo; el chip “Cargado” otro `QLabel` con QSS. |
| **C · Dos paneles**    | `QHBoxLayout` con dos `QFrame`; el derecho lleva la consola + un `QProgressBar` abajo. Las filas-paso son `QFrame` con la marca ✓. |

**Chip / píldora** (B): un `QLabel` con su propio QSS por `objectName`:
```python
chip = QLabel("Cargado"); chip.setObjectName("chip_ok")
# QSS:  QLabel#chip_ok { background:#eef6f1; color:#2f8c5f;
#         border:1px solid #cfe6da; border-radius:11px; padding:3px 11px;
#         font-size:11px; font-weight:600; }
```

**Barra de progreso** (C):
```python
from PySide6.QtWidgets import QProgressBar
bar = QProgressBar(); bar.setTextVisible(False); bar.setFixedHeight(6)
# QSS: QProgressBar { background:#e7e8ea; border:none; border-radius:3px; }
#      QProgressBar::chunk { background:#26282c; border-radius:3px; }
```

---

## 8. Detalles que elevan el acabado

- **Márgenes generosos:** `setContentsMargins(34, 30, 34, 30)` y `setSpacing(24)`.
  El aire es la mitad del rediseño.
- **Alto consistente en campos y botones** para que las filas “encajen”.
- **`setProperty` + repolish** si cambias un estado por código:
  ```python
  w.setProperty("ok", True)
  w.style().unpolish(w); w.style().polish(w)
  ```
- **Worker en hilo** (`QThread`/`QtConcurrent`) para que la conciliación no congele la
  ventana; emite señales para ir escribiendo en la consola.
- **Barra de título nativa:** déjala. Una barra custom (frameless) es más trabajo y
  raramente vale la pena para una herramienta interna.

---

¿Quieres que prepare el `app.py` completo y listo para correr de la variación que elijas
(A, B o C), con la consola a color y el worker en hilo ya cableados?
