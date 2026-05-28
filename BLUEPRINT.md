# BLUEPRINT — Cobranzas Tiendas Físicas

> Documento maestro del proyecto. Contiene todo el contexto técnico necesario
> para que cualquier persona (humana o Claude Code) pueda continuar el desarrollo
> sin necesidad de leer el código completo.
>
> **Versión:** 1.0 · **Última actualización:** 2026-05-13 · **Stack:** Python 3.11+

---

## 1. Resumen ejecutivo

### 1.1 Qué hace el sistema

Automatiza el proceso de **conciliación contable y generación de asientos** de las
ventas en tiendas físicas, en tres bloques:

1. **Conciliación de ventas** — cruza el *Cierre de Caja Resumen* (exportado
   de SAP) contra los reportes de cada pasarela (Izipay Mastercard, Izipay AMEX,
   Diners Ventas) por fecha × tienda × medio de pago. Identifica diferencias.
2. **Conciliación de depósitos** — cruza los abonos esperados (según pasarela)
   contra los movimientos reales en extractos bancarios (Interbank y BBVA).
3. **Generación de asiento contable** — produce un Excel "Importar de Excel"
   listo para cargar en SAP Business One, balanceado y con la estructura
   estándar (cuenta puente / banco / cliente genérico / proveedor comisión).

### 1.2 Por qué existe

El proceso manual hoy consume entre 30 min y 2 horas por tienda y período, con
fuerte riesgo de errores de tipeo en montos y de matcheo manual de depósitos.
La automatización lo reduce a un comando y deja trazabilidad por archivo.

### 1.3 Alcance actual (v1)

- **Medios de pago:** Mastercard, AMEX, Diners (en paralelo).
- **Bancos:** Interbank (MC/AMEX), BBVA (Diners).
- **Fuera de scope v1:** VISA, Yape, Lukita, Tunky, Wali, efectivo. El modelo
  los contempla en el enum `MedioPago` pero no se concilia ni asienta.

---

## 2. Arquitectura

```
  Archivos crudos          Catálogos          Plan de cuentas
  (SAP, Izipay,            (tiendas,          (cuentas puente,
   Diners, banco)           comercios)         proveedores comisión)
        │                       │                    │
        ▼                       ▼                    ▼
  ┌─────────────────────────────────────────────────────────┐
  │              LOADERS (uno por tipo de archivo)          │
  │   cierre_caja · izipay · diners · interbank · bbva      │
  └────────────────────────┬────────────────────────────────┘
                           ▼
              ┌────────────────────────────────┐
              │  Esquema canónico en memoria   │
              │         (src/modelos.py)       │
              └───────────────┬────────────────┘
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
       ┌──────────┐   ┌────────────┐   ┌──────────────┐
       │ Concilia │   │ Concilia   │   │  Generador   │
       │  ventas  │   │ depósitos  │   │  de asiento  │
       └─────┬────┘   └──────┬─────┘   └──────┬───────┘
             ▼               ▼                ▼
  ┌────────────────────────────────────────────────────────┐
  │  EXPORTERS: reporte_tienda.xlsx + asiento SAP B1.xlsx  │
  └────────────────────────────────────────────────────────┘
```

### 2.1 Principio rector

**Los loaders son la única capa que toca formatos crudos.** Todo lo demás
(conciliación, asiento, exporters) opera exclusivamente sobre los tipos
definidos en `src/modelos.py`. Esto significa:

- Cambiar el formato de un CSV de Izipay no toca la lógica de conciliación.
- Agregar un nuevo medio de pago = nuevo loader + entrada en el enum + entrada
  en `config/cuentas.yaml`. Nada más.
- Los tests de conciliación y asiento se hacen con fixtures en memoria, sin
  archivos Excel.

### 2.2 Estructura de carpetas

