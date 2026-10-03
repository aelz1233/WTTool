"""Render actual UI theme comparisons with sample telemetry and temporary settings."""
import tempfile
from pathlib import Path

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from wtflight.ui import main_window as wt_qt
from wtflight.ui.theme import THEMES


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    output = Path(__file__).parent / "design_previews"
    output.mkdir(exist_ok=True)
    original = wt_qt.CONFIG_PATH
    with tempfile.TemporaryDirectory() as folder:
        wt_qt.CONFIG_PATH = Path(folder) / "settings.json"
        window = wt_qt.MainWindow(start_background_updates=False)
        window.telemetry.stop()
        QTest.qWait(30)
        window.set_demo_mode(True)
        snapshots = []
        try:
            for key, theme in THEMES.items():
                window.set_theme(key)
                window.show()
                window.tabs.setCurrentIndex(0)
                QTest.qWait(40)
                editor = window.grab()
                editor.save(str(output / (key + ".png")))
                if key == "graphite":
                    for tab, name in ((3, "settings"), (4, "profiles")):
                        window.tabs.setCurrentIndex(tab)
                        QTest.qWait(20)
                        window.grab().save(str(output / (name + ".png")))
                window.hide()
                window.quick_settings.sync()
                window.quick_settings.show()
                window.quick_settings.tabs.setCurrentIndex(0)
                QTest.qWait(40)
                quick = window.quick_settings.grab()
                quick.save(str(output / (key + "_menu.png")))
                window.quick_settings.tabs.setCurrentIndex(2)
                QTest.qWait(30)
                window.quick_settings.grab().save(str(output / (key + "_keys.png")))
                window.quick_settings.hide()
                snapshots.append((theme, editor, quick))

            sheet = QPixmap(1860, 1120)
            sheet.fill(QColor("#101417"))
            painter = QPainter(sheet)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.setPen(QColor("#f1f4f5"))
            painter.setFont(QFont("Segoe UI", 22, QFont.DemiBold))
            painter.drawText(30, 42, "WT FLIGHT / Три варианта оформления")
            painter.setPen(QColor("#9ba9ae"))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(30, 70, "Реальные окна программы • пример телеметрии • переключение во вкладке «Настройки»")
            for index, (theme, editor, quick) in enumerate(snapshots):
                x = 30 + index * 610
                painter.setPen(QColor(theme["accent"] if index != 2 else "#8cbae8"))
                painter.setFont(QFont("Segoe UI", 20, QFont.DemiBold))
                painter.drawText(x, 117, f"0{index + 1}  {theme['name']}")
                painter.setPen(QColor("#a4b1b7"))
                painter.setFont(QFont("Segoe UI", 11))
                painter.drawText(x, 143, theme["description"])
                painter.drawPixmap(QRect(x, 163, 580, 451), editor)
                painter.setPen(QColor("#a4b1b7"))
                painter.drawText(x, 648, "МЕНЮ INSERT")
                painter.drawPixmap(QRect(x, 667, 304, 416), quick)
            painter.end()
            sheet.save(str(output / "comparison.png"))
        finally:
            window.stop_feature_timers()
            window.quick_settings.hide()
            window.hide()
            window.close_hotkeys()
            window.tray.hide()
            for overlay in window.overlays:
                overlay.hide()
            window.deleteLater()
            QTest.qWait(20)
            wt_qt.CONFIG_PATH = original
    print(output / "comparison.png")


if __name__ == "__main__":
    main()
