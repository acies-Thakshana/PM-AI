"""Local entry points. Makes ``lib/python`` importable when the package is not installed."""

from __future__ import annotations

import sys
from pathlib import Path

LIBRARY = Path(__file__).resolve().parents[1] / "lib" / "python"
if LIBRARY.is_dir() and str(LIBRARY) not in sys.path:
    sys.path.insert(0, str(LIBRARY))
