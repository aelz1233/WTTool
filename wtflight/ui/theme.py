"""Application themes, HUD text presets and the shared Qt stylesheet.

App themes recolour the editor only; HUD typography and colours belong to aircraft profiles.
"""
import re

# Editor / HUD palette shared by widgets.
INK = "#eaf2ff"
MUTED = "#8fa1b9"
TEAL = "#57e0c3"
ORANGE = "#ffbd5a"
RED = "#ff6879"

THEMES = {
    "graphite": {"name": "Graphite", "description": "Тёмный · спокойный зелёный", "accent": "#8fbca5", "muted": "#a8bcb1"},
    "cockpit": {"name": "Cockpit", "description": "Приборный · янтарный", "accent": "#e3b564", "muted": "#c4b28f"},
    "arctic": {"name": "Arctic", "description": "Светлый · синий акцент", "accent": "#2868ad", "muted": "#526a80"},
    "dark": {"name": "Dark", "description": "Глубокая тёмная тема", "accent": "#9aa7b7", "muted": "#9aa3ae"},
    "pink": {"name": "Rose", "description": "Тёмная · розовый акцент", "accent": "#f178b6", "muted": "#c7a2b5"},
}

HUD_STYLES = {
    "wtrti": {
        "name": "WTRTI · моноширинный",
        "font_family": "Lucida Console", "bold": True,
        "color": "#66d6a0", "accent": "#66d6a0",
        "outline": True, "outline_color": "#07140f", "outline_width": 1.4, "shadow": False,
    },
    "war_thunder": {
        "name": "War Thunder · игровой",
        "font_family": "Bahnschrift", "bold": False,
        "color": "#edf3f5", "accent": "#edf3f5",
        "outline": True, "outline_color": "#101820", "outline_width": 2.0, "shadow": False,
    },
    "amber": {
        "name": "Приборный · янтарный",
        "font_family": "Bahnschrift", "bold": True,
        "color": "#ffc86e", "accent": "#ffd895",
        "outline": True, "outline_color": "#21170a", "outline_width": 1.7, "shadow": True,
    },
    "ice": {
        "name": "Ледяной · голубой",
        "font_family": "Consolas", "bold": True,
        "color": "#9fe7ff", "accent": "#c7f2ff",
        "outline": True, "outline_color": "#07111c", "outline_width": 1.5, "shadow": False,
    },
    "rose": {
        "name": "Неон · розовый",
        "font_family": "Bahnschrift", "bold": True,
        "color": "#ff9bcc", "accent": "#ffc4df",
        "outline": True, "outline_color": "#210b17", "outline_width": 1.8, "shadow": False,
    },
}

COCKPIT = {
    "#15181b": "#111314", "#191e21": "#181b1c", "#202529": "#202425",
    "#e3e7e8": "#e9e3d5", "#f3f5f5": "#fff3d8", "#929b9f": "#a39f94",
    "#8fbca9": "#d7b779", "#8fbca5": "#e3b564", "#aecfbe": "#e3bd7a",
    "#91cdb4": "#e4bc79", "#21352e": "#373022", "#87b9a4": "#d9b572",
    "#344b40": "#4b3c24", "#28332e": "#343026", "#d5eee1": "#ffe4b3",
    "#a2cfb8": "#ebc57f", "#35423b": "#443a29", "#6a8d7b": "#9c8251",
    "#14241c": "#20190d", "#abd2be": "#f5ce90", "#34433c": "#484031",
    "#53635c": "#6a604d", "#cce2d6": "#f3d79f", "#46534c": "#605541",
    "#26372f": "#3d3324", "#e4f2eb": "#ffe7bf",
}

ARCTIC = {
    "#15181b": "#eef2f6", "#e3e7e8": "#233447", "#f3f5f5": "#1c2f43",
    "#8fbca9": "#386b9b", "#929b9f": "#617487", "#21352e": "#d9eae2",
    "#91cdb4": "#276846", "#30302a": "#f0e7d4", "#c9bc94": "#7b5b20",
    "#202529": "#ffffff", "#343c40": "#c7d2df", "#87b9a4": "#3f7fbd",
    "#242a2e": "#ffffff", "#344b40": "#d4e5f6", "#191e21": "#ffffff",
    "#2d3539": "#d2dce5", "#28332e": "#e4edf6", "#d5eee1": "#184c7e",
    "#26372f": "#e6eef8", "#e4f2eb": "#163e65", "#262d31": "#ffffff",
    "#394246": "#c6d3df", "#35423b": "#e2edf8", "#6a8d7b": "#8ba9c7",
    "#8fbca5": "#2868ad", "#14241c": "#ffffff", "#abd2be": "#397bbb",
    "#d8999d": "#a3434c", "#53635c": "#93a8bc", "#aecfbe": "#2868ad",
    "#34433c": "#ccdbe9", "#30383c": "#cdd7e2", "#939da0": "#62788d",
    "#cce2d6": "#245d96", "#46534c": "#a6b9cd",
}

DARK = {
    "#15181b": "#080b10", "#191e21": "#10151c", "#202529": "#171e27",
    "#e3e7e8": "#e7ecf3", "#f3f5f5": "#fbfcff", "#929b9f": "#8b97a6",
    "#8fbca9": "#9aa7b7", "#8fbca5": "#9aa7b7", "#aecfbe": "#c5d0dc",
    "#91cdb4": "#b6c3d2", "#21352e": "#1b242f", "#87b9a4": "#8595a8",
    "#344b40": "#283443", "#28332e": "#242e3a", "#d5eee1": "#e0e8f1",
    "#a2cfb8": "#b9c8d8", "#35423b": "#2a3542", "#6a8d7b": "#627286",
    "#14241c": "#0c1118", "#abd2be": "#d2dbe5", "#34433c": "#343f4d",
    "#53635c": "#586678", "#cce2d6": "#d6dfeb", "#46534c": "#566275",
    "#26372f": "#26303c", "#e4f2eb": "#e1e8f0", "#d8999d": "#df929b",
}

