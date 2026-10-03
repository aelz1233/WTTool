"""Centralized application paths."""
import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
RESOURCE_DIR = PACKAGE_DIR / "resources"
APP_DIR = Path(os.getenv("APPDATA") or Path.home()) / "WTFlightAssistant"
CONFIG_PATH = APP_DIR / "settings.json"

