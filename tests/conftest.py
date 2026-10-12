"""
Shared pytest fixtures
"""

import os
import tempfile
import textwrap
from collections.abc import Mapping

import pytest

from nova.llm import OllamaProvider
from nova.settings import get_settings


@pytest.fixture(autouse=True)
def _test_settings_home(monkeypatch, tmp_path):
    get_settings.cache_clear()
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / ".nova"))
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_session_manager():
    """Drop the process-global SessionManager between tests.

    Agent() falls back to get_session_manager(). Without a reset, a manager
    created in an earlier test keeps a data source whose connection the test
    fixture already closed; the next test reconnects it, leaking an aiosqlite
    worker thread that keeps pytest from exiting.
    """
    from nova.session import manager as session_manager_module

    previous = session_manager_module._manager
    session_manager_module._manager = None
    yield
    session_manager_module._manager = previous


@pytest.fixture(autouse=True)
def _reset_background_task_manager():
    """Drop the process-global BackgroundTaskManager between tests.

    The manager binds an asyncio.Semaphore to whichever loop first runs a
    task, and each pytest-asyncio test gets a fresh loop, so a singleton
    shared across tests can carry a semaphore bound to a closed loop. Same
    isolation rationale as _reset_session_manager above.
    """
    from nova.tasks import manager as task_manager_module

    previous = task_manager_module._manager
    task_manager_module._manager = None
    yield
    task_manager_module._manager = previous


@pytest.fixture
def make_executor():
    """Return a factory that wraps a coroutine function as a TaskExecutor.

    Lets a test register a one-off kind without writing a class:

        manager.register_executor(make_executor("example", run))
    """
    from nova.tasks.models import (
        TaskExecutionContext,
        TaskExecutionResult,
        TaskExecutor,
    )

    class _FunctionExecutor(TaskExecutor):
        def __init__(self, kind: str, run, *, unlimited: bool) -> None:
            self.kind = kind
            self.unlimited = unlimited
            self._run = run

        async def execute(
            self,
            arguments: Mapping[str, object],
            context: TaskExecutionContext,
        ) -> TaskExecutionResult:
            return await self._run(arguments, context)

    def _factory(kind: str, run, *, unlimited: bool = False) -> TaskExecutor:
        return _FunctionExecutor(kind, run, unlimited=unlimited)

    return _factory


@pytest.fixture
def llm():
    return OllamaProvider()


def _write_mcp_server_script() -> str:
    """Write a minimal MCP stdio server script and return its path.

    A real server, not a mock: it answers initialize, tools/list and tools/call
    over stdin/stdout, so a transport test and a connection probe exercise the
    same round trip a production server would. Shared here because both the MCP
    transport suite and the config-probe suite need it, and a copy in each is a
    copy that drifts.
    """
    code = textwrap.dedent("""\
    import json, sys
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        rid = msg.get("id")
        method = msg.get("method")
        params = msg.get("params", {})
        if method == "initialize":
            sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":rid,"result":{
                "protocolVersion":"2025-03-26",
                "capabilities":{"tools":{}},
                "serverInfo":{"name":"test-server","version":"1.0.0"},
            }}) + "\\n")
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":rid,"result":{
                "tools":[{
                    "name":"echo",
                    "description":"Echo input",
                    "inputSchema":{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]},
                }]
            }}) + "\\n")
        elif method == "tools/call":
            name = params.get("name","")
            args = params.get("arguments",{})
            if name == "echo":
                sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":rid,"result":{
                    "content":[{"type":"text","text":args.get("text","")}]
                }}) + "\\n")
            else:
                sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":rid,"error":{
                    "code":-32601,"message":f"Unknown tool: {name}"
                }}) + "\\n")
        else:
            sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":rid,"error":{
                "code":-32601,"message":f"Unknown method: {method}"
            }}) + "\\n")
        sys.stdout.flush()
    """)
    fd, path = tempfile.mkstemp(suffix=".py", prefix="mcp_test_server_", text=True)
    with os.fdopen(fd, "w") as f:
        f.write(code)
    os.chmod(path, 0o755)
    return path


@pytest.fixture
def mcp_server_path():
    path = _write_mcp_server_script()
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass
