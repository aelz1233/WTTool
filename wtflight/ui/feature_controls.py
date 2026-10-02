"""Flight tools and editor commands shared with the compact main window."""
import copy
import json
import math
import shutil
import time
import wave
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QMenu,
                               QMessageBox, QPushButton, QSlider, QVBoxLayout, QWidget)

from wtflight.core.alerts import AlertCooldown, alert_levels
from wtflight.core.fuel import FuelEstimator
from wtflight.core.history import LayoutHistory
from wtflight.core.metrics import metric_label, metric_value
from wtflight.core.profiles import reference_profile, validate_profile
from wtflight.ui.audio import WarningAudio
from wtflight.ui.controls import SteppedSpinBox
from wtflight.win32.foreground import game_is_foreground


class FeatureControls:
    def init_feature_state(self):
        self.history = LayoutHistory()
        self.history.record(self.settings.data["profiles"])
        self.settings.on_saved = self.history.record
        self.fuel_estimator = FuelEstimator()
        self.alert_cooldown = AlertCooldown()
        self.demo_active = False
        self.last_real_sample = ("offline", {}, {})
        self.audio = None
        self.demo_started = 0

    def target_screen(self):
        name = self.settings.data.get("screen_name")
        return next((screen for screen in QApplication.screens() if screen.name() == name), QApplication.primaryScreen())

    def build_preview_toolbar(self):
        row = QHBoxLayout()
        row.setSpacing(4)
        self.screen_box = QComboBox()
        self.screen_box.setMinimumContentsLength(7)
        self.screen_box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.screen_box.setToolTip("Монитор для игрового HUD и точного предпросмотра")
        self.screen_box.currentIndexChanged.connect(self.change_screen)
        row.addWidget(self.screen_box, 1)
        self.zoom_box = QComboBox()
        for label, value in (("Вписать", 0), ("50%", .5), ("100%", 1), ("150%", 1.5)):
            self.zoom_box.addItem(label, value)
        self.zoom_box.setToolTip("Масштаб макета. При увеличении пустой фон можно перетаскивать мышью.")
        self.zoom_box.currentIndexChanged.connect(lambda: self.canvas.set_zoom(self.zoom_box.currentData()))
        row.addWidget(self.zoom_box)
        align = QPushButton("↔")
        align.setToolTip("Выравнивание и привязка")
        menu = QMenu(align)
        for key, title in (("left", "К левому краю"), ("right", "К правому краю"),
                            ("top", "К верхнему краю"), ("bottom", "К нижнему краю"),
                            ("center_x", "По центру горизонтально"), ("center_y", "По центру вертикально"),
                            ("column", "Все группы в колонку от выбранной")):
            menu.addAction(title, lambda k=key: self.align_selected(k))
        menu.addSeparator()
        self.snap_action = menu.addAction("Привязка к краям и другим группам")
        self.snap_action.setCheckable(True)
        self.snap_action.setChecked(self.settings.data.get("snap", True))
        self.snap_action.toggled.connect(self.change_snap)
        align.setMenu(menu)
        row.addWidget(align)
        undo = QPushButton("↶")
        undo.setToolTip("Отменить · Ctrl+Z на макете")
        undo.clicked.connect(self.undo_layout)
        row.addWidget(undo)
        redo = QPushButton("↷")
        redo.setToolTip("Повторить · Ctrl+Y на макете")
        redo.clicked.connect(self.redo_layout)
        row.addWidget(redo)
        return row

    def populate_screens(self, *_):
        chosen = self.target_screen().name()
        self.screen_box.blockSignals(True)
        self.screen_box.clear()
        for index, screen in enumerate(QApplication.screens(), 1):
            size = screen.geometry().size()
            self.screen_box.addItem(f"{index} · {size.width()}×{size.height()}", screen.name())
        self.screen_box.setCurrentIndex(self.screen_box.findData(chosen))
        self.screen_box.blockSignals(False)
        self.canvas.set_screen_size(self.target_screen().geometry().size())
        self.canvas.snap_enabled = self.snap_action.isChecked()
        if hasattr(self, "overlays"):
            self.update_overlays()

    def change_screen(self):
        if not hasattr(self, "canvas") or self.screen_box.currentData() is None:
            return
        self.settings.data["screen_name"] = self.screen_box.currentData()
        self.settings.save()
        self.canvas.set_screen_size(self.target_screen().geometry().size())
        self.update_overlays()
        self.place_demo_badge()

    def change_snap(self, enabled):
        self.canvas.snap_enabled = enabled
        self.settings.data["snap"] = enabled
        self.settings.save()

    def align_selected(self, direction):
        selected = self.selected_group()
        if not selected:
            return
        view = next(v for v in self.canvas.views if v.group["id"] == selected["id"])
        size = self.canvas.virtual_size
        if direction == "column":
            y = selected["y"] * size.height()
            for group in self.groups():
                group_view = next(v for v in self.canvas.views if v.group["id"] == group["id"])
                group.update(x=selected["x"], y=min(y, size.height() - group_view.height()) / size.height())
                y += group_view.height() + 10
        elif direction in ("left", "right", "center_x"):
            selected["x"] = {"left": 0, "right": max(0, 1 - view.width() / size.width()),
                             "center_x": max(0, .5 - view.width() / (size.width() * 2))}[direction]
        else:
            selected["y"] = {"top": 0, "bottom": max(0, 1 - view.height() / size.height()),
                             "center_y": max(0, .5 - view.height() / (size.height() * 2))}[direction]
        self.layout_changed()

    def restore_history(self, groups):
        if groups is None:
            return
        self.settings.data["profiles"][self.aircraft] = groups
        self.selected_id = groups[0]["id"] if groups else None
        self.settings.save()
        self.refresh_layout()

    def undo_layout(self):
        self.restore_history(self.history.undo(self.aircraft))

    def redo_layout(self):
        self.restore_history(self.history.redo(self.aircraft))

    def add_feature_ui(self, prefs):
        prefs.addWidget(self.text("ПОВЕДЕНИЕ HUD", "eyebrow"))
        flight = self.settings.data.get("flight", {})
        self.hide_idle_check = QCheckBox("Скрывать HUD вне вылета")
        self.hide_idle_check.setChecked(flight.get("hide_idle", True))
        self.hide_other_check = QCheckBox("Скрывать поверх других программ")
        self.hide_other_check.setChecked(flight.get("hide_other", True))
        for widget in (self.hide_idle_check, self.hide_other_check):
            widget.toggled.connect(self.save_flight_options)
            prefs.addWidget(widget)
        telemetry_form = QFormLayout()
        self.telemetry_rate_box = QComboBox()
        for hz in (5, 10, 15):
            self.telemetry_rate_box.addItem(f"{hz} раз/с", hz)
        self.telemetry_rate_box.setCurrentIndex(self.telemetry_rate_box.findData(flight.get("telemetry_hz", 10)))
        self.telemetry_rate_box.setToolTip("Частота чтения локального API War Thunder. 10 раз/с подходит для большинства ПК.")
        self.telemetry_rate_box.currentIndexChanged.connect(self.save_flight_options)
        telemetry_form.addRow("Частота данных", self.telemetry_rate_box)
        self.aoa_limit_spin = SteppedSpinBox()
        self.aoa_limit_spin.setRange(5, 45)
        self.aoa_limit_spin.setSuffix("°")
        self.aoa_limit_spin.setValue(flight.get("aoa_limit", 15))
        self.aoa_limit_spin.setToolTip("Порог критического угла атаки. HUD предупредит с 90% и станет красным на самом пороге.")
        self.aoa_limit_spin.valueChanged.connect(self.save_flight_options)
        telemetry_form.addRow("Критический AoA", self.aoa_limit_spin)
        prefs.addLayout(telemetry_form)
        prefs.addWidget(self.text("ПРЕДУПРЕЖДЕНИЯ HUD", "eyebrow"))
        warning_categories = QHBoxLayout()
        self.warning_checks = {}
        for key, title in (("speed", "Скорость"), ("g", "Перегрузка"), ("fuel", "Топливо"),
                           ("stall", "Сваливание")):
            widget = QCheckBox(title)
            widget.setChecked(flight.get("warning_categories", {}).get(key, True))
            widget.toggled.connect(self.save_flight_options)
            warning_categories.addWidget(widget)
            self.warning_checks[key] = widget
        prefs.addLayout(warning_categories)
        warning_form = QFormLayout()
        self.warning_ratio_spin = SteppedSpinBox()
        self.warning_ratio_spin.setRange(75, 99)
        self.warning_ratio_spin.setSuffix(" %")
        self.warning_ratio_spin.setValue(flight.get("warning_ratio", 90))
        self.warning_ratio_spin.setToolTip("Жёлтое мигание начнётся при этом проценте от предела IAS, Mach, G или AoA.")
        self.warning_ratio_spin.valueChanged.connect(self.save_flight_options)
        warning_form.addRow("Раннее предупреждение", self.warning_ratio_spin)
        self.fuel_critical_spin = SteppedSpinBox()
        self.fuel_critical_spin.setRange(15, 300)
        self.fuel_critical_spin.setSuffix(" с")
        self.fuel_critical_spin.setValue(flight.get("fuel_critical_seconds", 60))
        self.fuel_critical_spin.setToolTip("Красное предупреждение о топливе начинается, когда остаётся меньше этого времени.")
        self.fuel_critical_spin.valueChanged.connect(self.save_flight_options)
        warning_form.addRow("Критическое топливо", self.fuel_critical_spin)
        prefs.addLayout(warning_form)
        prefs.addWidget(self.text("ЗВУКОВЫЕ ПРЕДУПРЕЖДЕНИЯ", "eyebrow"))
        self.sound_check = QCheckBox("Включить звук")
        self.sound_check.setChecked(self.settings.data.get("sound", True))
        self.sound_check.toggled.connect(self.save_flight_options)
        prefs.addWidget(self.sound_check)
        categories = QHBoxLayout()
        self.sound_checks = {}
        for key, title in (("speed", "Скорость"), ("g", "Перегрузка"), ("fuel", "Топливо"),
                           ("stall", "Сваливание")):
            widget = QCheckBox(title)
            widget.setChecked(flight.get("sound_categories", {}).get(key, True))
            widget.toggled.connect(self.save_flight_options)
            categories.addWidget(widget)
            self.sound_checks[key] = widget
        prefs.addLayout(categories)
        form = QFormLayout()
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(flight.get("volume", 65))
        self.volume_slider.valueChanged.connect(self.save_flight_options)
        form.addRow("Громкость", self.volume_slider)
        self.repeat_spin = SteppedSpinBox()
        self.repeat_spin.setRange(2, 60)
        self.repeat_spin.setSuffix(" с")
        self.repeat_spin.setValue(flight.get("repeat_seconds", 8))
        self.repeat_spin.valueChanged.connect(self.save_flight_options)
        form.addRow("Пауза между сигналами", self.repeat_spin)
        self.fuel_spin = SteppedSpinBox()
        self.fuel_spin.setRange(1, 20)
        self.fuel_spin.setSuffix(" мин")
        self.fuel_spin.setValue(flight.get("fuel_minutes", 3))
        self.fuel_spin.valueChanged.connect(self.save_flight_options)
        form.addRow("Предупреждать о топливе за", self.fuel_spin)
        prefs.addLayout(form)
        sound_test = QHBoxLayout()
        self.sound_test_kind = QComboBox()
        for key, title in (("speed", "Сигнал скорости"), ("g", "Сигнал перегрузки"), ("fuel", "Сигнал топлива"),
                           ("stall", "Сигнал сваливания")):
            self.sound_test_kind.addItem(title, key)
        sound_test.addWidget(self.sound_test_kind)
        test = QPushButton("Прослушать")
        test.clicked.connect(lambda: self.audio and self.audio.play(
            self.sound_test_kind.currentData(), self.volume_slider.value() / 100))
        sound_test.addWidget(test)
        choose_sound = QPushButton("Свой WAV…")
        choose_sound.clicked.connect(self.choose_warning_sound)
        sound_test.addWidget(choose_sound)
        reset_sound = QPushButton("Стандарт")
        reset_sound.clicked.connect(self.reset_warning_sound)
        sound_test.addWidget(reset_sound)
        prefs.addLayout(sound_test)
        self.sound_file_note = self.text("Стандартные сигналы", "muted")
        self.sound_file_note.setWordWrap(True)
        prefs.addWidget(self.sound_file_note)
        self.refresh_sound_file_note()

        page = QWidget()
        self.tabs.addTab(page, "Профили")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 12, 4, 4)
        layout.addWidget(self.text("ГОТОВЫЕ И СОХРАНЁННЫЕ МАКЕТЫ", "eyebrow"))
        self.preset_box = QComboBox()
        self.refresh_presets()
        layout.addWidget(self.preset_box)
        preset_hint = self.text("Применяется к текущему самолёту. Замену можно отменить кнопкой ↶ или Ctrl+Z на макете.", "muted")
        preset_hint.setWordWrap(True)
        layout.addWidget(preset_hint)
        actions = QHBoxLayout()
        for text, callback in (("Применить", self.apply_preset), ("Сохранить как…", self.save_preset),
                               ("Импорт…", self.import_profile), ("Экспорт…", self.export_profile)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        saved_actions = QHBoxLayout()
        self.overwrite_preset_button = QPushButton("Сохранить изменения")
        self.overwrite_preset_button.setToolTip("Перезаписать выбранный сохранённый конфиг текущим макетом")
        self.overwrite_preset_button.clicked.connect(self.overwrite_preset)
        saved_actions.addWidget(self.overwrite_preset_button)
        self.delete_preset_button = QPushButton("Удалить конфиг")
        self.delete_preset_button.setObjectName("danger")
        self.delete_preset_button.setToolTip("Удалить выбранный сохранённый конфиг")
        self.delete_preset_button.clicked.connect(self.delete_preset)
        saved_actions.addWidget(self.delete_preset_button)
        layout.addLayout(saved_actions)
        self.restore_preset_button = QPushButton("Восстановить выбранный стандартный макет")
        self.restore_preset_button.setToolTip("Вернуть исходный вариант выбранного стандартного макета для текущего самолёта. Изменение можно отменить через Ctrl+Z.")
        self.restore_preset_button.clicked.connect(self.restore_standard_preset)
        layout.addWidget(self.restore_preset_button)
        self.preset_box.currentIndexChanged.connect(self.update_restore_button)
        layout.addSpacing(14)
        layout.addWidget(self.text("ТЕСТ БЕЗ ЗАПУСКА ИГРЫ", "eyebrow"))
        self.demo_scenario = QComboBox()
        for label, key in (("Обычный полёт", "normal"), ("Превышение скорости", "speed"),
                            ("Высокая перегрузка", "g"), ("Мало топлива", "fuel")):
            self.demo_scenario.addItem(label, key)
        self.demo_scenario.currentIndexChanged.connect(lambda: self.demo_active and self.demo_pulse())
        layout.addWidget(self.demo_scenario)
        test_hint = self.text("Кнопка «Тест» сверху включает примерные данные. На игровом HUD появится пометка ТЕСТ; автоматические звуки в этом режиме выключены.", "muted")
        test_hint.setWordWrap(True)
        layout.addWidget(test_hint)
        missile = self.text("Ракеты: направление угрозы недоступно в используемом локальном API.", "muted")
        missile.setWordWrap(True)
        layout.addWidget(missile)
        layout.addStretch()

    def refresh_presets(self):
        boxes = [self.preset_box]
        if hasattr(self, "main_preset_box"):
            boxes.append(self.main_preset_box)
        for box in boxes:
            box.blockSignals(True)
            box.clear()
        for key, label in (
            ("combat", "Стандарт · воздушный бой"),
            ("engine", "Двигатель · по примеру"),
            ("helicopter", "Вертолёт · базовый"),
            ("empty", "Пустой"),
        ):
            for box in boxes:
                box.addItem(label, ("builtin", key))
        for name in sorted(self.settings.data.get("saved_layouts", {})):
            for box in boxes:
                box.addItem(name, ("saved", name))
        for box in boxes:
            box.blockSignals(False)
        self.update_restore_button()

    def sync_main_preset(self, index):
        source = self.main_preset_box
        target = self.preset_box
        if self.sender() is self.preset_box:
            source, target = target, source
        target.blockSignals(True)
        target.setCurrentIndex(index)
        target.blockSignals(False)
        self.update_restore_button()

    def select_preset(self, data):
        """Select a preset by its kind and name in both mirrored selectors."""
        for box in (self.preset_box, getattr(self, "main_preset_box", None)):
            if box is None:
                continue
            for index in range(box.count()):
                item = box.itemData(index)
                if item and tuple(item) == tuple(data):
                    box.setCurrentIndex(index)
                    break

    def update_restore_button(self, *_):
        if hasattr(self, "restore_preset_button"):
            data = self.preset_box.currentData()
            self.restore_preset_button.setEnabled(bool(data and data[0] == "builtin"))
        self.update_preset_action_buttons()

    def update_preset_action_buttons(self):
        data = self.preset_box.currentData() if hasattr(self, "preset_box") else None
        enabled = bool(data and data[0] == "saved")
        for name in ("overwrite_preset_button", "delete_preset_button",
                     "overwrite_main_preset_button", "delete_main_preset_button"):
            if hasattr(self, name):
                getattr(self, name).setEnabled(enabled)

    def preset_groups(self, kind):
        return reference_profile(kind)

    def build_helicopter_tab(self):
        """Create a helicopter workspace driven by fields the local API exposes."""
        page = QWidget()
        self.tabs.addTab(page, "Вертолёт")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 14, 4, 4)
        layout.addWidget(self.text("ВЕРТОЛЁТ", "eyebrow"))
        self.helicopter_title = self.text("Данные вертолёта появятся после входа в бой", "headline")
        self.helicopter_title.setWordWrap(True)
        layout.addWidget(self.helicopter_title)
        self.helicopter_note = self.text(
            "Панель показывает только значения, которые локальный API War Thunder передаёт для текущей машины.",
            "muted")
        self.helicopter_note.setWordWrap(True)
        layout.addWidget(self.helicopter_note)
        self.helicopter_values = QListWidget()
        self.helicopter_values.setAlternatingRowColors(True)
        self.helicopter_values.setToolTip("Выберите показатель и добавьте его в выделенную группу макета")
        layout.addWidget(self.helicopter_values, 1)
        actions = QHBoxLayout()
        self.apply_helicopter_button = QPushButton("Применить макет вертолёта")
        self.apply_helicopter_button.setToolTip("Создать компактный HUD: полёт, двигатель и топливо")
        self.apply_helicopter_button.clicked.connect(self.apply_helicopter_preset)
        actions.addWidget(self.apply_helicopter_button)
        self.add_helicopter_metric_button = QPushButton("Добавить в группу")
        self.add_helicopter_metric_button.setToolTip("Добавить выбранное поле в выделенную группу на вкладке «Расположение»")
        self.add_helicopter_metric_button.clicked.connect(self.add_helicopter_metric)
        actions.addWidget(self.add_helicopter_metric_button)
        layout.addLayout(actions)
        hint = self.text("Для оборотов несущего винта и редких датчиков войдите в бой: поле появится автоматически, если игра его отдаёт.", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def apply_helicopter_preset(self):
        for box in (self.preset_box, getattr(self, "main_preset_box", None)):
            if box is None:
                continue
            for index in range(box.count()):
                data = box.itemData(index)
                if data and tuple(data) == ("builtin", "helicopter"):
                    box.setCurrentIndex(index)
                    self.apply_preset(box)
                    return

    def add_helicopter_metric(self):
        item = self.helicopter_values.currentItem() if hasattr(self, "helicopter_values") else None
        if not item:
            return
        metric_id = item.data(Qt.ItemDataRole.UserRole)
        selected = self.selected_group()
        if selected:
            self.add_to_group(selected["id"], metric_id)
        else:
            self.create_empty_group()
            self.add_to_group(self.selected_id, metric_id)

    def update_helicopter_panel(self):
        if not hasattr(self, "helicopter_values"):
            return
        mode, state, indicators = self.sample
        live = mode in ("live", "demo") and state.get("valid")
        self.helicopter_title.setText(self.database.display_name(self.aircraft) if live and self.aircraft != "default"
                                      else "Данные вертолёта появятся после входа в бой")
        self.helicopter_values.clear()
        if not live:
            self.add_helicopter_metric_button.setEnabled(False)
            return
        preferred = ["ias", "altitude", "climb", "g", "throttle", "rpm", "power", "oil_temp", "water_temp",
                     "fuel", "fuel_flow", "fuel_time", "heading"]
        raw = [metric for metric in (self.available or [])
               if metric.startswith(("state:", "indicators:")) and
               any(word in metric.casefold() for word in ("rotor", "prop", "rpm", "engine", "oil", "water", "temp"))]
        metric_ids = list(dict.fromkeys([metric for metric in preferred if metric in (self.available or [])] + raw))
        limits = self.current_limits()
        for metric_id in metric_ids:
            item = QListWidgetItem(f"{metric_label(metric_id)}   {metric_value(metric_id, state, indicators, limits)}")
            item.setData(Qt.ItemDataRole.UserRole, metric_id)
            self.helicopter_values.addItem(item)
        self.add_helicopter_metric_button.setEnabled(bool(metric_ids))
        self.helicopter_note.setText("Поля двигателя и ротора обновляются из игры. Выберите строку, чтобы добавить её в макет.")

    def restore_standard_preset(self):
        data = self.preset_box.currentData()
        if not data or data[0] != "builtin":
            return
        self.apply_preset()

    def apply_preset(self, source_box=None):
        data = (source_box or self.preset_box).currentData()
        if not data:
            return
        kind, name = data
        groups = self.preset_groups(name) if kind == "builtin" else validate_profile(
            {"format": "wt-flight-profile", "version": 1, "groups": self.settings.data["saved_layouts"][name]})
        self.settings.data["profiles"][self.aircraft] = groups
        self.selected_id = groups[0]["id"] if groups else None
        self.layout_changed()

    def save_preset(self):
        name, ok = QInputDialog.getText(self, "Сохранить макет", "Название:")
        name = name.strip()[:60]
        if ok and name:
            saved = self.settings.data.setdefault("saved_layouts", {})
            unique = name
            index = 2
            while unique in saved:
                unique = f"{name} ({index})"
                index += 1
            saved[unique] = copy.deepcopy(self.groups())
            self.settings.save()
            self.refresh_presets()
            self.select_preset(("saved", unique))

    def overwrite_preset(self, source_box=None):
        data = (source_box or self.preset_box).currentData()
        if not data or data[0] != "saved":
            return
        self.settings.data.setdefault("saved_layouts", {})[data[1]] = copy.deepcopy(self.groups())
        self.settings.save()
        self.refresh_presets()
        self.select_preset(data)

    def delete_preset(self, source_box=None):
        data = (source_box or self.preset_box).currentData()
        if not data or data[0] != "saved":
            return
        name = data[1]
        answer = QMessageBox.question(self, "Удалить конфиг", f"Удалить сохранённый конфиг «{name}»?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.settings.data.setdefault("saved_layouts", {}).pop(name, None)
        self.settings.save()
        self.refresh_presets()

    def export_profile(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт макета", "wt-profile.json", "Профиль (*.json)")
        if path:
            try:
                Path(path).write_text(json.dumps({"format": "wt-flight-profile", "version": 1,
                                                 "groups": self.groups()}, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError as error:
                QMessageBox.warning(self, "Экспорт", str(error))

    def load_profile_file(self, path):
        if Path(path).stat().st_size > 1_000_000:
            raise ValueError("Файл профиля слишком большой")
        groups = validate_profile(json.loads(Path(path).read_text(encoding="utf-8-sig")))
        self.settings.data["profiles"][self.aircraft] = groups
        self.selected_id = groups[0]["id"] if groups else None
        self.layout_changed()

    def import_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт макета", "", "Профиль (*.json)")
        if path:
            try:
                self.load_profile_file(path)
            except (OSError, ValueError, TypeError) as error:
                QMessageBox.warning(self, "Не удалось импортировать", str(error))

    def save_flight_options(self, *_):
        self.settings.data["sound"] = self.sound_check.isChecked()
        self.settings.data.setdefault("flight", {}).update({
            "hide_idle": self.hide_idle_check.isChecked(), "hide_other": self.hide_other_check.isChecked(),
            "volume": self.volume_slider.value(), "repeat_seconds": self.repeat_spin.value(),
            "fuel_minutes": self.fuel_spin.value(), "telemetry_hz": self.telemetry_rate_box.currentData(),
            "aoa_limit": self.aoa_limit_spin.value(), "warning_ratio": self.warning_ratio_spin.value(),
            "fuel_critical_seconds": self.fuel_critical_spin.value(),
            "warning_categories": {key: widget.isChecked() for key, widget in self.warning_checks.items()},
            "sound_categories": {key: widget.isChecked() for key, widget in self.sound_checks.items()}})
        self.settings.save()
        if hasattr(self, "telemetry"):
            self.telemetry.set_interval(1 / self.telemetry_rate_box.currentData())
        if self.audio and not self.settings.data["sound"]:
            self.audio.stop()
        self.update_overlays()

    def choose_warning_sound(self):
        key = self.sound_test_kind.currentData()
        path, _ = QFileDialog.getOpenFileName(self, "Выберите звук предупреждения", "",
                                               "WAV, PCM 16-bit (*.wav)")
        if not path:
            return
        try:
            source = Path(path)
            if source.stat().st_size > 20_000_000:
                raise ValueError("WAV-файл больше 20 МБ")
            with wave.open(str(source), "rb") as wav:
                if (wav.getcomptype() != "NONE" or wav.getsampwidth() != 2 or
                        wav.getnchannels() not in (1, 2) or not 8000 <= wav.getframerate() <= 48000 or
                        wav.getnframes() / wav.getframerate() > 30):
                    raise ValueError("Поддерживается PCM WAV: 16 бит, mono/stereo, до 30 секунд")
            folder = self.settings.directory / "sounds"
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"custom_{key}.wav"
            if source.resolve() != target.resolve():
                shutil.copyfile(source, target)
            if not self.audio or not self.audio.set_source(key, target):
                raise ValueError("Не удалось загрузить этот WAV. Проверьте формат файла.")
            self.settings.data.setdefault("flight", {}).setdefault("sound_files", {})[key] = str(target)
            self.settings.save()
            self.refresh_sound_file_note()
        except (OSError, ValueError, wave.Error, EOFError) as error:
            QMessageBox.warning(self, "Звук предупреждения", str(error))

    def reset_warning_sound(self):
        key = self.sound_test_kind.currentData()
        if self.audio:
            self.audio.reset_source(key)
        self.settings.data.setdefault("flight", {}).setdefault("sound_files", {}).pop(key, None)
        self.settings.save()
        self.refresh_sound_file_note()

    def refresh_sound_file_note(self):
        paths = self.settings.data.get("flight", {}).get("sound_files", {})
        names = [f"{key}: {Path(path).name}" for key, path in paths.items() if Path(path).is_file()]
        self.sound_file_note.setText("Свои: " + " · ".join(names) if names else "Стандартные сигналы")

    def should_show_hud(self):
        if not self.hud_visible:
            return False
        if self.overlay_editing or self.demo_active:
            return True
        flight = self.settings.data.get("flight", {})
        if flight.get("hide_idle", True) and self.sample[0] != "live":
            return False
        if flight.get("hide_other", True) and not game_is_foreground():
            return False
        return True

    def start_feature_timers(self):
        self.populate_screens()
        QApplication.instance().screenAdded.connect(self.populate_screens)
        QApplication.instance().screenRemoved.connect(self.populate_screens)
        self.demo_timer = QTimer(self)
        self.demo_timer.setInterval(300)
        self.demo_timer.timeout.connect(self.demo_pulse)
        self.visibility_timer = QTimer(self)
        self.visibility_timer.setInterval(300)
        self.visibility_timer.timeout.connect(self.update_overlays)
        self.visibility_timer.start()
        self.demo_badge = QLabel("ТЕСТ — ПРИМЕР ДАННЫХ")
        self.demo_badge.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput)
        self.demo_badge.setStyleSheet("QLabel { background: #7f4f15; color: #fff2ce; padding: 5px 12px; font-size: 13px; }")
        self.demo_badge.setAttribute(Qt.WA_ShowWithoutActivating)
        self.place_demo_badge()
        try:
            self.audio = WarningAudio(self.settings.directory, self)
            for key, path in self.settings.data.get("flight", {}).get("sound_files", {}).items():
                self.audio.set_source(key, path)
        except OSError:
            self.audio = None

    def place_demo_badge(self):
        if hasattr(self, "demo_badge"):
            self.demo_badge.adjustSize()
            screen = self.target_screen().geometry()
            self.demo_badge.move(screen.center().x() - self.demo_badge.width() // 2, screen.top() + 8)

    def stop_feature_timers(self):
        if getattr(self, "features_stopped", False):
            return
        self.features_stopped = True
        if hasattr(self, "visibility_timer"):
            self.visibility_timer.stop()
            self.demo_timer.stop()
            self.demo_badge.hide()
            self.demo_badge.deleteLater()
            try:
                QApplication.instance().screenAdded.disconnect(self.populate_screens)
                QApplication.instance().screenRemoved.disconnect(self.populate_screens)
            except (RuntimeError, TypeError):
                pass
        if self.audio:
            self.audio.stop()

    def set_demo_mode(self, enabled):
        self.demo_active = bool(enabled)
        self.demo_button.setChecked(self.demo_active)
        self.fuel_estimator.reset()
        if enabled:
            self.demo_started = time.monotonic()
            self.demo_pulse()
            self.demo_timer.start()
        else:
            self.demo_timer.stop()
            self.present_sample(*self.last_real_sample)
            self.demo_badge.hide()

    def demo_pulse(self):
        if not self.demo_active:
            return
        aircraft = self.aircraft if self.database.resolve(self.aircraft) else "f_16c_block_50"
        scenario = self.demo_scenario.currentData()
        wave = math.sin((time.monotonic() - self.demo_started) / 4)
        limits = self.database.limits(aircraft, {"Mfuel, kg": 1000})
        state = {"valid": True, "IAS, km/h": limits.get("ias_kmh", 1000) * (.96 + .07 * wave if scenario == "speed" else .6),
                 "Ny": limits.get("positive_g", 10) * (1.02 if scenario == "g" else .25),
                 "M": .85, "H, m": 3200 + wave * 100, "Vy, m/s": wave * 20,
                 "Mfuel, kg": 100 if scenario == "fuel" else 1000, "Mfuel0, kg": 3000,
                 "fuel_seconds": 50 if scenario == "fuel" else 600, "fuel_flow": 100,
                 "RPM 1": 2200, "throttle 1, %": 95, "oil temp 1, C": 85,
                 "water temp 1, C": 100, "AoA, deg": 4.5}
        self.present_sample("demo", state, {"type": aircraft, "compass": 270})
        self.plane_label.setText("ТЕСТ · " + self.database.display_name(aircraft))

    def process_audio(self):
        if not self.audio or not self.settings.data.get("sound", True) or self.demo_active or self.sample[0] != "live":
            return
        flight = self.settings.data.get("flight", {})
        if flight.get("hide_other", True) and not game_is_foreground():
            return
        levels = alert_levels(self.sample[1], self.current_limits(), flight.get("fuel_minutes", 3),
                              flight.get("aoa_limit", 15), flight.get("warning_ratio", 90) / 100,
                              flight.get("fuel_critical_seconds", 60), flight.get("warning_categories", {}))
        key = self.alert_cooldown.choose(levels, time.monotonic(), flight.get("repeat_seconds", 8),
                                         flight.get("sound_categories", {}))
        if key:
            self.audio.play(key, flight.get("volume", 20) / 100)