PINK = {
    "#15181b": "#140d13", "#191e21": "#1d121b", "#202529": "#261722",
    "#e3e7e8": "#f0e7ef", "#f3f5f5": "#fff7fc", "#929b9f": "#b69bab",
    "#8fbca9": "#d16a9e", "#8fbca5": "#e47eae", "#aecfbe": "#f0b6d2",
    "#91cdb4": "#ee9bc2", "#21352e": "#33202c", "#87b9a4": "#d66b9f",
    "#344b40": "#4b2a3e", "#28332e": "#3a2332", "#d5eee1": "#ffe3f1",
    "#a2cfb8": "#f0b6d2", "#35423b": "#45283a", "#6a8d7b": "#a4527a",
    "#14241c": "#23101b", "#abd2be": "#ffd4e9", "#34433c": "#553348",
    "#53635c": "#76566c", "#cce2d6": "#f3cde1", "#46534c": "#77556b",
    "#26372f": "#3e2536", "#e4f2eb": "#ffe5f2", "#d8999d": "#f090ae",
}


def theme_style(base, theme):
    mapping = {"cockpit": COCKPIT, "arctic": ARCTIC, "dark": DARK, "pink": PINK}.get(theme, {})
    style = re.sub(r"#[0-9a-fA-F]{6}", lambda m: mapping.get(m[0].lower(), m[0]), base)
    if theme == "cockpit":
        style += "\nQPushButton, QLineEdit, QComboBox, QSpinBox, QTreeWidget, QListWidget { border-radius: 2px; }"
        style += "\nQLabel#headline, QLabel#eyebrow { font-family: 'Bahnschrift'; letter-spacing: 1px; }"
    elif theme == "arctic":
        style += "\nQPushButton, QLineEdit, QComboBox, QSpinBox, QTreeWidget, QListWidget { border-radius: 8px; }"
    elif theme in ("dark", "pink"):
        style += "\nQPushButton, QLineEdit, QComboBox, QSpinBox, QTreeWidget, QListWidget { border-radius: 5px; }"
    return style


STYLE = """
QWidget { background: #15181b; color: #e3e7e8; font-family: 'Segoe UI'; font-size: 12px; }
QLabel, QCheckBox { background: transparent; }
QLabel#eyebrow { color: #8fbca9; font-size: 10px; font-weight: 600; letter-spacing: 1px; }
QLabel#headline { color: #f3f5f5; font-size: 19px; font-weight: 600; }
QLabel#muted { color: #929b9f; font-size: 11px; }
QLabel#status { background: #21352e; border-radius: 5px; color: #91cdb4; padding: 5px 8px; font-size: 10px; }
QLabel#status[offline="true"] { background: #30302a; color: #c9bc94; }
QLineEdit, QComboBox, QSpinBox, QKeySequenceEdit { background: #202529; border: 1px solid #343c40; border-radius: 5px; padding: 6px; color: #e3e7e8; min-height: 16px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QKeySequenceEdit:focus { border-color: #87b9a4; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView { background: #242a2e; selection-background-color: #344b40; }
QListWidget { background: #191e21; border: 1px solid #2d3539; border-radius: 6px; padding: 3px; outline: none; }
QListWidget::item { border-radius: 4px; padding: 5px 3px; margin: 0; }
QListWidget::item:hover { background: #28332e; }
QListWidget::item:selected { background: #344b40; color: #d5eee1; }
QTreeWidget { background: #191e21; border: 1px solid #2d3539; border-radius: 6px; padding: 3px; outline: none; }
QTreeWidget::item { height: 27px; padding: 1px 2px; border: none; }
QTreeWidget::item:hover { background: #26372f; }
QTreeWidget::item:selected { background: #344b40; color: #e4f2eb; }
QPushButton { background: #262d31; border: 1px solid #394246; border-radius: 5px; padding: 7px 10px; font-weight: 500; }
QPushButton:hover { background: #35423b; border-color: #6a8d7b; }
QPushButton:checked { background: #344b40; border-color: #8fbca5; color: #d5eee1; }
QPushButton#primary { background: #8fbca5; border: 1px solid #8fbca5; color: #14241c; }
QPushButton#primary:hover { background: #abd2be; }
QPushButton#danger { color: #d8999d; }
QPushButton#stepButton { padding: 2px; min-width: 28px; max-width: 32px; min-height: 24px; font-size: 10px; }
QCheckBox { spacing: 7px; padding: 2px 0; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #53635c; border-radius: 3px; background: #202529; }
QCheckBox::indicator:checked { background: #8fbca5; border: 1px solid #aecfbe; }
QSlider::groove:horizontal { background: #34433c; height: 4px; border-radius: 2px; }
QSlider::handle:horizontal { background: #8fbca5; width: 12px; margin: -5px 0; border-radius: 6px; }
QTabWidget::pane { border: none; border-top: 1px solid #30383c; }
QTabBar::tab { background: transparent; color: #939da0; padding: 10px 16px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #cce2d6; border-bottom-color: #8fbca5; }
QTabBar::tab:hover { color: #e3e7e8; }
QScrollArea { border: none; }
QScrollBar:vertical { background: #191e21; width: 6px; }
QScrollBar::handle:vertical { background: #46534c; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""
