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
    # 软件完全离线:排除网络模块及其依赖的 DLL(select/_socket/_ssl/libssl/libcrypto)。
    # Windows 运行路径没有任何代码会导入它们(subprocess 对 selectors 的引用仅在 POSIX 分支)。
    excludes=['tkinter', 'unittest', 'pydoc_data',
              'socket', 'select', 'selectors', 'ssl', '_ssl', '_socket'],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

# 完全离线:丢弃 Qt 网络栈(TLS 插件/Qt6Network)及其顺 PATH 搜进来的 OpenSSL DLL
# (会误收 Git mingw64 的 libssl/libcrypto),纯本地启动路径永远不会加载它们。
_DROP = ('qt6network', 'plugins\\tls\\', 'plugins/tls/', 'libssl-', 'libcrypto-')
a.binaries = [b for b in a.binaries
              if not any(d in b[0].lower() or d in b[1].lower() for d in _DROP)]

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