```
cobranzas/
├── BLUEPRINT.md              ← este documento
├── CLAUDE.md                 ← contexto para Claude Code
├── README.md                 ← quickstart
├── requirements.txt
├── main.py                   ← orquestador CLI
├── config/
│   ├── cuentas.yaml          ← plan de cuentas y proveedores
│   ├── tiendas.yaml          ← catálogo maestro (NO versionar, contiene PII)
│   └── tiendas.example.yaml  ← ejemplo público (sí versionar)
├── src/
│   ├── __init__.py
│   ├── modelos.py            ← dataclasses canónicas (Tienda, Asiento, etc.)
│   ├── config.py             ← carga de YAMLs → dataclasses tipadas
│   ├── loaders/              ← un módulo por tipo de archivo crudo
│   │   ├── cierre_caja.py
│   │   ├── izipay.py
│   │   ├── diners.py
│   │   ├── interbank.py
│   │   └── bbva.py
│   ├── conciliacion/
│   │   ├── ventas.py         ← cierre vs pasarela
│   │   └── depositos.py      ← pasarela vs banco
│   ├── asiento/
│   │   └── generador.py      ← construye estructura del asiento
│   └── exporters/
│       ├── reporte_tienda.py ← Excel multi-hoja
│       └── sap_b1.py         ← Excel "Importar de Excel"
├── tests/
│   ├── conftest.py           ← fixtures compartidos
│   ├── fixtures/             ← Excels/CSVs de muestra (sanitizados)
│   ├── test_modelos.py
│   ├── test_loaders/
│   ├── test_conciliacion/
│   ├── test_asiento.py
│   └── test_integracion.py   ← end-to-end con fixtures
├── entradas/                 ← (gitignore) archivos crudos del usuario
└── salidas/                  ← (gitignore) entregables generados
```

---

## 3. Modelo de datos canónico

Definido en `src/modelos.py`. Toda la lógica de negocio depende de estas
estructuras, no de los archivos crudos.

### 3.1 Insumos

| Dataclass | Origen | Granularidad |
|---|---|---|
| `LineaCierreCaja` | Cierre Caja Resumen (SAP) | una fila = (tienda, fecha) con dict de importes por `MedioPago` |
| `TransaccionMedioPago` | Izipay MC/AMEX, Diners Ventas | una transacción individual |
| `PagoDiners` | Diners Pagos | un depósito consolidado |
| `MovimientoBancario` | Interbank, BBVA | una línea del extracto |
| `Tienda` | `config/tiendas.yaml` | una tienda del catálogo |

### 3.2 Salidas intermedias

| Dataclass | Productor | Significado |
|---|---|---|
| `DiferenciaConciliacion` | `conciliacion.ventas` | (fecha, tienda, medio) diferencia entre cierre y pasarela |
| `MatchDeposito` | `conciliacion.depositos` | depósito esperado emparejado (o no) con un movimiento bancario |

### 3.3 Salida final

| Dataclass | Productor | Destino |
|---|---|---|
| `Asiento` (con `LineaAsiento[]`) | `asiento.generador` | exporter → Excel SAP B1 |

### 3.4 Enums

- `MedioPago`: MASTERCARD, AMEX, DINERS, VISA, EFECTIVO, YAPE, LUKITA, TUNKY, WALI.
- `TipoTransaccion`: COMPRA, EXTORNO.

> **Regla crítica:** todos los importes usan `Decimal`, nunca `float`. Cualquier
> conversión `str → Decimal` debe pasar por una función helper que tolere
> notación con coma como separador de miles.

---

## 4. Flujo del pipeline (paso a paso)

Implementado en `main.py`. Cinco etapas:

1. **Configuración** — Carga `cuentas.yaml` y `tiendas.yaml`. Filtra tiendas por
   argumento `--tiendas` si se especifica.
2. **Ingesta** — Llama a cada loader con su archivo correspondiente. Resultado:
   listas planas en memoria.
3. **Filtrado por tienda** — Para cada tienda, filtra las transacciones por
   `codigo_comercio_mc_amex` y `codigo_comercio_diners`.
4. **Conciliación de ventas** — Produce `DiferenciaConciliacion` por
   (fecha × medio). Si abs(diferencia) > tolerancia → advertencia.
