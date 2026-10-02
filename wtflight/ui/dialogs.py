"""Modal dialogs of the editor."""

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QVBoxLayout)

from wtflight.core.metrics import number


class LimitsDialog(QDialog):
    def __init__(self, parent, aircraft, limits):
        super().__init__(parent)
        self.setWindowTitle("Пределы самолёта")
        self.setMinimumWidth(370)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Самолёт: {aircraft}"))
        info = QLabel("Пустое поле использует предел из базы. Число задаёт ваш порог для этого самолёта.\n"
                      "Оценка G учитывает массу топлива, но не массу подвесок и экипажа.")
        info.setWordWrap(True)
        info.setObjectName("muted")
        layout.addWidget(info)
        self.auto_check = QCheckBox("Автоматические пределы из базы")
        self.auto_check.setChecked(limits.get("_auto", True))
        layout.addWidget(self.auto_check)
        automatic = parent.database.limits(aircraft, parent.sample[1])
        self.entries = {}
        for key, title in (("positive_g", "Предел +G"),
                           ("negative_g", "Предел −G"),
                           ("ias_kmh", "Предел IAS, км/ч")):
            row = QHBoxLayout()
            row.addWidget(QLabel(title))
            edit = QLineEdit()
            value = limits.get(key)
            edit.setText(str(value) if value is not None else "")
            auto_value = automatic.get(key)
            edit.setPlaceholderText(f"Авто: {auto_value:.1f}" if auto_value is not None else "Нет данных")
            row.addWidget(edit)
            self.entries[key] = edit
            layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.values = None

    def validate(self):
        values = {}
        for key, edit in self.entries.items():
            raw = edit.text().strip().replace(",", ".")
            value = number(raw) if raw else None
            if raw and value is None:
                QMessageBox.warning(self, "Пределы", "Введите число или оставьте поле пустым.")
                return
            values[key] = value
        if ((values["positive_g"] is not None and values["positive_g"] <= 1) or
                (values["negative_g"] is not None and values["negative_g"] >= 0) or
                (values["ias_kmh"] is not None and values["ias_kmh"] <= 0)):
            QMessageBox.warning(self, "Пределы", "Нужно: +G > 1, −G < 0, IAS > 0.")
            return
        values["_auto"] = self.auto_check.isChecked()
        self.values = values
        self.accept()
