# -*- mode: python ; coding: utf-8 -*-
# Lulen 单文件打包配置:python -m PyInstaller --noconfirm Lulen.spec
# 产物:dist/Lulen.exe
#
# conda/Miniforge 构建的 Python,_ctypes(_ffi)与 zlib 等运行库位于
# Library\bin,PyInstaller 的依赖分析收不全,这里显式收编。
import glob
import os
import sys

ENV_ROOT = os.path.dirname(sys.executable)   # 构建用的解释器 = Lulen 环境
binaries = []
for pattern in ('ffi-*.dll', 'libffi-*.dll', 'zlib*.dll', 'vcruntime140*.dll'):
    for dll in glob.glob(os.path.join(ENV_ROOT, 'Library', 'bin', pattern)):
        binaries.append((dll, '.'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'pydoc_data'],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Lulen',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/lulen.ico',
)
