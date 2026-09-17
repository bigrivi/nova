from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

import nova.llm.request_hook as request_hook
from nova.llm.anthropic import AnthropicProvider
from nova.llm.openai import OpenAIProvider
from nova.llm.openai_response import OpenAIResponsesProvider
from nova.llm.request_hook import RequestHookError, resolve_hook_path


def _write_hook(tmp_path, name, body):
    target = tmp_path / name
    target.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(target)


ECHO_HOOK = """\
    import json, sys
    ctx = json.load(sys.stdin)
    assert ctx["session_id"] == "sess-1"
    print(json.dumps({"headers": {"x-opencode-session": "ses-from-hook"}}))
    """


def test_hook_headers_merged_and_win(tmp_path):
    hook = _write_hook(tmp_path, "hook.py", ECHO_HOOK)
    provider = OpenAIProvider(
        api_key="k",
        user_agent="nova/1.0",
        extra_headers={
            "x-opencode-client": "nova/1.0",
            "x-opencode-session": "stale",
        },
        request_hook=hook,
    )

    headers = provider._build_headers(session_id="sess-1")

    assert headers["User-Agent"] == "nova/1.0"
    assert headers["Authorization"] == "Bearer k"
    assert headers["x-opencode-client"] == "nova/1.0"
    assert headers["x-opencode-session"] == "ses-from-hook"


def test_hook_applies_across_providers(tmp_path):
    hook = _write_hook(tmp_path, "hook.py", ECHO_HOOK)
    for provider in (
        OpenAIProvider(request_hook=hook),
        OpenAIResponsesProvider(request_hook=hook),
        AnthropicProvider(request_hook=hook),
    ):
        headers = provider._build_headers(session_id="sess-1")
        assert headers["x-opencode-session"] == "ses-from-hook"


def test_no_hook_no_hook_headers():
    provider = OpenAIProvider(
        api_key="k",
        user_agent="nova/1.0",
        extra_headers={"x-opencode-client": "nova/1.0"},
    )
    headers = provider._build_headers(session_id="sess-1")

    assert headers["User-Agent"] == "nova/1.0"
    assert headers["Authorization"] == "Bearer k"
    assert headers["x-opencode-client"] == "nova/1.0"
    assert "x-opencode-session" not in headers


def test_hook_failure_modes(tmp_path):
    failing = _write_hook(
        tmp_path, "failing.py", "import sys; sys.exit(3)\n"
    )
    with pytest.raises(RequestHookError):
        OpenAIProvider(request_hook=failing)._build_headers(session_id="s")

    bad_json = _write_hook(tmp_path, "bad.py", 'print("not json")\n')
    with pytest.raises(RequestHookError):
        OpenAIProvider(request_hook=bad_json)._build_headers(session_id="s")

    with pytest.raises(RequestHookError):
        OpenAIProvider(request_hook=str(tmp_path / "missing.py"))._build_headers(
            session_id="s"
        )

    slow = _write_hook(tmp_path, "slow.py", "import time; time.sleep(30)\n")
    with pytest.raises(RequestHookError):
        request_hook.run_session_hook(slow, "s", timeout=1)


def test_hook_cached_per_session(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOK_COUNT_FILE", str(tmp_path / "count.txt"))
    hook = _write_hook(
        tmp_path,
        "counting.py",
        """\
        import json, os, sys
        json.load(sys.stdin)
        with open(os.environ["HOOK_COUNT_FILE"], "a") as f:
            f.write("x\\n")
        print(json.dumps({"headers": {"x-counted": "yes"}}))
        """,
    )
    provider = OpenAIProvider(request_session_hook=hook)
    assert provider._build_headers(session_id="a")["x-counted"] == "yes"
    assert provider._build_headers(session_id="a")["x-counted"] == "yes"
    assert provider._build_headers(session_id="b")["x-counted"] == "yes"
    count = (tmp_path / "count.txt").read_text(encoding="utf-8").count("x")
    assert count == 2


def test_request_hook_runs_every_time(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOK_COUNT_FILE", str(tmp_path / "count.txt"))
    hook = _write_hook(
        tmp_path,
        "counting.py",
        """\
        import json, os, sys
        json.load(sys.stdin)
        with open(os.environ["HOOK_COUNT_FILE"], "a") as f:
            f.write("x\\n")
        print(json.dumps({"headers": {"x-counted": "yes"}}))
        """,
    )
    provider = OpenAIProvider(request_hook=hook)
    assert provider._build_headers(session_id="a")["x-counted"] == "yes"
    assert provider._build_headers(session_id="a")["x-counted"] == "yes"
    count = (tmp_path / "count.txt").read_text(encoding="utf-8").count("x")
    assert count == 2


def test_request_hook_wins_over_session_hook(tmp_path):
    session_hook = _write_hook(
        tmp_path,
        "session.py",
        'import json; print(json.dumps({"headers": {"x-k": "session"}}))\n',
    )
    per_request = _write_hook(
        tmp_path,
        "per_request.py",
        'import json; print(json.dumps({"headers": {"x-k": "request"}}))\n',
    )
    provider = OpenAIProvider(
        request_hook=per_request, request_session_hook=session_hook
    )
    assert provider._build_headers(session_id="s")["x-k"] == "request"


def test_resolve_hook_path(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    assert resolve_hook_path("") is None
    assert resolve_hook_path(None) is None
    assert resolve_hook_path("~/hooks/z.py") == str(Path.home() / "hooks" / "z.py")
    assert resolve_hook_path("hooks/z.py").endswith("home/hooks/z.py")
    assert resolve_hook_path("/abs/z.py") == "/abs/z.py"


def test_hook_relative_path_resolves_against_nova_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    hooks_dir = home / "hooks"
    hooks_dir.mkdir(parents=True)
    _write_hook(hooks_dir, "rel.py", ECHO_HOOK)
    monkeypatch.setenv("NOVA_HOME", str(home))
    headers = request_hook.run_session_hook("hooks/rel.py", "sess-1")
    assert headers["x-opencode-session"] == "ses-from-hook"


def test_build_llm_wires_request_hook(tmp_path, monkeypatch):
    home = tmp_path / "nova-headers"
    home.mkdir(parents=True, exist_ok=True)
    hook = _write_hook(home, "hook.py", ECHO_HOOK)
    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "oc": {
                        "type": "openai-compatible",
                        "options": {
                            "base_url": "https://opencode.ai/zen/go/v1",
                            "api_key": "test-key",
                            "user_agent": "nova/1.0",
                            "headers": {"x-opencode-client": "nova/1.0"},
                            "request_hook": hook,
                        },
                        "models": {
                            "deepseek-v4-flash": {
                                "name": "deepseek-v4-flash",
                                "tools": True,
                            }
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVA_HOME", str(home))

    from nova.settings import get_settings
    import nova.app.runtime as runtime

    get_settings.cache_clear()
    runtime._llm_cache.clear()
    try:
        llm = runtime.build_llm(provider="oc", model="deepseek-v4-flash")
        headers = llm._build_headers(session_id="sess-1")
        assert headers["User-Agent"] == "nova/1.0"
        assert headers["x-opencode-client"] == "nova/1.0"
        assert headers["x-opencode-session"] == "ses-from-hook"
    finally:
        runtime._llm_cache.clear()
        get_settings.cache_clear()
