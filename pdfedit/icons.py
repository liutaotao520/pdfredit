"""Consistent vector icons shared by the native desktop controls."""
from pathlib import Path
from PySide6.QtGui import QIcon

ASSETS = Path(__file__).resolve().parents[1] / "assets"

def icon(name: str) -> QIcon:
    return QIcon(str(ASSETS / "icons" / f"{name}.svg"))
