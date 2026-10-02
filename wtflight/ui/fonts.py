"""HUD font choices limited to families installed on this PC."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase


def installed_hud_fonts():
    """Prefer familiar HUD fonts, but only offer families installed on this PC."""
    preferred = ["Consolas", "Lucida Console", "Bahnschrift", "Courier New", "Segoe UI",
                 "Arial", "Tahoma", "Verdana", "Impact"]
    installed = set(QFontDatabase.families())
    result = [name for name in preferred if name in installed]
    return result or ["Consolas"]


def fill_hud_font_box(combo):
    for family in installed_hud_fonts():
        combo.addItem(family)
        combo.setItemData(combo.count() - 1, QFont(family), Qt.FontRole)