5. **Conciliación de depósitos** — Para cada medio:
   - Calcula depósitos esperados.
   - Filtra movimientos del banco que corresponde (Interbank para MC/AMEX,
     BBVA para Diners) por patrón en `descripcion`.
   - Empareja por (fecha_abono, importe_neto). Permite duplicados siempre que
     el conteo cierre.
6. **Generación de asiento** — Por cada medio, construye un `Asiento` con la
   estructura del PDF (haber cuenta puente / debe banco × N / debe cliente
   genérico para extornos / debe proveedor comisión residual). Verifica
   `balanceado()`.
7. **Exportación** — Dos archivos por tienda:
   - `reporte_<tienda>_<periodo>.xlsx` (multi-hoja con todo el detalle)
   - `asiento_<tienda>_<medio>_<periodo>.xlsx` (formato SAP B1)

---

## 5. Reglas de negocio críticas

Estas son las invariantes que deben cumplirse siempre. **Todos los tests
deben validarlas explícitamente.**

### 5.1 Conciliación de ventas

- El total del Cierre Caja para `(fecha, tienda, medio)` debe coincidir con la
  suma de `importe_bruto` de las transacciones de esa pasarela para la misma
  `(fecha_proceso, tienda)`, excluyendo extornos.
- Tolerancia: `0.01` (configurable en `cuentas.yaml`).
- Si la diferencia supera la tolerancia → la fila se marca como *significativa*
  y **no se incluye** en el total a cancelar de la cuenta puente.

### 5.2 Conciliación de depósitos

- **MC/AMEX:** un depósito esperado = `sum(importe_neto) GROUP BY fecha_abono`,
  restando extornos. Solo se buscan en Interbank.
- **Diners:** un depósito esperado = una fila de Diners Pagos con
  `estado='PAGADO'`, importe = `pago_efectivo`. Solo se buscan en BBVA.
- **Filtro bancario:**
  - MC: `descripcion` contiene `tienda.prefijo_descripcion_mc` (ej. `001023366`).
  - AMEX: `descripcion` contiene literalmente `"AMEX"`.
  - Diners: `descripcion` contiene `tienda.codigo_filtro_diners_bancos`
    (ej. `R20100118760`).
- **Matching:** por `(fecha, importe)`. Duplicados se asignan FIFO. Está OK
  tener dos depósitos del mismo monto el mismo día siempre que el conteo total
  cuadre.

### 5.3 Asiento contable

Estructura de líneas (en orden):

1. **HABER cuenta puente** — total a cancelar (suma de diferencias *no
   significativas* del período).
2. **DEBE banco × N** — una línea por depósito identificado, con
   `nro_operacion` en referencia 1.
3. **DEBE cliente genérico** — si hay extornos, total de extornos del período.
4. **DEBE proveedor comisión** — residuo:
   `comision = total_a_cancelar - total_debitos_banco - total_extornos`.

**Invariante:** `total_debe == total_haber` ± tolerancia. Si no balancea, el
sistema debe emitir warning y marcar el asiento.

### 5.4 Proyecto SAP

- Cada `LineaAsiento` lleva `proyecto = tienda.codigo_proyecto`.
- Suele coincidir con `tienda.id_sap`.

---

## 6. Configuración

### 6.1 `config/cuentas.yaml`

```yaml
cuentas_puente:
  MASTERCARD: "121206"
  AMEX:       "121207"
  DINERS:     "121208"

nombres_cuenta_puente:
  MASTERCARD: "CTA POR COBR MASTERCARD"
  AMEX:       "CTA POR COBR AMERICAN EXPRESS"
  DINERS:     "CTA POR COBR DINERS"

bancos:
  INTERBANK:
    codigo_socio_sap: "104107"
  BBVA:
    codigo_socio_sap: "104XXX"   # ⚠️ PENDIENTE

cliente_generico:
  codigo_socio:      "C00000000"
  nombre:            "CLIENTE GENERICO"
  cuenta_asociada:   "461101"

proveedores_comision:
  MASTERCARD:
    codigo_socio:    "P20432405525"
    nombre:          "PROCESOS DE MEDIOS DE PAGO S.A."
    cuenta_asociada: "421201"
  AMEX:    # ⚠️ PENDIENTE
  DINERS:  # ⚠️ PENDIENTE

tolerancia_conciliacion: 0.01
```

