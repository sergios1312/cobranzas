"""Tests de utilidades compartidas de los loaders."""
from src.loaders._comun import texto_id


def test_texto_id_quita_punto_cero_de_float():
    """pandas lee el nro de operación como float; texto_id quita el '.0'."""
    assert texto_id(8224818.0) == "8224818"


def test_texto_id_quita_punto_cero_de_string():
    assert texto_id("8224818.0") == "8224818"


def test_texto_id_respeta_identificadores_normales():
    assert texto_id("04013819") == "04013819"   # conserva el cero a la izquierda
    assert texto_id("8224818") == "8224818"
    assert texto_id("ABC-123") == "ABC-123"


def test_texto_id_celda_vacia_devuelve_cadena_vacia():
    assert texto_id(None) == ""
    assert texto_id(float("nan")) == ""
    assert texto_id("") == ""
