"""主题:QSS 构建 + 绘制用调色板。"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor

DARK = "dark"
LIGHT = "light"


def _rgba(color: QColor, alpha: int) -> str:
    c = QColor(color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


@dataclass
class Palette:
    """委托 / 控件绘制用的运行时配色。"""

    dark: bool
    accent: QColor
    text: QColor
    text_dim: QColor
    hover: QColor
    pressed: QColor
    selected: QColor
    panel_border: QColor


def build_palette(theme: str, accent_hex: str) -> Palette:
    dark = theme == DARK
    accent = QColor(accent_hex if QColor(accent_hex).isValid() else "#4F8CFF")
    if dark:
        return Palette(
            dark=True, accent=accent,
            text=QColor("#E9EBF0"), text_dim=QColor(233, 235, 240, 115),
            hover=QColor(255, 255, 255, 20), pressed=QColor(255, 255, 255, 32),
            selected=QColor(accent.red(), accent.green(), accent.blue(), 52),
            panel_border=QColor(255, 255, 255, 24),
        )
    return Palette(
        dark=False, accent=accent,
        text=QColor("#1C1E24"), text_dim=QColor(28, 30, 36, 120),
        hover=QColor(0, 0, 0, 14), pressed=QColor(0, 0, 0, 24),
        selected=QColor(accent.red(), accent.green(), accent.blue(), 44),
        panel_border=QColor(0, 0, 0, 26),
    )


def build_qss(theme: str, accent_hex: str) -> str:
    dark = theme == DARK
    accent = QColor(accent_hex if QColor(accent_hex).isValid() else "#4F8CFF")
    if dark:
        bg = "rgba(23, 25, 32, 246)"
        border = "rgba(255,255,255,26)"
        text, text_dim = "#E9EBF0", "rgba(233,235,240,0.48)"
        hover, press = "rgba(255,255,255,0.07)", "rgba(255,255,255,0.12)"
        input_bg = "rgba(255,255,255,0.075)"
        menu_bg, tooltip_bg = "#20232C", "rgba(16,17,22,242)"
        dialog_bg = "#191C23"
    else:
        bg = "rgba(250, 251, 253, 248)"
        border = "rgba(0,0,0,26)"
        text, text_dim = "#1C1E24", "rgba(28,30,36,0.48)"
        hover, press = "rgba(0,0,0,0.055)", "rgba(0,0,0,0.10)"
        input_bg = "rgba(0,0,0,0.05)"
        menu_bg, tooltip_bg = "#FFFFFF", "rgba(255,255,255,250)"
        dialog_bg = "#F6F7FA"

    return f"""
#root {{
    background: {bg};
    border: 1px solid {border};
    border-radius: 14px;
}}
#strip {{ background: transparent; }}
QListView {{
    background: transparent; border: none; outline: none;
    font-size: 11px;
}}
#emptyHint {{
    background: transparent; color: {text_dim};
    font-size: 13px;
}}
#groupTab {{
    border: none; background: transparent; color: {text_dim};
    padding: 4px 9px; border-radius: 8px; font-size: 12px;
}}
#groupTab:hover {{ background: {hover}; color: {text}; }}
#groupTab:checked {{
    background: {_rgba(accent, 44)}; color: {accent.name()};
    font-weight: 600;
}}
#groupTab[dropHover="true"] {{ background: {_rgba(accent, 90)}; }}
QTabBar {{
    background: transparent; font-size: 12px;
}}
QTabBar::tab {{
    border: none; background: transparent; color: {text_dim};
    padding: 4px 10px; border-radius: 8px; margin-right: 2px;
    max-width: 96px;
}}
QTabBar::tab:hover {{ background: {hover}; color: {text}; }}
QTabBar::tab:selected {{
    background: {_rgba(accent, 44)}; color: {accent.name()};
    font-weight: 600;
}}
#addTab {{
    border: none; background: transparent; color: {text_dim};
    padding: 2px 8px; border-radius: 8px; font-size: 13px; font-weight: 600;
}}
#addTab:hover {{ background: {hover}; color: {text}; }}
#toolBtn {{
    border: none; background: transparent; color: {text_dim};
    border-radius: 7px; padding: 2px 6px; font-size: 12px;
}}
#toolBtn:hover {{ background: {hover}; color: {text}; }}
#cmdBar {{
    background: {input_bg}; border: 1px solid transparent;
    border-radius: 9px; padding: 5px 10px; color: {text};
    font-size: 12px; selection-background-color: {accent.name()};
}}
#cmdBar:focus {{ border: 1px solid {_rgba(accent, 150)}; }}
QScrollBar:vertical {{ background: transparent; width: 6px; margin: 6px 1px 6px 0; }}
QScrollBar::handle:vertical {{
    background: {press}; border-radius: 3px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {text_dim}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none; border: none; height: 0; width: 0;
}}
QMenu {{
    background: {menu_bg}; color: {text};
    border: 1px solid {border}; border-radius: 10px; padding: 5px;
}}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 7px; }}
QMenu::item:selected {{ background: {_rgba(accent, 52)}; }}
QMenu::item:disabled {{ color: {text_dim}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 5px 8px; }}
QToolTip {{
    background: {tooltip_bg}; color: {text};
    border: 1px solid {border}; border-radius: 6px;
    padding: 4px 9px; font-size: 11px;
}}
QDialog, QInputDialog {{ background: {dialog_bg}; color: {text}; }}
QDialog QLabel {{ color: {text}; font-size: 12px; background: transparent; }}
QDialog QPlainTextEdit, QDialog QLineEdit, QDialog QSpinBox, QDialog QComboBox {{
    background: {input_bg}; border: 1px solid transparent; border-radius: 7px;
    padding: 4px 8px; color: {text}; selection-background-color: {accent.name()};
    font-size: 12px;
}}
QDialog QLineEdit:focus, QDialog QSpinBox:focus, QDialog QComboBox:focus {{
    border: 1px solid {_rgba(accent, 160)};
}}
QDialog QPushButton {{
    background: {hover}; color: {text}; border: none;
    border-radius: 7px; padding: 5px 14px; font-size: 12px;
}}
QDialog QPushButton:hover {{ background: {press}; }}
QDialog QPushButton#primaryBtn {{ background: {accent.name()}; color: #FFFFFF; font-weight: 600; }}
QDialog QPushButton#primaryBtn:hover {{ background: {accent.lighter(112).name()}; }}
QComboBox QAbstractItemView {{
    background: {menu_bg}; color: {text};
    border: 1px solid {border}; border-radius: 8px;
    selection-background-color: {_rgba(accent, 60)};
    selection-color: {text};
    outline: none;
}}
QGroupBox {{
    border: 1px solid {border}; border-radius: 10px;
    margin-top: 12px; padding: 10px 8px 8px 8px; font-size: 12px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {text_dim};
}}
QDialog QCheckBox {{ color: {text}; font-size: 12px; spacing: 6px; }}
QDialog QSlider {{ color: {accent.name()}; }}
QDialog QSlider::groove:horizontal {{ height: 4px; background: {input_bg}; border-radius: 2px; }}
QDialog QSlider::handle:horizontal {{
    background: {accent.name()}; width: 14px; height: 14px;
    margin: -5px 0; border-radius: 7px;
}}
"""
