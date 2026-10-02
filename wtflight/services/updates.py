"""Network jobs that must not block the UI: aircraft database, app releases, installer."""

import json
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

from PySide6.QtCore import QThread, Signal

from wtflight import GITHUB_RELEASES, GITHUB_REPO
from wtflight.core.aircraft import download_database


def version_tuple(value):
    """Lenient ``1.2.3`` / ``v1.2.3`` parser for comparing release tags."""
    try:
        return tuple(int(part) for part in str(value).lstrip("vV").split(".")[:3])
    except (TypeError, ValueError):
        return (0, 0, 0)


class DatabaseUpdater(QThread):
    completed = Signal(object, str)

    def __init__(self, cache_dir, version):
        super().__init__()
        self.cache_dir, self.version = cache_dir, version

    def run(self):
        try:
            self.completed.emit(download_database(self.cache_dir, self.version), "")
        except (OSError, ValueError) as error:
            self.completed.emit(None, str(error))


class UpdateChecker(QThread):
    """Check the public GitHub release feed without blocking the editor."""
    completed = Signal(object, str)

    def run(self):
        try:
            request = Request(
                f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                headers={"User-Agent": "WT-Flight-Assistant", "Accept": "application/vnd.github+json"},
            )
            with urlopen(request, timeout=5) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise ValueError("GitHub вернул неожиданный ответ")
            tag = str(payload.get("tag_name", "")).strip()
            version = tag.lstrip("vV")
            asset = next((item.get("browser_download_url") for item in payload.get("assets", [])
                          if str(item.get("name", "")).lower().endswith(".exe")), "")
            self.completed.emit({"tag": tag, "version": version, "url": payload.get("html_url", GITHUB_RELEASES),
                                 "asset": asset, "name": payload.get("name", tag)}, "")
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.completed.emit(None, str(error))


class InstallerDownloader(QThread):
    progress = Signal(int)
    completed = Signal(str, str)

    def __init__(self, url, filename):
        super().__init__()
        self.url, self.filename = url, filename

    def run(self):
        try:
            target = Path(tempfile.gettempdir()) / self.filename
            request = Request(self.url, headers={"User-Agent": "WT-Flight-Assistant"})
            with urlopen(request, timeout=20) as response:
                total = int(response.headers.get("Content-Length", "0") or 0)
                received = 0
                with target.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 256)
                        if not chunk:
                            break
                        output.write(chunk)
                        received += len(chunk)
                        if total:
                            self.progress.emit(min(100, int(received * 100 / total)))
            self.completed.emit(str(target), "")
        except (OSError, ValueError) as error:
            self.completed.emit("", str(error))
