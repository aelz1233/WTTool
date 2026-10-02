"""Keyed UI translations for new widgets and dialogs."""
from __future__ import annotations

from typing import Final
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .main_window import MainWindow

CATALOG: Final[dict[str, dict[str, str]]] = {
    "app.update.available": {"ru": "Доступно обновление", "en": "Update available"},
    "app.update.download": {"ru": "Скачать и установить", "en": "Download and install"},
    "app.update.cancelled": {"ru": "Загрузка отменена", "en": "Download cancelled"},
    "app.update.integrity": {"ru": "Проверка SHA-256 установщика не пройдена", "en": "Installer SHA-256 check failed"},
    "hud.show": {"ru": "Показать HUD", "en": "Show HUD"},
    "hud.quick_menu": {"ru": "Быстрое меню", "en": "Quick menu"},
    "settings.title": {"ru": "Настройки", "en": "Settings"},
}


def tr(key: str, language: str = "en", **values) -> str:
    text = CATALOG.get(key, {}).get(language) or CATALOG.get(key, {}).get("en") or key
    return text.format(**values)

def apply_language(window: MainWindow, language: str):
    window.set_language(language)
