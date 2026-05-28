# Informe de avance — Proyecto Cobranzas Tiendas Físicas

> Documento exhaustivo del estado del proyecto: todo lo hecho, todo lo que
> falta y los detalles técnicos. Pensado para que cualquier persona (humana o
> Claude Code) pueda retomar el trabajo sin contexto previo.
>
> **Última actualización:** 2026-05-18
> **Versión de la sesión:** consolidación pasos 2-5 + GUI pasos 2-3
> **Modo:** DEMO / MVP funcional contra la muestra `Muestra al 30.04/`.

---

## 0. Resumen ejecutivo en 60 segundos

El proyecto automatiza la conciliación contable de cobranzas en tiendas
físicas: cruza el *Cierre Caja Resumen* de SAP contra los reportes de las
pasarelas de pago (Izipay MC/AMEX, Diners), concilia los depósitos esperados
contra los extractos bancarios y genera asientos contables para SAP
Business One.

**Estado en una línea:** los pasos 2 a 5 del PDF están automatizados,
testeados (55 tests `pytest`, `mypy` y `ruff` limpios) y disponibles como
CLI (`main.py`) y como ejecutable de escritorio para pasos 2-3
(`dist/ConciliadorVentas.exe`). Los pasos 1 (descarga) y 6 (carga a SAP)
siguen siendo manuales por diseño.

**Indicadores con la muestra de abril 2026:**

| Indicador | Valor |
|---|---|
| Tiendas en catálogo | 81 |
| Asientos válidos generados | 16 |
| Asientos omitidos por código contable pendiente | 42 |
| Conciliaciones omitidas por banco sin loader | 22 (Scotiabank 20, Pichincha 2) |
| Reportes por tienda generados | 76 |
| Asientos marcados para revisión | 1 (MIS.PI01, residuo negativo) |
| Tests automatizados | 55 (`pytest` verde) |
| Reproduce HABER del PDF (Schell MC 01-09) | 168,769.84 exacto ✓ |
| Reproduce diferencia documentada en PDF (Schell 06-04) | 586.00 exacto ✓ |

**Único bloqueante real para cerrar el flujo:** completar 8 códigos contables
en `config/cuentas.yaml` (socios SAP de bancos + proveedores de comisión) y
validar el formato del Excel "Importar de Excel" contra una plantilla real de
SAP B1. Ambos son insumos externos del usuario, no código.

---

## 1. El proceso del PDF — estado por paso

El PDF (`Proceso de cobranzas tiendas físicas.pdf`) describe 6 pasos. Mapeo
del estado actual:

### Paso 1 — Descargar reportes
**Estado:** 🔴 Manual (por diseño).

El usuario descarga manualmente de cada portal:
- Cierre Caja Resumen desde SAP Query Manager.
- Reportes MC y AMEX desde el portal de Izipay (CSV).
- Reportes de Ventas y Pagos desde el portal de Diners (Excel).
- Extractos bancarios del libro consolidado (Interbank, BBVA, BCP).

No es razonable automatizar porque requiere login a cada portal. El sistema
asume que estos 6 archivos están en una carpeta con la estructura esperada.

### Paso 2 — Consolidar reportes por tienda
**Estado:** ✅ Completo y validado.

Los loaders normalizan los archivos al modelo canónico (`src/modelos.py`) y
los filtran por código de comercio. El resultado son listas de
`TransaccionMedioPago` por tienda y por medio, listas para conciliarse.

Cubierto por tests unitarios (`test_conciliacion_*`) y por el test e2e que
valida contra la muestra (`test_e2e_muestra.py`).

### Paso 3 — Conciliar ventas vs Cierre SAP
**Estado:** ✅ Completo y validado al céntimo contra el PDF.

`src/conciliacion/ventas.py::conciliar_ventas_tienda` produce un
`DiferenciaConciliacion` por cada (fecha × medio) cruzando el Cierre Caja
Resumen contra el resumen por fecha de la pasarela. Las diferencias
superiores a la tolerancia (`0.01`) se marcan como significativas.

Pruebas concretas que pasan:
- El asiento MC de Schell para el período 01-09 reproduce el HABER del PDF
  exactamente: **168,769.84**.
- El 06/04 en Schell reproduce la diferencia documentada en el PDF
  exactamente: **586.00**.

### Paso 4 — Conciliar depósitos contra extractos bancarios
**Estado:** 🟡 Completo para los 3 bancos con datos. Faltan 2 bancos sin
muestra.

`src/conciliacion/depositos.py`:
- `depositos_esperados_izipay` genera un depósito esperado por transacción
  con `fecha_abono` y `importe_neto > 0`, excluyendo extornos.
- `depositos_esperados_diners` filtra por `estado='PAGADO'` y, si se pasan
  las ventas del período, excluye pagos multi-período (cuyo
  `importe_total_consumos` no cuadra con el bruto de las ventas en el CSV).
- `filtrar_movimientos` aplica el patrón en `descripcion` según
  (banco, medio): para MC usa el prefijo `00<codigo_comercio>`; para AMEX
  patrones case-insensitive; para Diners filtros desde `cuentas.yaml`.
- `emparejar` hace matching 1-a-1 por `(fecha, importe)` con FIFO para
  duplicados.

**Bancos cubiertos:** Interbank, BBVA, BCP (los 3 con loader y datos).
**Bancos sin loader (sin extractos de muestra):** Scotiabank y Pichincha.
Esto deja 22 conciliaciones reportadas como omitidas (20 Scotiabank +
2 Pichincha), con mensaje claro en el log y skip explícito.

### Paso 5 — Generar asiento contable SAP
**Estado:** 🟡 Funcional pero con dos bloqueantes externos para "cerrar".

`src/asiento/generador.py::construir_asiento` construye el asiento siguiendo
el patrón documentado en el PDF (pp. 19-22):

1. **Línea 1 — HABER cuenta puente** por el `total_a_cancelar` (suma de la
   pasarela del período).
2. **Líneas 2..N — DEBE banco** una por cada movimiento bancario casado
   (con `nro_operacion` en `Referencia 1`).
3. **Línea N+1 — DEBE cliente genérico** (C00000000 / 461101) por la suma
   de extornos del período, si los hay.
4. **Línea final — DEBE proveedor de comisión** por el residuo. Si el
   residuo es negativo (los depósitos más extornos superan lo cancelable),
   la línea se registra como **CRÉDITO** (en vez de un DEBE negativo que
   sería un asiento inválido) y el asiento se marca para revisión.

