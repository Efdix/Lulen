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
    out.parent.mkdir(parents=True, exist_ok=True)
    preview = out.parent / "_icon_preview.png"
    if not icon.pixmap(512, 512).save(str(preview), "PNG"):
        print("failed to write preview")
        return 1
    from PIL import Image

    base = Image.open(preview)
    sizes = (256, 128, 64, 48, 32, 24, 16)
    frames = [base.resize((s2, s2), Image.LANCZOS) for s2 in sizes]
    frames[0].save(out, format="ICO", sizes=[(s2, s2) for s2 in sizes],
                   append_images=frames[1:])
    preview.unlink()
    print(f"icon written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
