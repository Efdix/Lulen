"""数据模型与配置持久化(原子写入 + 备份恢复)。

配置位于 ``%APPDATA%/Lulen/config.json``;可用环境变量 ``LULEN_HOME``
覆盖为任意目录(测试 / 便携模式)。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import ClassVar

from . import APP_NAME

CONFIG_VERSION = 1
URL_RE = re.compile(r"^(https?://|www\.)\S+$", re.IGNORECASE)
_URL_RE = URL_RE
# 裸域名(无盘符/路径分隔符、本地不存在)按网址处理,如 "github.com"
_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*(\.[a-z0-9-]+)+(/\S*)?$", re.IGNORECASE)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def default_data_dir() -> Path:
    """默认数据目录(也是指针文件的固定落脚点)。"""
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_NAME


def data_dir_pointer_path() -> Path:
    """自定义数据目录的指针文件(固定位于默认目录下)。"""
    return default_data_dir() / "data_dir.txt"


def read_data_dir_pointer() -> Path | None:
    """读取自定义数据目录;无效或等于默认目录时返回 None。"""
    try:
        text = data_dir_pointer_path().read_text("utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    p = Path(text)
    if not p.is_absolute() or p == default_data_dir():
        return None
    return p


def write_data_dir_pointer(path: Path | None) -> None:
    """写入/清除自定义数据目录指针;清除后回到默认位置。"""
    anchor = data_dir_pointer_path()
    anchor.parent.mkdir(parents=True, exist_ok=True)
    if path is None:
        try:
            anchor.unlink()
        except FileNotFoundError:
            pass
        return
    anchor.write_text(str(Path(path).resolve()), "utf-8")


def config_dir() -> Path:
    """数据目录:`LULEN_HOME` 环境变量(便携/测试)> 指针文件 > 默认位置。"""
    custom = os.environ.get("LULEN_HOME")
    if custom:
        return Path(custom)
    pointed = read_data_dir_pointer()
    if pointed is not None:
        return pointed
    return default_data_dir()


@dataclass
class Item:
    """一个启动条目。"""

    id: str
    type: str  # app / file / folder / url / command
    name: str
    path: str = ""  # 目标:文件路径或网址
    args: str = ""  # 启动参数,支持 %mp%(所在目录)/ %mr%(所在盘根)
    workdir: str = ""  # 工作目录
    icon: str = ""  # 自定义图标(.ico/.png/.exe/.dll)
    hotkey: str = ""  # 条目快捷键,如 "Alt+1"

    @staticmethod
    def create(type_: str, name: str, path: str, **kw) -> Item:
        return Item(id=new_id(), type=type_, name=name, path=path, **kw)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type, "name": self.name, "path": self.path,
            "args": self.args, "workdir": self.workdir, "icon": self.icon,
            "hotkey": self.hotkey,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Item:
        return cls(
            id=str(d.get("id") or new_id()),
            type=str(d.get("type") or "app"),
            name=str(d.get("name") or ""),
            path=str(d.get("path") or ""),
            args=str(d.get("args") or ""),
            workdir=str(d.get("workdir") or ""),
            icon=str(d.get("icon") or ""),
            hotkey=str(d.get("hotkey") or ""),
        )


@dataclass
class Group:
    """一个分组(面板上的一页)。"""

    id: str
    name: str
    items: list[Item] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "items": [i.to_dict() for i in self.items]}

    @classmethod
    def from_dict(cls, d: dict) -> Group:
        return cls(
            id=str(d.get("id") or new_id()),
            name=str(d.get("name") or "分组"),
            items=[Item.from_dict(x) for x in d.get("items") or [] if isinstance(x, dict)],
        )


@dataclass
class Settings:
    """全局设置。"""

    hotkey: str = "Ctrl+Shift+Z"  # 呼出/隐藏面板的全局热键
    theme: str = "dark"  # dark / light
    accent: str = "#4F8CFF"
    columns: int = 10
    rows: int = 4
    icon_size: int = 48
    single_click: bool = True  # 单击启动(否则双击)
    hide_on_blur: bool = True  # 失焦自动隐藏
    hide_after_launch: bool = True
    autostart: bool = False
    opacity: int = 100  # 面板不透明度(%)
    locked: bool = False  # 锁定面板位置(禁止拖动)
    pos: list[int] | None = None  # 记忆的窗口位置 [x, y]

    _INT: ClassVar[set[str]] = {"columns", "rows", "icon_size", "opacity"}
    _BOOL: ClassVar[set[str]] = {"single_click", "hide_on_blur", "hide_after_launch", "autostart", "locked"}

    def to_dict(self) -> dict:
        return {
            "hotkey": self.hotkey, "theme": self.theme, "accent": self.accent,
            "columns": self.columns, "rows": self.rows, "icon_size": self.icon_size,
            "single_click": self.single_click, "hide_on_blur": self.hide_on_blur,
            "hide_after_launch": self.hide_after_launch, "autostart": self.autostart,
            "opacity": self.opacity, "locked": self.locked, "pos": self.pos,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Settings:
        s = cls()
        if not isinstance(d, dict):
            return s
        for f in fields(cls):
            if f.name.startswith("_") or f.name not in d:
                continue
            v = d[f.name]
            try:
                if f.name in cls._INT:
                    setattr(s, f.name, int(v))
                elif f.name in cls._BOOL:
                    setattr(s, f.name, bool(v))
                elif f.name == "pos":
                    setattr(s, f.name, [int(v[0]), int(v[1])] if isinstance(v, (list, tuple)) and len(v) == 2 else None)
                else:
                    setattr(s, f.name, str(v))
            except (TypeError, ValueError):
                pass
        return s


class ConfigStore:
    """配置的加载 / 保存 / 备份。"""

    def __init__(self) -> None:
        self.dir = config_dir()
        self.path = self.dir / "config.json"
        self.bak_path = self.dir / "config.bak.json"
        self.icon_cache = self.dir / "iconcache"
        self.settings = Settings()
        self.groups: list[Group] = []
        self.current_group = 0

    # ---------- 加载 ----------

    def load(self) -> None:
        data = self._read(self.path) or self._read(self.bak_path)
        if data is None:
            self.init_default()
            self.save()
            return
        try:
            self._apply(data)
        except Exception:
            bak = self._read(self.bak_path)
            if bak:
                try:
                    self._apply(bak)
                    return
                except Exception:
                    pass
            self.init_default()

    def _apply(self, data: dict) -> None:
        self.settings = Settings.from_dict(data.get("settings") or {})
        self.groups = [Group.from_dict(g) for g in data.get("groups") or [] if isinstance(g, dict)]
        if not self.groups:
            self.groups = [Group(id=new_id(), name="常用")]
        try:
            self.current_group = int(data.get("current_group") or 0)
        except (TypeError, ValueError):
            self.current_group = 0
        self.current_group = self._clamp_group(self.current_group)

    def init_default(self) -> None:
        self.settings = Settings()
        self.groups = [Group(id=new_id(), name="常用")]
        self.current_group = 0

    # ---------- 迁移 ----------

    def relocate(self, new_dir: Path, on_conflict: str = "keep") -> tuple[bool, str]:
        """把数据整体迁到 new_dir 并让本 store 改用新位置。

        返回 (是否成功, 错误信息)。on_conflict:目标已有 config.json 时,
        "keep" = 保留目标现有数据(仅迁移图标缓存),"overwrite" = 用当前数据覆盖。
        """
        new_dir = Path(new_dir).resolve()
        old_dir = self.dir.resolve()
        if new_dir == old_dir:
            return True, ""
        if old_dir in new_dir.parents or new_dir in old_dir.parents:
            return False, "新目录不能位于旧目录的内部或外部包含关系中"
        try:
            new_dir.mkdir(parents=True, exist_ok=True)
            probe = new_dir / ".lulen_write_test"
            probe.write_text("ok", "utf-8")
            probe.unlink()
        except OSError as exc:
            return False, f"目标目录不可写:{exc}"

        target_config = new_dir / "config.json"
        keep_existing = on_conflict == "keep" and target_config.exists()
        try:
            if not keep_existing:
                for name in ("config.json", "config.bak.json"):
                    src = old_dir / name
                    if src.exists():
                        shutil.copy2(src, new_dir / name)
            cache_src = old_dir / "iconcache"
            if cache_src.is_dir():
                cache_dst = new_dir / "iconcache"
                cache_dst.mkdir(parents=True, exist_ok=True)
                for f in cache_src.iterdir():
                    if f.is_file():
                        shutil.copy2(f, cache_dst / f.name)
        except OSError as exc:
            return False, f"迁移失败:{exc}"

        # 改用新位置并重新加载
        self.dir = new_dir
        self.path = new_dir / "config.json"
        self.bak_path = new_dir / "config.bak.json"
        self.icon_cache = new_dir / "iconcache"
        write_data_dir_pointer(new_dir)
        self.load()
        return True, ""

    @staticmethod
    def _read(path: Path) -> dict | None:
        try:
            return json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            return None

    # ---------- 保存 ----------

    def save(self) -> None:
        """原子写入:写临时文件后 replace;覆盖前把上一份转存为 .bak。"""
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                try:
                    self.bak_path.write_bytes(self.path.read_bytes())
                except OSError:
                    pass
            payload = {
                "version": CONFIG_VERSION,
                "current_group": self.current_group,
                "settings": self.settings.to_dict(),
                "groups": [g.to_dict() for g in self.groups],
            }
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass

    def export_to(self, path: str) -> bool:
        try:
            Path(path).write_text(
                json.dumps({
                    "version": CONFIG_VERSION,
                    "settings": self.settings.to_dict(),
                    "groups": [g.to_dict() for g in self.groups],
                }, ensure_ascii=False, indent=2),
                "utf-8",
            )
            return True
        except OSError:
            return False

    def import_from(self, path: str) -> bool:
        data = self._read(Path(path))
        if not data or not isinstance(data.get("groups"), list):
            return False
        try:
            self._apply(data)
        except Exception:
            return False
        self.save()
        return True

    # ---------- 查询 / 变更辅助 ----------

    def _clamp_group(self, index: int) -> int:
        return max(0, min(index, len(self.groups) - 1)) if self.groups else 0

    def group(self, index: int | None = None) -> Group:
        i = self._clamp_group(self.current_group if index is None else index)
        return self.groups[i]

    def find_item(self, item_id: str) -> tuple[Group, Item] | tuple[None, None]:
        for g in self.groups:
            for it in g.items:
                if it.id == item_id:
                    return g, it
        return None, None

    def all_items(self):
        for g in self.groups:
            yield from g.items


def tip_text(item: Item) -> str:
    """条目提示文本。"""
    if item.type == "command":
        return f"{item.name}\n{item.path}"
    if item.type == "url":
        return f"{item.name}\n{item.path}"
    return f"{item.name}\n{item.path}{('\n' + item.args) if item.args else ''}"


# ---------- 从拖入内容构造条目 ----------

def parse_url_file(path: str) -> str | None:
    """解析 .url 快捷方式中的 URL= 行。"""
    try:
        for line in Path(path).read_text("utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.lower().startswith("url="):
                return line[4:].strip()
    except OSError:
        pass
    return None


def guess_type(path: str) -> str:
    p = (path or "").strip()
    if _URL_RE.match(p) or p.lower().endswith(".url"):
        return "url"
    local = os.path.isfile(p) or os.path.isdir(p)
    if not local and "\\" not in p and "/" not in p and _DOMAIN_RE.match(p):
        return "url"  # 裸域名且本地不存在,如 "github.com"
    if os.path.isdir(p):
        return "folder"
    ext = os.path.splitext(p)[1].lower()
    if ext in {".exe", ".lnk", ".bat", ".cmd", ".com", ".msi", ".ahk", ".py", ".ps1", ".vbs", ".jar"}:
        return "app"
    return "file"


def guess_name(path: str) -> str:
    p = (path or "").strip().rstrip("/\\")
    if _URL_RE.match(p):
        host = re.sub(r"^(https?://|www\.)", "", p, flags=re.IGNORECASE)
        return host.split("/")[0] or host
    if p.lower().endswith(".url") and os.path.isfile(p):
        url = parse_url_file(p)
        if url:
            return guess_name(url)
    return Path(p).stem or p


def make_items(paths: list[str]) -> list[Item]:
    """把拖入的一批路径 / 网址转成条目列表。"""
    items: list[Item] = []
    for raw in paths:
        p = (raw or "").strip()
        if not p:
            continue
        if p.lower().endswith(".url") and os.path.isfile(p):
            url = parse_url_file(p)
            if url:
                items.append(Item.create("url", Path(p).stem, url))
                continue
        t = guess_type(p)
        if t == "url" and "://" not in p:
            p = "https://" + p
        items.append(Item.create(t, guess_name(raw), p))
    return items