Validaciones internas:
- Se valida que los códigos contables que el asiento necesita no sean
  placeholders (`XXX`/`PENDIENTE`). Si alguno lo es, el asiento se omite
  con un mensaje exacto del qué falta (en vez de exportar basura no
  importable a SAP).
- `Asiento.balanceado()` chequea `debe == haber` con tolerancia.
- `Asiento.requiere_revision()` es `True` si hay advertencias o no balancea
  → el archivo va a `salidas/_revisar/`.

**Bloqueantes para cerrar el paso 5:**
- **8 códigos contables pendientes** en `config/cuentas.yaml`. Sin ellos
  se generan 16/58 asientos; con ellos, los 58.
- **Plantilla real "Importar de Excel" de SAP B1** para validar que el
  formato del Excel de asiento se carga sin retoque. Hoy el formato es
  tentativo, basado en las capturas del PDF.

### Paso 6 — Importar el asiento a SAP B1
**Estado:** 🔴 Manual (por diseño).

El usuario abre el Excel del asiento en SAP B1 con la opción "Importar de
Excel". Esto no se automatiza sin acceso a la API/DI-API de SAP, que está
fuera de alcance.

---

## 2. Cambios aplicados en esta sesión

Esta sección documenta cada cambio hecho, en orden cronológico aproximado,
con suficiente detalle para reproducir o entender la decisión.

### 2.1 Análisis y reconocimiento inicial

Antes de tocar código, hice:

- **Lectura cruzada de BLUEPRINT.md, CLAUDE.md, ESTADO_DEL_PROYECTO.md** para
  entender la arquitectura, las reglas de negocio y el alcance MVP.
- **Inspección de la muestra `Muestra al 30.04/`** con un script que listó
  todas las hojas y columnas de cada archivo:
  - Libro de bancos: solo tiene hojas BBVA, BCP 94 e INTERBANK
    → **conclusión:** Scotiabank y Pichincha NO se pueden implementar con
    la muestra actual (no hay datos).
  - CIERRE DE TIENDAS.xlsx: 6,060 filas, 27 columnas con todos los medios.
  - mc_*.csv: 25,187 filas — pero solo 1,353 son MC puro (el resto VA, VK,
    etc.). Aparentaba un bug pero NO lo era: el campo "MASTERCARD" del
    Cierre SAP es el **total completo de la pasarela Izipay**, no solo
    MC puro. Verificado contra el cuadre manual de Schell. **El loader es
    correcto al cargar todas las filas.**
  - Reportes Diners: ventas (345) y pagos (274).
- **Drill-down al cuadre manual de Schell** (`CIERRE TIENDA SCHELL 04-26.xlsx`)
  para verificar que el `total_a_cancelar` de `main.py` reproduce el PDF.

### 2.2 Bugs de dominio corregidos

#### Bug 1 — `float` para importes en `conciliar_ventas.py`
**Síntoma:** `resumir()` y `conciliar_tienda()` convertían los `Decimal` a
`float` antes de sumarlos, violando la regla del proyecto "todos los
importes son `Decimal`".

**Fix:** Eliminé los `float()` en `conciliar_tienda()` y reemplacé los `0.0`
de inicialización en `resumir()` por `Decimal("0")`. La aritmética ahora es
exacta.

**Verificación:** la corrida vuelve a producir los mismos números (73
tiendas, 819 → luego 789 discrepancias con el filtro de fechas correcto), y
el Excel exportado funciona correctamente con `Decimal` (openpyxl los maneja
como números).

#### Bug 2 — `main.py` ignoraba `--desde/--hasta` para filtrar datos
**Síntoma:** los argumentos `--desde` y `--hasta` solo se usaban para
nombrar el archivo de salida y como `fecha_corte` del asiento; no filtraban
las transacciones. Una corrida con `--desde 2026-04-01 --hasta 2026-04-09`
silenciosamente procesaba el mes completo y etiquetaba mal el resultado.

**Fix:** agregué el filtrado de `lineas_cierre`, `txn_mc`, `txn_amex` y
`txn_diners` por el período entre `desde` y `hasta`. Los movimientos
bancarios NO se filtran (el abono de una venta del período puede caer en el
banco después de `hasta`).

**Verificación:** corrida con `--desde 2026-04-01 --hasta 2026-04-09
--tiendas MIS.MI01` produce un asiento MC con `haber=168769.84`, exacto al
PDF.

#### Bug 3 — Asientos con códigos placeholder se exportaban con basura
**Síntoma:** la documentación dice que el pipeline debe fallar temprano con
códigos `XXX`, pero `cargar_cuentas()` no validaba nada. Los asientos para
tiendas BBVA/BCP-banked o de medios AMEX/DINERS salían con códigos como
`104XXX` o `PXXXXXXXXXXXX` en el Excel — no importables a SAP.

**Fix (3 partes):**
1. `src/config.py`: agregué `es_placeholder(codigo)` (detecta `XXX`,
   `PENDIENTE`, vacío, None) y el método
   `ConfiguracionCuentas.placeholders_pendientes()` que devuelve la lista
   de qué falta.
2. `src/asiento/generador.py`: en `construir_asiento`, antes de armar las
   líneas, valida los códigos que el asiento realmente va a usar (banco,
   cliente genérico solo si hay extornos, proveedor solo si comisión ≠ 0).
   Si falta alguno, lanza `ValueError` con mensaje exacto.
3. `main.py` / `pipeline.py`: catchean ese `ValueError` y lo reportan en el
   log; siguen con la siguiente tienda. Al arrancar, se imprime la lista
   de placeholders pendientes como aviso.

**Decisión de diseño:** la documentación original decía "código XXX = el
pipeline se detiene". Lo cambié a "se omite ese asiento con mensaje claro y
el pipeline sigue". Razón: con la realidad actual (8 códigos pendientes)
el fail-fast global no permitiría generar NINGÚN asiento, pero los 16
asientos MC-Interbank sí tienen todos los códigos y deberían exportarse.
La nueva regla evita basura sin bloquear el trabajo útil.

**Verificación:** corrida completa muestra 8 placeholders al arranque,
genera 16 asientos válidos y omite 42 con mensaje exacto por cada uno.

#### Bug 4 — Asiento MIS.PI01 MC con DEBE negativo (residuo negativo)
**Síntoma documentado en ESTADO §5.3:** la línea de comisión salía con
débito −1,873.32, un asiento contablemente inválido.

