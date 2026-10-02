"""Start the War Thunder HUD editor with the local project environment."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main():
    try:
        import PySide6  # noqa: F401
    except ImportError:
        executable = Path(__file__).parent / ".venv" / "Scripts" / "python.exe"
        if executable.exists() and Path(sys.executable).resolve() != executable.resolve():
            os.execv(str(executable), [str(executable), str(Path(__file__).resolve())])
        raise SystemExit("PySide6 не найден. Установите зависимости: python -m pip install -r requirements.txt")
    from wt_qt import main as run
    if len(sys.argv) == 3 and sys.argv[1] == "--self-check":
        from wt_selfcheck import run as check
        raise SystemExit(check(Path(sys.argv[2])))
    run()


if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        import logging
        from logging.handlers import RotatingFileHandler
        logs = Path(os.environ.get("APPDATA", str(Path.home()))) / "WTFlightAssistant" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(level=logging.ERROR, handlers=[RotatingFileHandler(
            logs / "errors.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")])
        sys.excepthook = lambda kind, value, tb: logging.error("Unhandled exception", exc_info=(kind, value, tb))
    main()
