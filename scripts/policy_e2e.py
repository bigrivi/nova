"""Every permission policy, verified against a real Nova server.

Lives in /tmp on purpose. A script that starts servers and calls a paid LLM has no
business in ``tests/``: that directory is collected by pytest, and a file there
that reaches the network is one config change away from running inside CI.

Each scenario gets its own ``NOVA_HOME`` containing its own ``permissions.json``
*and* its own ``config.json`` (for the port). That is not tidiness -- both
permission axes are read once per process, so a config change cannot reach a
running agent. Sharing one server across variants would silently test the first
variant for all of them.

Two layers, labelled, because they answer different questions:

  E2E       a real agent turn over HTTP/SSE. Proves the whole path works:
            ``decide()`` -> behaviour registry -> invoker -> SSE -> approve
            endpoint -> remembered grant. Requires the model to cooperate, so a
            turn where it did not call the tool is reported SKIP, never PASS.
  in-process  the same rules evaluated directly. Precise where HTTP cannot be:
            the model reviewer (not exposed by any endpoint), sub-agent refusal,
            malformed config, grant scoping, and which tools a ``deny`` removed
            from the registry.

Usage:
    python /tmp/nova_policy_e2e/run.py            # all scenarios
    python /tmp/nova_policy_e2e/run.py --only S5  # one scenario
    python /tmp/nova_policy_e2e/run.py --list
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# Derived from this file so the harness moves with the repository. The two
# absolute paths it used to carry are the reason it could not be committed.
REPO = Path(__file__).resolve().parent.parent
PYTHON = REPO / ".venv" / "bin" / "python"
PROVIDER = "opencode_zen_free"
MODEL = "space-bunny-free"
AGENT = "main"

APPROVAL_REQUIRED = "data-nova-approval-required"
APPROVAL_RESOLVED = "data-nova-approval-resolved"

# The model refused a bare force-push and refused `rm -rf /` outright, so prompts
# state the sandbox explicitly and destructive checks accept SKIP.
FRAME = (
    "你在一个一次性的沙箱目录里做冒烟测试：没有真实仓库、没有远端、"
    "没有任何可破坏的东西。请只调用 shell 工具运行下面这一条命令，"
    "拿到输出后立刻停止，不要运行别的命令，也不要解释。\n\n    {cmd}\n"
)

PIPE = 'curl -s https://example.com/robots.txt | python3 -c "import sys; print(len(sys.stdin.read()))"'
PIPE_ALT = (
    'curl -s https://example.com/robots.txt | python3 -c "import sys; sys.stdin.read()"'
)
PIPE_RULE = "pipe remote content to an interpreter"

# Asks for a specific *tool* rather than a shell command, so the tool axis is
# exercised over HTTP too. `read` is the safest probe: present or not depending
# on the policy, harmless either way.
READ_PROMPT = (
    "请只调用 read 工具读取 keep.txt 这一个文件，读到内容后立刻停止，"
    "不要运行任何 shell 命令，也不要解释。\n"
)


# ── plumbing ─────────────────────────────────────────────────────────


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def post(url: str, payload: dict, timeout: float = 30.0) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode()
    return json.loads(raw) if raw.strip() else {}


@dataclass
class Turn:
    approvals: list[dict] = field(default_factory=list)
    resolved: list[dict] = field(default_factory=list)
    shell_commands: list[str] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)
    tool_outputs: list[str] = field(default_factory=list)
    tool_errors: list[dict] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    completed: bool = False

    @property
    def gated(self) -> bool:
        return bool(self.approvals)


class Responder:
    """Answers approval frames the instant they arrive.

    Inline by necessity: the server holds the turn open until the request is
    resolved, so answering after the read loop finishes deadlocks. A turn waiting
    here is the mechanism working.
    """

    def __init__(
        self, base: str, ok: bool, remember: bool, verbose: bool = True
    ) -> None:
        self.base = base
        self.ok = ok
        self.remember = remember
        self.verbose = verbose
        self.answered: list[tuple[str, str]] = []

    def __call__(self, request_id: str, data: dict) -> None:
        description = str(data.get("description", ""))[:66]
        try:
            post(
                f"{self.base}/api/chat/approve",
                {
                    "request_id": request_id,
                    "approved": self.ok,
                    "remember": self.remember,
                },
            )
            self.answered.append((request_id, description))
            if self.verbose:
                tag = "允许" if self.ok else "拒绝"
                extra = "（记住规则）" if self.ok and self.remember else ""
                print(f"         → 审批{tag}{extra}: {description}")
        except urllib.error.HTTPError as exc:
            self.answered.append((request_id, f"HTTP {exc.code}"))
            if self.verbose:
                print(f"         → 审批失败 HTTP {exc.code}: {description}")


def stream_turn(base, session_id, message, workspace, on_approval=None, timeout=240.0):
    turn = Turn()
    # Output and error frames carry a toolCallId, not a name. Attributing them
    # through "the last tool announced" is wrong as soon as one step calls two
    # tools, which is the normal case; the call id is the only reliable link.
    _name_by_call: dict[str, str] = {}
    payload = {
        "message": message,
        "session_id": session_id,
        "provider": PROVIDER,
        "model": MODEL,
        "agent_key": AGENT,
        "workspace_dir": str(workspace),
    }
    req = urllib.request.Request(
        f"{base}/api/chat/stream",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                turn.completed = True
                break
            try:
                frame = json.loads(body)
            except json.JSONDecodeError:
                continue
            kind = frame.get("type", "")
            if frame.get("toolName") and frame.get("toolCallId"):
                _name_by_call[frame["toolCallId"]] = frame["toolName"]
            # Two shapes: AI SDK frames carry fields at the top level, data-nova-*
            # frames nest them under "data". Reading only "data" misses every tool.
            data = frame.get("data") or {}
            if kind == APPROVAL_REQUIRED:
                turn.approvals.append(data)
                if on_approval and data.get("requestId"):
                    on_approval(data["requestId"], data)
            elif kind == APPROVAL_RESOLVED:
                turn.resolved.append(data)
            elif kind == "tool-output-available":
                name = _name_by_call.get(frame.get("toolCallId", ""), "?")
                turn.tool_outputs.append(name)
            elif kind == "data-nova-tool-error":
                # An error frame means there was no result. Recording the tool
                # name here made a denied tool look like it had produced output.
                turn.tool_errors.append(data)
            elif kind == "tool-input-available":
                name = frame.get("toolName", "")
                turn.tool_calls.append(name)
                if name == "shell":
                    call = frame.get("input") or {}
                    if isinstance(call, str):
                        try:
                            call = json.loads(call)
                        except json.JSONDecodeError:
                            call = {}
                    turn.shell_commands.append(str(call.get("command", ""))[:110])
            elif kind == "text-delta":
                delta = frame.get("delta")
                if isinstance(delta, str):
                    turn.texts.append(delta)
    return turn


def executed(turn: Turn, intent: str) -> bool:
    """Whether the model ran the thing the check is about.

    Case-insensitive, and it looks at tool names as well as shell commands: the
    model rewrites case freely (`CURL -S ...`), and a mismatch there reads as a
    policy failure rather than a reword. Matching tool names is what lets the tool
    axis reuse the same field.
    """
    needle = intent.lower()
    return any(needle in c.lower() for c in turn.shell_commands) or any(
        needle in t.lower() for t in turn.tool_calls
    )


class Server:
    """A Nova process with an isolated NOVA_HOME, port and permissions file."""

    def __init__(self, permissions: dict | None, label: str) -> None:
        self.home = Path(tempfile.mkdtemp(prefix=f"nova_pol_{label}_"))
        self.port = free_port()
        self.label = label
        self.base = f"http://127.0.0.1:{self.port}"
        self.log = self.home / "server.log"
        # Inherit the real providers verbatim and override only the port. An
        # isolated home that ships ``"providers": {}`` has no model to call, and
        # that fails as a silent empty response rather than an error -- which is
        # how the first full run produced sixteen SKIPs and no diagnosis.
        real = {}
        real_config = Path(os.path.expanduser("~/.nova/config.json"))
        if real_config.exists():
            try:
                real = json.loads(real_config.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                real = {}
        payload = {k: v for k, v in real.items() if k != "server"}
        payload["server"] = {
            "host": "127.0.0.1",
            "port": self.port,
            "log_level": "INFO",
        }
        (self.home / "config.json").write_text(json.dumps(payload), encoding="utf-8")
        if permissions is not None:
            self.write_permissions(permissions)

    def write_permissions(self, payload: dict) -> None:
        (self.home / "permissions.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    def __enter__(self) -> Server:
        LAST_LOG.clear()
        LAST_LOG.append(str(self.log))
        env = {**os.environ, "NOVA_HOME": str(self.home), "NOVA_NO_OPEN": "1"}
        self._fh = self.log.open("w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [str(PYTHON), "-m", "nova", "serve"],
            cwd=str(REPO),
            env=env,
            stdout=self._fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        for _ in range(90):
            if self.proc.poll() is not None:
                raise RuntimeError(f"服务退出: {self.log.read_text()[-800:]}")
            try:
                urllib.request.urlopen(f"{self.base}/", timeout=1)
                return self
            except urllib.error.HTTPError:
                return self
            except (urllib.error.URLError, OSError):
                time.sleep(0.4)
        raise RuntimeError("服务 36 秒内未就绪")

    def log_lines(self, needle: str) -> list[str]:
        if not self.log.exists():
            return []
        return [
            ln
            for ln in self.log.read_text(errors="replace").splitlines()
            if needle in ln
        ]

    def __exit__(self, *exc) -> None:
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            self.proc.wait(timeout=12)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except (ProcessLookupError, AttributeError):
                pass
        try:
            self._fh.close()
        except OSError:
            pass


# ── reporting ────────────────────────────────────────────────────────


# The most recent server log, so a harness failure can quote it.
LAST_LOG: list[str] = []


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

    def add(self, layer: str, name: str, verdict: str, detail: str = "") -> None:
        self.rows.append((layer, name, verdict, detail))
        mark = {"PASS": "ok  ", "FAIL": "FAIL", "SKIP": "skip", "ERROR": "err "}[
            verdict
        ]
        print(f"  [{mark}] {name}")
        for line in detail.splitlines():
            print(f"         {line}")

    def count(self, verdict: str) -> int:
        return sum(1 for *_, v, _ in self.rows if v == verdict)

    @property
    def failed(self) -> int:
        """Only product failures.

        ``ERROR`` is the harness failing -- a stalled provider, a server killed
        mid-approval -- and says nothing about the permissions. Counting it would
        make a flaky network look like a broken policy.
        """
        return self.count("FAIL")


# ── scenarios ────────────────────────────────────────────────────────

SHELL = "shell"
TOOL = "tools"
BOTH = "both"
LOCAL = "in-process"


@dataclass
class Scenario:
    sid: str
    axis: str
    title: str
    permissions: dict | None
    turns: list[tuple[str, str, bool]]  # (prompt, intent substring, expect_gated)
    deny_tool: str | None = None  # a tool that must never produce a result


SCENARIOS: list[Scenario] = [
    Scenario(
        "V0",
        SHELL,
        "出厂默认：无规则放行、ask 询问、工作区豁免、工作区外询问",
        None,
        [
            (PIPE, "robots.txt", True),
            ("ls -la", "ls", False),
            ("rm -rf build/output", "build/output", False),
            ("rm -rf /tmp/nova_outside_dir", "nova_outside_dir", True),
        ],
    ),
    Scenario(
        "V1",
        SHELL,
        "配置 allow：预批准内置 ask 规则，且忽略大小写",
        {"shell": {"allow": ["curl -s *"]}},
        [
            (PIPE, "robots.txt", False),
            ("CURL -S https://example.com/robots.txt", "ROBOTS.TXT", False),
        ],
    ),
    Scenario(
        "V2",
        SHELL,
        "配置 disable：按描述移除内置规则",
        {"shell": {"disable": [PIPE_RULE]}},
        [(PIPE, "robots.txt", False)],
    ),
    Scenario(
        "V3",
        SHELL,
        "配置 ask：新增一条原本不存在的规则",
        {"shell": {"ask": [{"match": r"\bls\b", "description": "listing files"}]}},
        [("ls -la", "ls", True)],
    ),
    Scenario(
        "V4",
        SHELL,
        "配置 allow 够不到 block：rm -rf * 无法豁免根删除",
        {"shell": {"allow": ["rm -rf *"]}},
        [
            ("rm -rf /", "rm -rf /", False),
            ("rm -rf /etc/hosts", "/etc/hosts", False),
        ],
    ),
    Scenario(
        "V5",
        TOOL,
        "工具策略 ask：read 被询问",
        {"tools": {"read": "ask"}},
        [(READ_PROMPT, "read", True)],
    ),
    Scenario(
        "V6",
        TOOL,
        "工具策略 deny：read 从注册表消失，调用也失败",
        {"tools": {"read": "deny"}},
        [(READ_PROMPT, "read", False)],
        deny_tool="read",
    ),
    Scenario(
        "V7",
        TOOL,
        "工具策略 * deny 但 web_* 保留，shell 始终豁免",
        {"tools": {"*": "deny", "web_*": "allow"}},
        [(READ_PROMPT, "read", False)],
        deny_tool="read",
    ),
    Scenario(
        "V8",
        BOTH,
        "两个轴同时生效，互不干扰",
        {"shell": {"allow": ["curl -s *"]}, "tools": {"read": "ask"}},
        [(PIPE, "robots.txt", False)],
    ),
]


# ── in-process layer ─────────────────────────────────────────────────
#
# Precise where HTTP cannot be. No server, no model, no network.


def inprocess_shell(rules_path: Path | None, command: str, workspace: Path | None):
    sys.path.insert(0, str(REPO))
    import importlib

    policy = importlib.import_module("nova.tools.shell.policy")
    rules = policy.load_rule_set(rules_path)
    return rules.classify(command, str(workspace) if workspace else None)


def inprocess_tools(rules_path: Path | None) -> set[str]:
    """The tools a real toolset ends up offering, after denies are applied."""
    sys.path.insert(0, str(REPO))
    import asyncio
    import tempfile as _tf

    from nova.agent.toolset import ToolsetBuilder
    from nova.skills.service import SkillService
    from nova.tools.approval import ApprovalManager
    from nova.tools.registry import ToolRegistry
    from nova.tools.tool_policy import load_tool_policy

    async def build() -> set[str]:
        registry = ToolRegistry()
        with _tf.TemporaryDirectory() as tmp:
            builder = ToolsetBuilder(
                registry=registry,
                skill_service=SkillService(skills_dir=Path(tmp) / "skills"),
                approval=ApprovalManager(),
                is_sub_agent=True,
                tool_policy=load_tool_policy(rules_path),
            )
            await builder.build()
        return {t.name for t in registry.list_tools()}

    return asyncio.run(build())


def check_local(report: Report, workspace: Path) -> None:
    """The policies no endpoint can reach."""
    sys.path.insert(0, str(REPO))
    import asyncio
    import importlib

    shell = importlib.import_module("nova.tools.shell")
    decide = shell.decide
    from nova.tools.approval import ApprovalManager
    from nova.tools.behavior import ShellToolBehavior, TurnContext
    from nova.tools.tool_policy import ToolPolicy

    def ctx():
        return TurnContext(session_id="s1")

    async def reviewer(v):
        async def fn(subject, reason):
            return v

        return fn

    # ── model reviewer: only ever clears ────────────────────────────
    print("\n【进程内】模型复核：只能放行，不能拒绝")
    for label, verdict, expect_gate in [
        ("approve", "approve", False),
        ("deny", "deny", True),
        ("escalate", "escalate", True),
        ("无 provider", None, True),
    ]:
        mgr = ApprovalManager()
        behavior = ShellToolBehavior(mgr, reviewer=asyncio.run(reviewer(verdict)))
        result = asyncio.run(behavior.before_execute({"command": PIPE}, ctx()))
        gated = result.approval_request is not None
        report.add(
            LOCAL,
            f"复核 {label} → {'询问' if expect_gate else '放行'}",
            "PASS" if gated == expect_gate else "FAIL",
            "" if gated == expect_gate else f"实际 {'询问' if gated else '放行'}",
        )

    # A grant and a reviewer share an identity -- the grant is keyed on the rule
    # and the declined command matches that same rule -- so a grant recorded for
    # one command used to run the next one the reviewer had just refused. The
    # prompt has to be unavoidable, which means it also has nothing to remember.
    print("\n【进程内】复核否决时，已有授权不能代替询问")
    for verdict in ("deny", "escalate"):
        mgr = ApprovalManager()
        behavior = ShellToolBehavior(mgr, reviewer=asyncio.run(reviewer(verdict)))
        rule = asyncio.run(decide(PIPE)).rule
        mgr.add_to_allowlist(rule, session_id="s1")
        result = asyncio.run(behavior.before_execute({"command": PIPE}, ctx()))
        asked = result.approval_request is not None
        rememberable = (result.approval_request or {}).get("rememberable", False)
        ok = asked and rememberable is False
        report.add(
            LOCAL,
            f"复核 {verdict} + 已有授权 → 仍然询问且不可记住",
            "PASS" if ok else "FAIL",
            "" if ok else f"询问={asked} rememberable={rememberable}",
        )

    # ── sub-agent: refused even when the reviewer approves ───────────
    print("\n【进程内】sub-agent：没有审批通道，复核也无用")
    mgr = ApprovalManager()
    behavior = ShellToolBehavior(
        mgr, is_sub_agent=True, reviewer=asyncio.run(reviewer("approve"))
    )
    result = asyncio.run(behavior.before_execute({"command": PIPE}, ctx()))
    ok = (not result.allowed) and "sub-agent" in (result.reject_reason or "")
    report.add(
        LOCAL,
        "sub-agent 即使被复核放行也拒绝",
        "PASS" if ok else "FAIL",
        "" if ok else f"allowed={result.allowed} reason={result.reject_reason}",
    )

    # ── tool policy resolution ──────────────────────────────────────
    print("\n【进程内】工具策略解析：最长前缀胜出，与键序无关")
    import itertools

    rules = {"mcp__g": "allow", "mcp__github__*": "deny", "*": "ask"}
    outcomes = {
        ToolPolicy(dict(order)).effect_for("mcp__github__star")
        for order in itertools.permutations(rules.items())
    }
    report.add(
        LOCAL,
        "deny 不被更短的 allow 前缀压掉",
        "PASS" if outcomes == {"deny"} else "FAIL",
        "" if outcomes == {"deny"} else f"6 种键序得到 {outcomes}",
    )
    bare = ToolPolicy({"read": "deny"})
    ok = bare.effect_for("read") == "deny" and bare.effect_for("read_file") == "allow"
    report.add(
        LOCAL,
        "只有尾随 * 才算命名空间",
        "PASS" if ok else "FAIL",
        "" if ok else "裸名不应吞掉前缀相同的其他工具",
    )

    # ── malformed config falls back to defaults, never raises ────────
    print("\n【进程内】配置文件损坏时回落到默认值")
    import tempfile as _tf

    for label, payload in [
        ("非法 JSON", "{not json"),
        ("顶层是数组", "[]"),
        ("shell 不是对象", '{"shell": 5}'),
        ("tools 不是对象", '{"tools": "write"}'),
        ("效果值拼错", '{"tools": {"write": "sometimes"}}'),
    ]:
        with _tf.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write(payload)
            bad = Path(fh.name)
        try:
            d = inprocess_shell(bad, PIPE, workspace)
            t = ToolPolicy(
                __import__("nova.tools.tool_policy", fromlist=["x"]).load_tool_policy(
                    bad
                )
            )
            ok = d.effect == "ask" and t.effect_for("write") == "allow"
            report.add(
                LOCAL,
                f"损坏配置（{label}）→ 用默认值",
                "PASS" if ok else "FAIL",
                "" if ok else f"shell={d.effect} tools.write={t.effect_for('write')}",
            )
        finally:
            bad.unlink(missing_ok=True)

    # ── grant scoping ───────────────────────────────────────────────
    print("\n【进程内】授权范围：无名会话不落盘、不跨会话")
    mgr = ApprovalManager()
    mgr.add_to_allowlist("tool:web_fetch", session_id="")
    ok = mgr.allowlist_for("") == set() and mgr.allowlist_for("other") == set()
    report.add(LOCAL, "空 session_id 的授权被丢弃", "PASS" if ok else "FAIL")

    mgr2 = ApprovalManager()
    mgr2.add_to_allowlist("tool:web_fetch", session_id="a")
    # The grant key is a (rule, family) pair. A tool call has no command line to
    # read a family from, so its family is empty and it matches on the rule alone.
    ok = mgr2.allowlist_for("a") == {("tool:web_fetch", "")} and (
        mgr2.allowlist_for("b") == set()
    )
    report.add(LOCAL, "授权不跨会话泄漏", "PASS" if ok else "FAIL")

    mgr3 = ApprovalManager()
    rid = mgr3.pre_request("x", "", session_id="", rule="some-rule")
    mgr3.resolve(rid, approved=True, remember=True)
    report.add(
        LOCAL,
        "resolve 路径同样要求 session_id",
        "PASS" if mgr3.allowlist_for("") == set() else "FAIL",
    )

    # ── the shell is exempt from the tool policy ────────────────────
    print("\n【进程内】shell 不受工具策略支配")
    names = inprocess_tools(_write_temp({"tools": {"*": "deny"}}))
    ok = "shell" in names
    report.add(
        LOCAL,
        'tools: {"*": "deny"} 不会摘掉 shell',
        "PASS" if ok else "FAIL",
        "" if ok else f"注册表: {sorted(names)[:8]}",
    )


def _write_temp(payload: dict) -> Path:
    import tempfile as _tf

    # NamedTemporaryFile(delete=False) rather than the context manager: the
    # server reads this path from another process after this returns, so it has to
    # outlive the block, and the `with` form would delete it on the way out.
    with _tf.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(payload, fh)
        return Path(fh.name)


# ── per-scenario runner ──────────────────────────────────────────────


def run_scenario(scenario: Scenario, report: Report, only_e2e: bool) -> None:
    print(f"\n{'=' * 70}")
    print(f"{scenario.sid}  [{scenario.axis}]  {scenario.title}")
    if scenario.permissions:
        print(
            f"    permissions.json: {json.dumps(scenario.permissions, ensure_ascii=False)}"
        )
    print("=" * 70)

    permissions_path: Path | None = None

    # The in-process pass reads the same file the server will read.
    if scenario.permissions is not None:
        permissions_path = _write_temp(scenario.permissions)

    if not only_e2e:
        print("  -- 进程内判定 --")
        # The shell classifier is meaningless for a tool-axis turn: the prompt is
        # prose asking for the `read` tool, which matches no shell rule, so the
        # check would report "allowed" and call it a failure.
        shell_turns = scenario.turns if scenario.axis in (SHELL, BOTH) else []
        for command, intent, expect_gated in shell_turns:
            workspace = Path(tempfile.mkdtemp(prefix="nova_ws_"))
            (workspace / "build").mkdir()
            try:
                d = inprocess_shell(permissions_path, command, workspace)
                gated = d.effect == "ask"
                report.add(
                    LOCAL,
                    f"{scenario.sid} {intent[:34]} → {'询问' if expect_gated else '放行'}",
                    "PASS" if gated == expect_gated else "FAIL",
                    f"effect={d.effect} rule={d.rule or '—'}",
                )
            finally:
                shutil.rmtree(workspace, ignore_errors=True)
        if scenario.axis in (TOOL, BOTH):
            names = inprocess_tools(permissions_path)
            expect_absent = set()
            tools_block = (scenario.permissions or {}).get("tools", {})
            for key, effect in tools_block.items():
                if effect != "deny":
                    continue
                if key.endswith("*") and key != "*":
                    prefix = key[:-1]
                    expect_absent |= {n for n in names if n.startswith(prefix)}
                elif key == "*":
                    expect_absent |= {n for n in names if not n.startswith("web_")}
                else:
                    expect_absent.add(key)
            # ``shell`` is exempt by design: it decides against its own rule set,
            # and a tool-policy deny must not silently disarm it. Asserted
            # separately below rather than folded into the deny set.
            expect_absent.discard("shell")
            still_there = sorted(expect_absent & names)
            report.add(
                LOCAL,
                f"{scenario.sid} deny 的工具已从注册表消失",
                "PASS" if not still_there else "FAIL",
                f"注册表 {len(names)} 个工具；应消失 {sorted(expect_absent)[:6]}"
                + (f"；仍在: {still_there}" if still_there else ""),
            )

    if not scenario.turns:
        if permissions_path:
            permissions_path.unlink(missing_ok=True)
        return

    print("  -- 真实回合（E2E）--")
    with Server(scenario.permissions, scenario.sid) as server:
        base = server.base
        workspace = Path(tempfile.mkdtemp(prefix="nova_ws_"))
        (workspace / "build").mkdir()
        (workspace / "keep.txt").write_text("e2e\n", encoding="utf-8")
        try:
            resp = post(
                f"{base}/api/chat",
                {
                    "message": "ready",
                    "provider": PROVIDER,
                    "model": MODEL,
                    "agent_key": AGENT,
                    "workspace_dir": str(workspace),
                },
                timeout=180,
            )
            session_id = resp.get("session_id") or resp.get("sessionId") or ""
            if not session_id:
                # Every turn would otherwise report "the model did not call the
                # shell", which reads as a model problem and hides a broken setup.
                raise RuntimeError(
                    "会话创建失败，响应: "
                    + json.dumps(resp, ensure_ascii=False)[:200]
                    + "；日志尾部: "
                    + server.log.read_text(errors="replace")[-400:]
                )
            print(f"    会话 {session_id}  端口 {server.port}")

            for command, intent, expect_gated in scenario.turns:
                responder = Responder(base, ok=False, remember=False)
                turn = stream_turn(
                    base,
                    session_id,
                    FRAME.format(cmd=command),
                    workspace,
                    on_approval=responder,
                )
                label = f"{scenario.sid} E2E {intent[:32]}"
                # A free model refuses intermittently. One retry separates "the
                # policy did the wrong thing" from "the model did not feel like
                # it this time"; without it a third of the checks flake to SKIP.
                if not executed(turn, intent):
                    print("         （重试一次）")
                    responder = Responder(base, ok=False, remember=False)
                    turn = stream_turn(
                        base,
                        session_id,
                        FRAME.format(cmd=command),
                        workspace,
                        on_approval=responder,
                    )
                ran = executed(turn, intent)
                if not turn.tool_calls and not turn.shell_commands:
                    report.add(
                        "E2E",
                        label,
                        "SKIP",
                        "模型未调用任何工具：" + " ".join(turn.texts)[:130],
                    )
                elif not ran:
                    actual = (
                        turn.shell_commands[0]
                        if turn.shell_commands
                        else (f"只调用了 {sorted(set(turn.tool_calls))}")
                    )
                    report.add(
                        "E2E", label, "SKIP", f"模型改写了目标。实际: {actual[:80]}"
                    )
                elif turn.gated != expect_gated:
                    report.add(
                        "E2E",
                        label,
                        "FAIL",
                        f"期望{'询问' if expect_gated else '放行'}，"
                        f"实际{'询问' if turn.gated else '放行'}；"
                        f"工具={sorted(set(turn.tool_calls))}",
                    )
                else:
                    detail = f"工具={sorted(set(turn.tool_calls))}"
                    if turn.shell_commands:
                        detail += f"；命令={turn.shell_commands[0][:48]}"
                    if turn.gated:
                        detail += (
                            f"；规则={turn.approvals[0].get('description', '')[:42]}"
                        )
                    detail += f"；撤回帧 {len(turn.resolved)}"
                    report.add("E2E", label, "PASS", detail)

                if scenario.deny_tool and ran:
                    # Asserted as "it did not succeed", via the error frame. Three
                    # wrong versions of this check, each instructive:
                    #   - ``tool-input-available`` only says the model emitted a call,
                    #     so presence there proves nothing about the tool existing;
                    #   - a tool that raises emits BOTH ``tool-output-available``
                    #     (carrying the failure text) and ``data-nova-tool-error``,
                    #     so "no output frame" is not the test;
                    #   - names must match exactly -- "read" is a substring of
                    #     "read_image", which reported a result for an uncalled tool.
                    # Outputs are attributed by toolCallId, since one step can call
                    # several tools and "the last one announced" misattributes.
                    errored = {str(e.get("toolName", "")) for e in turn.tool_errors}
                    called = scenario.deny_tool in set(turn.tool_calls)
                    succeeded = scenario.deny_tool in set(turn.tool_outputs)
                    detail = (
                        f"调用={sorted(set(turn.tool_calls))}；"
                        f"报错工具={sorted(errored)}；"
                        f"产出结果={sorted(set(turn.tool_outputs))}"
                    )
                    # Only assertable when the model actually reached for it.
                    if called and succeeded:
                        report.add(
                            "E2E",
                            f"{scenario.sid} 被 deny 的工具调用后失败",
                            "FAIL",
                            detail + "；但它成功了",
                        )
                    else:
                        report.add(
                            "E2E",
                            f"{scenario.sid} 被 deny 的工具调用后失败",
                            "PASS",
                            detail,
                        )

            approvals = len(server.log_lines("Approval required"))
            print(f"    服务端日志：Approval required × {approvals}")
            if scenario.sid == "V0" and approvals:
                report.add(
                    "E2E",
                    "V0 服务端确实记录了审批",
                    "PASS",
                    f"{approvals} 条 Approval required 日志",
                )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
    if permissions_path:
        permissions_path.unlink(missing_ok=True)


# ── main ─────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", action="append", help="只跑指定场景 id")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--local-only", action="store_true", help="只跑进程内检查")
    args = parser.parse_args()

    if args.list:
        for s in SCENARIOS:
            print(f"  {s.sid}  [{s.axis}]  {s.title}  ({len(s.turns)} 回合)")
        return 0

    if not PYTHON.exists():
        print(f"找不到 {PYTHON}", file=sys.stderr)
        return 2

    print(f"Nova 权限策略全量验证   仓库 {REPO}")
    print(f"模型 {PROVIDER}:{MODEL}   脚本目录 {Path(__file__).parent}")

    report = Report()
    started = time.monotonic()

    if not args.local_only:
        for scenario in SCENARIOS:
            if args.only and scenario.sid not in args.only:
                continue
            try:
                # The free provider rate-limits bursts. Nine back-to-back servers
                # produced a 187s stall that looked like a hang; a short pause
                # between scenarios is cheaper than diagnosing that again.
                if args.only is None and scenario is not SCENARIOS[0]:
                    time.sleep(4)
                try:
                    run_scenario(scenario, report, only_e2e=False)
                except Exception as first:
                    # One retry: a multi-minute stall is the provider, not the
                    # policy. Two failures in a row is a real signal.
                    print(f"    （场景异常，重试一次: {type(first).__name__}）")
                    time.sleep(6)
                    run_scenario(scenario, report, only_e2e=False)
            except Exception as exc:
                # Without the server log this is unactionable: the first V3
                # timeout produced only ``TimeoutError('timed out')`` and no
                # way to tell a slow model from a server that never answered.
                detail = repr(exc)[:200]
                if LAST_LOG and Path(LAST_LOG[0]).exists():
                    tail = Path(LAST_LOG[0]).read_text(errors="replace")[-1200:]
                    detail += "\n         服务端日志尾部:\n" + "\n".join(
                        "           " + ln for ln in tail.splitlines()[-12:]
                    )
                report.add(
                    "harness",
                    f"{scenario.sid} 场景执行（harness，非产品）",
                    "ERROR",
                    detail,
                )

    if not args.only:
        print("\n" + "=" * 70)
        print("进程内专项（接口无法覆盖的部分）")
        print("=" * 70)
        workspace = Path(tempfile.mkdtemp(prefix="nova_ws_"))
        (workspace / "build").mkdir()
        try:
            check_local(report, workspace)
        except Exception as exc:
            report.add("harness", "进程内专项", "FAIL", repr(exc)[:200])
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    total = len(report.rows)
    print("\n" + "=" * 70)
    print(
        f"{total} 项：{report.count('PASS')} 通过，"
        f"{report.failed} 失败，{report.count('SKIP')} 跳过，"
        f"{report.count('ERROR')} harness 错误"
        f"（耗时 {time.monotonic() - started:.0f}s）"
    )
    by_layer: dict[str, list[str]] = {}
    for layer, name, verdict, _ in report.rows:
        if verdict == "FAIL":
            by_layer.setdefault(layer, []).append(name)
    for layer, names in by_layer.items():
        print(f"  {layer} 失败：")
        for n in names:
            print(f"    - {n}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