**Diagnóstico:** Con un script de instrumentación encontré que MIS.PI01
tiene 11,796 en extornos en abril, pero solo ~8,000 de "espacio" (comisión
+ ventas sin depositar) para absorberlos. Causa más probable: extornos
que revierten ventas de un período anterior, mezcladas en el reporte.

**Fix (3 archivos):**
1. `src/modelos.py`: agregué `Asiento.advertencias: list[str]` y el método
   `Asiento.requiere_revision()` que devuelve `True` si hay advertencias o
   no balancea.
2. `src/asiento/generador.py`: cuando el residuo de comisión es negativo,
   la línea se registra como **CRÉDITO** (no como DEBE negativo) y se
   agrega una advertencia a `asiento.advertencias`. El asiento balancea y
   es contablemente válido.
3. `main.py` / `pipeline.py`: imprime las advertencias después del `[ok]`
   del asiento.

**Verificación:** MIS.PI01 MC ahora produce un asiento con `haber=161732.78`
que balancea (debe=banco+extornos=161732.78), con la línea de proveedor en
CRÉDITO 1873.32 y la advertencia clara.

### 2.3 Refactor: pipeline compartido (`src/pipeline.py`)

**Motivación:** la lógica del proceso completo (pasos 2-5) vivía inline en
`main()` de `main.py`. La GUI necesitaba llamarla por separado pero
duplicar código era frágil.

**Cambio:** extraje toda la orquestación a `src/pipeline.py` con una
interfaz limpia:

- Dataclasses: `Insumos`, `ResultadoTienda`, `ResultadoPipeline`.
- `descubrir_archivos(inputs)` localiza los 6 archivos por glob.
- `cargar_insumos(**paths)` los carga al modelo canónico.
- `ejecutar(insumos, tiendas, cuentas, desde, hasta, log=...)` corre los
  pasos 2-5 y devuelve `ResultadoPipeline`.
- `exportar(resultado, outputs, log=...)` escribe los Excel.

`main.py` quedó como un wrapper delgado (~65 líneas vs ~250) que solo
parsea args, llama al pipeline y muestra el resultado.

**Beneficios:**
- Una sola fuente de verdad para la lógica.
- Testeable de forma aislada.
- Cualquier frontend (GUI, exe, otra CLI) puede llamarlo.
- Un callback `log` configurable: la CLI usa `print`; la GUI puede usar
  un volcado a su panel.

**Verificación:** misma corrida sobre la muestra produce el mismo
resultado (16 asientos, 92 archivos, 1 marcado para revisión).

### 2.4 Suite de tests del dominio (55 tests)

**Antes:** cero tests. El BLUEPRINT §9 tenía un plan detallado, sin
implementar.

**Después:** 55 tests `pytest` en verde, distribuidos así:

- **`tests/conftest.py`** — fixtures compartidos:
  - `cuentas` con plan de cuentas completo (sin placeholders).
  - `tienda` con una tienda típica (MC/AMEX Interbank, Diners BBVA).
  - Factories: `make_txn`, `make_cierre`, `make_mov`, `make_pago_diners`.
- **`tests/test_conciliacion_ventas.py`** (8 tests) — V01..V08 del
  BLUEPRINT. Cada regla de negocio del §5.1 con un test que la cita.
- **`tests/test_conciliacion_depositos.py`** (12 tests) — depósitos
  esperados, filtros bancarios y matching. Cubre Diners multi-período,
  case-insensitive AMEX, FIFO en duplicados, etc.
- **`tests/test_asiento.py`** (13 tests) — A01..A10 del BLUEPRINT más
  tests del residuo negativo y la validación de placeholders.
- **`tests/test_config.py`** (4 tests) — `es_placeholder` y
  `placeholders_pendientes`.
- **`tests/test_e2e_muestra.py`** (2 tests) — corrida real contra
  `Muestra al 30.04/`:
  - Total pasarela MC de Schell 01-09 = 168,769.84.
  - Diferencia en Schell 06-04 = 586.00.
- **`tests/test_loaders.py`** (4 tests) — `texto_id` (limpieza del `.0`).
- **`tests/test_exporters.py`** (4 tests) — sap_b1 cabecera con
  advertencias + reporte con hoja DINERS_RESUMEN.
- **`tests/test_pipeline.py`** (8 tests) — `requiere_revision`,
  `_unico_archivo` (3 casos: 1 archivo, varios, ninguno), separación a
  `_revisar/`.

**Filosofía aplicada:** cada test cita explícitamente la regla que valida
en su docstring; las factories devuelven dataclasses, nunca archivos
crudos; los importes siempre son `Decimal`.

### 2.5 Configuración de calidad (`pyproject.toml`, `requirements-dev.txt`)

**Antes:** no había configuración. Los comandos `pytest`, `mypy` y `ruff`
del CLAUDE.md no se podían correr como estaban.

**Después:**
- `pyproject.toml`:
  - `[tool.pytest.ini_options]` con `pythonpath=["."]` y
    `testpaths=["tests"]`.
  - `[tool.ruff]` con `line-length=100`, `target-version="py311"` y
    `[tool.ruff.lint]` con `select=["E","F","W","I","B","UP"]` y
    `ignore=["E741","UP042"]` (la convención del proyecto usa `l` para
    "línea" y se mantiene `str+Enum` por riesgo de cambiar el repr).
  - `[tool.mypy]` con `python_version="3.11"`, `files=["src"]`,
    `ignore_missing_imports=true` (pandas no tiene stubs),
    `check_untyped_defs=true`, `warn_redundant_casts=true`,
    `warn_unused_ignores=true`, `no_implicit_optional=true`.
- `requirements-dev.txt` con `pytest`, `pytest-cov`, `mypy`, `ruff`,
  `pyinstaller`.

**Estado:** `pytest` 55 verdes, `ruff` sin errores, `mypy` sin errores en
20 archivos de `src/`.

**Limpieza de código por ruff (auto-fix):**
- 18 anotaciones `Optional[X]` → `X | None` (modernización).
- 13 imports desordenados → ordenados.
- 5 imports no usados → eliminados.
- 4 imports deprecados (typing) → reemplazos modernos.
- 1 anotación con comillas innecesarias → sin comillas.

Plus 9 líneas demasiado largas (>100 cols) wrapped manualmente.

### 2.6 Mejoras de calidad de la salida

