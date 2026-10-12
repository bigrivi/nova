"""MCP tool names: namespaced, length-bounded, unique, and reported when unusable.

Two defects live here and they pull against each other. Registering a server's
tool under the name it chose let it collide with Nova's own -- and the collision
was resolved by dropping the tool silently, so the connection test reported a
usable server and the agent could never call the thing it named. Namespacing
removes the collision, but a namespace alone can still collide: two server names
that sanitize alike, two long names that share a readable prefix, or a name the
provider rejects outright.

So these tests pin the properties rather than the examples: no built-in name is
ever handed out, every name fits the budget, no two tools share a name, and the
answer does not depend on the order the servers happened to connect in.
"""

from __future__ import annotations

import json

import pytest

from nova.mcp.manager import MCPManager
from nova.mcp.naming import (
    MAX_TOOL_NAME_LENGTH,
    MCP_TOOL_PREFIX,
    allocate,
    qualify,
    sanitize,
)
from nova.settings import get_settings
from nova.tools.registry import ToolRegistry

# ── the shape of a name ───────────────────────────────────────────────


def test_a_tool_is_namespaced_by_its_server() -> None:
    """The prefix is what Nova's own permission rules match on."""

    assert qualify("github", "list_issues") == "mcp__github__list_issues"


def test_names_sanitize_to_what_a_provider_accepts() -> None:
    """Real listings contain characters a tool name cannot carry."""

    assert sanitize("@modelcontextprotocol/server-filesystem", "server") == (
        "modelcontextprotocol_server-filesystem"
    )
    assert sanitize("list_services.v2", "tool") == "list_services_v2"
    assert sanitize("my server", "server") == "my_server"


def test_an_unusable_name_still_produces_one() -> None:
    """A naming quirk must not silently cost the user a working tool."""

    assert sanitize("///", "server") == "server"
    assert sanitize("", "tool") == "tool"


def test_the_server_and_tool_boundary_is_unambiguous() -> None:
    """Double underscore, so a name containing underscores still splits.

    The single-underscore form this replaces could not: `mcp_my_server_query`
    carries no way to tell a server called `my` from one called `my_server`.
    """

    name = qualify("my_server", "query")

    assert name == "mcp__my_server__query"
    prefix, _, tool = name[len(MCP_TOOL_PREFIX) :].partition("__")
    assert prefix == "my_server"
    assert tool == "query"


# ── collisions a namespace alone does not prevent ─────────────────────


def test_two_servers_may_offer_the_same_tool_name() -> None:
    """The cross-server case the bare name could not express at all."""

    names = allocate([("github", "create_issue"), ("linear", "create_issue")])

    assert set(names.values()) == {
        "mcp__github__create_issue",
        "mcp__linear__create_issue",
    }


def test_servers_whose_names_sanitize_alike_stay_distinct() -> None:
    """`a.b` and `a/b` both become `a_b`.

    Without this the second server's tool is dropped for the first -- the exact
    defect namespacing was meant to remove, reappearing one layer up.
    """

    names = allocate([("a.b", "query"), ("a/b", "query")])

    assert len(set(names.values())) == 2


def test_colliding_names_are_both_hashed_rather_than_one_kept_clean() -> None:
    """Uniqueness could be reached by letting the first keep the clean base and
    hashing only the second. Both carrying a suffix is the better outcome: neither
    name then looks like it addresses one specific server, which is what makes the
    pair read as a collision rather than as an accident.
    """

    names = allocate([("a.b", "query"), ("a/b", "query")])

    assert all("_" in value.rsplit(MCP_TOOL_PREFIX, 1)[-1] for value in names.values())
    assert not any(value.endswith("__query") for value in names.values())


def test_a_built_in_name_is_never_handed_to_a_server() -> None:
    """The reserved set is what keeps a server from displacing `edit`."""

    names = allocate([("github", "edit")], reserved=["edit", "read", "write"])

    assert "edit" not in names.values()
    assert names[("github", "edit")].startswith(MCP_TOOL_PREFIX)


# ── the provider's length budget ──────────────────────────────────────


