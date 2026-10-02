"""Opt-in package check: temporary settings, no game or user configuration needed."""
import json
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from wtflight.ui.main_window import MainWindow


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    previous_hook = sys.excepthook
    sys.excepthook = lambda kind, value, tb: errors.append(str(value))
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory(prefix="wt-flight-check-") as folder:
        window = MainWindow(start_background_updates=False, settings_path=Path(folder) / "settings.json")
        window.telemetry.stop()
        window.show()

        def finish():
            try:
                assert len(window.database.models) > 1000, "Aircraft database missing"
                assert not window.canvas.background.isNull(), "Default background missing"
                assert window.audio and all(e.isLoaded() for e in window.audio.effects.values()), "Audio not loaded"
                window.set_demo_mode(True)
                window.grab().save(str(output / "installed-editor.png"))
                window.toggle_quick_settings()
                assert window.quick_settings.isVisible(), "Quick menu did not open"
                assert not errors, errors
            except Exception as error:
                errors.append(str(error))
            finally:
                result = {"ok": not errors, "errors": errors,
                          "frozen": bool(getattr(sys, "frozen", False)),
                          "executable": sys.executable, "models": len(window.database.models),
                          "database": window.database.version,
                          "hotkey_conflicts": {key: value for key, value in window.hotkey_errors.items() if value}}
                (output / "self-check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                window.stop_workers()
                window.close_hotkeys()
                window.quick_settings.hide()
                window.tray.hide()
                window.hide()
                for overlay in window.overlays:
                    overlay.close()
                window.deleteLater()
                QTimer.singleShot(100, app.quit)

        QTimer.singleShot(2500, finish)
        app.exec()
    sys.excepthook = previous_hook
    return 1 if errors else 0