#### Limpieza del `nro_operacion` (sin `.0`)
**Síntoma:** la columna `Referencia 1` del asiento mostraba números como
`8224818.0` (con `.0` espurio) porque pandas lee las celdas numéricas como
float y los loaders hacían `str(float)`.

**Fix:** nuevo `src/loaders/_comun.py::texto_id(valor)` que normaliza:
- `8224818.0` (float) → `"8224818"`.
- `"8224818.0"` (string) → `"8224818"`.
- `"04013819"` (string con cero a la izquierda) → `"04013819"` (preserva).
- `None`, `NaN`, `""` → `""`.

Aplicado en los 3 loaders bancarios (`interbank`, `bbva`, `bcp`) al campo
`nro_operacion`.

**Verificación:** abrí el Excel con openpyxl y las celdas `Referencia 1`
son texto limpio (`data_type='s'`, valor `'8215577'`). El `.0` que veía
con pandas era artefacto de `read_excel` infiriendo float; el archivo
guardado es correcto y SAP lo leerá limpio.

#### Advertencias visibles en el asiento
**Síntoma:** un asiento marcado por residuo negativo no daba pista visible
de que necesita revisión: la `Cabecera` solo decía `Balanceado: True`.

**Fix (dos formas complementarias):**
1. **En la `Cabecera` del Excel del asiento**: nuevas columnas
   `Requiere revision` (True/False) y `Advertencias` (texto). Usan
   `Asiento.requiere_revision()` y `" | ".join(asiento.advertencias)`.
2. **En el nombre de archivo y la ubicación**: en `pipeline.exportar`,
   los asientos con `requiere_revision()` se escriben en
   `<outputs>/_revisar/` en vez de en la raíz. Así el contador puede
   importar todo de `salidas/` sin mezclarse con los que necesitan
   ojo humano.

#### Validación de archivos de entrada (`_unico_archivo`)
**Síntoma:** `_primer_archivo` tomaba `sorted(glob)[0]`. Si en la carpeta
de inputs había dos archivos MC de períodos distintos, se elegía el
alfabéticamente primero — silenciosamente, podría ser el equivocado.

**Fix:** renombré a `_unico_archivo` y agregué validación:
- Ignora temporales de Excel (`~$...`).
- Si hay **0** archivos: `FileNotFoundError`.
- Si hay **1**: lo devuelve.
- Si hay **2 o más**: `ValueError` con mensaje claro listando los
  candidatos. Forza al usuario a quitar el que no corresponde.

**Verificación:** la muestra carga bien (un archivo por patrón); tests
cubren los 3 escenarios.

#### Hoja DINERS_RESUMEN en el reporte por tienda
**Síntoma:** asimetría — `MC_RESUMEN` y `AMEX_RESUMEN` existían en el
reporte pero faltaba `DINERS_RESUMEN`.

**Fix:** agregué la hoja con el mismo formato (compras / extornos / neto
por fecha) al exporter `reporte_tienda`. El reporte ahora tiene 9 hojas:
CIERRE, MASTERCARD, MC_RESUMEN, AMEX, AMEX_RESUMEN, DINERS,
**DINERS_RESUMEN**, Diners Pagos, Bancos.

### 2.7 GUI / ejecutable para pasos 2-3

**Decisión del usuario:** el ejecutable cubre solo los pasos 2-3
(conciliación de ventas). El pipeline completo (5 pasos) corre desde la
CLI.

**`conciliar_gui.py` reescrito:**
- Título: "Conciliación de ventas — Pasos 2 y 3".
- 5 botones de carga, uno por archivo: "Cargar Cierre Caja (SAP)",
  "Cargar Mastercard (Izipay)", "Cargar AMEX (Izipay)", "Cargar Diners
  — Ventas", "Cargar Diners — Pagos". (*Nota: Diners — Pagos se carga
  pero no se usa en los pasos 2-3; está como placeholder por compatibilidad
  con el formato de inputs; ver §5.3*).
- Dos campos de fecha **Desde / Hasta** (YYYY-MM-DD). Se autollenan al
  elegir el Cierre, con primer y último día del mes que cubre. Editables
  para acotar (excluir primeros o últimos días).
- Carpeta de resultados configurable.
- Botón PROCESAR con estado en colores ("Procesando...", "Listo en X",
  "Error").
- Panel de resultados con resumen ejecutivo (tiendas, totales, top 10
  discrepancias) más el Excel exportado con 3 hojas (Resumen, Detalle,
  Discrepancias).

**Reusa la lógica validada:** llama a `conciliar_ventas.cargar_inputs_archivos`,
`filtrar_por_periodo`, `conciliar_tienda`, `resumir`, `exportar_excel`.
Cero duplicación.

**Ejecutable recompilado:** `dist/ConciliadorVentas.exe` (46 MB) generado
con PyInstaller. Incluye los catálogos embebidos (`config/tiendas.yaml`,
`config/cuentas.yaml`).

### 2.8 Documentación actualizada

Cuatro documentos del proyecto se actualizaron para reflejar la realidad:

- **`CLAUDE.md`**: snapshot del estado actual (16/76/22 en vez de 58/76/22
  del demo); "errores vs warnings" actualizado (códigos pendientes son
  warning que omite el asiento, no excepción global); "estructura de
  tests" ahora describe la real (no la planificada); referencias a
  pipeline.py y al alcance de la GUI.
- **`BLUEPRINT.md`** §7: tabla de estado del código con pipeline.py,
  main.py thin, GUI, tests ✅; el bug B1 marcado como resuelto.
- **`README.md`**: tabla de estado actualizada; pendientes para producción
  ajustados (8 placeholders + plantilla SAP B1 + Scotiabank/Pichincha).
- **`ESTADO_DEL_PROYECTO.md`**: §1 indicadores; §2.3 (GUI/exe ahora pasos
  2-3); §5.3 (B1 resuelto); §5.4 (P6/P7 hechos); §7 (git al día); §9
  (próximos pasos reordenados).

---

## 3. Arquitectura del sistema

### 3.1 Flujo de alto nivel

