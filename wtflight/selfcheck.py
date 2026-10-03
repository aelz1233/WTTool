"""Opt-in package check: temporary settings, no game or user configuration needed."""
import json
import sys
import tempfile
import wave
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from wtflight.ui import feature_controls as wt_feature_ui
from wtflight.ui import main_window as wt_qt


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    previous_hook = sys.excepthook
    sys.excepthook = lambda kind, value, tb: errors.append(str(value))
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory(prefix="wt-flight-check-") as folder:
        config_path = Path(folder) / "settings.json"
        wt_qt.CONFIG_PATH = config_path
        wt_feature_ui.CONFIG_PATH = config_path
        window = wt_qt.MainWindow(start_background_updates=False)
        window.telemetry.stop()
        window.show()

        def finish():
            try:
                assert len(window.database.models) > 1000, "Aircraft database missing"
                assert not window.canvas.background.isNull(), "Default background missing"
                assert window.audio, "Audio service missing"
                for path in window.audio.default_paths.values():
                    with wave.open(str(path), "rb") as sound:
                        assert sound.getnframes() > 0, "Empty warning sound"
                if QMediaDevices.audioOutputs():
                    assert all(e.isLoaded() for e in window.audio.effects.values()), "Audio not loaded"
                assert app._wt_translator is not None, "Russian Qt translations missing"
                window.set_demo_mode(True)
                QTest.qWait(50)
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
                          "audio_output_available": bool(QMediaDevices.audioOutputs()),
                          "hotkey_conflicts": {key: value for key, value in window.hotkey_errors.items() if value}}
                (output / "self-check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps(result, ensure_ascii=True), flush=True)
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
