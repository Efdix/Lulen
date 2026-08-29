"""条目启动逻辑:统一通过 ShellExecuteW 分发,保证与资源管理器双击一致。"""
from __future__ import annotations

import ctypes
import os

from .config import Item

SW_SHOWNORMAL = 1

_SE_ERR_TEXT = {
    0: "内存不足",
    2: "文件不存在",
    3: "路径不存在",
    5: "拒绝访问",
    8: "内存不足",
    11: "可执行文件格式无效",
    26: "发生共享错误",
    27: "文件关联不完整",
    28: "DDE 超时",
    29: "DDE 失败",
    30: "DDE 忙",
    31: "没有关联的应用程序",
    32: "不支持的 16 位程序",
}


def expand_variables(item: Item) -> tuple[str, str]:
    """展开 %mp%(条目所在目录)、%mr%(所在盘根)与环境变量。"""
    args = item.args
    workdir = item.workdir
    if item.path:
        base = os.path.dirname(os.path.abspath(item.path))
        drive = os.path.splitdrive(base)[0]
        root = drive + os.sep if drive else ""
        args = args.replace("%mp%", base).replace("%mr%", root)
        workdir = workdir.replace("%mp%", base).replace("%mr%", root)
    return os.path.expandvars(args), os.path.expandvars(workdir)


def _shell_open(path: str, args: str = "", workdir: str = "", verb: str = "open") -> tuple[bool, str]:
    r = ctypes.windll.shell32.ShellExecuteW(
        None, verb, path, args or None, workdir or None, SW_SHOWNORMAL
    )
    if r > 32:
        return True, ""
    return False, _SE_ERR_TEXT.get(r, f"启动失败(错误码 {r})")


def open_item(item: Item, run_as_admin: bool = False) -> tuple[bool, str]:
    """启动一个条目,返回 (是否成功, 错误信息)。"""
    target = (item.path or "").strip()
    try:
        if item.type == "command":
            if not target:
                return False, "命令为空"
            os.system(f'start "" {target}')  # 经由 cmd start 打开独立终端
            return True, ""
        if not target:
            return False, "目标为空"
        if item.type == "url":
            url = target if "://" in target else "https://" + target
            ok, err = _shell_open(url)
            return ok, err
        if item.type in ("app", "file", "folder"):
            if item.type != "folder" and not os.path.exists(target) and not target.lower().endswith(".lnk"):
                return False, f"目标不存在:{target}"
            args, workdir = expand_variables(item)
            verb = "runas" if run_as_admin else "open"
            return _shell_open(target, args, workdir, verb)
        return False, f"未知类型:{item.type}"
    except Exception as exc:  # 防御:任何启动异常都不应让面板崩溃
        return False, str(exc)


def open_containing(item: Item) -> tuple[bool, str]:
    """在资源管理器中定位条目目标。"""
    target = (item.path or "").strip()
    if not target or item.type in ("url", "command"):
        return False, "该条目没有本地路径"
    if os.path.isdir(target):
        return _shell_open(target)
    parent = os.path.dirname(os.path.abspath(target))
    if not os.path.isdir(parent):
        return False, "目录不存在"
    # explorer /select 定位文件本身
    r = ctypes.windll.shell32.ShellExecuteW(
        None, "open", "explorer.exe", f'/select,"{os.path.abspath(target)}"', None, SW_SHOWNORMAL
    )
    return (True, "") if r > 32 else (False, f"打开失败(错误码 {r})")
