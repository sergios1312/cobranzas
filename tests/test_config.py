"""Tests de la validacion de codigos contables (src/config.py)."""
from src.config import Banco, ProveedorComision, es_placeholder
from src.modelos import MedioPago


def test_es_placeholder_detecta_marcadores():
    """XXX, PENDIENTE, vacio y None se reconocen como placeholders."""
    assert es_placeholder("104XXX")
    assert es_placeholder("PXXXXXXXXXXXX")
    assert es_placeholder("PENDIENTE")
    assert es_placeholder("")
    assert es_placeholder(None)


def test_es_placeholder_acepta_codigos_reales():
    """Un codigo contable real no se marca como placeholder."""
    assert not es_placeholder("104107")
    assert not es_placeholder("P20432405525")
    assert not es_placeholder("421201")


def test_placeholders_pendientes_lista_vacia_si_completa(cuentas):
    """La configuracion del fixture esta completa: sin pendientes."""
    assert cuentas.placeholders_pendientes() == []


def test_placeholders_pendientes_detecta_codigos_incompletos(cuentas):
    """Detecta un banco y un proveedor con codigos placeholder."""
    cuentas.bancos["BBVA"] = Banco("104XXX", "x", "BANCO BBVA")
    cuentas.proveedores_comision[MedioPago.AMEX] = ProveedorComision(
        "PXXXXXXXXXXXX", "PENDIENTE", "421XXX")
    pendientes = cuentas.placeholders_pendientes()
    assert any("BBVA" in p for p in pendientes)
    assert any("AMEX" in p for p in pendientes)
