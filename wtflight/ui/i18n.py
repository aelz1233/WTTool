"""Central translations for the desktop UI.

The legacy window still stores Russian source strings on widgets so switching
back is lossless.  This table covers labels, menus, tooltips and dialog text;
the window applies it to every Qt child instead of translating only a small
hand-written subset of controls.
"""
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

# Russian is the source language used by the existing UI.  Keeping the map
# keyed by source text makes it possible to migrate the remaining widgets to
# Qt .ts files later without leaving untranslated controls behind today.
UI_TRANSLATIONS: Final[dict[str, str]] = {
    "Русский": "Russian", "Английский": "English", "Вид": "View", "Полёт": "Flight",
    "Двигатель": "Engine", "Топливо и двигатель": "Fuel & engine", "Навигация": "Navigation",
    "Другие данные": "Other data", "Доступно на этом самолёте": "Available on this aircraft",
    "Добавить отдельный показатель": "Add individual metric", "Ничего не найдено": "Nothing found",
    "Данные появятся в бою": "Data appears in battle", "Выберите группу на макете": "Select a group on the layout",
    "Выберите блок на макете, чтобы изменить его вид.": "Select a block on the layout to change its style.",
    "Перетащите показатель на макет · Рамка выделяет несколько": "Drag a metric to the layout · Drag a frame to select several",
    "Перетащите на макет или на существующую группу.": "Drag to the layout or an existing group.",
    "Макет": "Layout", "Готовые и сохранённые конфигурации оверлея": "Built-in and saved overlay configurations",
    "ГОТОВЫЕ И СОХРАНЁННЫЕ МАКЕТЫ": "BUILT-IN AND SAVED LAYOUTS", "Профили": "Profiles",
    "Стандарт · воздушный бой": "Default · air combat", "Двигатель · по примеру": "Engine · reference",
    "Вертолёт · базовый": "Helicopter · basic", "Пустой": "Empty", "Стандарт": "Default",
    "Сохранить макет": "Save layout", "Сохранить макет как…": "Save layout as…", "Сохранить изменения": "Save changes",
    "Удалить конфиг": "Delete config", "Удалить выбранный сохранённый конфиг": "Delete selected saved config",
    "Перезаписать выбранный сохранённый конфиг текущим макетом": "Overwrite the selected saved config with the current layout",
    "Восстановить выбранный стандартный макет": "Restore selected built-in layout",
    "Импорт макета": "Import layout", "Импорт макета…": "Import layout…", "Импорт…": "Import…",
    "Экспорт макета": "Export layout", "Экспорт макета…": "Export layout…", "Экспорт…": "Export…",
    "Инструменты макета": "Layout tools", "Показать сетку": "Show grid", "Сбросить расположение": "Reset layout",
    "Загрузить фон…": "Load background…", "Убрать фон": "Remove background", "Макеты, фон, масштаб и выравнивание": "Layouts, background, zoom and alignment",
    "Монитор для игрового HUD и точного предпросмотра": "Monitor for the game HUD and accurate preview",
    "Масштаб макета. При увеличении пустой фон можно перетаскивать мышью.": "Layout zoom. When zoomed in, drag the empty background with the mouse.",
    "Вписать": "Fit", "Выравнивание и привязка": "Alignment and snapping", "К левому краю": "Align left",
    "К правому краю": "Align right", "К верхнему краю": "Align top", "К нижнему краю": "Align bottom",
    "По центру горизонтально": "Center horizontally", "По центру вертикально": "Center vertically",
    "Все группы в колонку от выбранной": "Stack all groups from the selected one",
    "Привязка к краям и другим группам": "Snap to edges and other groups", "Отменить · Ctrl+Z на макете": "Undo · Ctrl+Z on the layout",
    "Повторить · Ctrl+Y на макете": "Redo · Ctrl+Y on the layout", "Оформление выбранного текста": "Style selected text",
    "Шрифт": "Font", "Размер": "Size", "Название": "Name", "Название группы": "Group title", "Отображение": "Display",
    "Текст без фона": "Text without background", "Компактная панель": "Compact panel", "Готовый стиль HUD": "HUD style preset",
    "Между строками": "Line spacing", "На макете: Ctrl + колесо — размер": "On the layout: Ctrl + wheel — size",
    "Дополнительные настройки": "Additional settings", "Подписи": "Labels", "Короткие подписи: IAS / LDF": "Compact labels: IAS / LDF",
    "Жирный": "Bold", "Тень текста": "Text shadow", "Обводка": "Outline", "Цвет значений": "Value color",
    "Цвет подписей": "Label color", "Цвет обводки": "Outline color", "Убрать показатель": "Remove metric",
    "Удалить группу": "Delete group", "Пределы самолёта": "Aircraft limits", "Пределы": "Limits",
    "Самолёт": "Aircraft", "Предельная IAS": "IAS limit", "Предельный Mach": "Mach limit",
    "Предел +G · оценка": "+G limit · estimate", "Предел −G · оценка": "−G limit · estimate",
    "Скорость выпуска шасси": "Gear deployment speed", "Посадочные закрылки": "Landing flaps",
    "Обновить базу": "Update database", "Свои пороги": "Custom limits", "Автоматические пределы из базы": "Automatic limits from database",
    "Настройки": "Settings", "ОФОРМЛЕНИЕ ПРОГРАММЫ": "APP APPEARANCE", "Оформление программы": "App appearance",
    "ГЛОБАЛЬНЫЕ КЛАВИШИ": "GLOBAL HOTKEYS", "Язык интерфейса": "Interface language", "Клавиши": "Hotkeys",
    "Проверить обновления": "Check for updates", "ОБНОВЛЕНИЯ": "UPDATES", "ОБНОВЛЕНИЕ": "UPDATE",
    "Поведение HUD": "HUD behavior", "ПОВЕДЕНИЕ HUD": "HUD BEHAVIOR", "Скрывать HUD вне вылета": "Hide HUD outside a sortie",
    "Скрывать поверх других программ": "Hide when other apps are active", "Частота данных": "Data update rate",
    "Критический AoA": "Critical AoA", "ПРЕДУПРЕЖДЕНИЯ HUD": "HUD WARNINGS", "Скорость": "Speed", "Перегрузка": "G-load",
    "Топливо": "Fuel", "Сваливание": "Stall", "Раннее предупреждение": "Early warning", "Критическое топливо": "Critical fuel",
    "ЗВУКОВЫЕ ПРЕДУПРЕЖДЕНИЯ": "AUDIO WARNINGS", "Включить звук": "Enable sound", "Громкость": "Volume",
    "Пауза между сигналами": "Alert repeat delay", "Предупреждать о топливе за": "Warn about fuel with",
    "Прослушать": "Play", "Свой WAV…": "Custom WAV…", "Стандартные сигналы": "Default sounds",
    "ТЕСТ БЕЗ ЗАПУСКА ИГРЫ": "DEMO WITHOUT THE GAME", "Тест": "Demo", "Обычный полёт": "Normal flight",
    "Превышение скорости": "Overspeed", "Высокая перегрузка": "High G-load", "Мало топлива": "Low fuel",
    "ВЕРТОЛЁТ": "HELICOPTER", "Данные вертолёта появятся после входа в бой": "Helicopter data appears after entering battle",
    "Применить макет вертолёта": "Apply helicopter layout", "Добавить в группу": "Add to group",
    "Открыть редактор": "Open editor", "Готово · Esc": "Done · Esc", "Показать HUD": "Show HUD", "Быстрое меню": "Quick menu",
    "Включите перемещение и перетащите группу прямо на экране. Закройте меню, чтобы вернуться к игре.": "Enable moving and drag a group directly on screen. Close the menu to return to the game.",
    "ИГРА НЕ НАЙДЕНА": "GAME NOT FOUND", "ОЖИДАНИЕ ИГРЫ": "WAITING FOR GAME", "ОЖИДАНИЕ БОЯ": "WAITING FOR BATTLE",
    "Подключение к игре автоматически": "Connecting to the game automatically", "Подключение к 127.0.0.1:8111 автоматически": "Connecting to 127.0.0.1:8111 automatically",
    "Самолёт определится в бою": "Aircraft will be detected in battle", "Модель ещё не получена из игры": "The game has not provided an aircraft model yet",
    "Профиль: общий": "Profile: default", "ПРОФИЛЬ: ОБЩИЙ": "PROFILE: DEFAULT", "Общий профиль": "Default profile",
    "Ракеты: направление угрозы недоступно в используемом локальном API.": "Missile direction is not available in the local API.",
    "Отмена": "Cancel", "Позже": "Later", "Применить": "Apply", "Сохранить": "Save", "Удалить": "Delete", "Сброс": "Reset",
    "Обновить": "Update", "Обновление": "Update", "Обновление WT Flight": "WT Flight update", "Скачать и установить": "Download and install",
    "Проверка обновлений": "Update check", "Проверка GitHub…": "Checking GitHub…", "Доступно обновление": "Update available",
    "Больше не напоминать об этой версии": "Do not remind me about this version", "Установить обновление": "Install update",
    "Скачивание установщика…": "Downloading installer…", "Не удалось проверить обновления": "Could not check for updates",
    "Не удалось скачать установщик: ": "Could not download installer: ", "Не удалось запустить установщик: ": "Could not start installer: ",
    "Выберите изображение PNG, JPEG, WebP или BMP.": "Choose a PNG, JPEG, WebP or BMP image.", "Затемнение фона": "Background dimming",
    "Затемнить картинку для проверки читаемости текста": "Dim the image to check text readability",
    "Создать пустую группу на макете; затем перетащите в неё нужные показатели": "Create an empty layout group, then drag metrics into it",
    "Выберите показатель и добавьте его в выделенную группу макета": "Select a metric and add it to the selected layout group",
    "Добавить выбранное поле в выделенную группу на вкладке «Расположение»": "Add the selected field to the selected group on the Layout tab",
    "Панель показывает только значения, которые локальный API War Thunder передаёт для текущей машины.": "This panel shows only values provided by War Thunder's local API for the current vehicle.",
    "Поля двигателя и ротора обновляются из игры. Выберите строку, чтобы добавить её в макет.": "Engine and rotor fields are updated from the game. Select a row to add it to the layout.",
    "Свои: ": "Custom: ", "Стандартные сигналы": "Default signals", "Файл профиля слишком большой": "Profile file is too large",
    "Удалить сохранённый конфиг «{name}»?": "Delete saved config '{name}'?", "Профиль (*.json)": "Profile (*.json)",
    "Не удалось импортировать": "Import failed", "Сохранить макет": "Save layout", "Название:": "Name:",
    "Применяется к текущему самолёту. Замену можно отменить кнопкой ↶ или Ctrl+Z на макете.": "Applies to the current aircraft. Undo with ↶ or Ctrl+Z on the layout.",
    "Кнопка «Тест» сверху включает примерные данные. На игровом HUD появится пометка ТЕСТ; автоматические звуки в этом режиме выключены.": "The Demo button above enables sample data. The HUD shows a DEMO badge; automatic sounds are disabled in this mode.",
    "Тёмный · спокойный зелёный": "Dark · calm green", "Приборный · янтарный": "Instrument · amber", "Светлый · синий акцент": "Light · blue accent", "Глубокая тёмная тема": "Deep dark theme", "Тёмная · розовый акцент": "Dark · pink accent", "Показать / скрыть HUD": "Show / hide HUD", "Перемещать HUD": "Move HUD",
    "Нажмите новое сочетание, затем ✓. Работает и в игре.": "Press a new shortcut, then ✓. It also works in-game.",
    "В редакторе: Del — удалить выделенное; Ctrl+D — копия группы; стрелки — сдвиг на 1 px, Shift+стрелки — на 10 px; Ctrl+F — поиск. Удаление работает на макете и в списке показателей группы.": "Editor: Del removes the selection; Ctrl+D duplicates a group; arrows move 1 px, Shift+arrows move 10 px; Ctrl+F searches. Delete works on the layout and in a group's metric list.",
    "Для оборотов несущего винта и редких датчиков войдите в бой: поле появится автоматически, если игра его отдаёт.": "For main rotor RPM and rare sensors, enter a battle: the field appears automatically when the game provides it.",
    "Пределы загружаются автоматически при получении модели самолёта из игры.": "Limits load automatically when the aircraft model is received from the game.",
    "В бою список обновится автоматически": "The list updates automatically in battle", "БЫСТРОЕ МЕНЮ": "QUICK MENU", "Показывать HUD": "Show HUD",
    "Ins • быстрое меню": "Ins • quick menu", "Перемещать текст мышью": "Move text with mouse",
    "Самолёт определится в бою": "Aircraft will be detected in battle", "Модель ещё не получена из игры": "The game has not provided an aircraft model yet",
    "Пределы загружаются автоматически при получении модели самолёта из игры.": "Limits load automatically when the aircraft model is received from the game.",
    "ОБЩИЙ": "DEFAULT", "ПРОФИЛЬ: ": "PROFILE: ", "Общий профиль · ожидание самолёта": "Default profile · waiting for aircraft",
    "Клавиша занята • откройте меню": "Key is busy • open the menu", "Отключено": "Disabled",
    "Клавиша занята другой программой. Выберите другую; прежняя настройка сохранена.": "This key is already used by another program. Choose another one; the previous setting was kept.",
    "Определён автоматически · ": "Detected automatically · ", "Этой модели нет в базе · ": "This model is not in the database · ",
    "Рассчитано по пустой массе и текущему топливу; подвески и экипаж не учтены.": "Estimated from empty weight and current fuel; stores and crew are not included.",
}


def tr(key: str, language: str = "en", **values) -> str:
    text = CATALOG.get(key, {}).get(language) or CATALOG.get(key, {}).get("en") or key
    return text.format(**values)

def apply_language(window: MainWindow, language: str):
    window.set_language(language)
