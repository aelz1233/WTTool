"""Small translation facade; the UI can migrate to keyed translations incrementally."""
from wt_qt import MainWindow

def apply_language(window: MainWindow, language: str):
    window.set_language(language)

