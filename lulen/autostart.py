"""开机自启:写 HKCU Run 注册表项,指向 pythonw + main.py --hidden。"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import winreg
except ImportError:  # 非 Windows 环境占位
    winreg = None

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Lulen"


def _command() -> str:
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
