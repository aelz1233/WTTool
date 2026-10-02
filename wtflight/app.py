"""Application entry point."""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import APP_NAME, __version__
from .ui.main_window import main as run
from .selfcheck import run as run_selfcheck


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        import PySide6  # noqa: F401
    except ImportError as error:
        raise SystemExit("PySide6 is required. Install dependencies from requirements.txt") from error
    if getattr(sys, "frozen", False):
        log_dir = Path(os.environ.get("APPDATA", str(Path.home()))) / "WTFlightAssistant" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(level=logging.ERROR, handlers=[RotatingFileHandler(
            log_dir / "errors.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")])
    if len(argv) == 2 and argv[0] == "--self-check":
        return run_selfcheck(Path(argv[1]))
    run()
    return 0
