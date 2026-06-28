"""
On-demand Python package installer for runtime dependency management.

Installs packages to ~/.nova/site-packages/ so the frozen app bundle stays lean.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from nova.llm import ToolResult

log = logging.getLogger(__name__)

NOVA_SITE_PACKAGES = Path.home() / ".nova" / "site-packages"
_installed_in_session: set[str] = set()


def init_site_packages() -> None:
    """Ensure ~/.nova/site-packages/ exists and is on sys.path.

    Must be called once at startup (e.g. when building the agent).
    """
    NOVA_SITE_PACKAGES.mkdir(parents=True, exist_ok=True)
    path_str = str(NOVA_SITE_PACKAGES)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def _is_importable(pkg_name: str) -> bool:
    normalized = pkg_name.lower().replace("-", "_").replace(".", "_")
    try:
        importlib.import_module(normalized)
        return True
    except ImportError:
        return False


async def ensure_deps(packages: list[str]) -> None:
    """Install missing packages to ~/.nova/site-packages/ with session-level dedup."""
    missing = [
        pkg for pkg in packages
        if pkg not in _installed_in_session and not _is_importable(pkg)
    ]
    if not missing:
        return
    await _install(missing)
    _installed_in_session.update(missing)


async def _install(packages: list[str]) -> None:
    log.info("Installing missing packages: %s", packages)
    NOVA_SITE_PACKAGES.mkdir(parents=True, exist_ok=True)

    pip_args = ["install", "--target", str(NOVA_SITE_PACKAGES), *packages]

    if getattr(sys, "frozen", False):
        pip_candidates = [
            [shutil.which("pip3") or shutil.which("pip")],
            [shutil.which("python3") or shutil.which("python"), "-m", "pip"],
        ]
        cmd = None
        for candidate in pip_candidates:
            if candidate[0]:
                cmd = [*candidate, *pip_args]
                break
        if not cmd:
            raise RuntimeError(
                "pip not found on system. Install Python 3 with pip, "
                "or use the shell tool to install packages."
            )
    else:
        cmd = [sys.executable, "-m", "pip", *pip_args]

    spawn_kwargs = {}
    if sys.platform == "win32":
        spawn_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    result = await asyncio.to_thread(
        lambda: subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=120,
            **spawn_kwargs,
        )
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"pip install failed for {packages}:\n{result.stderr.strip()}"
        )

