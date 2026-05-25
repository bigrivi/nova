"""
On-demand Python package installer for runtime dependency management.

Installs packages to ~/.nova/site-packages/ so the frozen app bundle stays lean.
"""

from __future__ import annotations

import importlib
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from nova.tools.registry import tool

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


def ensure_deps(packages: list[str]) -> None:
    """Install missing packages to ~/.nova/site-packages/ with session-level dedup."""
    missing = [
        pkg for pkg in packages
        if pkg not in _installed_in_session and not _is_importable(pkg)
    ]
    if not missing:
        return
    _install(missing)
    _installed_in_session.update(missing)


def _install(packages: list[str]) -> None:
    log.info("Installing missing packages: %s", packages)
    NOVA_SITE_PACKAGES.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--target", str(NOVA_SITE_PACKAGES),
            *packages,
        ],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"pip install failed for {packages}:\n{result.stderr.strip()}"
        )


@tool(
    name="install_python_package",
    description="Install a Python package. Use this when you need a library that "
                "is not currently available (e.g. pandas, matplotlib, playwright, "
                "numpy, Pillow) to complete the current task. Already installed "
                "packages are skipped automatically.",
)
async def install_python_package(package: str, version: str = "") -> dict:
    pkg_spec = f"{package}=={version}" if version else package
    try:
        ensure_deps([pkg_spec])
        return {"success": True, "message": f"{package} is now available."}
    except Exception as e:
        return {"success": False, "error": str(e)}
