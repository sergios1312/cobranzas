# Conciliación de Ventas — Interfaz PySide6 (Variación A)

Interfaz rediseñada para tu ejecutable. Look grafito neutro, IBM Plex,
campos con indicador de carga y consola a color.

## Estructura

```
entrega/
├─ app.py            ← la interfaz (este es el archivo principal)
├─ requirements.txt
├─ README.md
└─ fonts/            ← (créala tú) pon aquí los .ttf de IBM Plex
   ├─ IBMPlexSans-Regular.ttf
   ├─ IBMPlexSans-Medium.ttf
   ├─ IBMPlexSans-SemiBold.ttf
   ├─ IBMPlexSans-Bold.ttf
   ├─ IBMPlexMono-Regular.ttf
   └─ IBMPlexMono-Medium.ttf
```

> Las fuentes son **opcionales**: si no las pones, Qt usa la fuente del sistema y
> todo sigue funcionando. Pero con los `.ttf` el aspecto es idéntico en cualquier PC.
> Descárgalas gratis de Google Fonts: "IBM Plex Sans" e "IBM Plex Mono".

## 1. Instalar

```bash
pip install -r requirements.txt
```

## 2. Probar

```bash
python app.py
```

Verás la ventana con datos de demostración al pulsar **Procesar conciliación**.

## 3. Conectar tu lógica

Toda tu lógica actual de conciliación va dentro de **`Worker.run()`** (en `app.py`,
busca el comentario `>>> REEMPLAZA <<<`). Ahí tienes disponibles:

- `self.rutas` → diccionario `{ "Cierre Caja Resumen (SAP)": "C:/...ruta", ... }`
  con la ruta completa de cada archivo elegido.
- `self.salida` → la carpeta de resultados (texto).

Para escribir en la consola desde tu proceso usa:

```python
self.t("10:42:14", "Mi mensaje normal")          # línea con hora
self.t("", "Mastercard   conciliado", "OK")      # marcador verde
self.t("", "Diners       diferencia", "REV")     # marcador ámbar
self.progreso.emit(60)                            # 0..100 (opcional)
self.terminado.emit(num_observaciones)            # al final
```

Como corre en un **hilo aparte (`QThread`)**, la ventana nunca se congela mientras
procesas, aunque tarde varios segundos.

## 4. Empaquetar el .exe

```bash
pip install pyinstaller
pyinstaller --noconsole --onefile --add-data "fonts;fonts" app.py
```

El ejecutable queda en `dist/app.exe`.
(En macOS/Linux el separador de `--add-data` es `:` en vez de `;`).

---

Si quieres la **Variación B (tarjetas)** o **C (dos paneles)** en este mismo estilo,
o ajustar colores/medidas, avísame.
