"""Hotkey capture field and the shared global-hotkey settings panel."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QHBoxLayout, QKeySequenceEdit, QLineEdit, QPushButton, QVBoxLayout, QWidget

from wtflight.win32.hotkey import HOTKEYS


class HotkeyCapture(QKeySequenceEdit):
    """Capture one chord without the native editor clearing globally consumed keys."""

    def __init__(self):
        super().__init__()
        self.setMaximumSequenceLength(1)
        self.installEventFilter(self)
        for child in self.findChildren(QLineEdit):
            child.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.ShortcutOverride:
            if event.key() not in (Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Escape):
                event.accept()
                return True
        if event.type() in (QEvent.KeyPress, QEvent.KeyRelease):
            key = event.key()
            if key in (Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Escape):
                return super().eventFilter(watched, event)
            if event.type() == QEvent.KeyPress:
                if key == Qt.Key_Backspace:
                    self.clear()
                elif key not in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr):
                    self.setKeySequence(QKeySequence(event.keyCombination()))
            event.accept()
            return True
        return super().eventFilter(watched, event)


class HotkeyPanel(QWidget):
    """Shared keyboard settings for the full editor and the Insert menu."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.edits = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for action, (label, default) in HOTKEYS.items():
            layout.addWidget(owner.text(label, "muted"))
            row = QHBoxLayout()
            row.setSpacing(5)
            edit = HotkeyCapture()
            edit.setMaximumSequenceLength(1)
            edit.setKeySequence(QKeySequence(owner.configured_hotkey(action)))
            self.edits[action] = edit
            row.addWidget(edit, 1)
            apply = QPushButton("✓")
            apply.setFixedWidth(32)
            apply.setToolTip("Применить сочетание")
            apply.clicked.connect(lambda _checked=False, key=action: self.apply(key))
            row.addWidget(apply)
            disable = QPushButton("×")
            disable.setFixedWidth(32)
            disable.setToolTip("Отключить это сочетание" if action != "menu" else "Для меню нужна клавиша")
            disable.setEnabled(action != "menu")
            disable.clicked.connect(lambda _checked=False, key=action: self.disable(key))
            row.addWidget(disable)
            layout.addLayout(row)
        self.feedback = owner.text("Нажмите новое сочетание, затем ✓. Работает и в игре.", "muted")
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        layout.addStretch()

    def sync(self, action=None):
        for key, edit in self.edits.items():
            if action is None or action == key:
                edit.setKeySequence(QKeySequence(self.owner.configured_hotkey(key)))
        if hasattr(self.owner, "hotkey_errors"):
            errors = [HOTKEYS[k][0] + ": " + v for k, v in self.owner.hotkey_errors.items() if v]
            self.feedback.setText("\n".join(errors) if errors else
                                  "Нажмите новое сочетание, затем ✓. Работает и в игре.")

    def apply(self, action):
        sequence = self.edits[action].keySequence().toString(QKeySequence.PortableText)
        ok, error = self.owner.apply_hotkey(action, sequence)
        self.feedback.setText("Сохранено: " + (sequence or "отключено") if ok else error)

    def disable(self, action):
        self.edits[action].clear()
        self.apply(action)
