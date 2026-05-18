# Estado del Proyecto — Cobranzas Tiendas Físicas

> Documento de seguimiento. Resume todo lo hecho, lo pendiente y los puntos
> abiertos del proyecto de automatización de la conciliación de cobranzas.
>
> **Última actualización:** 2026-05-15
> **Modo de trabajo:** DEMO / MVP — funcionar con la muestra del PDF
> (`Muestra al 30.04/`), no con todos los casos de producción.

---

## 1. Resumen ejecutivo

El proyecto automatiza la conciliación contable de ventas en tiendas físicas:
cruza el *Cierre Caja Resumen* de SAP contra los reportes de las pasarelas de
pago (Izipay MC/AMEX, Diners), concilia los depósitos contra los extractos
bancarios y genera asientos contables para SAP Business One.

**Estado global:** pipeline funcional end-to-end contra la muestra de abril
2026. Se reproduce el ejemplo del PDF (tienda Schell) al céntimo.

| Indicador | Valor |
|---|---|
| Tiendas en el catálogo | 81 |
| Pipeline completo (`main.py`) | 58 asientos balanceados + 76 reportes |
| Conciliaciones omitidas (bancos sin loader) | 22 (Scotiabank 20, Pichincha 2) |
| Script de conciliación de ventas (`conciliar_ventas.py`) | 73 tiendas, 819 discrepancias detectadas |
| Ejecutable de escritorio | `dist/ConciliadorVentas.exe` (≈49 MB) |
| Asientos que NO balancean | 0 |
| Asientos con anomalía (DEBE negativo) | 1 (MIS.PI01 MC) |

---

## 2. Qué hace el sistema hoy

El proyecto tiene **tres formas de uso**, todas funcionales:

### 2.1 Pipeline completo — `main.py`
Ejecuta los 5 pasos del PDF: carga archivos crudos → consolida → concilia
ventas → concilia depósitos contra bancos → genera asientos contables.
Produce en `salidas/`:
- `reporte_<tienda>_<periodo>.xlsx` — Excel multi-hoja de conciliación.
- `asiento_<tienda>_<medio>_<periodo>.xlsx` — asiento para SAP B1.

### 2.2 Script de conciliación de ventas — `conciliar_ventas.py`
Solo los pasos 2 y 3 del PDF (consolidar MC/AMEX/Diners y cotejar contra el
Cierre SAP). NO toca bancos ni genera asientos. Produce
`conciliacion_ventas_<periodo>.xlsx` con 3 hojas (Resumen, Detalle,
Discrepancias). Pensado como demo de conciliación de ventas.

### 2.3 Ejecutable de escritorio — `ConciliadorVentas.exe`
Interfaz gráfica (ventana) sobre el script anterior. El usuario selecciona los
5 archivos crudos con botones, presiona Procesar y obtiene el Excel. Los
catálogos van embebidos en el .exe. No requiere Python instalado.

---

## 3. Lo que se ha completado

### 3.1 Configuración y catálogos

| Archivo | Estado | Detalle |
|---|---|---|
| `config/tiendas.yaml` | ✅ Generado | 81 tiendas desde `TIENDAS GENERAL QTC.xlsx`. Bancos normalizados: `INTER`/`IBK`/`INTK` → `INTERBANK`, `SCTK` → `SCOTIABANK`. Campos por tienda: `banco_mc`, `banco_amex`, `banco_diners`, `banco_efectivo`, `banco_visa_puntos`, códigos de comercio, encargado |
| `config/tiendas.example.yaml` | ✅ Actualizado | 4 ejemplos sanitizados (típica, MC/AMEX en bancos distintos, PENDIENTE, sin POS) |
| `config/cuentas.yaml` | 🟡 Parcial | Cuentas puente OK. Bancos con `cuenta_corriente` + `nombre_largo`. `filtros_bancos` por (banco, medio). **7 placeholders pendientes — ver §5.1** |

### 3.2 Modelo de datos — `src/modelos.py`