**TODO:** completar BBVA, proveedor AMEX y Diners con contabilidad antes de
producción.

### 6.2 `config/tiendas.yaml`

Una entrada por tienda. Campos por tienda:

| Campo | Significado | Ejemplo |
|---|---|---|
| `id_sap` | Código de tienda en SAP | `MIS.M101` |
| `nombre` | Descriptivo | `MI STORE SCHELL MIRAFLORES` |
| `codigo_proyecto` | Código de proyecto SAP (usual = id_sap) | `MIS.M101` |
| `codigo_comercio_mc_amex` | Asignado por Izipay | `1023366` |
| `codigo_comercio_diners` | Asignado por Diners | `1001299773` |
| `banco_mc_amex` | Banco de abono MC/AMEX | `INTERBANK` |
| `cuenta_mc_amex` | Cuenta corriente específica | `108-3002238284` |
| `prefijo_descripcion_mc` | Patrón en `descripcion` del banco | `001023366` |
| `banco_diners` | Banco de abono Diners | `BBVA` |
| `codigo_filtro_diners_bancos` | Patrón en `Concepto` del banco | `R20100118760` |

> ⚠️ `tiendas.yaml` contiene info comercial sensible. Va en `.gitignore`.
> Solo `tiendas.example.yaml` se versiona.

---

## 7. Estado del código

Validado contra la muestra real de abril 2026 (`Muestra al 30.04/`) y cubierto
por una suite de tests (`pytest`). Pipeline end-to-end funcional: **16 asientos
válidos / 76 reportes** de 81 tiendas; **42 asientos omitidos** por códigos
contables pendientes y **22 conciliaciones omitidas** por bancos sin loader
(Scotiabank, Pichincha).

| Componente | Estado | Comentario |
|---|---|---|
| `modelos.py` | ✅ Validado | `Tienda` con `banco_mc`, `banco_amex`, `banco_diners` separados. `PagoDiners` con `orden_pago` e `importe_total_consumos` |
| `config.py` | ✅ Validado | Bancos con `cuenta_corriente` y `nombre_largo`; `filtros_bancos` indexado por (banco, medio) |
| `conciliacion/ventas.py` | ✅ Validado | Reproduce las 6 diferencias MC del PDF y las 7 AMEX al céntimo |
| `conciliacion/depositos.py` | ✅ Validado | Matching universal 1-a-1 por (fecha, importe). Filtro Diners multi-período por `importe_total_consumos` |
| `asiento/generador.py` | ✅ Validado | Reproduce el ejemplo Schell MC 01-09 del PDF (HABER 168,769.84 exacto) |
| `loaders/cierre_caja.py` | ✅ Validado | 6,060 líneas cargadas. Ignora medios fuera de v1 (RAPPI, NOTA CREDITO, etc.) |
| `loaders/izipay.py` | ✅ Validado | sep `;`, UTF-8, extorno por `Status`, fechas duales (DD/MM/YYYY y YYYYMMDD) |
| `loaders/diners.py` | ✅ Validado | `fecha_proceso` desde `Fecha de ticket` (alinea con cierre SAP) |
| `loaders/interbank.py` | ✅ Validado | Detección dinámica de cabecera, parseo de fecha europea |
| `loaders/bbva.py` | ✅ Validado | Importe único con signo → split en abono/cargo |
| `loaders/bcp.py` | ✅ Validado | Estructura tipo BBVA, hoja `BCP 94` |
| `exporters/reporte_tienda.py` | ✅ Validado | 6+2 hojas: CIERRE, MASTERCARD, MC_RESUMEN, AMEX, AMEX_RESUMEN, DINERS, Diners Pagos, Bancos |
| `exporters/sap_b1.py` | 🟡 Tentativo | Formato basado en pantalla del PDF; validar contra plantilla SAP real |
| `pipeline.py` | ✅ Validado | Pipeline completo (pasos 2-5) compartido por la CLI y la GUI |
| `main.py` | ✅ Validado | CLI delgada sobre `pipeline.py`; filtra los insumos por `--desde/--hasta` |
| `conciliar_gui.py` | ✅ Validado | GUI del proceso completo sobre `pipeline.py` |
| `config/cuentas.yaml` | 🟡 Parcial | 8 placeholders pendientes (socio SAP de BBVA/BCP/SCOTIA/PICHINCHA + proveedor comisión AMEX/Diners); el pipeline los detecta y omite esos asientos |
| `config/tiendas.yaml` | ✅ Generado | 81 tiendas desde el Excel maestro, bancos normalizados |
| Tests | ✅ 39 tests | `pytest` en verde; `mypy` y `ruff` limpios — ver §9 |

