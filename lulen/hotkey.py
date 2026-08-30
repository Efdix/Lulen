"""全局热键:Win32 RegisterHotKey + Qt 原生事件过滤器。

- 主热键(呼出/隐藏面板)占用 ID 1;
- 条目热键从 ID 100 起分配。
注册时 hWnd 传 None,WM_HOTKEY 投递到线程消息队列,由 Qt 事件循环泵出,
经 ``_NativeFilter`` 转成 Qt 信号。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

WM_HOTKEY = 0x0312

MOD_ALT = 0x1
MOD_CONTROL = 0x2
MOD_SHIFT = 0x4
MOD_WIN = 0x8

_MOD_MAP = {"alt": MOD_ALT, "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
            "shift": MOD_SHIFT, "win": MOD_WIN, "meta": MOD_WIN}

# 单字符命名键 -> VK 码(US 布局)
_NAMED_VK = {
    "space": 0x20, "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "enter": 0x0D,
    "return": 0x0D, "backspace": 0x08, "home": 0x24, "end": 0x23,
    "pgup": 0x21, "pgdown": 0x22, "ins": 0x2D, "del": 0x2E,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC,
    ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF,
}

user32 = ctypes.windll.user32


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """``"Ctrl+Shift+Z"`` -> ``(mods, vk)``;无法识别返回 None。"""
    parts = [p.strip() for p in (text or "").split("+") if p.strip()]
    if not parts:
        return None
    mods = 0
    key: str | None = None
    for p in parts:
        lp = p.lower()
        if lp in _MOD_MAP:
            mods |= _MOD_MAP[lp]
        elif key is None:
            key = p
        else:
            return None  # 出现两个主键
    if key is None:
        return None
    vk = _key_to_vk(key)
    if vk is None:
        return None
    return mods, vk


def _key_to_vk(key: str) -> int | None:
    if len(key) == 1:
        ch = key.upper()
        if ch.isdigit():
            return 0x30 + int(ch)
        if "A" <= ch <= "Z":
            return ord(ch)
    if key.lower().startswith("f") and key[1:].isdigit():
        n = int(key[1:])
        if 1 <= n <= 24:
            return 0x70 + n - 1
    named = _NAMED_VK.get(key.lower())
    if named is not None:
        return named
    # 其余字符(含符号)经 VkKeyScanW;Shift/Ctrl/Alt 状态合并进 mods 由调用方处理
    r = user32.VkKeyScanW(ord(key[0]))
    if r == -1:
        return None
    return r & 0xFF


def _shift_state_of(key: str) -> int:
    """VkKeyScanW 的 shift/ctrl/alt 位(bit0/1/2),供符号键合并。"""
    if len(key) != 1:
        return 0
    r = user32.VkKeyScanW(ord(key[0]))
    if r == -1:
        return 0
    return (r >> 8) & 0xFF


def hotkey_mods_with_symbol(text: str) -> tuple[int, int] | None:
    """考虑符号键自带 Shift 状态的解析(如 Ctrl+/)。"""
    hk = parse_hotkey(text)
    if hk is None:
        return None
    parts = [p.strip() for p in (text or "").split("+") if p.strip()]
    symbol = [p for p in parts if p.lower() not in _MOD_MAP]
    if symbol and len(symbol[0]) == 1 and not (symbol[0].upper().isdigit() or "A" <= symbol[0].upper() <= "Z"):
        ss = _shift_state_of(symbol[0])
        if ss & 1:
            hk = (hk[0] | MOD_SHIFT, hk[1])
        if ss & 2:
            hk = (hk[0] | MOD_CONTROL, hk[1])
        if ss & 4:
            hk = (hk[0] | MOD_ALT, hk[1])
    return hk


class _NativeFilter(QAbstractNativeEventFilter):
    """把线程队列里的 WM_HOTKEY 转成回调。"""

    def __init__(self, callback) -> None:
        super().__init__()
        self._callback = callback

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self._callback(int(msg.wParam))
                return True, 0
        return False, 0


class HotkeyManager(QObject):
    """注册 / 注销全局热键,并转发为 Qt 信号。"""

    main_activated = Signal()
    item_activated = Signal(str)       # 条目热键文本
    register_failed = Signal(str)      # 注册失败的热键文本

    MAIN_ID = 1
    ITEM_BASE = 100

    def __init__(self, app: QObject) -> None:
        super().__init__(app)
        self._filter = _NativeFilter(self._dispatch)
        app.installNativeEventFilter(self._filter)
        self._main_text = ""
        self._items: dict[int, str] = {}  # id -> 热键文本
        self._next_id = self.ITEM_BASE

    # ---------- 主热键 ----------

    def register_main(self, text: str) -> bool:
        self.unregister_main()
        hk = hotkey_mods_with_symbol(text)
        if hk is None or hk[0] == 0:
            return False
        if not user32.RegisterHotKey(None, self.MAIN_ID, hk[0], hk[1]):
            self.register_failed.emit(text)
            return False
        self._main_text = text
        return True

    def unregister_main(self) -> None:
        if self._main_text:
            user32.UnregisterHotKey(None, self.MAIN_ID)
            self._main_text = ""

    @property
    def main_text(self) -> str:
        return self._main_text

    # ---------- 条目热键 ----------

    def register_item(self, text: str) -> bool:
        if not text:
            return False
        if text in self._items.values():
            return True
        hk = hotkey_mods_with_symbol(text)
        if hk is None or hk[0] == 0:
            return False
        hid = self._next_id
        self._next_id += 1
        if not user32.RegisterHotKey(None, hid, hk[0], hk[1]):
            return False
        self._items[hid] = text
        return True

    def unregister_item(self, text: str) -> None:
        for hid, t in list(self._items.items()):
            if t == text:
                user32.UnregisterHotKey(None, hid)
                del self._items[hid]

    def register_all_item_hotkeys(self, items) -> None:
        """启动时批量注册;冲突的条目热键静默跳过。"""
        for it in items:
            if it.hotkey:
                self.register_item(it.hotkey)

    def unregister_all(self) -> None:
        self.unregister_main()
        for hid in list(self._items):
            user32.UnregisterHotKey(None, hid)
        self._items.clear()

    # ---------- 分发 ----------

    def _dispatch(self, hotkey_id: int) -> None:
        if hotkey_id == self.MAIN_ID:
            self.main_activated.emit()
            return
        text = self._items.get(hotkey_id)
        if text:
            self.item_activated.emit(text)
