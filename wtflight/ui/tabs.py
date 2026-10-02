"""Top-level editor tabs.

Tabs own their widget tree while the main window remains the controller for
state and actions.  Keeping this boundary small lets more of the legacy UI be
moved out without changing the public MainWindow attributes used by plugins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget, QPushButton, QFrame

if TYPE_CHECKING:
    from wtflight.ui.main_window import MainWindow


class AircraftTab(QWidget):
    """Aircraft model, limits and database controls."""

    def __init__(self, owner: MainWindow, tabs):
        super().__init__()
        self.owner = owner
        self.tabs = tabs
        self._build()

    def _build(self):
        owner = self.owner
        tabs = self.tabs
        tabs.addTab(self, "Самолёт")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 14, 4, 4)
        owner.aircraft_name = owner.text("Самолёт определится в бою", "headline")
        owner.aircraft_name.setWordWrap(True)
        layout.addWidget(owner.aircraft_name)
        owner.aircraft_details = owner.text("", "muted")
        owner.aircraft_details.setWordWrap(True)
        layout.addWidget(owner.aircraft_details)
        limits_form = QFormLayout()
        limits_form.setVerticalSpacing(10)
        limits_form.setHorizontalSpacing(24)
        owner.aircraft_values = {}
        for key, title in (("ias_kmh", "Предельная IAS"), ("mach", "Предельный Mach"),
                           ("positive_g", "Предел +G · оценка"), ("negative_g", "Предел −G · оценка"),
                           ("gear_kmh", "Скорость выпуска шасси"),
                           ("flaps_landing_kmh", "Посадочные закрылки")):
            value = owner.text("—")
            owner.aircraft_values[key] = value
            limits_form.addRow(title, value)
        layout.addLayout(limits_form)
        owner.limit_note = owner.text("", "muted")
        owner.limit_note.setWordWrap(True)
        layout.addWidget(owner.limit_note)
        layout.addStretch()
        owner.database_note = owner.text("", "muted")
        owner.database_note.setWordWrap(True)
        layout.addWidget(owner.database_note)
        actions = QHBoxLayout()
        owner.database_update_button = QPushButton("Обновить базу")
        owner.database_update_button.clicked.connect(owner.check_database_update)
        actions.addWidget(owner.database_update_button)
        custom_limits = QPushButton("Свои пороги")
        custom_limits.clicked.connect(owner.edit_limits)
        actions.addWidget(custom_limits)
        layout.addLayout(actions)


class SettingsTab(QScrollArea):
    """Scroll container reserved for the application preferences controls."""

    def __init__(self, owner: MainWindow):
        super().__init__()
        self.owner = owner
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