### Casos residuales conocidos (MVP)

- **Residuo de comisión negativo** (caso MIS.PI01 MC, −1,873.32): cuando los
  depósitos más los extornos superan el total a cancelar, el residuo se
  registra como CRÉDITO (no como DEBE negativo) y el asiento se marca en
  `Asiento.advertencias` para revisión contable.
- **AMEX**: 2 días de Schell (30-31/03) marcados como diferencia significativa
  porque están en el CSV pero fuera del cierre del mes; comportamiento
  esperado (período de cobertura distinto).
- **Loaders Scotiabank y Pichincha** sin implementar (sin archivos de muestra
  para validar). 22 conciliaciones quedan reportadas como "no procesado".

---

## 8. Roadmap de implementación

Orden recomendado para ir cerrando el pipeline. Cada paso es self-contained y
testeable antes de avanzar.

### Fase 1 — Cerrar la base testeable (sin loaders reales)
1. Crear `tests/conftest.py` con fixtures sintéticos en memoria.
2. Tests unitarios de `conciliacion/ventas.py` (ver §9.2).
3. Tests unitarios de `conciliacion/depositos.py` (ver §9.3).
4. Tests unitarios de `asiento/generador.py` (ver §9.4).
5. **Hito:** todo el núcleo del dominio cubierto sin tocar archivos reales.

### Fase 2 — Loaders contra archivos de muestra
6. Generar `config/tiendas.yaml` desde el Excel maestro.
7. Completar códigos pendientes en `cuentas.yaml` (BBVA / AMEX / Diners).
8. Cablear `loaders/cierre_caja.py` contra el Excel real. Test de loader.
9. Cablear `loaders/izipay.py` (MC y AMEX). Test.
10. Cablear `loaders/diners.py` (ventas y pagos). Test.
11. Cablear `loaders/interbank.py`. Test.
12. Cablear `loaders/bbva.py`. Test.

### Fase 3 — Exporters
13. Implementar `exporters/reporte_tienda.py` (multi-hoja).
14. Conseguir plantilla SAP B1, implementar `exporters/sap_b1.py`.
15. Cablear ambos exporters en `main.py`.

### Fase 4 — End-to-end y robustez
16. Test de integración end-to-end con set completo de fixtures.
17. Logging estructurado y modo `--verbose`.
18. Modo `--dry-run` (no escribe archivos).
19. Validación de inputs (archivos faltantes, columnas faltantes).
20. Empaquetar como CLI instalable (opcional).

---

## 9. Estrategia de testing y validación

> **Esta es la sección de mayor énfasis del blueprint.** El sistema toca dinero
> y emite asientos contables que se cargan en producción. Cualquier silencio o
> bug numérico se traduce en trabajo manual de reversa por contabilidad.

### 9.1 Filosofía

- **Pirámide invertida del costo, no del volumen:** muchos tests unitarios
  baratos que cubren reglas de negocio; pocos tests de integración caros con
  archivos completos.
