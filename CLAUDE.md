# CLAUDE.md

Este archivo es el contexto que Claude Code lee al inicio de cada sesión.
**No reemplaza `BLUEPRINT.md`** — para profundidad técnica leer ese primero.

---

## Qué es este proyecto

Pipeline Python que automatiza la conciliación contable de ventas en tiendas
físicas contra reportes de medios de pago (Mastercard, AMEX, Diners) y
extractos bancarios (Interbank, BBVA), y genera asientos para SAP Business One.

Flujo: **archivos crudos → loaders → modelo canónico → conciliación →
generador de asiento → exporters → Excel para SAP B1**.

Ver `BLUEPRINT.md` para arquitectura completa, modelo de datos, reglas de
negocio e invariantes.

---

## Stack y comandos

- **Python 3.11+**, sin frameworks pesados. Dependencias: `pandas`, `openpyxl`,
  `PyYAML`, `xlrd`.
- **pytest** para tests, **mypy** y **ruff** sobre `src/` (ambos configurados
  en `pyproject.toml`). Dependencias de desarrollo en `requirements-dev.txt`.

Comandos frecuentes:

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Tests
pytest                            # todos
pytest -k <expr>                  # filtrar por nombre
pytest --cov=src                  # con cobertura

# Lint / type-check
ruff check src/ tests/
mypy src/

# Ejecutar pipeline
python main.py --inputs ./entradas --outputs ./salidas \
               --desde 2026-04-01 --hasta 2026-04-09
```

---

## Convenciones del proyecto

### Numéricas
- **Todos los importes son `Decimal`**, nunca `float`. Si ves `float` en una
  comparación de dinero, es un bug.
- Comparaciones de igualdad de Decimal contra `Decimal("0")` o con tolerancia
  explícita. Nunca `math.isclose`.

### Modelado
- La capa de dominio (conciliación, asiento) **solo conoce los tipos de
  `src/modelos.py`**. No debe importar `pandas` ni leer archivos.
- Los loaders son los únicos que tocan `pandas.read_*` y formatos crudos.
- Nuevos medios de pago o bancos = nuevo loader + entrada en enum + entrada en
  config. No tocar la lógica de conciliación.

### Configuración
- `config/tiendas.yaml` **NO se versiona** (PII comercial). Solo
  `tiendas.example.yaml`.
- `config/cuentas.yaml` se versiona pero tiene placeholders `XXX` para códigos
  pendientes. El pipeline debe fallar temprano si encuentra placeholders.

### Errores vs warnings
- **Excepción** = el pipeline se detiene. Ej.: archivo no encontrado, columna
  obligatoria faltante.
- **Warning** = el pipeline continúa. Ej.: diferencia significativa en
  conciliación, asiento no balancea, depósito no emparejado, código contable
  pendiente (`XXX`/`PENDIENTE`) — se omite ese asiento y no se exporta basura.

### Estructura de tests
- `tests/conftest.py` — fixtures y factories en memoria que construyen las
  dataclasses del dominio, sin tocar archivos.
- `tests/test_*.py` — tests unitarios del dominio; cada regla de negocio del
  §5 del BLUEPRINT tiene un test que la cita por nombre.
- `tests/test_e2e_muestra.py` — test end-to-end contra `Muestra al 30.04/`.

---

## Estado actual (snapshot)

**Pipeline end-to-end funcional** (pasos 2-5 del proceso) contra la muestra
`Muestra al 30.04/`, ejecutable desde la CLI (`main.py`) o la GUI
(`conciliar_gui.py`). La lógica vive en `src/pipeline.py`, compartida por
ambos frontends. El asiento Schell MC 01-09 reproduce el HABER 168,769.84
exacto del PDF (cubierto por un test e2e).

✅ Validado contra datos reales y cubierto por tests (39 tests `pytest` en
verde; `mypy` y `ruff` limpios): `modelos.py`, `config.py`,
`conciliacion/ventas.py`, `conciliacion/depositos.py`, `asiento/generador.py`,
`pipeline.py`, los 6 loaders, ambos exporters, `main.py`.

🟡 Pendiente de insumos del usuario (no bloquean el desarrollo):
- 8 placeholders en `config/cuentas.yaml`: socio SAP de BBVA/BCP/SCOTIABANK/
  PICHINCHA + proveedor comisión (socio y cuenta) de AMEX/Diners. El pipeline
  los detecta y omite esos asientos con un mensaje claro en vez de exportar
  códigos basura; los generará todos en cuanto se completen.
- `exporters/sap_b1.py`: formato tentativo basado en las capturas del PDF —
  validar contra una plantilla "Importar de Excel" real de SAP B1.

🔴 No implementado (sin datos de muestra):
- Loaders Scotiabank y Pichincha — el libro de bancos no trae esas hojas;
  22 conciliaciones quedan reportadas como omitidas.

Modo de trabajo: **DEMO/MVP** — funcionar con la muestra del PDF, no con
todos los casos de producción. Las decisiones de scope reflejan eso.

Roadmap detallado en `BLUEPRINT.md` §7-8.

---

## Cómo trabajar conmigo (Claude Code)

1. **Antes de tocar código de dominio**, leer `BLUEPRINT.md` §5 (reglas de
   negocio) y §9 (testing).
2. **Si vas a modificar una regla de negocio**, primero actualiza el test que
   la verifica; si no existe, créalo; luego modifica la lógica. Nunca al revés.
3. **Si vas a tocar un loader**, asegúrate de tener el archivo de muestra real
   en `Muestra al 30.04/`. Si no lo tienes, pregunta antes de asumir columnas.
4. **No introduzcas dependencias nuevas** sin confirmar. Pandas + openpyxl +
   PyYAML + xlrd debería bastar para todo.
5. **No silencies warnings.** Si un test genera un `RuntimeWarning` o
   `DeprecationWarning`, repórtalo. Estamos en territorio contable.
6. **Commits pequeños y temáticos.** Idealmente: 1 commit = 1 fase del roadmap
   o 1 regla de negocio + su test.

---

## Anti-patrones a evitar

- ❌ Usar `float` para importes.
- ❌ Hacer comparaciones de Decimal con `==` después de operaciones (usar
  tolerancia explícita).
- ❌ Hardcodear cuentas contables en el código; deben venir de `cuentas.yaml`.
- ❌ Acoplar la lógica de conciliación a un formato Excel específico.
- ❌ Tests que dependen del orden del filesystem o del clock.
- ❌ Capturar `Exception` sin re-lanzar o loguear.
- ❌ Suprimir advertencias de pandas con `warnings.filterwarnings("ignore")`.
- ❌ Generar un asiento que no balancea y exportarlo igual.

---

## Referencias rápidas

- Arquitectura, decisiones, reglas: `BLUEPRINT.md`
- Quickstart usuario final: `README.md`
- Modelos canónicos: `src/modelos.py`
- Plan de cuentas: `config/cuentas.yaml`
- Catálogo de tiendas: `config/tiendas.yaml` (no versionado) / `tiendas.example.yaml`
