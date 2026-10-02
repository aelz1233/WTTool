import sys
from wtflight.ui import feature_controls as _implementation

sys.modules[__name__] = _implementation
