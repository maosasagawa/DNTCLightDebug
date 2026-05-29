# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['supplier_debug_tool/__main__.py'],
    pathex=[],
    binaries=[('drivers/CH347DLLA64.DLL', '.')],
    datas=[('drivers/CH347DLL_EN.H', 'drivers')],
    hiddenimports=[
        'serial',
        'serial.tools.list_ports',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='DNTCLightDebug',
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
