"""
Nova - General-purpose agent system.

Launch command: python -m nova
"""

import asyncio
import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from dataclasses import replace
from pathlib import Path

from nova.desktop.main import run_desktop
from nova.mcp.manager import MCPManager
from nova.server import run_server
from nova.settings import Settings, configure_logging, get_settings
from nova.tools.dependency_manager import init_site_packages


def _build_frontend(project_root: Path) -> Path:
    """Return the built web UI directory, building it with npm when absent."""
    frontend_dir = project_root / "frontend"
    dist_dir = frontend_dir / "dist"
    if (dist_dir / "index.html").is_file():
        return dist_dir

    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit(
            "Nova web UI needs a built frontend. Install Node.js/npm and run "
            "`cd frontend && npm install && npm run build`."
        )
    if not (frontend_dir / "node_modules").is_dir():
        print("Nova web: installing frontend dependencies...", file=sys.stderr)
        subprocess.run([npm, "install"], cwd=str(frontend_dir), check=True)
    print("Nova web: building frontend...", file=sys.stderr)
    subprocess.run([npm, "run", "build"], cwd=str(frontend_dir), check=True)
    if not (dist_dir / "index.html").is_file():
        raise SystemExit("Nova web: frontend build produced no dist/index.html")
    return dist_dir


def _open_browser_when_ready(url: str) -> None:
    """Open the default browser once the server answers, off the main thread."""

    def worker() -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1):
                    break
            except Exception:
                time.sleep(0.3)
        webbrowser.open(url)

    threading.Thread(target=worker, daemon=True).start()


def _web_settings(settings: Settings, project_root: Path) -> Settings:
    """Resolve the frontend dist and return settings that serve it."""
    dist_dir = settings.frontend_dist_path
    if dist_dir is None or not (dist_dir / "index.html").is_file():
        dist_dir = _build_frontend(project_root)
    return replace(settings, frontend_dist_path=dist_dir)


def _run_tui() -> None:
    """Launch the repository's OpenTUI client from any caller directory."""
    project_root = Path(__file__).resolve().parent.parent
    tui_dir = project_root / "tui"
    if not (tui_dir / "package.json").is_file():
        raise SystemExit(f"Nova TUI sources not found: {tui_dir}")

    bun = shutil.which("bun")
    if bun is None:
        raise SystemExit("Nova TUI requires Bun. Install it from https://bun.sh")

    environment = os.environ.copy()
    environment.setdefault("NOVA_PROJECT_ROOT", str(project_root))
    environment.setdefault("NOVA_PYTHON", sys.executable)
    environment.setdefault("NOVA_TUI_BACKEND", "1")
    environment.setdefault("NOVA_WORKSPACE_DIR", str(Path.cwd().resolve()))

    os.chdir(tui_dir)
    bundle = tui_dir / "dist" / "index.js"
    if bundle.is_file():
        os.execvpe(bun, [bun, str(bundle)], environment)
    print(
        "Nova TUI bundle not found at tui/dist/index.js; "
        "run `cd tui && bun install && bun run build`. Falling back to source.",
        file=sys.stderr,
    )
    os.execvpe(bun, [bun, "run", "src/index.tsx"], environment)


def main():
    # Internal flag: run a Python script and exit (no GUI).
    # Used by code_run in PyInstaller desktop builds where sys.executable
    # is the app bundle, not a standalone Python interpreter.
    if len(sys.argv) >= 3 and sys.argv[1] == "--_run-code":
        script_path = sys.argv[2]
        script_args = sys.argv[3:]
        sys.argv = [script_path, *script_args]
        sys.path.insert(0, str(Path(script_path).parent))
        with open(script_path) as f:
            code = f.read()
        exec(compile(code, script_path, "exec"), {"__name__": "__main__", "__file__": script_path})
        sys.exit(0)
    parser = argparse.ArgumentParser(description="Nova agent runtime")
    settings = get_settings()
    provider_names = settings.provider_names or []
    parser.add_argument("mode", nargs="?", choices=["serve", "web", "tui", "desktop"], default="serve",
                        help="Run mode: serve (HTTP backend, default), web (backend + browser UI), tui (OpenTUI client), desktop (GUI window)")
    provider_default = provider_names[0] if provider_names else None
    parser.add_argument("--provider", "-p", choices=provider_names, default=provider_default,
                        help="LLM provider alias (default: first configured provider)")
    parser.add_argument("--model", "-m", default=None,
                        help="Model name (default: per-agent DB config)")
    from nova.constants import DEFAULT_AGENT_KEY
    parser.add_argument("--agent", default=DEFAULT_AGENT_KEY,
                        help=f"Agent key (default: {DEFAULT_AGENT_KEY})")
    parser.add_argument("--dev", action="store_true",
                        help="[desktop] Load frontend from Vite dev server (http://localhost:5173) instead of built-in server")
    parser.add_argument("--no-open", action="store_true",
                        help="[web] Do not open the browser automatically")
    args = parser.parse_args()
    init_site_packages()
    configure_logging(settings, console=args.mode in ("serve", "web"))

    try:
        if args.mode == "tui":
            _run_tui()
            return
        if args.mode == "desktop":
            run_desktop(settings=settings, dev=args.dev)
            return

        if args.mode == "web":
            project_root = Path(__file__).resolve().parent.parent
            settings = _web_settings(settings, project_root)
            if not args.no_open:
                url = f"http://{settings.host}:{settings.backend_port}"
                print(f"Nova web: opening {url}", file=sys.stderr)
                _open_browser_when_ready(url)

        asyncio.run(run_server(settings=settings))
    finally:
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(MCPManager.get_shared().shutdown())
            loop.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