✅ Validado contra datos reales. Cambios respecto al diseño original:
- `Tienda`: separó `banco_mc_amex` en `banco_mc` y `banco_amex` (una tienda
  puede acreditar MC y AMEX en bancos distintos — confirmado: 12 tiendas).
  Campos opcionales, property `prefijo_descripcion_mc` derivada, método
  `banco_para(medio)`.
- `PagoDiners`: se eliminó el campo `pago_efectivo` (estaba mal nombrado: la
  columna del Excel es una fecha, no un importe). Se agregaron `orden_pago` e
  `importe_total_consumos` (para detectar pagos multi-período).
- `TransaccionMedioPago`: se agregó `orden_pago` (solo aplica a Diners).
- `MatchDeposito`: cambió de 1 movimiento a una **lista** de movimientos.

### 3.3 Carga de configuración — `src/config.py`

✅ Validado. `Banco` con `codigo_socio_sap`, `cuenta_corriente`,
`nombre_largo`. `FiltroPorBancoMedio` = dict indexado por (banco, medio).

### 3.4 Loaders — `src/loaders/`

| Loader | Estado | Notas de validación |
|---|---|---|
| `cierre_caja.py` | ✅ Validado | 6,060 líneas del Cierre SAP. Ignora los 15 medios fuera de v1 (RAPPI, NOTA CREDITO, etc.) |
| `izipay.py` | ✅ Validado | MC (25,187 txn) + AMEX (829 txn). Separador `;`, encoding UTF-8, extorno detectado por columna `Status`, fechas en dos formatos (DD/MM/YYYY string y YYYYMMDD numérico) |
| `diners.py` | ✅ Validado | Ventas (345) + Pagos (274). `fecha_proceso` se toma de `Fecha de ticket` (alinea con el cierre SAP). Carga `orden_pago` e `importe_total_consumos` |
| `interbank.py` | ✅ Validado | 2,032 movs. Detección dinámica de cabecera (fila 4). Fechas europeas DD/MM/YYYY |
| `bbva.py` | ✅ Validado | 5,264 movs. Importe único con signo → se parte en abono/cargo |
| `bcp.py` | ✅ Validado | 2,686 movs. Hoja `BCP 94`, estructura tipo BBVA |
| Scotiabank | 🔴 No existe | Falta archivo de muestra — ver §5.2 |
| Pichincha | 🔴 No existe | Falta archivo de muestra — ver §5.2 |

### 3.5 Conciliación — `src/conciliacion/`

| Módulo | Estado | Notas |
|---|---|---|
| `ventas.py` | ✅ Validado | Reproduce las 6 diferencias MC del PDF y las 7 AMEX al céntimo |
| `depositos.py` | ✅ Validado | Matching universal **1-a-1** por (fecha, importe). Filtro de pagos Diners multi-período por `importe_total_consumos`. Filtros bancarios por (banco, medio) |

### 3.6 Generación de asiento — `src/asiento/generador.py`

✅ Validado. Reproduce el ejemplo del PDF (Schell MC período 01-09): HABER de
la cuenta puente = **168,769.84** exacto. Estructura: HABER cuenta puente +
DEBE banco × N movimientos individuales + DEBE cliente genérico (extornos) +
DEBE proveedor comisión (residuo).

### 3.7 Exporters — `src/exporters/`

| Exporter | Estado | Notas |
|---|---|---|
| `reporte_tienda.py` | ✅ Validado | 8 hojas: CIERRE, MASTERCARD, MC_RESUMEN, AMEX, AMEX_RESUMEN, DINERS, Diners Pagos, Bancos |
| `sap_b1.py` | 🟡 Tentativo | Formato basado en la pantalla del PDF (Cabecera + Líneas). **Falta validar contra una plantilla oficial de "Importar de Excel" de SAP B1** |

### 3.8 Orquestador — `main.py`

✅ Validado. Descubre archivos por glob, carga los 3 bancos en un dict,
procesa las 81 tiendas, reporta tiendas omitidas por banco sin loader.

