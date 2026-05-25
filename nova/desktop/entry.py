"""
PyInstaller entry point for the Nova desktop app.

Resolves bundled frontend assets and launches the GUI.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from nova.desktop.main import run_desktop
from nova.settings import Settings


def _resolve_frontend_dist() -> str | None:
    if getattr(sys, "frozen", False):
        meipass = Path(sys._MEIPASS)
        dist_path = meipass / "frontend" / "dist"
        if dist_path.exists():
            return str(dist_path)
    return None


def main() -> None:
    dist = os.environ.get("NOVA_FRONTEND_DIST") or _resolve_frontend_dist()
    if dist:
        os.environ["NOVA_FRONTEND_DIST"] = dist

    settings = Settings.load_config()
    run_desktop(settings=settings, dev=False)


if __name__ == "__main__":
    main()
