"""Make the analytics modules importable the way the service imports them (flat, from analytics/)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analytics"))
