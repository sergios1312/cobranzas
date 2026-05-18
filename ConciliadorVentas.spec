# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('pandas')


a = Analysis(
    ['C:\\Users\\s_ara\\OneDrive\\Escritorio\\Proyectos\\cobranzas\\conciliar_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('C:\\Users\\s_ara\\OneDrive\\Escritorio\\Proyectos\\cobranzas\\config\\cuentas.yaml', 'config'), ('C:\\Users\\s_ara\\OneDrive\\Escritorio\\Proyectos\\cobranzas\\config\\tiendas.yaml', 'config')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ConciliadorVentas',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
