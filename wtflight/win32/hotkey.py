"""Configurable Windows hotkeys, without polling or keyboard hooks."""

import ctypes
import sys
import itertools
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, Qt, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

HOTKEYS = {
    "menu": ("Быстрое меню", "Ins"),
    "hud": ("Показать / скрыть HUD", "Ctrl+Shift+H"),
    "move": ("Перемещать HUD", "Ctrl+Shift+E"),
    "editor": ("Открыть редактор", "Ctrl+Shift+O"),
}


class GlobalHotkey(QAbstractNativeEventFilter):
    _ids = itertools.count(0x5754)
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.active_id = None
        self.sequence = ""
        self.user32 = ctypes.WinDLL("user32", use_last_error=True) if sys.platform == "win32" else None
        if self.user32:
            self.user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
            self.user32.RegisterHotKey.restype = wintypes.BOOL
            self.user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
            self.user32.UnregisterHotKey.restype = wintypes.BOOL
        QApplication.instance().installNativeEventFilter(self)

    @staticmethod
    def decode(sequence):
        seq = QKeySequence(sequence)
        if seq.count() != 1:
            raise ValueError("Выберите одну клавишу или одно сочетание.")
        combination = seq[0]
        key = combination.key()
        mods = combination.keyboardModifiers()
        flags = 0x4000  # MOD_NOREPEAT: holding Insert must not toggle repeatedly.
        for qt_mod, win_mod in ((Qt.AltModifier, 1), (Qt.ControlModifier, 2),
                                (Qt.ShiftModifier, 4), (Qt.MetaModifier, 8)):
            if mods & qt_mod:
                flags |= win_mod
        special = {Qt.Key_Insert: 0x2D, Qt.Key_Delete: 0x2E, Qt.Key_Home: 0x24,
                   Qt.Key_End: 0x23, Qt.Key_PageUp: 0x21, Qt.Key_PageDown: 0x22,
                   Qt.Key_Pause: 0x13, Qt.Key_ScrollLock: 0x91, Qt.Key_Space: 0x20,
                   Qt.Key_Left: 0x25, Qt.Key_Up: 0x26, Qt.Key_Right: 0x27, Qt.Key_Down: 0x28}
        if key in special:
            vk = special[key]
        elif Qt.Key_F1 <= key <= Qt.Key_F24:
            vk = 0x70 + int(key) - int(Qt.Key_F1)
            if key == Qt.Key_F12:
                raise ValueError("F12 зарезервирована Windows. Выберите другую клавишу.")
        elif Qt.Key_A <= key <= Qt.Key_Z or Qt.Key_0 <= key <= Qt.Key_9:
            vk = int(key)
        else:
            raise ValueError("Подойдут Insert, F1–F11, буквы, цифры или сочетание с Ctrl / Alt / Shift.")
        return seq.toString(QKeySequence.PortableText), flags, vk

    def register(self, sequence):
        if not self.user32:
            return False, "Глобальная клавиша доступна в Windows. Меню можно открыть из трея."
        try:
            normalized, flags, vk = self.decode(sequence)
        except ValueError as error:
            return False, str(error)
        if self.active_id is not None and normalized == self.sequence:
            return True, ""
        candidate = next(self._ids)
        if not self.user32.RegisterHotKey(None, candidate, flags, vk):
            return False, "Клавиша занята другой программой. Выберите другую; прежняя настройка сохранена."
        if self.active_id is not None:
            self.user32.UnregisterHotKey(None, self.active_id)
        self.active_id, self.sequence = candidate, normalized
        return True, ""

    def nativeEventFilter(self, event_type, message):
        if self.user32 and bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam == self.active_id:
                QTimer.singleShot(0, self.callback)
                return True, 0
        return False, 0

    def disable(self):
        if self.active_id is not None:
            self.user32.UnregisterHotKey(None, self.active_id)
            self.active_id = None
        self.sequence = ""

    def close(self):
        self.disable()
        QApplication.instance().removeNativeEventFilter(self)