```
┌─────────────────────────────────────────────────────────────────┐
│  PASO 1 — Descarga manual de reportes (fuera de alcance)        │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  Archivos crudos:                  │ Catálogos:                 │
│  - Cierre Caja Resumen (SAP)       │ - tiendas.yaml             │
│  - mc_*.csv (Izipay MC)            │ - cuentas.yaml             │
│  - movi_amex*.csv (Izipay AMEX)    │                            │
│  - ventas-*.xlsx (Diners ventas)   │                            │
│  - pagos-*.xlsx (Diners pagos)     │                            │
│  - Movimientos bancos.xlsx (3 hojas)│                           │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│              src/loaders/  (uno por tipo de archivo)            │
│  cierre_caja · izipay · diners · interbank · bbva · bcp         │
└────────────────────┬────────────────────────────────────────────┘
                     ▼
         ┌─────────────────────────────┐
         │ Modelo canónico en memoria  │
         │ (src/modelos.py)            │
         │ - Tienda, LineaCierreCaja,  │
         │   TransaccionMedioPago,     │
         │   PagoDiners, MovimientoBancario │
         └───────────────┬─────────────┘
                         │
   ┌─────────────────────┼─────────────────────────────────┐
   ▼                     ▼                                 ▼
┌────────┐         ┌──────────┐                     ┌──────────────┐
│ PASO 2-3│        │ PASO 4   │                     │ PASO 5       │
│ ventas  │        │ depósitos│                     │ asiento SAP  │
│ (Cierre │        │ (vs bancos)│                   │ (cuenta puente│
│ vs MC/  │        │           │                    │ /banco/cliente│
│ AMEX/   │        │           │                    │ gen/proveedor)│
│ Diners) │        │           │                    │              │
└────┬────┘         └─────┬────┘                     └──────┬───────┘
     ▼                    ▼                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│      src/exporters/                                             │
│      reporte_tienda  ·  sap_b1                                  │
└─────────────────────────────────────────────────────────────────┘
     │                                                       │
     ▼                                                       ▼
salidas/reporte_<tienda>_<periodo>.xlsx        salidas/asiento_<tienda>_<medio>_<periodo>.xlsx
                                                salidas/_revisar/asiento_... (los marcados)
                                                       │
                                                       ▼
                                            ┌──────────────────┐
                                            │ PASO 6 — Import  │
                                            │ manual a SAP B1  │
                                            └──────────────────┘
```

### 3.2 Capas y responsabilidades

| Capa | Responsabilidad | No debe… |
|---|---|---|
| `src/loaders/*` | Leer formatos crudos (CSV, Excel) y devolver dataclasses | Conocer la lógica de conciliación |
| `src/modelos.py` | Definir el modelo canónico | Saber de pandas o de archivos |
| `src/config.py` | Cargar `cuentas.yaml` / `tiendas.yaml` | Conocer lógica de negocio |
| `src/conciliacion/*` | Reglas puras de conciliación de ventas y depósitos | Tocar pandas o archivos |
| `src/asiento/generador.py` | Construir el asiento siguiendo el patrón del PDF | Conocer formato Excel |
| `src/exporters/*` | Volcar al formato Excel final | Tener lógica de negocio |
| `src/pipeline.py` | Orquestar pasos 2-5; descubrir, cargar, ejecutar, exportar | Asumir CLI o GUI específica |
| `main.py` | CLI sobre el pipeline | Tener lógica que no esté en `pipeline.py` |
| `conciliar_ventas.py` | CLI standalone solo para pasos 2-3 | Tocar bancos o asientos |
| `conciliar_gui.py` | GUI tkinter sobre `conciliar_ventas.py` | Replicar lógica |

### 3.3 Estructura de carpetas

```
cobranzas/
├── AVANCE.md                        ← este documento
├── BLUEPRINT.md                     ← arquitectura y reglas
├── CLAUDE.md                        ← contexto para Claude Code
├── ESTADO_DEL_PROYECTO.md           ← snapshot de tracking
├── README.md                        ← quickstart usuario final
├── pyproject.toml                   ← pytest + ruff + mypy
├── requirements.txt
├── requirements-dev.txt
├── main.py                          ← CLI del pipeline completo
├── conciliar_ventas.py              ← CLI standalone pasos 2-3
├── conciliar_gui.py                 ← GUI pasos 2-3
├── build_exe.py                     ← script PyInstaller
├── ConciliadorVentas.spec           ← spec PyInstaller
├── config/
│   ├── cuentas.yaml                 ← plan de cuentas (8 placeholders)
│   ├── tiendas.yaml                 ← catálogo (no versionar — PII)
│   └── tiendas.example.yaml         ← ejemplo público
├── src/
│   ├── modelos.py                   ← dataclasses canónicas
│   ├── config.py                    ← carga YAMLs
│   ├── pipeline.py                  ← orquestador compartido
│   ├── loaders/
│   │   ├── _comun.py                ← texto_id, helper compartido
│   │   ├── cierre_caja.py
│   │   ├── izipay.py
│   │   ├── diners.py
│   │   ├── interbank.py
│   │   ├── bbva.py
│   │   └── bcp.py
│   ├── conciliacion/
│   │   ├── ventas.py
│   │   └── depositos.py
│   ├── asiento/
│   │   └── generador.py
│   └── exporters/
│       ├── reporte_tienda.py
│       └── sap_b1.py
├── tests/
│   ├── conftest.py                  ← fixtures + factories
│   ├── test_conciliacion_ventas.py
│   ├── test_conciliacion_depositos.py
│   ├── test_asiento.py
│   ├── test_config.py
│   ├── test_exporters.py
│   ├── test_loaders.py
│   ├── test_pipeline.py
│   └── test_e2e_muestra.py
├── Muestra al 30.04/                ← datos reales de ejemplo
│   ├── Reporte SAP/
│   ├── Reportes CSV/
│   ├── Extractos bancarios/
│   ├── Tiendas cuadradas/
│   └── TIENDAS GENERAL QTC.xlsx
├── dist/
│   └── ConciliadorVentas.exe        ← 46 MB, ejecutable pasos 2-3
├── salidas/                         ← outputs CLI (gitignorables)
├── resultados/                      ← outputs conciliar_ventas
└── build/                           ← intermedios PyInstaller
```

### 3.4 Stack técnico

- **Python 3.11+** (uso de `match`, `dict[X,Y]`, `X | None`, dataclasses).
- **pandas** + **openpyxl** + **xlrd** para los archivos.
- **PyYAML** para los catálogos.
- **tkinter** (stdlib) para la GUI.
- **PyInstaller** para empacar el .exe.
- **pytest** + **mypy** + **ruff** para calidad.

Sin frameworks pesados, sin dependencias innecesarias.

---

## 4. Tests y verificaciones

### 4.1 Suite de tests (55 tests, todos verdes)

