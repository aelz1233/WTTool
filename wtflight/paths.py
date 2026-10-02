"""Filesystem locations: bundled resources and per-user application data."""

import os
from pathlib import Path

# Read-only files shipped with the application (also inside the PyInstaller bundle).
RESOURCES = Path(__file__).resolve().parent / "resources"
FLIGHT_MODELS = RESOURCES / "flight_models"
ICON = RESOURCES / "wt-flight.ico"
DEFAULT_BACKGROUND = RESOURCES / "default_hud_background.png"

# Writable per-user data: settings, downloaded database, sounds, logs.
APP_DIR = Path(os.getenv("APPDATA") or Path.home()) / "WTFlightAssistant"
CONFIG_PATH = APP_DIR / "settings.json"
LOG_DIR = APP_DIR / "logs"
