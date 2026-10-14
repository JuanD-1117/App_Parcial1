"""Hace importables los módulos de app/ sin instalarlos como paquete."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
