"""Background polling of the War Thunder local telemetry API."""

from __future__ import annotations

import json
import threading
import time
from urllib.request import urlopen

from PySide6.QtCore import QThread, Signal

API = "http://127.0.0.1:8111"


class Telemetry(QThread):
    sample = Signal(str, dict, dict)

    def __init__(self, interval: float = 0.1):
        super().__init__()
        self.stop_event = threading.Event()
        self.interval = max(0.05, min(0.5, float(interval)))

    def set_interval(self, interval: float) -> None:
        self.interval = max(0.05, min(0.5, float(interval)))

    def run(self) -> None:
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                with urlopen(API + "/state", timeout=0.25) as response:
                    state = json.load(response)
                if not isinstance(state, dict) or not state.get("valid"):
                    self.sample.emit("waiting", {}, {})
                else:
                    try:
                        with urlopen(API + "/indicators", timeout=0.25) as response:
                            indicators = json.load(response)
                        if not isinstance(indicators, dict) or not indicators.get("valid"):
                            indicators = {}
                    except (OSError, ValueError):
                        indicators = {}
                    self.sample.emit("live", state, indicators)
            except (OSError, ValueError):
                self.sample.emit("offline", {}, {})
            self.stop_event.wait(max(0, self.interval - (time.monotonic() - started)))

    def stop(self) -> None:
        self.stop_event.set()
        self.wait(2500)
