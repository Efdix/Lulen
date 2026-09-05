"""Windows 快捷方式(.lnk)解析:取出真实目标路径/参数/起始位置(纯 ctypes,无新依赖)。

拖入快捷方式时解析目标,条目存真实路径而不是 .lnk,桌面快捷方式被删后条目仍然有效。
"""
from __future__ import annotations

import ctypes
from ctypes import byref, c_int, c_ulong, c_void_p, c_wchar_p, cast, pointer
from dataclasses import dataclass
from pathlib import Path


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text: str) -> None:
        super().__init__()
        import uuid
        raw = uuid.UUID(text).bytes_le  # 前三段本就是小端存储
        self.Data1 = int.from_bytes(raw[0:4], "little")
        self.Data2 = int.from_bytes(raw[4:6], "little")
        self.Data3 = int.from_bytes(raw[6:8], "little")
        self.Data4 = (ctypes.c_ubyte * 8)(*raw[8:16])


CLSID_SHELL_LINK = _GUID("{00021401-0000-0000-C000-000000000046}")
IID_ISHELL_LINKW = _GUID("{000214F9-0000-0000-C000-000000000046}")
IID_IPERSIST_FILE = _GUID("{0000010B-0000-0000-C000-000000000046}")
STGM_READ = 0
BUF = 1024


@dataclass
class LnkInfo:
    path: str
    args: str
    workdir: str


class _FindDataW(ctypes.Structure):
    # WIN32_FIND_DATAW 的布局;FILETIME 用 8 字节整数占位即可
    _fields_ = [
        ("dwFileAttributes", c_ulong),
        ("ftCreationTime", ctypes.c_ulonglong),
        ("ftLastAccessTime", ctypes.c_ulonglong),
        ("ftLastWriteTime", ctypes.c_ulonglong),
        ("nFileSizeHigh", c_ulong),
        ("nFileSizeLow", c_ulong),
        ("dwReserved0", c_ulong),
        ("dwReserved1", c_ulong),
        ("cFileName", ctypes.c_wchar * 260),
        ("cAlternateFileName", ctypes.c_wchar * 14),
    ]


def _vtbl_method(obj: c_void_p, index: int, restype, *atypes):
    """取 COM 对象 vtable 第 index 个方法(IUnknown 占 0-2)。"""
    vtbl = cast(cast(obj, ctypes.POINTER(c_void_p)).contents, ctypes.POINTER(c_void_p * 32)).contents
    proto = ctypes.WINFUNCTYPE(restype, c_void_p, *atypes)
    return cast(vtbl[index], proto)


def resolve_lnk(lnk: str) -> LnkInfo | None:
    """解析 .lnk;失败(非 COM 环境/损坏/特殊快捷方式)返回 None。"""
    coinited = False
    try:
        pv = c_void_p()
        hr = ctypes.windll.ole32.CoInitialize(None)
        if hr in (0, 1):  # S_OK / S_FALSE
            coinited = True
        hr = ctypes.windll.ole32.CoCreateInstance(
            byref(CLSID_SHELL_LINK), None, 1, byref(IID_ISHELL_LINKW), byref(pv))
        if hr != 0 or not pv:
            return None
        # 同一对象上 QueryInterface 拿 IPersistFile(此前误建两个实例导致 Load/GetPath 落在不同对象)
        ppf = c_void_p()
        qi = _vtbl_method(pv, 0, ctypes.HRESULT, ctypes.POINTER(_GUID), ctypes.POINTER(c_void_p))
        if qi(pv, byref(IID_IPERSIST_FILE), byref(ppf)) != 0 or not ppf:
            return None
        load = _vtbl_method(ppf, 5, ctypes.HRESULT, c_wchar_p, c_ulong)  # IPersistFile::Load
        if load(ppf, str(Path(lnk).absolute()), STGM_READ) != 0:
            return None
        get_path = _vtbl_method(pv, 3, ctypes.HRESULT, c_wchar_p, c_int,
                                ctypes.POINTER(_FindDataW), c_ulong)
        get_args = _vtbl_method(pv, 12, ctypes.HRESULT, c_wchar_p, c_int)  # IShellLinkW::GetArguments
        get_workdir = _vtbl_method(pv, 10, ctypes.HRESULT, c_wchar_p, c_int)  # ::GetWorkingDirectory
        buf = ctypes.create_unicode_buffer(BUF)
        fd = _FindDataW()
        if get_path(pv, buf, BUF, pointer(fd), 0) != 0:  # S_FALSE = 无文件系统路径
            return None
        target = buf.value
        args = ctypes.create_unicode_buffer(BUF)
        get_args(pv, args, BUF)
        workdir = ctypes.create_unicode_buffer(BUF)
        get_workdir(pv, workdir, BUF)
        return LnkInfo(target, args.value, workdir.value)
    except Exception:
        return None
    finally:
        if coinited:
            try:
                ctypes.windll.ole32.CoUninitialize()
            except Exception:
                pass