def test_a_long_name_is_shortened_into_the_budget() -> None:
    """OpenAI's tool-use API rejects a function name over 64 characters."""

    name = qualify("s" * 60, "t" * 60)

    assert len(name) <= MAX_TOOL_NAME_LENGTH


def test_shortened_names_that_share_a_prefix_stay_distinct() -> None:
    """Truncation alone would collapse these two into one name."""

    names = allocate([("server_one", "x" * 50), ("server_two", "x" * 50)])

    assert len(set(names.values())) == 2
    assert all(len(name) <= MAX_TOOL_NAME_LENGTH for name in names.values())


def test_shortening_keeps_the_readable_part() -> None:
    """A hash alone would be unambiguous and useless to anyone reading it."""

    name = qualify("a" * 50, "b" * 50)

    assert name.startswith(MCP_TOOL_PREFIX + "a" * 20)


# ── determinism ───────────────────────────────────────────────────────


def test_the_assignment_does_not_depend_on_connect_order() -> None:
    """A resumed session calls tools by name; the name has to be the same one.

    Servers connect in whatever order their sockets settle, so an allocator that
    resolved collisions by arrival would hand the same server a different tool
    name on the next run.
    """

    forward = allocate([("s", "a"), ("s", "b")], reserved=["edit"])
    backward = allocate([("s", "b"), ("s", "a")], reserved=["edit"])

    assert forward == backward


def test_a_short_name_is_left_exactly_as_it_is() -> None:
    """No trailing hash on names that never needed one."""

    names = allocate([("github", "list_issues")])

    assert names[("github", "list_issues")] == "mcp__github__list_issues"


# ── what the agent registers, and what it reports ─────────────────────


def _client(name: str, tools: list[dict]):
    from nova.mcp.client import McpClient

    client = McpClient(name, None)
    client._tools = tools
    return client


def _manager(clients: list) -> MCPManager:
    """A connected manager, planned the way ``ensure_initialized`` plans it.

    The plan is built there rather than at registration so the settings page can
    report before any agent has run; a test that skipped it would be testing a
    state the manager is never in.
    """
    manager = MCPManager()
    manager._mcp_clients = clients
    manager._initialized = True
    manager._plan = manager._build_plan()
    return manager


def _tool_def(name: str) -> dict:
    return {
        "name": name,
        "description": f"{name} does a thing",
        "inputSchema": {"type": "object", "properties": {}},
    }


def test_a_server_tool_registered_named_like_a_builtin_leaves_it_alone() -> None:
    """The defect: this tool used to be dropped for colliding with `edit`."""
    registry = ToolRegistry()
    registry.register_direct(
        name="edit",
        description="Nova's editor",
        func=lambda **_kw: None,
        params_schema={"type": "object", "properties": {}},
    )
    manager = _manager([_client("github", [_tool_def("edit")])])

    manager.register_tools(registry)

    assert registry.get("edit").description == "Nova's editor"
    assert "mcp__github__edit" in registry.tools


def test_registered_tools_are_marked_as_coming_from_a_server() -> None:
    """The flag is what keeps Nova from prompting on a call it cannot reason about."""
    registry = ToolRegistry()
    manager = _manager([_client("github", [_tool_def("list_issues")])])

    manager.register_tools(registry)

    assert registry.get("mcp__github__list_issues").from_mcp is True


def test_the_report_counts_what_the_server_offered() -> None:
    """Advertised against loaded, because the two can disagree."""
    registry = ToolRegistry()
    manager = _manager(
        [_client("github", [_tool_def("a"), _tool_def("b"), _tool_def("c")])]
    )

    manager.register_tools(registry)

    report = manager.load_report()
    assert len(report) == 1
    assert report[0].server == "github"
    assert report[0].advertised == 3
    assert report[0].loaded == 3


def test_a_duplicated_tool_is_reported_rather_than_overwritten() -> None:
    """A server listing one tool twice is a server bug the user can act on.

    Silent is the failure mode being avoided: without this, the second copy
    quietly replaces the first and the count still looks right.
    """
    registry = ToolRegistry()
    manager = _manager([_client("github", [_tool_def("query"), _tool_def("query")])])

    manager.register_tools(registry)

    report = manager.load_report()[0]
    assert report.advertised == 2
    assert report.loaded == 1
    assert report.skipped == [
        {"tool": "query", "reason": "the server listed this tool more than once"}
    ]


