"""生成应用图标 assets/lulen.ico(256px,由代码绘制,无需美术资源)。

用法::

    python tools/make_icon.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from lulen.icons import app_icon


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841 -- 需保持应用引用
    out = Path(__file__).resolve().parent.parent / "assets" / "lulen.ico"
    out.parent.mkdir(parents=True, exist_ok=True)
    icon = app_icon("#4F8CFF")
    if not icon.pixmap(256, 256).save(str(out), "ICO"):
        print("failed to write", out)
        return 1
    print(f"icon written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