```
tests/test_conciliacion_ventas.py        8 tests   (V01-V08)
tests/test_conciliacion_depositos.py    12 tests
tests/test_asiento.py                   13 tests   (A01-A10 + extras)
tests/test_config.py                     4 tests
tests/test_loaders.py                    4 tests   (texto_id)
tests/test_exporters.py                  4 tests   (sap_b1 + reporte)
tests/test_pipeline.py                   8 tests   (validación, routing)
tests/test_e2e_muestra.py                2 tests   (golden numbers)
                                       ─────────
                                        55 tests
```

### 4.2 Verificaciones contra el PDF

Estas son las pruebas concretas que confirman que el código reproduce los
números documentados en el PDF:

| Verificación | Esperado (PDF) | Obtenido | Estado |
|---|---|---|---|
| HABER asiento Schell MC 01-09 | 168,769.84 | 168,769.84 | ✅ exacto |
| Diferencia Schell 06-04 MC | 586.00 | 586.00 | ✅ exacto |
| Estructura de líneas del asiento (puente/banco/cliente-gen/proveedor) | Pp. 19-22 | Idéntica | ✅ |
| Asiento balanceado | Sí | Sí | ✅ |

### 4.3 Cobertura de calidad

| Herramienta | Estado |
|---|---|
| `pytest` | 55/55 verdes en ~30s |
| `mypy src/` | "no issues found in 20 source files" |
| `ruff check ...` | "All checks passed!" |
| Compilación CLI | OK (`python -m py_compile main.py`) |
| Compilación GUI | OK (`python -m py_compile conciliar_gui.py`) |
| Build PyInstaller | OK, 46 MB |

### 4.4 Corridas reales contra la muestra

| Comando | Resultado |
|---|---|
| `main.py --inputs "Muestra al 30.04" --desde 2026-04-01 --hasta 2026-04-30` | 16 asientos + 76 reportes; 1 a revisar (`_revisar/`); 22 omitidos por banco |
| `main.py --tiendas MIS.MI01 --desde 2026-04-01 --hasta 2026-04-09` | Asiento MC con HABER 168,769.84 ✓ |
| `conciliar_ventas.py --inputs "Muestra al 30.04" --outputs resultados` | 73 tiendas, 819 discrepancias detectadas, Excel con 3 hojas |
| Flujo GUI (pasos 2-3) headless | 73 tiendas, 789 discrepancias (con filtro de fechas), Excel generado |

---

## 5. Lo que falta para cerrar el flujo

### 5.1 Bloqueantes externos (insumos del usuario, no código)

#### B1 — 8 códigos contables pendientes
Sin estos, 42 de los 58 asientos posibles se omiten correctamente (con
mensaje claro). El pipeline los genera todos en cuanto se completen.

Faltan en `config/cuentas.yaml`:

| Tipo | Quién | Campos | Valor actual |
|---|---|---|---|
| Banco | BBVA | `codigo_socio_sap` | `104XXX` |
| Banco | BCP | `codigo_socio_sap` | `104XXX` |
| Banco | SCOTIABANK | `codigo_socio_sap` | `104XXX` |
| Banco | PICHINCHA | `codigo_socio_sap` | `104XXX` |
| Proveedor comisión | AMEX | `codigo_socio` | `PXXXXXXXXXXXX` |
| Proveedor comisión | AMEX | `cuenta_asociada` | `421XXX` |
| Proveedor comisión | DINERS | `codigo_socio` | `PXXXXXXXXXXXX` |
| Proveedor comisión | DINERS | `cuenta_asociada` | `421XXX` |

**Dónde obtenerlos:** maestro de Socios de Negocio de SAP B1
(ruta del PDF, p. 17). El proveedor de Mastercard ya está
documentado (P20432405525, "PROCESOS DE MEDIOS DE PAGO S.A.",
421201). Los demás son rutina contable.

**Responsable:** contabilidad / TI.

#### B2 — Plantilla real "Importar de Excel" de SAP B1
El exporter `src/exporters/sap_b1.py` genera el asiento con la estructura
Cabecera + Líneas basada en las **capturas** del PDF (pp. 20-22). Para
que el Excel sea importable a SAP sin retoque manual hay que validar:

- Nombres exactos de las columnas que SAP espera.
- Si SAP exige hojas adicionales (categorías, dimensiones, etc.).
- Si hay tipos especiales (fechas con formato fijo, números con coma).

**Cómo conseguirlo:** un asiento de cualquier período YA importado a SAP
por contabilidad. Se exporta o se copia su estructura.

**Responsable:** TI / contabilidad.

#### B3 — Extractos de muestra de Scotiabank y Pichincha
22 conciliaciones (20 Scotiabank, 2 Pichincha) quedan reportadas como
omitidas. Implementar los loaders es sencillo (similar a `bbva.py`/`bcp.py`)
una vez que haya un archivo de muestra para detectar la cabecera y el
formato del importe.

**Responsable:** tesorería.

### 5.2 Mejoras posibles dentro del alcance actual

Estas son mejoras de calidad que sí están a mi alcance (no requieren
insumos externos). Las priorizadas en su momento:

| # | Mejora | Estado |
|---|---|---|
| ✅ 1 | `nro_operacion` limpio (sin `.0`) | Hecho |
| ✅ 2 | Advertencias visibles en el Excel del asiento (Cabecera + nombre) | Hecho |
| ✅ 3 | Asientos a revisar en subcarpeta `_revisar/` | Hecho |
| ✅ 4 | Validar archivos de entrada (no tomar el primero por glob) | Hecho |
| ✅ 5 | Hoja `DINERS_RESUMEN` en el reporte | Hecho |
| 🟡 6 | Tests unitarios dedicados de cada loader con archivos sintéticos | Pendiente |
| 🟡 7 | Higiene del repo: `.gitignore` excluyendo `salidas/`, `resultados/`, `dist/*.exe` | Pendiente |
| 🟡 8 | Quitar Diners — Pagos del formulario GUI (no se usa en pasos 2-3) | Identificado, no aplicado |

### 5.3 Notas sobre Diners — Pagos en la GUI

En los pasos 2-3 (que es lo que hace el ejecutable), Diners — Pagos NO se
usa para la conciliación. Solo aporta a los pasos 4-5 (depósitos + asiento).

En el ejecutable actual lo estoy pidiendo "de más" — el usuario debe cargar
un archivo que el script no consume. Es trivial quitarlo del formulario
(borrar una entrada de `ARCHIVOS` y un parámetro del flujo), no se hizo
porque no fue pedido explícitamente todavía.

