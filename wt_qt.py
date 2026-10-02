import sys
from wtflight.ui import main_window as _implementation

# Preserve the historical ``import wt_qt`` API, including writable module
# globals used by desktop tests and portable launchers.
sys.modules[__name__] = _implementation