### 3.9 Script standalone y ejecutable

| Archivo | Estado | Descripción |
|---|---|---|
| `conciliar_ventas.py` | ✅ Validado | CLI de los pasos 2-3. Funciones reutilizables (`cargar_inputs_archivos`, `procesar`, `resource_path`) |
| `conciliar_gui.py` | ✅ Funcional | GUI tkinter. Pendiente prueba interactiva final del usuario |
| `build_exe.py` | ✅ Validado | Script de compilación con PyInstaller |
| `dist/ConciliadorVentas.exe` | ✅ Compilado | Ejecutable ≈49 MB. Arranca sin error; catálogos embebidos verificados en el `.spec` |

### 3.10 Documentación actualizada

`BLUEPRINT.md` §7, `CLAUDE.md` y `README.md` reflejan el estado MVP actual.

---

## 4. Validaciones realizadas

- **Schell vs PDF:** la conciliación de ventas reproduce las 6 diferencias MC
  citadas/implícitas del PDF (incluido el +586 del 06/04). El asiento MC
  período 01-09 balancea en 168,769.84, igual que el PDF.
- **Schell generado vs manual** (`CIERRE TIENDA SCHELL 04-26.xlsx`): los
  importes MC del cierre cuadran al céntimo en los 30 días.
- **Chequeo masivo:** 58/58 asientos del pipeline balancean. 76/76 reportes
  con todas las hojas esperadas.
- **Hallazgo automático — cross-ups MC↔AMEX:** el sistema detecta solo el
  patrón donde una venta AMEX se digitó como MC (o viceversa). Ejemplos:
  DJI.JP (+34,599 MC / −31,300 AMEX), DJI.SM (+7,061 / −6,872),
  Schell (+586 / −586 el 06/04).

---

## 5. Lo que falta — pendientes

### 5.1 BLOQUEANTES para producción

**P1 — Códigos contables en `config/cuentas.yaml` (7 placeholders).**
Sin estos, los asientos salen con códigos `XXX` y NO se pueden importar a SAP:
- `codigo_socio_sap` de **BBVA** (hoy `104XXX`)
- `codigo_socio_sap` de **BCP** (hoy `104XXX`)
- `codigo_socio_sap` de **SCOTIABANK** (hoy `104XXX`)
- `codigo_socio_sap` de **PICHINCHA** (hoy `104XXX`)
- Proveedor comisión **AMEX**: `codigo_socio` + `nombre` + `cuenta_asociada`
  (hoy `PXXXXXXXXXXXX` / "PENDIENTE" / `421XXX`)
- Proveedor comisión **DINERS**: `codigo_socio` + `nombre` + `cuenta_asociada`
  (hoy `PXXXXXXXXXXXX` / "PENDIENTE" / `421XXX`)
- `cuenta_corriente` de **SCOTIABANK** y **PICHINCHA** (hoy `"PENDIENTE"`)

> Responsable: contabilidad. Cuando lleguen los datos son 7 ediciones de 1
> línea en `config/cuentas.yaml`.

**P2 — Plantilla oficial "Importar de Excel" de SAP B1.**
El exporter `sap_b1.py` produce un formato tentativo basado en las capturas
del PDF. Para que los asientos sean realmente importables hay que validar el
formato contra una plantilla real (un asiento ya importado a SAP sirve).

### 5.2 Funcionalidad incompleta

**P3 — Loaders de Scotiabank y Pichincha.**
20 tiendas usan Scotiabank y 2 usan Pichincha para algún medio de pago. Hoy
esas 22 conciliaciones se reportan como "omitidas". Falta:
- Conseguir un archivo de extracto real de cada banco.
- Implementar `src/loaders/scotiabank.py` y `src/loaders/pichincha.py`
  (similar a `bbva.py`/`bcp.py`).
- Agregar los patrones de filtro a `filtros_bancos` en `cuentas.yaml`.

