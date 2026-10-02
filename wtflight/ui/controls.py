"""Spin controls with explicit, dependable step buttons."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractSpinBox, QHBoxLayout, QPushButton, QSpinBox, QWidget


class SteppedSpinBox(QWidget):
    valueChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        self.spin = QSpinBox(self)
        self.spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        row.addWidget(self.spin, 1)
        self.down_button = QPushButton("▼", self)
        self.down_button.setObjectName("stepButton")
        self.down_button.setFixedWidth(32)
        self.down_button.setToolTip("Уменьшить на один шаг")
        row.addWidget(self.down_button)
        self.up_button = QPushButton("▲", self)
        self.up_button.setObjectName("stepButton")
        self.up_button.setFixedWidth(32)
        self.up_button.setToolTip("Увеличить на один шаг")
        row.addWidget(self.up_button)
        self.down_button.clicked.connect(self.spin.stepDown)
        self.up_button.clicked.connect(self.spin.stepUp)
        self.spin.valueChanged.connect(self.valueChanged)

    def setRange(self, low, high):
        self.spin.setRange(low, high)

    def setSuffix(self, suffix):
        self.spin.setSuffix(suffix)

    def setValue(self, value):
        self.spin.setValue(value)

    def value(self):
        return self.spin.value()

    def setToolTip(self, text):
        super().setToolTip(text)
        self.spin.setToolTip(text)