- **Fixtures sintéticos como ciudadanos de primera clase.** Los archivos reales
  cambian de formato; los fixtures en memoria no.
- **Toda regla de negocio del §5 tiene un test que la verifica explícitamente,
  con un nombre que cita la regla.** Si la regla cambia, el test cambia, y se
  documenta en el PR.
- **Decimal everywhere.** Cualquier test que compare importes usa `Decimal`,
  no `float`, y no `math.isclose`.

### 9.2 Tests de `conciliacion/ventas.py`

| ID | Caso | Esperado |
|---|---|---|
| V01 | Tienda con cierre = pasarela en todas las fechas | `diferencias` con `diferencia=0` y no significativas |
| V02 | Diferencia de S/ 0.005 (menor a tolerancia) | `es_significativa()` → False |
| V03 | Diferencia de S/ 0.50 | `es_significativa()` → True |
| V04 | Fecha que aparece solo en cierre, no en pasarela | `total_medio_pago=0`, diferencia = total cierre |
| V05 | Fecha que aparece solo en pasarela, no en cierre | `total_cierre=0`, diferencia = -total pasarela |
| V06 | Pasarela con un extorno y dos compras | `resumen_por_fecha` cuenta solo las compras |
| V07 | Tienda con id `A` no contamina diferencias de tienda `B` | filtrado por `id_tienda` es estricto |
| V08 | Múltiples medios de pago en paralelo | un `DiferenciaConciliacion` por (fecha, medio) |

### 9.3 Tests de `conciliacion/depositos.py`

| ID | Caso | Esperado |
|---|---|---|
| D01 | MC: 3 transacciones mismo `fecha_abono` se suman | `depositos_esperados_izipay` produce 1 tupla |
| D02 | MC: extornos restan del neto del día de abono | el monto esperado refleja la resta |
| D03 | MC: transacciones con `fecha_abono = None` se ignoran | no aparecen en esperados |
| D04 | Diners: solo pagos con `estado='PAGADO'` se consideran | los pendientes se excluyen |
| D05 | Filtro MC: solo movimientos con prefijo en descripción | descarta movimientos de otras tiendas |
| D06 | Filtro AMEX: case-insensitive sobre "AMEX" | matchea "AMEX", "amex", "Amex Pago" |
| D07 | Filtro Diners: filtra por código tienda en concepto | descarta otras tiendas |
| D08 | Match exacto (1 esperado, 1 movimiento mismo día e importe) | `encontrado=True` |
| D09 | Match con duplicados (2 esperados, 2 movs iguales) | ambos `encontrado=True` |
| D10 | Match con duplicados desbalanceados (2 esp, 1 mov) | uno `encontrado=True`, otro `False` |
| D11 | Sin movimiento bancario para un esperado | `encontrado=False`, `movimiento=None` |
| D12 | Movimiento bancario sobrante (3 movs, 2 esperados) | matches devuelve 2; sobrante no se reporta aquí |

### 9.4 Tests de `asiento/generador.py`

| ID | Caso | Esperado |
|---|---|---|
| A01 | Asiento MC con 3 depósitos, sin extornos, sin residuo | 4 líneas: 1 haber puente + 3 debe banco |
| A02 | Asiento con extornos > 0 | aparece línea cliente genérico C00000000 |
| A03 | Asiento con comisión > 0 | aparece línea proveedor pasarela |
| A04 | Asiento con comisión = 0 | NO aparece línea proveedor |
| A05 | `balanceado()` con asiento correcto | True |
| A06 | `balanceado()` con haber alterado a propósito | False |
| A07 | `total_a_cancelar` se imputa al haber de la cuenta puente correcta por medio | MC → 121206, AMEX → 121207, Diners → 121208 |
| A08 | Glosa contiene rango de días `dd-dd` | `INGRESOS MASTERCARD 01-09` |
| A09 | Cada línea tiene `proyecto = tienda.codigo_proyecto` | todas las líneas, sin excepción |
| A10 | Banco MC/AMEX usa `tienda.banco_mc_amex`; Diners usa `tienda.banco_diners` | nombre largo de banco correcto |

