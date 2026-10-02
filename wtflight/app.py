"""Application start-up: dependency check, crash logging and the Qt event loop."""

from __future__ import annotations

import sys
from pathlib import Path


def _install_crash_log():
    """A windowed frozen build has no console, so unhandled errors go to a file."""
    import logging
    from logging.handlers import RotatingFileHandler

    from wtflight.paths import LOG_DIR

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.ERROR, handlers=[RotatingFileHandler(
        LOG_DIR / "errors.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")])
    sys.excepthook = lambda kind, value, tb: logging.error("Unhandled exception", exc_info=(kind, value, tb))


def main():
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from wtflight import APP_NAME, __version__
    from wtflight.paths import ICON
    from wtflight.ui.main_window import MainWindow
    from wtflight.ui.theme import STYLE

    app = QApplication([])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QIcon(str(ICON)))
    app.setStyleSheet(STYLE)
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    window.show()
    app.aboutToQuit.connect(window.stop_workers)
    app.aboutToQuit.connect(window.close_hotkeys)
    app.exec()


def run():
    if getattr(sys, "frozen", False):
        _install_crash_log()
    try:
        import PySide6  # noqa: F401
    except ImportError:
        raise SystemExit("PySide6 не найден. Установите зависимости: python -m pip install -r requirements.txt")
    if len(sys.argv) == 3 and sys.argv[1] == "--self-check":
        from wtflight.selfcheck import run as check
        raise SystemExit(check(Path(sys.argv[2])))
    main()


if __name__ == "__main__":
    run()
