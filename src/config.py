"""Carga de configuración desde archivos YAML."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from .modelos import MedioPago, Tienda


@dataclass
class Banco:
    codigo_socio_sap: str
    cuenta_corriente: str
    nombre_largo: str


# Filtros bancarios indexados por (banco, medio_pago) → patron a buscar en
# la columna Descripcion/Concepto del extracto.
FiltroPorBancoMedio = dict[str, dict[MedioPago, str]]


@dataclass
class ProveedorComision:
    codigo_socio: str
    nombre: str
    cuenta_asociada: str


@dataclass
class ConfiguracionCuentas:
    cuentas_puente: dict[MedioPago, str]
    nombres_cuenta_puente: dict[MedioPago, str]
    bancos: dict[str, Banco]
    filtros_bancos: FiltroPorBancoMedio
    cliente_generico_codigo: str
    cliente_generico_nombre: str
    cliente_generico_cuenta_asociada: str
    proveedores_comision: dict[MedioPago, ProveedorComision]
    tolerancia_conciliacion: Decimal


def _parse_filtros(raw: dict[str, Any]) -> FiltroPorBancoMedio:
    """Parsea el YAML 'filtros_bancos' a un dict[banco_str, dict[MedioPago, str]]."""
    result: FiltroPorBancoMedio = {}
    for banco, medios in (raw or {}).items():
        if not isinstance(medios, dict):
            continue
        # Formato anterior {medio: {patron: '...'}} no se soporta; debe ser plano
        # {banco: {MEDIO: 'patron'}}.
        result[banco] = {MedioPago(k): str(v) for k, v in medios.items()}
    return result


def cargar_cuentas(path: str | Path) -> ConfiguracionCuentas:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return ConfiguracionCuentas(
        cuentas_puente={
            MedioPago(k): v for k, v in raw["cuentas_puente"].items()
        },
        nombres_cuenta_puente={
            MedioPago(k): v for k, v in raw["nombres_cuenta_puente"].items()
        },
        bancos={
            nombre: Banco(
                codigo_socio_sap=cfg["codigo_socio_sap"],
                cuenta_corriente=cfg["cuenta_corriente"],
                nombre_largo=cfg["nombre_largo"],
            )
            for nombre, cfg in raw["bancos"].items()
        },
        filtros_bancos=_parse_filtros(raw.get("filtros_bancos", {})),
        cliente_generico_codigo=raw["cliente_generico"]["codigo_socio"],
        cliente_generico_nombre=raw["cliente_generico"]["nombre"],
        cliente_generico_cuenta_asociada=raw["cliente_generico"]["cuenta_asociada"],
        proveedores_comision={
            MedioPago(k): ProveedorComision(
                codigo_socio=v["codigo_socio"],
                nombre=v["nombre"],
                cuenta_asociada=v["cuenta_asociada"],
            )
            for k, v in raw["proveedores_comision"].items()
        },
        tolerancia_conciliacion=Decimal(str(raw["tolerancia_conciliacion"])),
    )


def cargar_tiendas(path: str | Path) -> list[Tienda]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [Tienda(**t) for t in raw["tiendas"]]
