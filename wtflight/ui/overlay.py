"""Frameless, click-through window that shows one HUD group above the game."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from wtflight.ui.group_view import GroupView


class OverlayWindow(GroupView):
    def __init__(self, group, screen_provider=None):
        super().__init__(group, False)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.screen_provider = screen_provider or QApplication.primaryScreen

    def set_editing(self, editing):
        self.editor = editing
        self.is_selected = editing
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not editing)
        self.setWindowFlag(Qt.WindowTransparentForInput, not editing)
        self.setCursor(Qt.OpenHandCursor if editing else Qt.ArrowCursor)
        self.press = None

    def mousePressEvent(self, event):
        if self.editor and event.button() == Qt.LeftButton:
            self.press = event.globalPosition().toPoint() - self.pos()
            self.selected.emit(self.group["id"])
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.editor and self.press is not None and event.buttons() & Qt.LeftButton:
            screen = self.screen_provider().geometry()
            point = event.globalPosition().toPoint() - self.press
            x = max(screen.left(), min(screen.right() + 1 - self.width(), point.x()))
            y = max(screen.top(), min(screen.bottom() + 1 - self.height(), point.y()))
            self.move(x, y)
            self.group["x"] = (x - screen.left()) / screen.width()
            self.group["y"] = (y - screen.top()) / screen.height()

    def place(self):
        screen = self.screen_provider().geometry()
        self.adjustSize()
        if self.press is None:
            self.move(screen.left() + min(max(0, screen.width() - self.width()),
                                         int(self.group.get("x", 0) * screen.width())),
                      screen.top() + min(max(0, screen.height() - self.height()),
                                        int(self.group.get("y", 0) * screen.height())))
