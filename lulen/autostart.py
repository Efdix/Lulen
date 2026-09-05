"""开机自启:写 HKCU Run 注册表项。

命令行:exe 打包版指向 ``"<exe路径>" --hidden``;源码运行指向 pythonw + main.py --hidden。
启动时由 :func:`sync` 按 config 开关自愈——exe 被移动后注册表指向的旧路径会被重写为当前
exe,记录被外部清理也会补回;``LULEN_HOME``(测试/便携)不触碰注册表。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import winreg
except ImportError:  # 非 Windows 环境占位
    winreg = None

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Lulen"


def _command() -> str:
    if getattr(sys, "frozen", False):  # PyInstaller 单文件:自启动直接指向 exe
        return f'"{Path(sys.executable).resolve()}" --hidden'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = exe
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{pythonw}" "{main_py}" --hidden'


def is_enabled() -> bool:
    return _query() is not None


def _query() -> str | None:
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return str(value)
    except OSError:
        return None


def set_enabled(on: bool) -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if on:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def sync(enabled: bool) -> str | None:
    """启动自愈:按 config 里的开关校正注册表项,返回动作("rewritten"/"cleared")或 None。

    exe 被移动后注册表仍指向旧路径,或记录被外部清理,这里以当前运行环境为准重写;
    ``LULEN_HOME``(测试/便携)不动注册表。"""
    if winreg is None or os.environ.get("LULEN_HOME"):
        return None
    current = _query()
    if enabled:
        if current != _command():
            return "rewritten" if set_enabled(True) else None
        return None
    if current is not None:
        set_enabled(False)
        return "cleared"
    return None
