# Cobranzas Tiendas Físicas — Automatización

Pipeline de conciliación contable de ventas en tiendas físicas contra reportes
de medios de pago (Mastercard, AMEX, Diners) y extractos bancarios (Interbank,
BBVA), con generación final de archivo importable a SAP Business One.

## Arquitectura

```
  Archivos crudos          Catálogos          Plan de cuentas
  (SAP, Izipay,            (tiendas,          y proveedores
   Diners, banco)           proveedores)
        │                       │                    │
        ▼                       ▼                    ▼
  ┌─────────────────────────────────────────────────────────┐
  │              Loaders (uno por tipo de archivo)          │
  │   cierre_caja · izipay · diners · interbank · bbva      │
  └────────────────────────┬────────────────────────────────┘
                           ▼
              ┌────────────────────────────────┐
              │  Esquema canónico en memoria   │
              │         (src/modelos.py)        │
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
  │  Exporters: reporte_tienda.xlsx + asiento SAP B1.xlsx  │
  └────────────────────────────────────────────────────────┘
```

## Decisiones de diseño cerradas

| Pregunta | Respuesta |
|---|---|
| Catálogo maestro de tiendas | Existe — se carga desde `config/tiendas.yaml` |
| Match ambiguo de depósitos | Dentro del filtro por tienda, match por (fecha, importe) es válido aunque haya duplicados, siempre que el conteo total cierre |
| Formato asiento SAP | Excel para "Importar de Excel" en SAP B1 |
| Medios de pago en scope | Mastercard, AMEX, Diners (los tres en paralelo) |

## Estado actual

**MVP funcional end-to-end** contra la muestra `Muestra al 30.04/`:
58 asientos balanceados, 76 reportes, 22 omitidos (bancos sin loader).
Reproduce el ejemplo Schell del PDF al céntimo (HABER 168,769.84).

| Pieza | Estado |
|---|---|
| Esquema canónico (`modelos.py`) | ✅ Validado |
| Conciliación de ventas + depósitos | ✅ Validado |
| Generador de asiento | ✅ Validado |
| Loaders (6: cierre, izipay, diners, interbank, bbva, bcp) | ✅ Validados |
| Exporter reporte por tienda | ✅ Validado |
| Exporter SAP B1 | 🟡 Tentativo (validar plantilla real) |
| Orquestador `main.py` | ✅ Validado |
| `config/tiendas.yaml` | ✅ 81 tiendas desde catálogo Excel |
| `config/cuentas.yaml` | 🟡 7 placeholders pendientes |
| Tests | 🔴 No implementados |
| Loaders Scotiabank, Pichincha | 🔴 Sin muestras |

## Pendientes para producción

1. **Códigos contables** en `cuentas.yaml` (7 placeholders):
   - Socio SAP de BBVA, BCP, SCOTIABANK, PICHINCHA (hoy `104XXX`)
   - Proveedor comisión AMEX y Diners: socio + nombre + cuenta asociada
2. **Plantilla "Importar de Excel"** de SAP B1 oficial para validar el formato del exporter.
3. **Archivos de muestra** de extractos Scotiabank y Pichincha (para implementar sus loaders).
4. **1 caso residual**: asiento MIS.PI01 MC tiene DEBE negativo (S/−1,873) por motivos no identificados aún.

## Setup

```bash
pip install -r requirements.txt
```

## Uso

```bash
# Estructura esperada en --inputs:
#   Reporte SAP/CIERRE DE TIENDAS.xlsx
#   Reportes CSV/mc_*.csv
#   Reportes CSV/movi_amex*.csv
#   Reportes CSV/ventas-*.xlsx     (Diners ventas)
#   Reportes CSV/pagos-*.xlsx      (Diners pagos)
#   Extractos bancarios/*.xlsx     (libro consolidado con hojas BBVA, BCP 94, INTERBANK)

python main.py \
  --inputs "Muestra al 30.04/" \
  --outputs ./salidas/ \
  --desde 2026-04-01 --hasta 2026-04-30
```

Filtrar a una o varias tiendas específicas:

```bash
python main.py --inputs ... --outputs ... --desde ... --hasta ... \
               --tiendas MIS.MI01,MIS.SA01
```

Genera en `./salidas/`:
- `reporte_<id_tienda>_<periodo>.xlsx` — Excel multi-hoja (8 hojas: CIERRE,
  MASTERCARD, MC_RESUMEN, AMEX, AMEX_RESUMEN, DINERS, Diners Pagos, Bancos)
- `asiento_<id_tienda>_<medio>_<periodo>.xlsx` — formato tentativo SAP B1
  (Cabecera + Líneas)
