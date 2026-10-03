"""Updater integrity and cancellation checks without network or installer execution."""
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wtflight.ui.main_window import InstallerDownloader, MainWindow


class Response(io.BytesIO):
    def __init__(self, data, size=None):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data) if size is None else size)}


class UpdateTests(unittest.TestCase):
    def download(self, data=b"test installer", *, size=None, checksum=None, cancel=False, response=None):
        digest = hashlib.sha256(data).hexdigest() if checksum is None else checksum
        with tempfile.TemporaryDirectory() as directory:
            worker = InstallerDownloader("https://example.invalid/setup.exe", "setup.exe", digest)
            results = []
            worker.completed.connect(lambda path, error: results.append((path, error)))
            if cancel:
                worker.cancel()
            def make_dir(**_):
                folder = Path(directory) / "download"
                folder.mkdir()
                return str(folder)
            with patch("wtflight.ui.main_window.tempfile.mkdtemp", side_effect=make_dir), patch(
                    "wtflight.ui.main_window.urlopen", return_value=response or Response(data, size)):
                worker.run()
            self.assertEqual(len(results), 1)
            path, error = results[0]
            if path:
                self.assertEqual(Path(path).read_bytes(), data)
            else:
                self.assertEqual(list(Path(directory).rglob("*")), [])
            return error

    def test_verified_installer(self):
        self.assertEqual(self.download(), "")

    def test_bad_or_missing_digest_is_rejected(self):
        for digest in ("", "0" * 64, "sha256:invalid"):
            with self.subTest(digest=digest):
                self.assertIn("SHA-256", self.download(checksum=digest))

    def test_truncated_download_is_removed(self):
        self.assertIn("не полностью", self.download(size=99))

    def test_cancellation_cleans_partial_file(self):
        self.assertEqual(self.download(cancel=True), "Отменено пользователем")

    def test_network_failure_cleans_partial_file(self):
        response = Response(b"x")
        response.read = lambda _: (_ for _ in ()).throw(OSError("connection lost"))
        self.assertEqual(self.download(response=response), "connection lost")

    def test_versions_are_normalized_and_reject_invalid_values(self):
        self.assertEqual(MainWindow._version_tuple("v1.2"), (1, 2, 0))
        for value in ("1.-1.4", "1.2.3.exe", "1.2.3.4", None):
            self.assertEqual(MainWindow._version_tuple(value), (0, 0, 0))