### 9.5 Tests de loaders

Para **cada loader**, mismo patrón:

| Test | Qué valida |
|---|---|
| `test_<loader>_columnas_completas` | Carga un Excel/CSV con todas las columnas y compara contra una lista de dataclasses esperada |
| `test_<loader>_columnas_extra_se_ignoran` | Agregar columnas extra no rompe el loader |
| `test_<loader>_columnas_faltantes` | Falta una columna obligatoria → excepción clara |
| `test_<loader>_decimales_con_coma` | `"1,234.56"` se parsea a `Decimal("1234.56")` |
| `test_<loader>_celdas_vacias` | `NaN`, `""`, `None` → `Decimal("0")` o `None` según corresponda |
| `test_<loader>_fechas_varios_formatos` | `"2026-04-01"`, `"01/04/2026"`, datetime nativo, todos → date |

**Loaders bancarios** (Interbank/BBVA) además:

| Test | Qué valida |
|---|---|
| `test_<banco>_detecta_cabecera_dinamica` | Si la cabecera está en fila 7 en lugar de 0, el loader la encuentra |
| `test_<banco>_falla_si_no_hay_cabecera` | Excepción clara, no `KeyError` opaco |
| `test_bbva_separa_importe_en_abono_cargo` | importe positivo → abono; negativo → cargo |

### 9.6 Tests de integración end-to-end

Bajo `tests/test_integracion.py`. Usan un set completo de archivos sanitizados
en `tests/fixtures/e2e/`.

| Test | Qué valida |
|---|---|
| `test_pipeline_completo_tienda_schell_un_periodo` | Corre `main.py` sobre un período conocido y compara los Excels generados contra fixtures `expected_*.xlsx` |
| `test_asientos_generados_balancean` | Para cada asiento producido en el e2e, `balanceado() is True` |
| `test_sin_diferencias_significativas_en_caso_feliz` | Caso "limpio" no produce warnings |
| `test_diferencia_significativa_produce_warning` | Inyectar un mismatch de S/ 50 → aparece en stderr/log |
| `test_deposito_faltante_no_rompe_pipeline` | Quitar 1 fila del extracto → asiento sale con menos líneas pero balanceado por residuo en comisión |

### 9.7 Fixtures

Estructura sugerida:

```
tests/fixtures/
├── unit/
│   ├── transacciones_mc_basico.py     ← factory functions
│   ├── transacciones_amex_basico.py
│   └── ...
└── e2e/
    ├── entradas/
    │   ├── cierre_caja.xlsx           ← versión sanitizada del archivo real
    │   ├── mastercard.csv
    │   ├── amex.csv
    │   ├── diners_ventas.xls
    │   ├── diners_pagos.xls
    │   ├── interbank.xlsx
    │   └── bbva.xlsx
    ├── config/
    │   ├── tiendas.yaml               ← 1-2 tiendas representativas
    │   └── cuentas.yaml               ← con códigos dummy si los reales son sensibles
    └── expected/
        ├── reporte_MIS.M101_2026-04-01_2026-04-09.xlsx
        └── asiento_MIS.M101_MASTERCARD_2026-04-01_2026-04-09.xlsx
```

**Reglas:**

- Los archivos en `unit/` son módulos Python que construyen dataclasses
  programáticamente. NO son archivos Excel.
- Los archivos en `e2e/entradas/` son archivos reales **sanitizados**
  (RUC/cuenta/montos modificados pero estructura idéntica).
- Los archivos en `e2e/expected/` se generan una vez, se revisan a mano contra
  el archivo manual que produciría un asistente contable, y se commitean.

### 9.8 Herramientas

- **pytest** + **pytest-cov** (objetivo: 85% en módulos del dominio, no en loaders).
- **mypy** en modo estricto sobre `src/` (no sobre tests).
- **ruff** para linting (sustituye flake8/black/isort).
- **pre-commit** opcional para correr ruff + mypy antes de commit.

