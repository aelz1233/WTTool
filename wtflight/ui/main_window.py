"""Main editor window: layout preview, text style, aircraft data, settings and tray."""

from __future__ import annotations

import copy
import subprocess
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QEvent, QIODevice, QRect, QSaveFile, Qt, QTimer, QUrl
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QIcon, QImageReader, QKeySequence,
                           QPainter, QPixmap, QShortcut)
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QCheckBox, QColorDialog, QComboBox,
                               QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QKeySequenceEdit,
                               QLabel, QLineEdit, QListWidget, QMainWindow, QMenu, QMessageBox,
                               QProgressDialog, QPushButton, QScrollArea, QSlider, QSystemTrayIcon,
                               QTabWidget, QVBoxLayout, QWidget)

from wtflight import GITHUB_RELEASES, __version__ as APP_VERSION
from wtflight.core.aircraft import AircraftDatabase, normalized_id
from wtflight.core.alerts import add_margins
from wtflight.core.metrics import METRICS, available_metrics, metric_label, number
from wtflight.core.profiles import HUD_LABELS, default_profile, new_group
from wtflight.core.settings import Settings
from wtflight.paths import DEFAULT_BACKGROUND
from wtflight.services.telemetry import Telemetry
from wtflight.services.updates import DatabaseUpdater, InstallerDownloader, UpdateChecker, version_tuple
from wtflight.ui.canvas import ScreenCanvas
from wtflight.ui.controls import SteppedSpinBox
from wtflight.ui.dialogs import LimitsDialog
from wtflight.ui.feature_controls import FeatureControls
from wtflight.ui.fonts import fill_hud_font_box
from wtflight.ui.group_view import GroupView
from wtflight.ui.hotkey_panel import HotkeyPanel
from wtflight.ui.i18n import EN
from wtflight.ui.metric_list import MetricList
from wtflight.ui.overlay import OverlayWindow
from wtflight.ui.quick_settings import QuickSettings
from wtflight.ui.theme import HUD_STYLES, INK, STYLE, THEMES, theme_style
from wtflight.win32.hotkey import HOTKEYS, GlobalHotkey