### 5.4 Bugs conocidos no críticos

- **B2 — Diferencias significativas residuales en Diners**: tras alinear
  `fecha_proceso` con `Fecha de ticket` quedan unas pocas diferencias
  reales que pueden ser desfases de período o ajustes. Falta revisar
  caso por caso.
- **B3 — Cobertura parcial del CSV de AMEX**: la muestra de AMEX solo
  cubre 30/03 a 09/04. En los días sin datos AMEX el sistema marca
  "discrepancia" porque el cierre tiene venta pero la pasarela no. Es
  comportamiento esperado dado el insumo parcial.

---

## 6. Decisiones técnicas y por qué

### 6.1 `Decimal` siempre, nunca `float`
La regla del proyecto (CLAUDE.md): todos los importes son `Decimal`. La
razón es elemental — los errores de redondeo de IEEE 754 acumulados sobre
miles de transacciones contables son inaceptables. Implementación:

- Los loaders convierten con `Decimal(str(v).replace(",",""))`.
- La aritmética entre Decimals es exacta.
- Las comparaciones de igualdad usan tolerancia explícita
  (`abs(a-b) <= 0.01`), nunca `math.isclose`.
- `pyproject.toml` no agrega nada especial: `Decimal` es stdlib y openpyxl
  lo maneja nativamente al escribir Excel.

### 6.2 Pipeline compartido en vez de duplicar entre CLI y GUI
Las dos formas de uso del sistema (CLI `main.py` y GUI futura del proceso
completo) corrían riesgo de divergir. `src/pipeline.py` es el único lugar
donde vive la orquestación pasos 2-5; ambos frontends llaman lo mismo.

### 6.3 Códigos placeholder: omitir el asiento, no detener el pipeline
La documentación original decía "fallo global". Lo cambié a "skip por
asiento" porque:
- La realidad MVP tiene placeholders y va a tenerlos un rato.
- Bloquear todo impedía ver el progreso real (16 asientos MC-Interbank).
- El mensaje exacto en el log + el aviso al arranque sigue forzando que
  el problema sea evidente.
- Cuando se completen los códigos, el comportamiento es el mismo: se
  generan todos.

### 6.4 Residuo negativo como CRÉDITO, no DEBE negativo
Cuando depósitos + extornos superan el total a cancelar, el residuo de
comisión sería negativo. Antes el código emitía una línea con `debito < 0`,
que es contablemente inválido. La nueva regla:
- Si `comision > 0` → DEBE proveedor por `comision`.
- Si `comision < 0` → CRÉDITO proveedor por `-comision`.
- En ambos casos balancea.
- Si pasa el caso negativo, se agrega advertencia (`requiere_revision()`
  devuelve `True`) y el archivo va a `_revisar/`.

Esto NO resuelve la causa de fondo (probablemente extornos de un período
anterior contaminando la consolidación), pero hace que el asiento sea
contablemente válido y queda flaggeado para que un humano lo revise.

### 6.5 `_revisar/` en vez de sufijo en el nombre
Inicialmente puse el sufijo `_REVISAR` al nombre del archivo. Lo cambié a
una **subcarpeta `_revisar/`** porque:
- El contador puede importar todo el contenido de `salidas/` (raíz) sin
  filtrar.
- Lo de `_revisar/` queda separado, fácil de ver en el explorador.
- Más limpio que un sufijo redundante.

### 6.6 `texto_id` para limpiar `.0` en identificadores
Pandas lee celdas numéricas como float, así un número de operación
`8224818` llega como `8224818.0`. `str(8224818.0)` = `"8224818.0"`.
Para SAP esa Referencia es incorrecta (lleva un `.0` que no es real).

`texto_id` normaliza: si el valor es un float entero, lo pasa a int antes
de stringificar. Si es un string que termina en `.0` con dígitos antes,
lo recorta. Preserva strings normales y ceros a la izquierda.

### 6.7 `_unico_archivo` falla si hay varios
`_primer_archivo` antes tomaba el primero por glob, riesgo de elegir el
equivocado. La nueva regla es estricta: si hay varios archivos que
matchean un patrón, se aborta con un mensaje claro listándolos. El
usuario debe dejar solo el del período. Para la operación contable la
ambigüedad silenciosa es más peligrosa que un error con instrucciones.

### 6.8 La GUI/exe cubre solo pasos 2-3, no el pipeline completo
Decisión explícita del usuario: el ejecutable es para los pasos 2-3
(consolidación + conciliación de ventas), porque es el uso interactivo
más frecuente. El pipeline completo (con bancos y asiento) se corre
desde CLI, donde se puede automatizar y batchear. Si se necesita una
GUI del proceso completo, se hace bajo pedido.

### 6.9 Tests con factories en memoria, no con fixtures de archivos
Los archivos crudos cambian de formato. Las dataclasses no. Los tests del
dominio construyen sus datos con factories Python (`make_txn(...)`) y
nunca tocan disco. El único test que toca archivos es el e2e contra
`Muestra al 30.04/`, y se omite (skip) si la carpeta no está.

---

## 7. Cómo usar el sistema

### 7.1 Pipeline completo (CLI)

```bash
python main.py \
  --inputs "Muestra al 30.04/" \
  --outputs ./salidas/ \
  --desde 2026-04-01 --hasta 2026-04-30
```

Opcional: `--tiendas MIS.MI01,MIS.SA01` para acotar.

Genera en `./salidas/`:
- `reporte_<tienda>_<periodo>.xlsx` — 9 hojas (CIERRE, MASTERCARD,
  MC_RESUMEN, AMEX, AMEX_RESUMEN, DINERS, DINERS_RESUMEN, Diners Pagos,
  Bancos).
- `asiento_<tienda>_<medio>_<periodo>.xlsx` — Cabecera + Líneas SAP B1.
- `_revisar/asiento_...xlsx` — los que necesitan revisión humana.

### 7.2 GUI / ejecutable (pasos 2-3)

Doble clic en `dist/ConciliadorVentas.exe`.

1. Cargar Cierre Caja (SAP) → al cargarlo, las fechas Desde/Hasta se
   autollenan con el primer y último día del mes.
2. Cargar Mastercard, AMEX, Diners — Ventas, Diners — Pagos.
3. (Opcional) ajustar Desde/Hasta para excluir días.
4. (Opcional) elegir carpeta de resultados.
5. PROCESAR → resumen en pantalla + Excel `conciliacion_ventas_<periodo>.xlsx`.

