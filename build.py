#!/usr/bin/env python3
"""
Cross-platform build script for Nova Desktop.

Builds the frontend, then packages with PyInstaller using the appropriate
platform-specific spec file.

Usage:
    python build.py              # Build for current platform
    python build.py --clean      # Clean previous build first
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def platform() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    return sys.platform


def spec_file() -> Path:
    plat = platform()
    name = f"build_desktop_{plat}.spec"
    path = ROOT / name
    if not path.exists():
        print(f"Error: no spec file for platform '{plat}' ({name})", file=sys.stderr)
        sys.exit(1)
    return path


def build_frontend() -> None:
    frontend_dir = ROOT / "frontend"
    dist_dir = frontend_dir / "dist"
    if not frontend_dir.exists():
        return
    if dist_dir.exists():
        print(f">>> Frontend dist already exists at {dist_dir}, skipping build")
        return
    print(">>> Building frontend...")
    npm = shutil.which("npm")
    if not npm:
        print("Warning: npm not found, skipping frontend build", file=sys.stderr)
        return
    subprocess.run([npm, "run", "build"], cwd=str(frontend_dir), check=True)
    if not dist_dir.exists():
        print("Error: frontend build produced no dist/ output", file=sys.stderr)
        sys.exit(1)


def clean() -> None:
    for d in [ROOT / "build", ROOT / "dist"]:
        if d.exists():
            print(f"  Removing {d}...")
            shutil.rmtree(d)


def resolve_python(override: str | None = None) -> str:
    if override:
        return override
    project_python = ROOT / ".venv" / "bin" / "python3"
    if project_python.exists():
        return str(project_python)
    return sys.executable


def package(spec: Path, python: str) -> None:
    print(f">>> Packaging with PyInstaller ({spec.name})...")
    env = os.environ.copy()
    env["NOVA_PROJECT_ROOT"] = str(ROOT)
    subprocess.run(
        [python, "-m", "PyInstaller", "--clean", str(spec)],
        cwd=str(ROOT), env=env, check=True,
    )


def package_with_obfuscation(spec: Path) -> None:
    print(f">>> Obfuscating with PyArmor and packaging ({spec.name})...")
    subprocess.run(
        ["pyarmor", "gen", "--pack", str(spec), "-r", "nova/desktop/entry.py", "nova/"],
        cwd=str(ROOT), check=True,
    )


def output_path() -> Path:
    plat = platform()
    if plat == "macos":
        return ROOT / "dist" / "Nova.app"
    return ROOT / "dist" / "Nova"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Nova Desktop")
    parser.add_argument("--clean", action="store_true", help="Remove previous build output before building")
    parser.add_argument("--python", default=None, help="Python interpreter to use for PyInstaller (default: .venv/bin/python3)")
    parser.add_argument("--obfuscate", action="store_true", help="Obfuscate source with PyArmor before packaging")
    args = parser.parse_args()

    plat = platform()
    spec = spec_file()
    python = resolve_python(args.python)
    print(f"=== Building Nova Desktop for {plat} ===")
    print(f"    Python: {python}")

    if args.clean:
        clean()

    build_frontend()
    if args.obfuscate:
        package_with_obfuscation(spec)
    else:
        package(spec, python=python)

    out = output_path()
    print(f"\n=== Done: {out} ===")


if __name__ == "__main__":
    main()