Comando único:
```bash
pytest -v --cov=src --cov-report=term-missing
```

### 9.9 Invariantes que se chequean en runtime (no solo en tests)

Incluso en producción, `main.py` debe imprimir warnings (no fallar) cuando:

- Hay diferencias significativas en conciliación de ventas → muestra cuáles.
- Hay depósitos esperados sin movimiento bancario emparejado → lista.
- Un asiento no balancea → no exporta, lo deja en `salidas/_revisar/`.
- Faltan códigos en `cuentas.yaml` (placeholders `XXX`) → falla temprano con
  mensaje claro antes de empezar a procesar.

---

## 10. Setup y uso

### 10.1 Setup local

```bash
# Python 3.11+
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # cuando exista (pytest, mypy, ruff)
```

### 10.2 Ejecución

```bash
python main.py \
  --inputs ./entradas/ \
  --outputs ./salidas/ \
  --desde 2026-04-01 --hasta 2026-04-09 \
  --tiendas MIS.M101,MIS.M102      # opcional; vacío = todas
```

### 10.3 Tests

```bash
pytest                            # todos
pytest tests/test_asiento.py      # un archivo
pytest -k balanceado              # por nombre
pytest --cov=src                  # con cobertura
```

---

## 11. Decisiones de diseño cerradas

| Decisión | Resolución | Razón |
|---|---|---|
| Catálogo de tiendas en YAML vs DB | YAML | Pocos cambios, versionable, no necesita migraciones |
| Match de depósitos: ¿requiere campo de desempate? | No | Dentro del filtro por tienda, (fecha, importe) basta aunque haya duplicados, siempre que el conteo cierre |
| Tipo numérico | `Decimal` siempre | `float` introduce errores de redondeo no aceptables en contabilidad |
| Formato salida asiento | Excel "Importar de Excel" SAP B1 | Es lo que el ERP acepta |
| Medios de pago en scope v1 | MC, AMEX, Diners | Los tres que generan asiento; el resto van por otro flujo |
| Loaders en stubs hasta tener archivos reales | Sí | Evita asumir columnas y rehacer trabajo |
| Tests sin archivos reales para dominio | Sí | Fixtures en memoria, archivos solo para e2e |
| `tiendas.yaml` versionado | No | Contiene info comercial sensible |
| Excepciones vs warnings | Errores que rompen pipeline = excepción. Diferencias contables = warning. | Permite procesar resto de tiendas si una falla parcialmente |

---

## 12. Pendientes externos (no son código)

| # | Pendiente | Responsable |
|---|---|---|
| 1 | Excel maestro de catálogo de tiendas → convertir a `tiendas.yaml` | Sergio |
| 2 | Código SAP de banco BBVA | Contabilidad |
| 3 | Proveedor de comisión AMEX (código + cuenta) | Contabilidad |
| 4 | Proveedor de comisión Diners (código + cuenta) | Contabilidad |
| 5 | Plantilla "Importar de Excel" SAP B1 (un asiento ejemplo importado previamente) | TI/Contabilidad |
| 6 | Set completo de archivos crudos de un período cualquiera (los 7 archivos del README) | Sergio |

---

## 13. Glosario

| Término | Significado |
|---|---|
| **Cierre Caja Resumen** | Reporte de SAP con totales de venta por tienda × día × medio de pago |
| **Pasarela** | Procesador del medio de pago (Izipay para MC/AMEX, Diners para Diners) |
| **Cuenta puente** | Cuenta contable transitoria donde se acumulan los comprobantes de venta antes de ser cancelados por el cobro real |
| **Asiento** | Registro contable balanceado (debe = haber) que se carga al ERP |
| **Cliente genérico** | Socio de negocio comodín (C00000000) para registrar extornos sin imputarlos a un cliente real |
| **Glosa** | Texto descriptivo del asiento (ej. "INGRESOS MASTERCARD 01-09") |
| **Extorno** | Reversa de una transacción de venta (devolución, anulación) |
| **SAP B1** | SAP Business One, el ERP donde se cargan los asientos |