**P4 — Tiendas con banco combinado `BCP/BBVA`.**
El catálogo tiene tiendas con la celda `BCP/BBVA` (ej. en banco efectivo). El
loader del catálogo lo guarda literal y esas no se procesan. Falta decidir
cómo resolver la ambigüedad (¿se concilia contra ambos bancos?).

**P5 — Filtro AMEX en BCP no confirmado.**
En BCP, el patrón `"DE PROCESOS DE MEDIOS"` cubre MC y AMEX juntos. El
matching 1-a-1 por importe los desambigua, pero no se validó con un caso real
de AMEX depositado en BCP (la muestra no tenía suficientes casos claros).

### 5.3 Bugs y casos residuales conocidos

**B1 — Asiento MIS.PI01 MASTERCARD con DEBE negativo (−S/1,873.32).**
Único asiento con anomalía. La línea de comisión sale negativa. No es un caso
Diners (el fix multi-período no aplica). Causa probable: un abono del banco
sin contraparte en el CSV (depósito de un período anterior). Falta debug
específico.

**B2 — 35 diferencias significativas residuales en conciliación de ventas
Diners.** Tras alinear `fecha_proceso` con `Fecha de ticket` se eliminaron
~95% de las diferencias fantasma, pero quedan 35 reales/semireales a través de
todas las tiendas. Pueden ser desfases de período o ajustes. Falta revisar
caso por caso si son discrepancias verdaderas.

**B3 — Archivos de muestra con cobertura parcial.**
El CSV de AMEX de la muestra solo cubre del 30/03 al 09/04. En los días sin
datos AMEX el sistema marca "discrepancia" porque el cierre tiene venta pero
la pasarela no. Es comportamiento esperado dado el insumo parcial, pero hay
que tenerlo presente al interpretar resultados (no es un bug del código).

**B4 — Diners Pagos puede traer depósitos de meses anteriores.**
Resuelto parcialmente con el filtro por `importe_total_consumos`. Los pagos
cuyo total no cuadra con las ventas del CSV se excluyen. Si el período de los
archivos cambia, revisar que el filtro siga siendo correcto.

### 5.4 Calidad y testing

**P6 — No hay tests automatizados (pytest).**
El `BLUEPRINT.md` §9 tiene el plan completo de tests (V01-V08 conciliación
ventas, D01-D12 depósitos, A01-A10 asiento, tests de loaders). Nada está
implementado. Para un MVP de demo no es bloqueante, pero antes de producción
es necesario (el sistema toca dinero).

**P7 — `mypy` y `ruff` no se han corrido.**
El `CLAUDE.md` pide mypy estricto sobre `src/` y ruff para lint. No se
verificó el cumplimiento tras todos los cambios.

### 5.5 Decisiones pospuestas

**D1 — Tolerancia de matching de depósitos.**
Hoy el matching es por fecha e importe exactos. Se decidió "ver más adelante"
si se necesita tolerancia de ±N días para depósitos que el banco acredita con
retraso. Pendiente de definir.

**D2 — Reporte de cross-ups MC↔AMEX como alerta explícita.**
El sistema ya detecta el patrón (montos opuestos el mismo día), pero no lo
marca con una etiqueta especial tipo "posible error de digitación". Sería un
valor agregado fácil de implementar.

---

## 6. Insumos que faltan del lado del usuario

| # | Insumo | Para qué | Responsable |
|---|---|---|---|
| 1 | Códigos socio SAP de BBVA/BCP/Scotiabank/Pichincha | Completar `cuentas.yaml` (P1) | Contabilidad |
| 2 | Proveedor comisión AMEX y Diners (socio + nombre + cuenta) | Completar `cuentas.yaml` (P1) | Contabilidad |
| 3 | Cuenta corriente de Scotiabank y Pichincha | Completar `cuentas.yaml` (P1) | Contabilidad / Tesorería |
| 4 | Plantilla "Importar de Excel" de SAP B1 | Validar `sap_b1.py` (P2) | TI / Contabilidad |
| 5 | Extracto bancario de muestra de Scotiabank | Implementar su loader (P3) | Tesorería |
| 6 | Extracto bancario de muestra de Pichincha | Implementar su loader (P3) | Tesorería |

