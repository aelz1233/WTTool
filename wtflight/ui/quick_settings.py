"""Compact Insert menu shown above the game without opening the editor."""

import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QFormLayout, QHBoxLayout,
                               QPushButton, QTabWidget, QVBoxLayout, QWidget)

from wtflight.core.profiles import HUD_GREEN
from wtflight.ui.controls import SteppedSpinBox
from wtflight.ui.fonts import fill_hud_font_box
from wtflight.ui.hotkey_panel import HotkeyPanel
from wtflight.ui.theme import HUD_STYLES, THEMES
from wtflight.win32.hotkey import HOTKEYS


class QuickSettings(QDialog):
    """Independent tool window; opening it never restores the main editor."""

    def __init__(self, owner):
        super().__init__(owner, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.owner = owner
        self.syncing = False
        self.setWindowTitle("WT Flight · Быстрое меню")
        self.setFixedSize(380, 520)
        self.setModal(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(9)
        header = QHBoxLayout()
        header.addWidget(owner.text("WT FLIGHT", "headline"))
        header.addStretch()
        header.addWidget(owner.text("БЫСТРОЕ МЕНЮ", "eyebrow"))
        layout.addLayout(header)
        self.plane = owner.text("Общий профиль", "muted")
        self.plane.setWordWrap(True)
        layout.addWidget(self.plane)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        hud = QWidget()
        self.tabs.addTab(hud, "HUD")
        hud_layout = QVBoxLayout(hud)
        hud_layout.setContentsMargins(2, 16, 2, 6)
        hud_layout.setSpacing(14)
        self.visible_check = QCheckBox("Показывать HUD")
        self.visible_check.toggled.connect(self.change_visibility)
        hud_layout.addWidget(self.visible_check)
        self.move_check = QCheckBox("Перемещать текст мышью")
        self.move_check.toggled.connect(self.change_editing)
        hud_layout.addWidget(self.move_check)
        hint = owner.text("Включите перемещение и перетащите группу прямо на экране. Закройте меню, чтобы вернуться к игре.", "muted")
        hint.setWordWrap(True)
        hud_layout.addWidget(hint)
        self.action_hints = owner.text("", "muted")
        self.action_hints.setWordWrap(True)
        hud_layout.addWidget(self.action_hints)
        hud_layout.addStretch()
        self.theme_box = QComboBox()
        for key, theme in THEMES.items():
            self.theme_box.addItem(theme["name"] + " · " + theme["description"], key)
        self.theme_box.currentIndexChanged.connect(self.change_theme)
        hud_layout.addWidget(owner.text("ОФОРМЛЕНИЕ ПРОГРАММЫ", "eyebrow"))
        hud_layout.addWidget(self.theme_box)

        look = QWidget()
        self.tabs.addTab(look, "Вид текста")
        look_layout = QVBoxLayout(look)
        look_layout.setContentsMargins(2, 12, 2, 6)
        self.group_box = QComboBox()
        self.group_box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.group_box.currentIndexChanged.connect(self.select_group)
        look_layout.addWidget(self.group_box)
        self.style_box = QComboBox()
        self.style_box.addItem("Текст без фона", "text")
        self.style_box.addItem("Компактная панель", "panel")
        self.font_box = QComboBox()
        fill_hud_font_box(self.font_box)
        self.size_spin = SteppedSpinBox()
        self.size_spin.setRange(10, 48)
        self.size_spin.setSuffix(" px")
        form = QFormLayout()
        form.addRow("Вид", self.style_box)
        form.addRow("Шрифт", self.font_box)
        self.hud_style_box = QComboBox()
        for key, preset in HUD_STYLES.items():
            self.hud_style_box.addItem(preset["name"], key)
        form.addRow("Готовый стиль HUD", self.hud_style_box)
        form.addRow("Размер", self.size_spin)
        look_layout.addLayout(form)
        self.shadow = QCheckBox("Тень текста")
        self.compact = QCheckBox("Короткие подписи: IAS / LDF")
        look_layout.addWidget(self.shadow)
        look_layout.addWidget(self.compact)
        colors = QHBoxLayout()
        for key, label in (("color", "Цвет значений"), ("accent", "Цвет подписей")):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, k=key: self.choose_color(k))
            colors.addWidget(button)
        look_layout.addLayout(colors)
        look_layout.addStretch()
        self.style_box.currentIndexChanged.connect(self.apply_group)
        self.font_box.currentTextChanged.connect(self.apply_group)
        self.size_spin.valueChanged.connect(self.apply_group)
        self.hud_style_box.currentIndexChanged.connect(self.apply_hud_style)
        self.shadow.toggled.connect(self.apply_group)
        self.compact.toggled.connect(self.apply_group)

        keys = QWidget()
        self.tabs.addTab(keys, "Клавиши")
        keys_layout = QVBoxLayout(keys)
        keys_layout.setContentsMargins(2, 12, 2, 0)
        self.key_panel = HotkeyPanel(owner)
        keys_layout.addWidget(self.key_panel)
        self.key_edit = self.key_panel.edits["menu"]
        self.feedback = self.key_panel.feedback
        self.history_shortcuts = []
        for keys, callback in (("Ctrl+Z", owner.undo_layout), ("Ctrl+Y", owner.redo_layout)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(callback)
            self.history_shortcuts.append(shortcut)
        actions = QHBoxLayout()
        editor = QPushButton("Открыть редактор")
        editor.clicked.connect(self.open_editor)
        actions.addWidget(editor)
        done = QPushButton("Готово · Esc")
        done.setObjectName("primary")
        done.clicked.connect(self.hide)
        actions.addWidget(done)
        layout.addLayout(actions)

    def change_theme(self):
        if not self.syncing:
            self.owner.set_theme(self.theme_box.currentData())

    def sync(self):
        self.syncing = True
        self.plane.setText(self.owner.database.display_name(self.owner.aircraft) if self.owner.aircraft != "default"
                           else "Общий профиль · ожидание самолёта")
        self.visible_check.setChecked(self.owner.hud_visible)
        self.move_check.setChecked(self.owner.overlay_editing)
        self.group_box.clear()
        for group in self.owner.groups():
            self.group_box.addItem(self.owner.group_caption(group), group["id"])
        self.group_box.setCurrentIndex(self.group_box.findData(self.owner.selected_id))
        self.key_panel.sync()
        self.action_hints.setText("\n".join(f"{self.owner.configured_hotkey(key) or 'Отключено'}  ·  {HOTKEYS[key][0]}"
                                          for key in ("hud", "move", "editor")))
        self.theme_box.setCurrentIndex(self.theme_box.findData(self.owner.settings.data.get("theme", "graphite")))
        self.syncing = False
        self.sync_group()

    def sync_group(self):
        self.syncing = True
        group = self.owner.selected_group()
        for widget in (self.style_box, self.font_box, self.size_spin, self.shadow, self.compact,
                       self.hud_style_box):
            widget.setEnabled(bool(group))
        if group:
            self.style_box.setCurrentIndex(0 if group.get("style") == "text" else 1)
            self.font_box.setCurrentText(group.get("font_family", "Consolas"))
            self.hud_style_box.setCurrentIndex(self.hud_style_box.findData(group.get("hud_style", "wtrti")))
            self.size_spin.setValue(group.get("size", 18))
            self.shadow.setChecked(group.get("shadow", True))
            self.compact.setChecked(group.get("compact_labels", True))
        self.syncing = False

    def select_group(self):
        if not self.syncing:
            self.owner.select_group(self.group_box.currentData())
            self.sync_group()

    def apply_group(self):
        group = self.owner.selected_group()
        if self.syncing or not group:
            return
        selected = [g for g in self.owner.groups() if g["id"] in self.owner.canvas.selected_ids]
        targets = selected if len(selected) > 1 else [group]
        values = dict(style=self.style_box.currentData(), font_family=self.font_box.currentText(),
                      size=self.size_spin.value(), shadow=self.shadow.isChecked(),
                      compact_labels=self.compact.isChecked())
        field = {self.style_box: "style", self.font_box: "font_family", self.size_spin: "size",
                 self.shadow: "shadow", self.compact: "compact_labels"}.get(self.sender())
        changes = {field: values[field]} if field else values
        for target in targets:
            target.update(changes)
            target["hud_style"] = "custom"
        self.owner.settings.save()
        self.owner.select_group(group["id"], preserve_selection=True)
        self.owner.canvas.set_sample(self.owner.sample, self.owner.current_limits())
        self.owner.update_overlays()

    def apply_hud_style(self):
        if self.syncing:
            return
        key = self.hud_style_box.currentData()
        if key not in HUD_STYLES:
            return
        selected = [g for g in self.owner.groups() if g["id"] in self.owner.canvas.selected_ids]
        group = self.owner.selected_group()
        for target in selected or ([group] if group else []):
            values = copy.deepcopy(HUD_STYLES[key])
            values.pop("name", None)
            target.update(values)
            target["hud_style"] = key
        if group:
            self.owner.settings.save()
            self.sync_group()
            self.owner.canvas.set_sample(self.owner.sample, self.owner.current_limits())
            self.owner.update_overlays()

    def choose_color(self, key):
        group = self.owner.selected_group()
        if not group:
            return
        color = QColorDialog.getColor(QColor(group.get(key, HUD_GREEN)), self, "Цвет HUD")
        if color.isValid():
            group[key] = color.name()
            self.owner.settings.save()
            self.owner.canvas.set_sample(self.owner.sample, self.owner.current_limits())
            self.owner.update_overlays()

    def change_visibility(self, visible):
        if not self.syncing:
            self.owner.hud_visible = visible
            if not visible:
                self.move_check.setChecked(False)
            self.owner.update_overlays()

    def change_editing(self, editing):
        if not self.syncing:
            self.owner.set_overlay_editing(editing)

    def apply_hotkey(self):
        self.key_panel.apply("menu")

    def open_editor(self):
        self.hide()
        self.owner.open_editor()

    def hideEvent(self, event):
        self.owner.set_overlay_editing(False)
        super().hideEvent(event)
