"""Which effect wins when two rules both match one tool.

The bug this pins: resolution scanned the rule dict in declaration order and took
the first prefix match, so the outcome was decided by JSON key order. A short
``allow`` prefix shadowed a longer ``deny`` one:

    {"mcp__g": "allow", "mcp__github__*": "deny"}   →  allow

A `deny` is the strongest statement a user can make about a tool, and key order
decided it. That is the class of bug that survives review, because the docstring
promised the opposite behaviour and the tests only ever had non-overlapping keys.
"""

from __future__ import annotations

import pytest

from nova.tools.tool_policy import ToolPolicy

# ── exact beats everything ───────────────────────────────────────────


def test_an_exact_name_wins_over_a_namespace() -> None:
    policy = ToolPolicy({"mcp__github__star": "allow", "mcp__github__*": "deny"})

    assert policy.effect_for("mcp__github__star") == "allow"
    assert policy.effect_for("mcp__github__push") == "deny"


def test_an_exact_name_wins_over_the_star_fallback() -> None:
    policy = ToolPolicy({"*": "ask", "read": "allow"})

    assert policy.effect_for("read") == "allow"
    assert policy.effect_for("write") == "ask"


# ── among namespaces, the longest prefix wins ─────────────────────────


def test_a_deny_namespace_beats_a_shorter_allow_prefix_however_ordered() -> None:
    """The regression, in both key orders.

    Both orderings must deny. Before the fix the first allowed and the second
    denied, which means the file's formatting decided whether a denied MCP server
    was reachable.
    """
    deny_first = ToolPolicy({"mcp__github__*": "deny", "mcp__g": "allow"})
    allow_first = ToolPolicy({"mcp__g": "allow", "mcp__github__*": "deny"})

    assert deny_first.effect_for("mcp__github__star") == "deny"
    assert allow_first.effect_for("mcp__github__star") == "deny"


@pytest.mark.parametrize(
    ("rules", "tool", "expected"),
    [
        ({"mcp__a__b__c__*": "deny", "mcp__a__*": "ask"}, "mcp__a__b__c__d", "deny"),
        ({"mcp__a__b__c__*": "ask", "mcp__a__*": "deny"}, "mcp__a__b__c__d", "ask"),
        ({"mcp__a__*": "allow", "mcp__a__b__*": "deny"}, "mcp__a__b__c", "deny"),
        ({"mcp__*": "deny", "mcp__a__*": "allow"}, "mcp__a__b", "allow"),
        # Neither is a prefix of the other; neither may claim the tool.
        ({"mcp__a__*": "deny", "mcp__b__*": "allow"}, "mcp__c__d", "allow"),
    ],
)
def test_the_longest_matching_prefix_decides(rules: dict, tool: str, expected: str) -> None:
    assert ToolPolicy(rules).effect_for(tool) == expected


def test_key_order_cannot_change_any_outcome() -> None:
    """Stated as a property over every ordering of one rule set.

    Asserting the two orderings that mattered would only catch those two. This
    catches any future reordering of the resolution logic.
    """
    import itertools

    rules = {"mcp__g": "allow", "mcp__github__*": "deny", "*": "ask"}
    outcomes = {
        tuple(sorted(order)): ToolPolicy(dict(order)).effect_for("mcp__github__star")
        for order in itertools.permutations(rules.items())
    }

    assert set(outcomes.values()) == {"deny"}, outcomes


# ── what counts as a namespace ────────────────────────────────────────


def test_only_a_trailing_star_makes_a_prefix_rule() -> None:
    """A bare name is a whole name, not a prefix.

    Without the star, ``read`` would also swallow ``read_file`` and ``readdir``.
    """
    policy = ToolPolicy({"read": "deny"})

    assert policy.effect_for("read") == "deny"
    assert policy.effect_for("read_file") == "allow"


def test_a_star_in_the_middle_is_not_a_namespace_marker() -> None:
    policy = ToolPolicy({"web_*_fetch": "deny"})

    assert policy.effect_for("web_a_fetch") == "allow"


def test_the_bare_star_is_only_a_fallback() -> None:
    policy = ToolPolicy({"*": "deny"})

    assert policy.effect_for("anything") == "deny"
    assert policy.effect_for("mcp__github__star") == "deny"


# ── unconfigured ──────────────────────────────────────────────────────


def test_an_empty_policy_allows_everything() -> None:
    policy = ToolPolicy()

    assert policy.effect_for("write") == "allow"
    assert policy.effect_for("rm") == "allow"
    assert not policy


def test_an_unrecognised_effect_is_dropped_rather_than_guessed() -> None:
    """A typo must not become a silent allow or a silent deny."""
    policy = ToolPolicy({"web_fetch": "sometimes", "write": "ask"})

    assert policy.effect_for("web_fetch") == "allow"
    assert policy.effect_for("write") == "ask"


def test_a_policy_reports_whether_it_has_anything_to_apply() -> None:
    # `denies` used to exist as a property and was wrong: it claimed a namespace
    # deny was only enforced at dispatch, while registration resolves namespaces
    # through `effect_for` and unregisters them like any exact name. Its only
    # caller was a test asserting the false version, so it was dead weight that
    # also contradicted the behaviour. The registration path is pinned in
    # `test_tool_policy.py` instead, where it actually happens.
    assert not ToolPolicy()
    assert not ToolPolicy({})
    assert ToolPolicy({"read": "allow"})
    assert ToolPolicy({"*": "ask"})
