"""novakit must stay independent of Nova's application and user state."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "novakit"


def test_novakit_never_imports_nova() -> None:
    forbidden: list[str] = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                forbidden.extend(
                    alias.name for alias in node.names if alias.name == "nova"
                )
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and (node.module == "nova" or node.module.startswith("nova."))
            ):
                forbidden.append(f"{path.name}: {node.module}")
    assert forbidden == []


def test_import_does_not_load_application_surfaces() -> None:
    code = """
import sys
import novakit
for name in (
    "fastapi", "uvicorn", "pywebview", "playwright",
    "nova", "nova.server", "nova.desktop", "nova.gateway",
):
    assert name not in sys.modules, name
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PACKAGE_ROOT.parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_core_objects_do_not_touch_the_user_directory(tmp_path: Path) -> None:
    home = tmp_path / "home"
    nova_home = tmp_path / "nova-home"
    code = """
from novakit.llm import FakerLLMProvider, Message
from novakit.session import SessionContext
from novakit.tools import ToolRegistry

provider = FakerLLMProvider(seed=1)
session = SessionContext.create("developer-agent")
registry = ToolRegistry()
assert provider is not None
assert session.id
assert registry.tools == {}
assert Message(role="user", content="hello").content == "hello"
"""
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["NOVA_HOME"] = str(nova_home)
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert not home.exists()
    assert not nova_home.exists()