def test_a_tool_listed_without_a_name_is_reported() -> None:
    registry = ToolRegistry()
    manager = _manager([_client("github", [{"name": "  ", "description": ""}])])

    manager.register_tools(registry)

    report = manager.load_report()[0]
    assert report.loaded == 0
    assert len(report.skipped) == 1
    assert "no name" in report.skipped[0]["reason"]


def test_nothing_is_reported_before_any_server_connects() -> None:
    """Zero would read as 'this server has no tools', which is a different claim."""
    manager = MCPManager()

    assert manager.load_report() == []


def test_the_report_is_available_without_building_a_toolset() -> None:
    """The settings page asks this before anyone has run an agent."""
    manager = _manager([_client("github", [_tool_def("a"), _tool_def("b")])])

    report = manager.load_report()

    assert report[0].advertised == 2
    assert report[0].loaded == 2
    assert report[0].names == ["mcp__github__a", "mcp__github__b"]


@pytest.mark.asyncio
async def test_connecting_is_enough_to_report(
    monkeypatch, tmp_path, mcp_server_path
) -> None:
    """Drives the real wiring rather than ``_build_plan`` directly.

    A helper that plans by hand would pass this file while the production path
    never planned at all, leaving the settings page reporting nothing until an
    agent happened to run. So this goes through ``ensure_initialized`` against a
    real config and a real server, which is the only thing that proves the
    report is planned at connect time rather than at registration time.
    """
    import sys

    home = tmp_path / "home"
    home.mkdir()
    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {},
                "mcp_servers": {
                    "github": {"command": sys.executable, "args": [mcp_server_path]}
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    get_settings.cache_clear()

    manager = MCPManager()
    try:
        await manager.ensure_initialized()

        report = manager.load_report()
        assert len(report) == 1, "connecting alone must populate the report"
        assert report[0].server == "github"
        assert report[0].loaded >= 1
        assert report[0].names == [
            name for name in report[0].names if name.startswith(MCP_TOOL_PREFIX)
        ]
        # The pairing is what registration reads, so it has to be settled here.
        assert all(raw and registered for raw, registered in report[0].tools)
    finally:
        await manager.shutdown()


def test_the_planned_names_are_the_registered_names() -> None:
    """The settings page and the agent must not describe different name sets."""
    manager = _manager([_client("github", [_tool_def("edit")])])
    registry = ToolRegistry()

    manager.register_tools(registry)

    planned = manager.load_report()[0].names
    registered = [name for name in registry.tools if name.startswith(MCP_TOOL_PREFIX)]
    assert registered == planned


def test_shutdown_discards_a_report_about_tools_that_are_gone() -> None:
    manager = _manager([_client("github", [_tool_def("a")])])
    assert manager.load_report(), "connected servers should already be reported"
    manager._initialized = False

    manager._plan = {}

    assert manager.load_report() == []


def test_the_tool_is_called_by_the_name_the_server_knows_it_as() -> None:
    """The namespace is for the model; the protocol still expects the bare name."""
    registry = ToolRegistry()
    manager = _manager([_client("github", [_tool_def("list_issues")])])
    manager.register_tools(registry)

    wrapper = registry.get("mcp__github__list_issues").func
    assert wrapper.__qualname__ == "McpClient.github.list_issues"


@pytest.mark.parametrize(
    "servers",
    [
        [("github", "list_issues")],
        [("github", "edit"), ("linear", "edit"), ("a.b", "x"), ("a/b", "x")],
        [("s" * 40, "t" * 40), ("s" * 40 + "b", "t" * 40)],
    ],
)
def test_every_registered_name_is_unique_and_within_budget(servers) -> None:
    """The invariant the whole module exists to hold, checked as an invariant."""
    names = allocate(servers, reserved=["edit", "read", "write"])

    assert len(set(names.values())) == len(servers)
    assert all(len(name) <= MAX_TOOL_NAME_LENGTH for name in names.values())
    assert not set(names.values()) & {"edit", "read", "write"}