class MainWindow(FeatureControls, QMainWindow):
    def __init__(self, start_background_updates=True, settings_path=None):
        super().__init__()
        self.settings = Settings(settings_path)
        self.init_feature_state()
        self.database = AircraftDatabase.load(self.settings.directory)
        self.db_updater = None
        self.update_checker = None
        self.installer_downloader = None
        self.update_progress = None
        self.database_status = "локальная копия"
        self.aircraft = "default"
        self.sample = ("offline", {}, {})
        self.available = None
        self.selected_id = None
        self.overlays = []
        self.hud_visible = False
        self.overlay_editing = False
        self.loading_inspector = False
        self.setWindowTitle("WT Flight · Редактор HUD")
        self.resize(720, 560)
        self.setMinimumSize(640, 520)
        self.build_ui()
        self.set_language(self.settings.data.get("language", "en"), save=False)
        self.set_theme(self.settings.data.get("theme", "graphite"))
        self.install_editor_shortcuts()
        QApplication.instance().installEventFilter(self)
        self.restore_background()
        self.build_tray()
        self.refresh_palette()
        if self.groups():
            self.selected_id = self.groups()[0]["id"]
        self.refresh_layout()
        self.hotkeys = {}
        self.hotkey_errors = {}
        for action in HOTKEYS:
            binding = GlobalHotkey(lambda key=action: self.dispatch_hotkey(key))
            self.hotkeys[action] = binding
            sequence = self.configured_hotkey(action)
            ok, error = binding.register(sequence) if sequence else (True, "")
            self.hotkey_errors[action] = error
        self.hotkey = self.hotkeys["menu"]
        self.hotkey_error = self.hotkey_errors["menu"]
        self.hotkey_hint.setText(f"{self.hotkey.sequence} • быстрое меню" if not self.hotkey_error else
                                "Клавиша занята • откройте меню")
        self.quick_settings = QuickSettings(self)
        # Quick menu is created after the main window; apply the selected language to it too.
        self.set_language(self.settings.data.get("language", "en"), save=False)
        self.main_key_panel.sync()
        self.settings.save()
        interval = 1 / self.settings.data.get("flight", {}).get("telemetry_hz", 10)
        self.telemetry = Telemetry(interval)
        self.telemetry.sample.connect(self.on_sample)
        self.telemetry.start()
        self.start_feature_timers()
        self.update_aircraft_panel()
        if start_background_updates and time.time() - self.settings.data.get("database_checked_at", 0) > 86400:
            self.check_database_update()
        if start_background_updates and not self.settings.data.get("updates_disabled"):
            self.check_for_updates(silent=True)

    def groups(self):
        return self.settings.groups(self.aircraft)

    def configured_hotkey(self, action):
        saved = self.settings.data.get("hotkeys", {})
        if action in saved:
            return saved[action]
        return self.settings.data.get("menu_hotkey", "Ins") if action == "menu" else HOTKEYS[action][1]

    def dispatch_hotkey(self, action):
        focus = QApplication.focusWidget() if QApplication.activeWindow() else None
        while focus:
            if isinstance(focus, QKeySequenceEdit):
                focus.setKeySequence(QKeySequence(self.hotkeys[action].sequence))
                return
            focus = focus.parentWidget()
        {"menu": self.toggle_quick_settings, "hud": self.toggle_hud,
         "move": self.toggle_move_hotkey, "editor": self.open_editor}[action]()

    def apply_hotkey(self, action, sequence):
        if not sequence:
            if action == "menu":
                return False, "Назначьте клавишу для меню."
            self.hotkeys[action].disable()
        else:
            try:
                sequence, _flags, _vk = GlobalHotkey.decode(sequence)
            except ValueError as error:
                return False, str(error)
            for key, binding in self.hotkeys.items():
                if key != action and binding.sequence == sequence:
                    return False, "Уже назначено: " + HOTKEYS[key][0]
            ok, error = self.hotkeys[action].register(sequence)
            if not ok:
                return False, error
        self.settings.data.setdefault("hotkeys", {})[action] = sequence
        self.hotkey_errors[action] = ""
        if action == "menu":
            self.settings.data["menu_hotkey"] = sequence
            self.hotkey_error = ""
            self.hotkey_hint.setText(f"{sequence} • быстрое меню")
        self.settings.save()
        self.main_key_panel.sync(action)
        self.quick_settings.key_panel.sync(action)
        return True, ""

    def close_hotkeys(self):
        for binding in self.hotkeys.values():
            binding.close()

    def toggle_move_hotkey(self):
        if not self.quick_settings.isVisible():
            self.toggle_quick_settings()
        self.set_overlay_editing(not self.overlay_editing)
        self.quick_settings.sync()
        self.quick_settings.tabs.setCurrentIndex(0)

    def set_theme(self, theme):
        theme = theme if theme in THEMES else "graphite"
        self.settings.data["theme"] = theme
        QApplication.instance().setProperty("theme", theme)
        QApplication.instance().setStyleSheet(theme_style(STYLE, theme))
        for key, button in self.theme_buttons.items():
            button.setChecked(key == theme)
        self.theme_description.setText(THEMES[theme]["description"])
        if hasattr(self, "quick_settings"):
            self.quick_settings.theme_box.blockSignals(True)
            self.quick_settings.theme_box.setCurrentIndex(self.quick_settings.theme_box.findData(theme))
            self.quick_settings.theme_box.blockSignals(False)
        self.refresh_palette()
        self.settings.save()

    def install_editor_shortcuts(self):
        self.editor_shortcuts = []
        def bind(keys, widget, callback, context=Qt.WidgetWithChildrenShortcut):
            shortcut = QShortcut(QKeySequence(keys), widget)
            shortcut.setContext(context)
            shortcut.activated.connect(callback)
            self.editor_shortcuts.append(shortcut)
        bind("Del", self.canvas, self.delete_group)
        bind("Del", self.group_metrics, self.remove_metric)
        bind("Ctrl+D", self.canvas, self.duplicate_group)
        bind("Ctrl+A", self.canvas, self.select_all_groups)
        bind("Ctrl+F", self, self.focus_search, Qt.WindowShortcut)
        bind("Ctrl+Z", self, self.undo_layout, Qt.WindowShortcut)
        bind("Ctrl+Y", self, self.redo_layout, Qt.WindowShortcut)
        for key, dx, dy in (("Left", -1, 0), ("Right", 1, 0), ("Up", 0, -1), ("Down", 0, 1)):
            for modifier, step in (("", 1), ("Shift+", 10)):
                bind(modifier + key, self.canvas, lambda x=dx * step, y=dy * step: self.nudge_group(x, y))

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Wheel:
            return super().eventFilter(watched, event)
        modifiers = event.modifiers() | QApplication.keyboardModifiers()

        # A wheel over controls must never silently change the selected font, size,
        # spacing, zoom or another setting. Use clicks and keyboard for those fields.
        if isinstance(watched, (QComboBox, QAbstractSpinBox, QSlider)):
            event.accept()
            return True

        if modifiers & Qt.ControlModifier:
            widget = watched if isinstance(watched, QWidget) else None
            if widget is None:
                widget = QApplication.widgetAt(event.globalPosition().toPoint())
            in_editor = False
            while widget:
                if isinstance(widget, GroupView) and widget.editor:
                    in_editor = True
                    break
                if widget is self.canvas.viewport() or widget is self.canvas:
                    in_editor = True
                    break
                widget = widget.parentWidget()
            if in_editor:
                group = self.selected_group()
                delta = event.angleDelta().y() or event.pixelDelta().y()
                if group and delta:
                    steps = max(1, round(abs(delta) / (120 if event.angleDelta().y() else 40)))
                    direction = 1 if delta > 0 else -1
                    for selected in self.groups():
                        if selected["id"] not in self.canvas.selected_ids:
                            continue
                        selected["size"] = max(10, min(48, int(selected.get("size", 18)) + direction * steps))
                    self.settings.save()
                    self.select_group(group["id"], preserve_selection=True)
                    self.canvas.set_sample(self.sample, self.current_limits())
                    self.canvas.position_views()
                    self.update_overlays()
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    def focus_search(self):
        self.tabs.setCurrentIndex(0)
        self.search.setFocus()
        self.search.selectAll()

    def duplicate_group(self):
        group = self.selected_group()
        if not group:
            return
        duplicate = copy.deepcopy(group)
        duplicate.update(id=uuid.uuid4().hex[:10], x=min(.9, group["x"] + .025), y=min(.9, group["y"] + .025))
        self.groups().append(duplicate)
        self.selected_id = duplicate["id"]
        self.layout_changed()

    def select_all_groups(self):
        self.canvas.set_selection({group["id"] for group in self.groups()})
        self.select_group(self.canvas.selected_id, preserve_selection=True)

    def nudge_group(self, dx, dy):
        group = self.selected_group()
        if group:
            view = next(v for v in self.canvas.views if v.group["id"] == group["id"])
            self.canvas.move_selected_by(view, view.x() + dx, view.y() + dy, snap=False)
            self.settings.save()
            self.canvas.position_views()
            self.update_overlays()

    def current_limits(self):
        overrides = self.settings.limits(self.aircraft)
        live_type = normalized_id(self.sample[2].get("type")) if self.sample[0] in ("live", "demo") else ""
        limits = (self.database.limits(live_type, self.sample[1], self.sample[2])
                  if live_type and overrides.get("_auto", True) else {})
        for key, value in overrides.items():
            if not key.startswith("_") and number(value) is not None:
                limits[key] = number(value)
        if number(overrides.get("positive_g")) is not None and number(overrides.get("negative_g")) is not None:
            limits.pop("_g_estimate", None)
        if number(overrides.get("ias_kmh")) is not None:
            limits.pop("_sweep_conservative", None)
        if limits:
            limits["_fuel_minutes"] = self.settings.data.get("flight", {}).get("fuel_minutes", 3)
        return limits

    def selected_group(self):
        return next((g for g in self.groups() if g["id"] == self.selected_id), None)

    def text(self, label, object_name=None):
        widget = QLabel(label)
        if object_name:
            widget.setObjectName(object_name)
        return widget

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(10)
        header = QHBoxLayout()
        header.addWidget(self.text("WT FLIGHT", "headline"))
        header.addStretch()
        self.demo_button = QPushButton("Тест")
        self.demo_button.setCheckable(True)
        self.demo_button.clicked.connect(self.set_demo_mode)
        header.addWidget(self.demo_button)
        self.update_button = QPushButton("Обновить")
        self.update_button.setToolTip("Проверить новую версию программы на GitHub")
        self.update_button.clicked.connect(self.check_for_updates)
        header.addWidget(self.update_button)
        self.status = self.text("ОЖИДАНИЕ ИГРЫ", "status")
        self.status.setProperty("offline", True)
        header.addWidget(self.status)
        outer.addLayout(header)
        self.plane_label = self.text("Подключение к игре автоматически", "muted")
        self.plane_label.setWordWrap(True)
        outer.addWidget(self.plane_label)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        layout_page = QWidget()
        self.tabs.addTab(layout_page, "Расположение")
        body = QHBoxLayout(layout_page)
        body.setContentsMargins(0, 12, 0, 0)
        body.setSpacing(12)
        left = QWidget()
        left.setFixedWidth(232)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        library_header = QHBoxLayout()
        library_header.addWidget(self.text("ПОКАЗАТЕЛИ", "eyebrow"))
        library_header.addStretch()
        self.metric_count = self.text("", "muted")
        library_header.addWidget(self.metric_count)
        ll.addLayout(library_header)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск · IAS, топливо…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh_palette)
        ll.addWidget(self.search)
        self.palette = MetricList()
        self.palette.metric_requested.connect(self.add_metric_from_catalog)
        ll.addWidget(self.palette, 1)
        self.palette_hint = self.text("Данные появятся в бою", "muted")
        self.palette_hint.setWordWrap(True)
        ll.addWidget(self.palette_hint)
        self.palette_hint.hide()
        body.addWidget(left)
        ml = QVBoxLayout()
        self.profile_label = self.text("ПРОФИЛЬ: ОБЩИЙ", "eyebrow")
        self.profile_label.setWordWrap(True)
        self.profile_label.setParent(layout_page)
        self.profile_label.hide()
        self.canvas_tools = QWidget()
        tools_layout = QVBoxLayout(self.canvas_tools)
        tools_layout.setContentsMargins(0, 4, 0, 4)
        tools_layout.addLayout(self.build_preview_toolbar())
        self.background_button = QPushButton("⋯")
        self.background_button.setFixedWidth(36)
        background_menu = QMenu(self.background_button)
        background_menu.addAction("Сохранить макет как…", self.save_preset)
        background_menu.addAction("Импорт макета…", self.import_profile)
        background_menu.addAction("Экспорт макета…", self.export_profile)
        background_menu.addSeparator()
        background_menu.addAction("Загрузить фон…", self.choose_background)
        self.remove_background_action = background_menu.addAction("Убрать фон", self.clear_background)
        background_menu.addSeparator()
        self.grid_action = background_menu.addAction("Показать сетку")
        self.grid_action.setCheckable(True)
        self.grid_action.toggled.connect(self.change_preview_grid)
        self.canvas_tools_action = background_menu.addAction("Инструменты макета")
        self.canvas_tools_action.setCheckable(True)
        self.canvas_tools_action.toggled.connect(self.canvas_tools.setVisible)
        background_menu.addSeparator()
        background_menu.addAction("Сбросить расположение", self.reset_layout)
        self.background_button.setMenu(background_menu)
        self.background_button.setToolTip("Макеты, фон, масштаб и выравнивание")
        profile_row = QHBoxLayout()
        profile_row.addWidget(self.text("Макет", "muted"))
        self.main_preset_box = QComboBox()
        self.main_preset_box.setMinimumContentsLength(18)
        self.main_preset_box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.main_preset_box.setToolTip("Готовые и сохранённые конфигурации оверлея")
        profile_row.addWidget(self.main_preset_box, 1)
        self.apply_main_preset_button = QPushButton("Применить")
        self.apply_main_preset_button.setToolTip("Применить макет к текущему профилю самолёта")
        self.apply_main_preset_button.clicked.connect(lambda: self.apply_preset(self.main_preset_box))
        profile_row.addWidget(self.apply_main_preset_button)
        self.overwrite_main_preset_button = QPushButton("Сохранить")
        self.overwrite_main_preset_button.setToolTip("Перезаписать выбранный сохранённый конфиг текущим макетом")
        self.overwrite_main_preset_button.clicked.connect(lambda: self.overwrite_preset(self.main_preset_box))
        profile_row.addWidget(self.overwrite_main_preset_button)
        self.delete_main_preset_button = QPushButton("Удалить")
        self.delete_main_preset_button.setObjectName("danger")
        self.delete_main_preset_button.setToolTip("Удалить выбранный сохранённый конфиг")
        self.delete_main_preset_button.clicked.connect(lambda: self.delete_preset(self.main_preset_box))
        profile_row.addWidget(self.delete_main_preset_button)
        profile_row.addWidget(self.background_button)
        ml.addLayout(profile_row)
        ml.addWidget(self.canvas_tools)
        self.canvas_tools.hide()
        self.canvas = ScreenCanvas()
        # The visible hint below the canvas explains selection and shortcuts. A widget
        # tooltip here masks the per-metric descriptions shown on the preview.
        self.canvas.image_dropped.connect(self.load_background)
        self.canvas.group_selected.connect(lambda group_id: self.select_group(group_id, preserve_selection=True))
        self.canvas.group_added.connect(self.add_to_group)
        self.canvas.group_created.connect(self.create_group)
        self.canvas.group_moved.connect(self.layout_changed)
        ml.addWidget(self.canvas, 1)
        background_controls = QHBoxLayout()
        background_controls.addWidget(self.text("Затемнение фона", "muted"))
        self.background_dim = QSlider(Qt.Horizontal)
        self.background_dim.setRange(0, 75)
        self.background_dim.setMaximumWidth(115)
        self.background_dim.setToolTip("Затемнить картинку для проверки читаемости текста")
        self.background_dim.valueChanged.connect(self.change_background_dimming)
        background_controls.addWidget(self.background_dim)
        background_controls.addStretch()
        tools_layout.addLayout(background_controls)
        hint = self.text("Перетащите показатель на макет · Рамка выделяет несколько", "muted")
        hint.setWordWrap(True)
        ml.addWidget(hint)
        edit_row = QHBoxLayout()
        create_group = QPushButton("＋ Группа")
        create_group.setToolTip("Создать пустую группу на макете; затем перетащите в неё нужные показатели")
        create_group.clicked.connect(self.create_empty_group)
        edit_row.addWidget(create_group)
        look = QPushButton("Оформление выбранного текста")
        look.clicked.connect(lambda: self.tabs.setCurrentIndex(1))
        edit_row.addWidget(look)
        ml.addLayout(edit_row)
        body.addLayout(ml, 1)

        appearance_scroll = QScrollArea()
        appearance_scroll.setWidgetResizable(True)
        appearance_scroll.setFrameShape(QFrame.NoFrame)
        self.tabs.addTab(appearance_scroll, "Вид текста")
        appearance = QWidget()
        appearance_scroll.setWidget(appearance)
        rl = QVBoxLayout(appearance)
        rl.setContentsMargins(2, 14, 6, 6)
        self.group_selector = QComboBox()
        self.group_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.group_selector.currentIndexChanged.connect(self.select_from_combo)
        rl.addWidget(self.group_selector)
        self.inspector_note = self.text("Выберите группу на макете", "muted")
        self.inspector_note.setWordWrap(True)
        rl.addWidget(self.inspector_note)
        form = QFormLayout()
        form.setHorizontalSpacing(22)
        form.setVerticalSpacing(9)
        self.text_details = QWidget()
        details_layout = QVBoxLayout(self.text_details)
        details_layout.setContentsMargins(0, 8, 0, 0)
        details_form = QFormLayout()
        details_form.setVerticalSpacing(9)
        details_layout.addLayout(details_form)
        self.title_edit = QLineEdit()
        self.title_edit.editingFinished.connect(self.apply_inspector)
        details_form.addRow("Название", self.title_edit)
        self.style_box = QComboBox()
        self.style_box.addItem("Текст без фона", "text")
        self.style_box.addItem("Компактная панель", "panel")
        self.style_box.currentIndexChanged.connect(self.apply_inspector)
        details_form.addRow("Отображение", self.style_box)
        self.font_box = QComboBox()
        fill_hud_font_box(self.font_box)
        self.font_box.currentTextChanged.connect(self.apply_inspector)
        form.addRow("Шрифт", self.font_box)
        self.hud_style_box = QComboBox()
        for key, preset in HUD_STYLES.items():
            self.hud_style_box.addItem(preset["name"], key)
        self.hud_style_box.currentIndexChanged.connect(self.apply_hud_style)
        form.addRow("Готовый стиль HUD", self.hud_style_box)
        self.size_slider = SteppedSpinBox()
        self.size_slider.setRange(10, 48)
        self.size_slider.setSuffix(" px")
        self.size_slider.valueChanged.connect(self.apply_inspector)
        form.addRow("Размер", self.size_slider)
        self.spacing_spin = SteppedSpinBox()
        self.spacing_spin.setRange(0, 16)
        self.spacing_spin.setSuffix(" px")
        self.spacing_spin.valueChanged.connect(self.apply_inspector)
        details_form.addRow("Между строками", self.spacing_spin)
        wheel_hint = self.text("На макете: Ctrl + колесо — размер", "muted")
        wheel_hint.setWordWrap(True)
        form.addRow(wheel_hint)
        rl.addLayout(form)
        self.text_details_button = QPushButton("Дополнительные настройки")
        self.text_details_button.setCheckable(True)
        self.text_details_button.toggled.connect(self.text_details.setVisible)
        rl.addWidget(self.text_details_button)
        rl.addWidget(self.text_details)
        self.text_details.hide()
        checks = QHBoxLayout()
        self.labels_check = QCheckBox("Подписи")
        self.title_check = QCheckBox("Название группы")
        self.compact_check = QCheckBox("IAS / LDF / CLMB")
        for check in (self.labels_check, self.title_check, self.compact_check):
            check.toggled.connect(self.apply_inspector)
            checks.addWidget(check)
        details_layout.addLayout(checks)
        effects = QHBoxLayout()
        self.bold_check = QCheckBox("Жирный")
        self.shadow_check = QCheckBox("Тень текста")
        self.outline_check = QCheckBox("Обводка")
        for check in (self.bold_check, self.shadow_check, self.outline_check):
            check.toggled.connect(self.apply_inspector)
            effects.addWidget(check)
        self.text_color = QPushButton("Цвет значений")
        self.text_color.clicked.connect(lambda: self.choose_color("color"))
        self.accent_color = QPushButton("Цвет подписей")
        self.accent_color.clicked.connect(lambda: self.choose_color("accent"))
        self.outline_color = QPushButton("Цвет обводки")
        self.outline_color.clicked.connect(lambda: self.choose_color("outline_color"))
        details_layout.addLayout(effects)
        colors = QHBoxLayout()
        colors.addWidget(self.text_color)
        colors.addWidget(self.accent_color)
        colors.addWidget(self.outline_color)
        details_layout.addLayout(colors)
        self.group_metrics = QListWidget()
        self.group_metrics.setFixedHeight(95)
        details_layout.addWidget(self.group_metrics)
        actions = QHBoxLayout()
        remove_metric = QPushButton("Убрать показатель")
        remove_metric.clicked.connect(self.remove_metric)
        actions.addWidget(remove_metric)
        delete = QPushButton("Удалить группу")
        delete.setObjectName("danger")
        delete.clicked.connect(self.delete_group)
        actions.addWidget(delete)
        limits = QPushButton("Пределы самолёта")
        limits.clicked.connect(self.edit_limits)
        actions.addWidget(limits)
        details_layout.addLayout(actions)
        rl.addStretch()

        aircraft_page = QWidget()
        self.tabs.addTab(aircraft_page, "Самолёт")
        aircraft_layout = QVBoxLayout(aircraft_page)
        aircraft_layout.setContentsMargins(4, 14, 4, 4)
        self.aircraft_name = self.text("Самолёт определится в бою", "headline")
        self.aircraft_name.setWordWrap(True)
        aircraft_layout.addWidget(self.aircraft_name)
        self.aircraft_details = self.text("", "muted")
        self.aircraft_details.setWordWrap(True)
        aircraft_layout.addWidget(self.aircraft_details)
        limits_form = QFormLayout()
        limits_form.setVerticalSpacing(10)
        limits_form.setHorizontalSpacing(24)
        self.aircraft_values = {}
        for key, title in (("ias_kmh", "Предельная IAS"), ("mach", "Предельный Mach"),
                           ("positive_g", "Предел +G · оценка"), ("negative_g", "Предел −G · оценка"),
                           ("gear_kmh", "Скорость выпуска шасси"),
                           ("flaps_landing_kmh", "Посадочные закрылки")):
            value = self.text("—")
            self.aircraft_values[key] = value
            limits_form.addRow(title, value)
        aircraft_layout.addLayout(limits_form)
        self.limit_note = self.text("", "muted")
        self.limit_note.setWordWrap(True)
        aircraft_layout.addWidget(self.limit_note)
        aircraft_layout.addStretch()
        self.database_note = self.text("", "muted")
        self.database_note.setWordWrap(True)
        aircraft_layout.addWidget(self.database_note)
        db_actions = QHBoxLayout()
        self.database_update_button = QPushButton("Обновить базу")
        self.database_update_button.clicked.connect(self.check_database_update)
        db_actions.addWidget(self.database_update_button)
        custom_limits = QPushButton("Свои пороги")
        custom_limits.clicked.connect(self.edit_limits)
        db_actions.addWidget(custom_limits)
        aircraft_layout.addLayout(db_actions)

        self.build_helicopter_tab()

        preferences = QScrollArea()
        preferences.setWidgetResizable(True)
        preferences.setFrameShape(QFrame.NoFrame)
        self.tabs.addTab(preferences, "Настройки")
        preferences_body = QWidget()
        preferences.setWidget(preferences_body)
        prefs = QVBoxLayout(preferences_body)
        prefs.setContentsMargins(3, 14, 8, 6)
        prefs.addWidget(self.text("ОФОРМЛЕНИЕ ПРОГРАММЫ", "eyebrow"))
        themes_row = QHBoxLayout()
        self.theme_buttons = {}
        for key, theme in THEMES.items():
            button = QPushButton(theme["name"])
            button.setCheckable(True)
            button.setToolTip(theme["description"])
            button.clicked.connect(lambda _checked=False, name=key: self.set_theme(name))
            self.theme_buttons[key] = button
            themes_row.addWidget(button)
        prefs.addLayout(themes_row)
        self.theme_description = self.text("", "muted")
        prefs.addWidget(self.theme_description)
        prefs.addSpacing(8)
        prefs.addWidget(self.text("ГЛОБАЛЬНЫЕ КЛАВИШИ", "eyebrow"))
        self.main_key_panel = HotkeyPanel(self)
        prefs.addWidget(self.main_key_panel)
        local_help = self.text("В редакторе: Del — удалить выделенное; Ctrl+D — копия группы; "
                               "стрелки — сдвиг на 1 px, Shift+стрелки — на 10 px; Ctrl+F — поиск. "
                               "Удаление работает на макете и в списке показателей группы.", "muted")
        local_help.setWordWrap(True)
        prefs.addWidget(local_help)
        self.add_feature_ui(prefs)
        language_row = QHBoxLayout()
        language_row.addWidget(self.text("Язык интерфейса", "muted"))
        self.language_box = QComboBox()
        self.language_box.addItem("Русский", "ru")
        self.language_box.addItem("English", "en")
        self.language_box.currentIndexChanged.connect(lambda: self.set_language(self.language_box.currentData()))
        language_row.addWidget(self.language_box)
        language_row.addStretch()
        prefs.addLayout(language_row)
        updates_row = QHBoxLayout()
        self.update_check_button = QPushButton("Проверить обновления")
        self.update_check_button.clicked.connect(self.check_for_updates)
        updates_row.addWidget(self.update_check_button)
        self.update_status = self.text(f"Версия программы: {APP_VERSION}", "muted")
        updates_row.addWidget(self.update_status)
        updates_row.addStretch()
        prefs.addLayout(updates_row)
        self.main_preset_box.currentIndexChanged.connect(self.sync_main_preset)
        self.preset_box.currentIndexChanged.connect(self.sync_main_preset)
        self.refresh_presets()

        footer = QHBoxLayout()
        self.hotkey_hint = self.text("Ins • быстрое меню", "muted")
        footer.addWidget(self.hotkey_hint)
        footer.addStretch()
        quick = QPushButton("Быстрое меню")
        quick.clicked.connect(self.toggle_quick_settings)
        footer.addWidget(quick)
        start = QPushButton("Показать HUD")
        start.setObjectName("primary")
        start.clicked.connect(self.show_hud)
        footer.addWidget(start)
        outer.addLayout(footer)

    def set_language(self, language="ru", save=True):
        language = language if language in ("ru", "en") else "ru"
        self.settings.data["language"] = language
        QApplication.instance().setProperty("language", language)
        for widget in self.findChildren(QWidget):
            original = widget.property("wt_ru_text")
            if original is None:
                if isinstance(widget, (QLabel, QPushButton, QCheckBox)) and widget.text():
                    original = widget.text()
                    widget.setProperty("wt_ru_text", original)
                elif isinstance(widget, QLineEdit) and widget.placeholderText():
                    original = widget.placeholderText()
                    widget.setProperty("wt_ru_placeholder", original)
            if original is not None and isinstance(widget, (QLabel, QPushButton, QCheckBox)):
                widget.setText(original if language == "ru" else EN.get(original, original))
            placeholder = widget.property("wt_ru_placeholder")
            if placeholder is not None and isinstance(widget, QLineEdit):
                widget.setPlaceholderText(placeholder if language == "ru" else EN.get(placeholder, placeholder))
        for index in range(self.tabs.count()):
            ru = self.tabs.tabBar().tabData(index) or self.tabs.tabText(index)
            if self.tabs.tabBar().tabData(index) is None:
                self.tabs.tabBar().setTabData(index, ru)
            self.tabs.setTabText(index, ru if language == "ru" else EN.get(ru, ru))
        if hasattr(self, "language_box"):
            self.language_box.blockSignals(True)
            self.language_box.setCurrentIndex(self.language_box.findData(language))
            self.language_box.blockSignals(False)
        if save:
            self.settings.save()
        if hasattr(self, "palette"):
            self.refresh_palette()

    def check_for_updates(self, silent=False):
        if self.update_checker and self.update_checker.isRunning():
            return
        if not silent:
            self.update_status.setText("Проверка GitHub…")
        self.update_button.setEnabled(False)
        if hasattr(self, "update_check_button"):
            self.update_check_button.setEnabled(False)
        self.update_checker = UpdateChecker()
        self.update_checker.completed.connect(lambda info, error, quiet=silent: self.on_update_checked(info, error, quiet))
        self.update_checker.start()

    def on_update_checked(self, info, error, silent=False):
        self.update_button.setEnabled(True)
        if hasattr(self, "update_check_button"):
            self.update_check_button.setEnabled(True)
        if error or not info:
            if not silent:
                self.update_status.setText("Не удалось проверить обновления")
                QMessageBox.warning(self, "Проверка обновлений", "GitHub недоступен. Проверьте интернет-соединение.")
            return
        latest = info.get("version", "")
        if version_tuple(latest) <= version_tuple(APP_VERSION):
            self.update_status.setText(f"Установлена последняя версия · {APP_VERSION}")
            if not silent:
                QMessageBox.information(self, "Обновления", f"У вас уже последняя версия {APP_VERSION}.")
            return
        self.update_status.setText(f"Доступна версия {latest}")
        if self.settings.data.get("updates_skip_version") == latest:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("Доступно обновление")
        box.setText(f"Доступна новая версия WT Flight: {latest}\nТекущая версия: {APP_VERSION}")
        box.setInformativeText("Скачайте установщик из GitHub. Он обновит программу в папке D:\\WT Flight.")
        skip = QCheckBox("Больше не напоминать об этой версии", box)
        box.setCheckBox(skip)
        download = box.addButton("Скачать и установить", QMessageBox.AcceptRole)
        box.addButton("Позже", QMessageBox.RejectRole)
        box.exec()
        if skip.isChecked():
            self.settings.data["updates_skip_version"] = latest
            self.settings.save()
        if box.clickedButton() is download:
            self.download_and_install(info)

    def download_and_install(self, info):
        asset = info.get("asset")
        if not asset:
            QDesktopServices.openUrl(QUrl(info.get("url") or GITHUB_RELEASES))
            return
        filename = f"WT-Flight-Setup-{info.get('version', 'latest')}.exe"
        self.update_progress = QProgressDialog("Скачивание установщика…", "Отмена", 0, 100, self)
        self.update_progress.setWindowTitle("Обновление WT Flight")
        self.update_progress.setAutoClose(False)
        self.update_progress.setMinimumDuration(0)
        self.update_progress.show()
        self.installer_downloader = InstallerDownloader(asset, filename)
        self.installer_downloader.progress.connect(self.update_progress.setValue)
        self.installer_downloader.completed.connect(self.on_installer_downloaded)
        self.update_progress.canceled.connect(self.installer_downloader.terminate)
        self.installer_downloader.start()

    def on_installer_downloaded(self, path, error):
        if self.update_progress:
            self.update_progress.close()
        if error or not path or not Path(path).is_file():
            QMessageBox.warning(self, "Обновление", "Не удалось скачать установщик: " + (error or "файл не найден"))
            return
        answer = QMessageBox.question(
            self, "Установить обновление", "Установщик скачан. Закрыть WT Flight и запустить установку сейчас?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            return
        try:
            subprocess.Popen([path], cwd=str(Path(path).parent))
            QTimer.singleShot(250, QApplication.instance().quit)
        except OSError as error:
            QMessageBox.warning(self, "Обновление", "Не удалось запустить установщик: " + str(error))

    def select_from_combo(self):
        self.select_group(self.group_selector.currentData())

    def update_aircraft_panel(self):
        limits = self.current_limits()
        aircraft = self.aircraft
        known = self.database.resolve(aircraft)
        self.aircraft_name.setText(self.database.display_name(aircraft) if aircraft != "default"
                                   else "Самолёт определится в бою")
        self.aircraft_details.setText(
            ("Определён автоматически · " + aircraft) if known else
            "Модель ещё не получена из игры" if aircraft == "default" else
            "Этой модели нет в базе · " + aircraft)
        for key, label in self.aircraft_values.items():
            value = limits.get(key)
            text = "—"
            if value is not None:
                if key.endswith("g"):
                    text = ("≈ " if limits.get("_g_estimate") else "") + f"{value:+.1f} G"
                elif key == "mach":
                    text = f"{value:.2f} M"
                else:
                    text = f"{value:.0f} км/ч"
            label.setText(text)
        notes = []
        if limits.get("_g_estimate"):
            notes.append("G рассчитана по пустой массе и текущему топливу; подвески и экипаж не учтены.")
        if limits.get("_sweep_conservative"):
            notes.append("Стреловидность неизвестна: для IAS / Mach взят минимальный предел из таблицы крыла.")
        if not notes:
            notes.append("Пределы загружаются автоматически при получении модели самолёта из игры.")
        self.limit_note.setText(" ".join(notes))
        if not self.db_updater or not self.db_updater.isRunning():
            self.database_note.setText(f"База {self.database.version} · {len(self.database.models)} моделей · {self.database_status}")

    def check_database_update(self):
        if self.db_updater and self.db_updater.isRunning():
            return
        self.database_update_button.setEnabled(False)
        self.database_note.setText(f"База {self.database.version} · проверка обновления…")
        self.db_updater = DatabaseUpdater(self.settings.directory, self.database.version)
        self.db_updater.completed.connect(self.on_database_update)
        self.db_updater.start()

    def on_database_update(self, database, error):
        self.database_update_button.setEnabled(True)
        if database:
            self.database = database
        self.database_status = ("нет связи, локальная копия" if error else "последняя доступная версия")
        self.settings.data["database_checked_at"] = time.time()
        self.settings.save()
        if self.demo_active:
            self.demo_pulse()
        else:
            self.present_sample(*self.last_real_sample)
        self.database_note.setText(f"База {self.database.version} · {self.database_status}")
        self.database_note.setToolTip(error or "https://github.com/SpaceCapo/warthunder-byo-fm")

    def restore_background(self):
        preview = self.settings.data.get("preview", {})
        self.background_dim.setValue(int(preview.get("dimming", 22)))
        self.grid_action.setChecked(bool(preview.get("grid", False)))
        path = preview.get("image")
        default = DEFAULT_BACKGROUND
        if path is None and default.is_file():
            self.load_background(str(default))
            return
        if path:
            self.canvas.set_background(QPixmap(path))
        self.remove_background_action.setEnabled(not self.canvas.background.isNull())

    def choose_background(self):
        path, _ = QFileDialog.getOpenFileName(self, "Фон предпросмотра — выберите скриншот", "",
                                            "Изображения (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.load_background(path)

    def load_background(self, path):
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            QMessageBox.warning(self, "Не удалось открыть фон", "Выберите изображение PNG, JPEG, WebP или BMP.")
            return False
        if image.width() > 2560 or image.height() > 2560:
            image = image.scaled(2560, 2560, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        target = self.settings.directory / "preview_background.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        output = QSaveFile(str(target))
        if not output.open(QIODevice.WriteOnly) or not image.save(output, "PNG") or not output.commit():
            QMessageBox.warning(self, "Не удалось сохранить фон", "Не удалось сохранить изображение в папке настроек.")
            return False
        self.settings.data.setdefault("preview", {})["image"] = str(target)
        self.settings.save()
        self.canvas.set_background(QPixmap.fromImage(image))
        self.remove_background_action.setEnabled(True)
        return True

    def clear_background(self):
        self.settings.data.setdefault("preview", {})["image"] = ""
        self.settings.save()
        self.canvas.set_background(QPixmap())
        self.remove_background_action.setEnabled(False)

    def change_background_dimming(self, value):
        self.canvas.dimming = value
        self.canvas.viewport().update()
        self.settings.data.setdefault("preview", {})["dimming"] = value
        self.settings.save()

    def change_preview_grid(self, enabled):
        self.canvas.show_grid = enabled
        self.canvas.viewport().update()
        self.settings.data.setdefault("preview", {})["grid"] = enabled
        self.settings.save()

    def sync_group_selector(self):
        self.group_selector.blockSignals(True)
        self.group_selector.clear()
        for group in self.groups():
            self.group_selector.addItem(self.group_caption(group), group["id"])
        self.group_selector.setCurrentIndex(self.group_selector.findData(self.selected_id))
        self.group_selector.blockSignals(False)

    @staticmethod
    def group_caption(group):
        return " / ".join(HUD_LABELS.get(m, metric_label(m)) for m in group["metrics"])

    def build_tray(self):
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor("#57e0c3"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(2, 2, 60, 60, 14, 14)
        painter.setPen(QColor("#0b1725"))
        painter.setFont(QFont("Segoe UI", 25, QFont.Bold))
        painter.drawText(QRect(0, 0, 64, 64), Qt.AlignCenter, "W")
        painter.end()
        self.tray = QSystemTrayIcon(QIcon(pixmap), self)
        menu = QMenu()
        menu.addAction("Быстрое меню настроек", self.toggle_quick_settings)
        menu.addAction("Открыть редактор", self.open_editor)
        menu.addAction("Показать / скрыть HUD", self.toggle_hud)
        menu.addSeparator()
        menu.addAction("Выход", self.exit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.open_editor()
                            if reason == QSystemTrayIcon.DoubleClick else None)
        self.tray.show()

    def refresh_palette(self):
        if not hasattr(self, "palette"):
            return
        query = self.search.text().casefold()
        ids = self.available if self.available is not None else list(METRICS)
        count = self.palette.populate(ids, query)
        self.metric_count.setText(str(count))
        self.palette_hint.setText("Ничего не найдено" if count == 0 else
                                 "Доступно на этом самолёте" if self.available is not None else
                                 "В бою список обновится автоматически")

    def refresh_layout(self):
        self.profile_label.setText("ПРОФИЛЬ: " + (self.aircraft if self.aircraft != "default" else "ОБЩИЙ"))
        self.canvas.set_groups(self.groups())
        self.canvas.set_sample(self.sample, self.current_limits())
        self.sync_group_selector()
        self.select_group(self.selected_id, preserve_selection=True)
        self.rebuild_overlays()
        if hasattr(self, "quick_settings") and self.quick_settings.isVisible():
            self.quick_settings.sync()

    def select_group(self, group_id, preserve_selection=False):
        group_id = group_id or None
        self.selected_id = group_id
        if not preserve_selection or group_id not in self.canvas.selected_ids:
            self.canvas.select(group_id)
        self.group_selector.blockSignals(True)
        self.group_selector.setCurrentIndex(self.group_selector.findData(group_id))
        self.group_selector.blockSignals(False)
        group = self.selected_group()
        self.loading_inspector = True
        self.group_metrics.clear()
        if group:
            self.inspector_note.setText("Изменения сразу применяются к HUD и сохраняются.")
            self.title_edit.setText(group.get("title", ""))
            self.style_box.setCurrentIndex(0 if group.get("style") == "text" else 1)
            self.labels_check.setChecked(bool(group.get("labels", True)))
            self.title_check.setChecked(bool(group.get("title_visible", False)))
            self.size_slider.setValue(int(group.get("size", 20)))
            self.font_box.setCurrentText(group.get("font_family", "Consolas"))
            self.spacing_spin.setValue(group.get("spacing", 1))
            self.compact_check.setChecked(group.get("compact_labels", True))
            self.bold_check.setChecked(group.get("bold", True))
            self.shadow_check.setChecked(group.get("shadow", True))
            self.outline_check.setChecked(group.get("outline", True))
            self.hud_style_box.blockSignals(True)
            self.hud_style_box.setCurrentIndex(self.hud_style_box.findData(group.get("hud_style", "wtrti")))
            self.hud_style_box.blockSignals(False)
            for metric_id in group.get("metrics", []):
                self.group_metrics.addItem(metric_label(metric_id))
        else:
            self.inspector_note.setText("Выберите блок на макете, чтобы изменить его вид.")
            self.title_edit.clear()
        self.loading_inspector = False

    def apply_inspector(self, *_args):
        if self.loading_inspector:
            return
        group = self.selected_group()
        if not group:
            return
        group.update(title=self.title_edit.text().strip() or "БЛОК",
                     style=self.style_box.currentData(), labels=self.labels_check.isChecked(),
                     title_visible=self.title_check.isChecked(), size=self.size_slider.value(),
                     font_family=self.font_box.currentText(),
                     spacing=self.spacing_spin.value(), compact_labels=self.compact_check.isChecked(),
                     bold=self.bold_check.isChecked(), shadow=self.shadow_check.isChecked(),
                     outline=self.outline_check.isChecked())
        if self.sender() in (self.font_box, self.bold_check, self.shadow_check, self.outline_check):
            group["hud_style"] = "custom"
            self.hud_style_box.blockSignals(True)
            self.hud_style_box.setCurrentIndex(-1)
            self.hud_style_box.blockSignals(False)
        field = {self.size_slider: "size", self.font_box: "font_family", self.style_box: "style",
                 self.spacing_spin: "spacing", self.labels_check: "labels", self.title_check: "title_visible",
                 self.compact_check: "compact_labels", self.bold_check: "bold",
                 self.shadow_check: "shadow", self.outline_check: "outline"}.get(self.sender())
        if field:
            for selected in self.groups():
                if selected["id"] in self.canvas.selected_ids:
                    selected[field] = group[field]
                    if field in ("font_family", "bold", "shadow", "outline"):
                        selected["hud_style"] = "custom"
        self.settings.save()
        self.canvas.set_sample(self.sample, self.current_limits())
        self.update_overlays()

    def choose_color(self, key):
        group = self.selected_group()
        if not group:
            return
        color = QColorDialog.getColor(QColor(group.get(key, INK)), self, "Цвет HUD")
        if color.isValid():
            group[key] = color.name()
            if key in ("color", "accent", "outline_color"):
                group["hud_style"] = "custom"
                self.hud_style_box.blockSignals(True)
                self.hud_style_box.setCurrentIndex(-1)
                self.hud_style_box.blockSignals(False)
            self.settings.save()
            self.canvas.set_sample(self.sample, self.current_limits())
            self.update_overlays()

    def apply_hud_style(self, *_):
        if self.loading_inspector:
            return
        group = self.selected_group()
        key = self.hud_style_box.currentData()
        if not group or key not in HUD_STYLES:
            return
        values = copy.deepcopy(HUD_STYLES[key])
        values.pop("name", None)
        values["hud_style"] = key
        for target in self.groups():
            if target["id"] in self.canvas.selected_ids or target is group:
                target.update(values)
        self.loading_inspector = True
        self.font_box.setCurrentText(group["font_family"])
        self.bold_check.setChecked(group["bold"])
        self.shadow_check.setChecked(group["shadow"])
        self.outline_check.setChecked(group["outline"])
        self.loading_inspector = False
        self.layout_changed()

    def create_group(self, metric_id, x, y):
        group = new_group(metric_id, max(0, min(0.85, x)), max(0, min(0.85, y)))
        group["title"] = metric_label(metric_id)
        self.groups().append(group)
        self.selected_id = group["id"]
        self.layout_changed()

    def create_empty_group(self):
        """Create a visible drop target without forcing an unrelated metric into it."""
        index = len(self.groups())
        group = new_group("ias", 0.08 + (index // 6 % 3) * 0.24, 0.10 + (index % 6) * 0.12)
        group.update(title="НОВАЯ ГРУППА", metrics=[], title_visible=True)
        self.groups().append(group)
        self.selected_id = group["id"]
        self.layout_changed()

    def add_to_group(self, group_id, metric_id):
        group = next((g for g in self.groups() if g["id"] == group_id), None)
        if group and metric_id not in group["metrics"]:
            group["metrics"].append(metric_id)
            self.selected_id = group_id
            self.layout_changed()

    def add_metric_from_catalog(self, metric_id):
        index = len(self.groups())
        self.create_group(metric_id, 0.08 + (index // 6 % 3) * 0.24, 0.10 + (index % 6) * 0.12)

    def remove_metric(self):
        group = self.selected_group()
        row = self.group_metrics.currentRow()
        if not group or row < 0:
            return
        group["metrics"].pop(row)
        if not group["metrics"]:
            self.groups().remove(group)
            self.selected_id = None
        self.layout_changed()

    def delete_group(self):
        ids = set(self.canvas.selected_ids)
        if not ids and self.selected_id:
            ids.add(self.selected_id)
        if ids:
            self.groups()[:] = [group for group in self.groups() if group["id"] not in ids]
            self.selected_id = None
            self.layout_changed()

    def layout_changed(self):
        self.settings.save()
        self.refresh_layout()

    def reset_layout(self):
        self.settings.data["profiles"][self.aircraft] = default_profile()
        self.selected_id = self.groups()[0]["id"]
        self.layout_changed()

    def edit_limits(self):
        dialog = LimitsDialog(self, self.aircraft, self.settings.limits(self.aircraft))
        if dialog.exec() == QDialog.Accepted:
            self.settings.data.setdefault("limits", {})[self.aircraft] = dialog.values
            self.settings.save()
            self.canvas.set_sample(self.sample, self.current_limits())
            self.update_overlays()
            self.update_aircraft_panel()

    def on_sample(self, mode, state, indicators):
        self.last_real_sample = (mode, state, indicators)
        if not self.demo_active:
            self.present_sample(mode, state, indicators)

    def present_sample(self, mode, state, indicators):
        state = dict(state)
        flight = self.settings.data.get("flight", {})
        state["_fuel_minutes"] = flight.get("fuel_minutes", 3)
        state["_aoa_limit"] = flight.get("aoa_limit", 15)
        state["_warning_ratio"] = flight.get("warning_ratio", 90) / 100
        state["_warning_categories"] = dict(flight.get("warning_categories", {}))
        state["_fuel_critical_seconds"] = flight.get("fuel_critical_seconds", 60)
        if mode == "live":
            state.update(self.fuel_estimator.update(str(indicators.get("type") or ""), state.get("Mfuel, kg"), time.monotonic()))
        elif mode != "demo":
            self.fuel_estimator.reset()
        self.sample = (mode, state, indicators)
        if mode in ("live", "demo"):
            aircraft = self.aircraft if mode == "demo" else normalized_id(indicators.get("type")) or "default"
            if aircraft != self.aircraft:
                self.aircraft = aircraft
                self.settings.groups(aircraft)
                self.selected_id = self.groups()[0]["id"] if self.groups() else None
                self.refresh_layout()
            add_margins(state, self.current_limits())
            available = available_metrics(state, indicators, self.current_limits())
            if available != self.available:
                self.available = available
                self.refresh_palette()
            self.status.setText("ТЕСТ · ПРИМЕР ДАННЫХ" if mode == "demo" else "В БОЮ  ·  LIVE")
            self.status.setProperty("offline", False)
            self.plane_label.setText(self.database.display_name(aircraft) if aircraft != "default" else "Самолёт не определён")
        else:
            if self.available is not None:
                self.available = None
                self.refresh_palette()
            self.status.setText("ОЖИДАНИЕ БОЯ" if mode == "waiting" else "ИГРА НЕ НАЙДЕНА")
            self.status.setProperty("offline", True)
            self.plane_label.setText("Подключение к 127.0.0.1:8111 автоматически")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.canvas.set_sample(self.sample, self.current_limits())
        self.update_overlays()
        self.update_aircraft_panel()
        self.update_helicopter_panel()
        self.process_audio()

    def rebuild_overlays(self):
        for overlay in self.overlays:
            overlay.close()
            overlay.deleteLater()
        self.overlays = [OverlayWindow(group, self.target_screen) for group in self.groups()]
        for overlay in self.overlays:
            overlay.selected.connect(self.select_live_group)
            overlay.moved.connect(self.save_overlay_position)
            overlay.set_editing(self.overlay_editing)
        self.update_overlays()

    def select_live_group(self, group_id):
        self.select_group(group_id)
        if hasattr(self, "quick_settings"):
            self.quick_settings.sync()

    def save_overlay_position(self):
        self.settings.save()
        self.canvas.position_views()

    def set_overlay_editing(self, editing):
        if self.overlay_editing and not editing:
            self.settings.save()
        self.overlay_editing = editing
        if editing:
            self.hud_visible = True
        for overlay in self.overlays:
            overlay.set_editing(editing)
        self.update_overlays()
        if hasattr(self, "quick_settings"):
            self.quick_settings.visible_check.blockSignals(True)
            self.quick_settings.visible_check.setChecked(self.hud_visible)
            self.quick_settings.visible_check.blockSignals(False)

    def toggle_quick_settings(self):
        if self.quick_settings.isVisible():
            self.quick_settings.hide()
        else:
            self.quick_settings.sync()
            screen = QApplication.primaryScreen().availableGeometry()
            self.quick_settings.adjustSize()
            self.quick_settings.move(screen.center() - self.quick_settings.rect().center())
            self.quick_settings.show()
            self.quick_settings.raise_()
            self.quick_settings.activateWindow()
            self.quick_settings.visible_check.setFocus()

    def update_overlays(self):
        visible = self.should_show_hud()
        for overlay in self.overlays:
            overlay.set_sample(self.sample, self.current_limits())
            overlay.place()
            if visible and overlay.lines():
                overlay.show()
            else:
                overlay.hide()
        if hasattr(self, "demo_badge"):
            self.demo_badge.setVisible(visible and self.demo_active)

    def show_hud(self):
        self.hud_visible = True
        self.quick_settings.hide()
        self.hide()
        self.update_overlays()

    def toggle_hud(self):
        self.hud_visible = not self.hud_visible
        if not self.hud_visible:
            self.set_overlay_editing(False)
        self.update_overlays()
        if self.quick_settings.isVisible():
            self.quick_settings.sync()

    def open_editor(self):
        self.quick_settings.hide()
        self.hud_visible = False
        self.update_overlays()
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        event.ignore()
        self.show_hud()

    def exit_app(self):
        self.close_hotkeys()
        self.telemetry.stop()
        self.tray.hide()
        QApplication.instance().quit()

    def stop_workers(self):
        self.stop_feature_timers()
        self.telemetry.stop()
        if self.db_updater:
            self.db_updater.wait(20000)

