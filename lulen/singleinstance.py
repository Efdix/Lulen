"""单实例:命名互斥体保证唯一,命名事件把 "show" 转给首个进程后退出。

名字按配置目录区分:默认安装只有一份配置 → 全机单实例;
LULEN_HOME 隔离的测试实例互不干扰,也不与正式实例冲突。
内核对象随最后一个句柄的关闭自动销毁,崩溃残留无需手工清理。
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import threading
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal

_ERROR_ALREADY_EXISTS = 0x00B7
_EVENT_MODIFY_STATE = 0x0002
_INFINITE = 0xFFFFFFFF

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_k32.CreateMutexW.restype = wintypes.HANDLE
_k32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_k32.CreateEventW.restype = wintypes.HANDLE
_k32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_k32.OpenEventW.restype = wintypes.HANDLE
_k32.SetEvent.argtypes = [wintypes.HANDLE]
_k32.SetEvent.restype = wintypes.BOOL
_k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.WaitForSingleObject.restype = wintypes.DWORD
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.CloseHandle.restype = wintypes.BOOL


def _names() -> tuple[str, str]:
    home = os.environ.get("LULEN_HOME")
    if home:
        tag = hashlib.md5(home.encode("utf-8")).hexdigest()[:8]
        return f"Local\\Lulen-single-{tag}-v2", f"Local\\Lulen-show-{tag}-v2"
    return "Local\\Lulen-single-v2", "Local\\Lulen-show-v2"


class SingleInstance(QObject):
    another_show = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.is_primary = True
        mutex_name, event_name = _names()

        self._mutex_handle = _k32.CreateMutexW(None, False, mutex_name)
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            # 已有实例:置事件让它呼出面板,自身退出
            event = _k32.OpenEventW(_EVENT_MODIFY_STATE, False, event_name)
            if event:
                _k32.SetEvent(event)
                _k32.CloseHandle(event)
            self.is_primary = False
            return

        # 首个实例:自动复位事件 + 后台线程等待,每次唤醒都呼出一次面板
        self._event_handle = _k32.CreateEventW(None, False, False, event_name)
        threading.Thread(target=self._wait_show, args=(self._event_handle,), daemon=True).start()

    def _wait_show(self, handle: int) -> None:
        while _k32.WaitForSingleObject(handle, _INFINITE) == 0:
            self.another_show.emit()  # 经 Qt 队列切回主线程