---

## 7. Estado de Git

| Aspecto | Estado |
|---|---|
| Repositorio | `github.com/sergios1312/cobranzas` (privado) |
| Commits | 1 ("Initial commit") |
| Cambios sin commitear | `conciliar_ventas.py`, `conciliar_gui.py`, `build_exe.py`, `ConciliadorVentas.spec`, `dist/`, `.gitignore`, `resultados/`, `.claude/settings.local.json` |
| `.gitignore` | Actualizado para excluir `build/` y temporales de Excel |

> ⚠️ **Pendiente:** los commits de la GUI + ejecutable quedaron preparados pero
> no se ejecutaron (`git commit` / `git push`). Falta cerrar esa subida.
>
> ⚠️ **Nota de seguridad:** el "Initial commit" incluyó datos sensibles
> (`config/tiendas.yaml` con PII, extractos bancarios reales de
> `Muestra al 30.04/`). El repositorio es privado, así que el riesgo es
> acotado, pero conviene tenerlo presente si alguna vez se hace público.

---

## 8. Cómo ejecutar cada componente

### 8.1 Pipeline completo
```bash
py main.py --inputs "Muestra al 30.04/" --outputs ./salidas/ \
           --desde 2026-04-01 --hasta 2026-04-30
```

### 8.2 Script de conciliación de ventas
```bash
py conciliar_ventas.py --inputs "Muestra al 30.04/" --outputs ./resultados/
# Variantes:
py conciliar_ventas.py --inputs ... --outputs ... --tiendas MIS.MI01 --solo-discrepancias
py conciliar_ventas.py --inputs ... --outputs ... --desde 2026-04-01 --hasta 2026-04-09
```

### 8.3 Ejecutable de escritorio
Doble click en `dist/ConciliadorVentas.exe`, seleccionar los 5 archivos
crudos, presionar PROCESAR.

### 8.4 Recompilar el ejecutable
```bash
py build_exe.py
```

### 8.5 Setup de dependencias
```bash
pip install -r requirements.txt
# Para compilar el .exe además: pip install pyinstaller
```

---

## 9. Próximos pasos recomendados (priorizados)

1. **Cerrar la subida a Git** — commitear y pushear la GUI + ejecutable
   (quedó a medias).
2. **Probar el ejecutable** end-to-end con la muestra (prueba interactiva del
   usuario; confirmar que el resumen muestra 73 tiendas / 819 discrepancias).
3. **Conseguir los códigos contables (P1)** — desbloquea la importación real a
   SAP de los asientos.
4. **Conseguir la plantilla SAP B1 (P2)** — valida el formato del asiento.
5. **Debug del caso B1** (MIS.PI01 MC con DEBE negativo).
6. **Loaders Scotiabank y Pichincha (P3)** — cuando lleguen archivos de
   muestra; cubre 22 conciliaciones hoy omitidas.
7. **Tests del dominio (P6)** — antes de pasar de demo a producción.
8. **Validar contra un período completo** distinto a la muestra de abril.

---

## 10. Glosario rápido

| Término | Significado |
|---|---|
| Cierre Caja Resumen | Reporte de SAP con ventas por tienda × día × medio de pago |
| Pasarela | Procesador del medio de pago (Izipay para MC/AMEX, Diners) |
| Cuenta puente | Cuenta contable transitoria donde se acumulan los cobros |
| Asiento | Registro contable balanceado (debe = haber) que se carga al ERP |
| Cross-up | Venta de un medio digitada por error como otro medio en el cierre |
| Extorno | Reversa de una transacción de venta |
| Multi-período | Pago Diners que agrupa tickets de más de un mes |
| MVP | Mínimo producto viable — alcance acotado a la muestra del PDF |