### 7.3 Script CLI standalone pasos 2-3

```bash
python conciliar_ventas.py --inputs "Muestra al 30.04/" --outputs ./resultados/
# Variantes:
python conciliar_ventas.py --inputs ... --outputs ... --tiendas MIS.MI01
python conciliar_ventas.py --inputs ... --outputs ... --solo-discrepancias
python conciliar_ventas.py --inputs ... --outputs ... --desde 2026-04-01 --hasta 2026-04-09
```

### 7.4 Tests

```bash
pip install -r requirements-dev.txt
pytest                            # todos
pytest -k V0                      # los V01..V08
pytest --cov=src                  # con cobertura
mypy                              # types de src/
ruff check src/ tests/ main.py    # lint
```

### 7.5 Recompilar el ejecutable

```bash
python build_exe.py
# Genera dist/ConciliadorVentas.exe (~46 MB)
```

### 7.6 Setup de desarrollo

```bash
python -m venv .venv
.venv\Scripts\activate           # Windows
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

---

## 8. Archivos importantes — dónde está cada cosa

### 8.1 Para entender qué hace el sistema
- **`BLUEPRINT.md`** — arquitectura, modelo de datos, reglas de negocio,
  invariantes. El documento maestro técnico.
- **`AVANCE.md`** (este) — estado actual, todo lo hecho, todo lo que falta.
- **`ESTADO_DEL_PROYECTO.md`** — tracking con tablas, próximos pasos.
- **`README.md`** — quickstart para el usuario final.
- **`CLAUDE.md`** — convenciones del proyecto + estado para Claude Code.

### 8.2 Para tocar el código
- **`src/modelos.py`** — todas las dataclasses canónicas.
- **`src/pipeline.py`** — orquestación de pasos 2-5.
- **`src/conciliacion/ventas.py`** — conciliación de ventas (paso 3).
- **`src/conciliacion/depositos.py`** — conciliación de depósitos (paso 4).
- **`src/asiento/generador.py`** — generación del asiento SAP (paso 5).

### 8.3 Para entender los archivos de entrada/salida
- **`src/loaders/`** — un archivo por tipo de archivo crudo, con sus
  particularidades documentadas en docstrings.
- **`src/exporters/reporte_tienda.py`** — el Excel multi-hoja por tienda.
- **`src/exporters/sap_b1.py`** — el Excel del asiento.

### 8.4 Para tocar la configuración
- **`config/cuentas.yaml`** — plan de cuentas. **Tiene 8 placeholders
  pendientes**.
- **`config/tiendas.yaml`** — catálogo de 81 tiendas. **No versionable
  (contiene PII)**.
- **`config/tiendas.example.yaml`** — versión sanitizada.

### 8.5 Para correr la calidad
- **`pyproject.toml`** — config pytest + ruff + mypy.
- **`requirements.txt`** y **`requirements-dev.txt`**.

### 8.6 Para entender los tests
- **`tests/conftest.py`** — fixtures + factories. Cualquier test nuevo
  empieza acá.
- Cada `test_<modulo>.py` cubre el módulo correspondiente.

### 8.7 Para empacar el ejecutable
- **`conciliar_gui.py`** — la GUI (pasos 2-3).
- **`build_exe.py`** — script de PyInstaller.
- **`ConciliadorVentas.spec`** — spec generada (regenerable).
- **`dist/ConciliadorVentas.exe`** — el binario.

---

## 9. Roadmap propuesto (orden recomendado para terminar)

### Pri 1 — Bloqueantes de producción
1. **Obtener los 8 códigos contables** de SAP y rellenar `cuentas.yaml`.
   Tiempo: minutos una vez que están a mano.
2. **Conseguir una plantilla "Importar de Excel"** de un asiento ya
   importado a SAP. Ajustar `src/exporters/sap_b1.py` si el formato
   difiere de las capturas del PDF.

### Pri 2 — Funcionalidad faltante por insumos
3. **Conseguir extractos de muestra de Scotiabank y Pichincha** y
   implementar sus loaders. Hoy son 22 conciliaciones omitidas.

### Pri 3 — Mejoras de calidad
4. **Tests unitarios dedicados de cada loader** con archivos sintéticos.
5. **Higiene del repo**: `.gitignore` para excluir `salidas/`,
   `resultados/`, `dist/*.exe`, `Muestra al 30.04/` (si no debe
   versionarse).
6. **Validar período completo distinto** a abril 2026.
7. (Si se pide) **Quitar Diners — Pagos del formulario GUI** ya que no
   se usa en pasos 2-3.

---

## 10. Comandos útiles para retomar el trabajo

```bash
# Validar que todo sigue verde
pytest -q
mypy
ruff check src/ tests/ main.py conciliar_ventas.py conciliar_gui.py

# Corrida CLI completa
python main.py --inputs "Muestra al 30.04/" --outputs ./salidas/ \
               --desde 2026-04-01 --hasta 2026-04-30

# Corrida CLI pasos 2-3
python conciliar_ventas.py --inputs "Muestra al 30.04/" --outputs ./resultados/

# Recompilar ejecutable
python build_exe.py
```

---

## 11. Glosario

| Término | Significado |
|---|---|
| **Cierre Caja Resumen** | Reporte de SAP con ventas por tienda × día × medio de pago |
| **Pasarela** | Procesador del medio de pago (Izipay para MC/AMEX, Diners para Diners) |
| **Cuenta puente** | Cuenta contable transitoria donde se acumulan los comprobantes de venta antes del cobro |
| **Asiento** | Registro contable balanceado (debe = haber) que se carga al ERP |
| **Cliente genérico** | Socio comodín (C00000000) para registrar extornos sin imputarlos a un cliente real |
| **Glosa** | Texto descriptivo del asiento (p. ej. "INGRESOS MASTERCARD 01-09") |
| **Extorno** | Reversa de una venta (devolución, anulación) |
| **SAP B1** | SAP Business One, el ERP donde se cargan los asientos |
| **Placeholder** | Marcador `XXX`/`PENDIENTE` en `cuentas.yaml` indicando que falta un código real |
| **Residuo de comisión** | Diferencia entre total a cancelar y depósitos+extornos; va al proveedor de comisión |
| **Multi-período (Diners)** | Pago Diners cuyo `importe_total_consumos` cubre tickets de meses distintos |
| **MVP** | Mínimo Producto Viable — alcance acotado a la muestra del PDF |

---

**Fin del informe.**
