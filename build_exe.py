"""Compila el ejecutable de la GUI de conciliacion de ventas.

Uso:
    py build_exe.py

Genera:
    dist/ConciliadorVentas.exe   <- ejecutable final (un solo archivo)
    build/                       <- intermedios (se puede borrar)
    ConciliadorVentas.spec       <- receta generada por PyInstaller

Los catalogos config/cuentas.yaml y config/tiendas.yaml se embeben dentro del
.exe; el codigo los lee via conciliar_ventas.resource_path().
"""

from __future__ import annotations

import os
from pathlib import Path

import PyInstaller.__main__

RAIZ = Path(__file__).parent
SEP = os.pathsep  # ';' en Windows, ':' en Unix


def main():
    cuentas = RAIZ / "config" / "cuentas.yaml"
    tiendas = RAIZ / "config" / "tiendas.yaml"

    for archivo in (cuentas, tiendas):
        if not archivo.exists():
            raise FileNotFoundError(
                f"Falta {archivo}. Genera config/tiendas.yaml antes de compilar."
            )

    args = [
        str(RAIZ / "conciliar_gui.py"),
        "--onefile",
        "--windowed",
        "--name", "ConciliadorVentas",
        "--add-data", f"{cuentas}{SEP}config",
        "--add-data", f"{tiendas}{SEP}config",
        "--collect-submodules", "pandas",
        "--noconfirm",
        "--clean",
    ]
    # Las fuentes IBM Plex son opcionales: si la carpeta `fonts/` con los .ttf
    # esta presente, se empaqueta dentro del .exe para que el look sea el mismo
    # en cualquier PC; si no, Qt cae a la fuente del sistema.
    fonts = RAIZ / "fonts"
    if fonts.exists() and any(fonts.iterdir()):
        args[6:6] = ["--add-data", f"{fonts}{SEP}fonts"]

    PyInstaller.__main__.run(args)

    exe = RAIZ / "dist" / "ConciliadorVentas.exe"
    if exe.exists():
        print(f"\n[ok] Ejecutable generado: {exe}  ({exe.stat().st_size / 1e6:.0f} MB)")
    else:
        print("\n[!] El build termino pero no se encontro el .exe esperado.")


if __name__ == "__main__":
    main()
