"""Shell rules are configurable, and a bad config does not take the bridge down.

The rules were a Python literal, so changing one meant editing source and
restarting, and nothing outside it could ever be added. Claude Code, OpenCode and
Hermes all ship theirs as data with an ordered rule list.

The rule set is ordered -- first match wins, blocking before asking -- so a config
can narrow the defaults without having to restate them. Anything malformed is
reported and skipped rather than raised: a typo in a security file must not leave
the agent unable to run commands at all.
"""

from __future__ import annotations

import json

import pytest

from nova.tools.shell import Decision
from nova.tools.shell_policy import RuleSet, load_rule_set


def _write(path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


# ── the shipped defaults ─────────────────────────────────────────────


def test_without_a_config_the_builtin_rules_apply(tmp_path) -> None:
    rules = load_rule_set(tmp_path / "absent.json")

    assert rules.classify("rm -rf /").effect == "block"
    assert rules.classify("git push --force").needs_approval
    assert rules.classify("ls -la").allowed


def test_the_default_rule_set_is_the_python_one() -> None:
    from nova.tools.shell import DANGEROUS_PATTERNS, HARDLINE_PATTERNS

    rules = RuleSet.defaults()

    assert len(rules.block) == len(HARDLINE_PATTERNS)
    assert len(rules.ask) == len(DANGEROUS_PATTERNS)


# ── allow ────────────────────────────────────────────────────────────


def test_an_allow_prefix_skips_approval(tmp_path) -> None:
    config = tmp_path / "permissions.json"
    _write(config, {"allow": ["git push *"]})

    rules = load_rule_set(config)

    assert rules.classify("git push --force origin main").allowed
    assert rules.classify("chmod 777 f").needs_approval, (
        "a narrower allow must not widen anything else"
    )


def test_allow_takes_precedence_over_an_ask_rule(tmp_path) -> None:
    # Otherwise the built-in list would win and the allow would be unreachable,
    # which is the ordering bug that makes a config look ignored.
    config = tmp_path / "permissions.json"
    _write(config, {"allow": ["killall *"]})

    rules = load_rule_set(config)

    assert rules.classify("killall -9 foo").allowed


def test_allow_never_overrides_a_block(tmp_path) -> None:
    config = tmp_path / "permissions.json"
    _write(config, {"allow": ["rm *"]})

    rules = load_rule_set(config)

    assert rules.classify("rm -rf /").effect == "block", (
        "a block exists because nothing may undo it"
    )


# ── disable ──────────────────────────────────────────────────────────


def test_a_builtin_rule_can_be_switched_off(tmp_path) -> None:
    config = tmp_path / "permissions.json"
    _write(config, {"disable": ["git force push (rewrites remote history)"]})

    rules = load_rule_set(config)

    assert rules.classify("git push --force").allowed


def test_disabling_an_unknown_rule_is_harmless(tmp_path) -> None:
    config = tmp_path / "permissions.json"
    _write(config, {"disable": ["a rule that never existed"]})

    rules = load_rule_set(config)

    assert rules.classify("git push --force").needs_approval


# ── extend ───────────────────────────────────────────────────────────


def test_a_config_can_add_a_rule(tmp_path) -> None:
    config = tmp_path / "permissions.json"
    _write(
        config,
        {
            "ask": [
                {
                    "match": r"\bnpm\s+publish\b",
                    "description": "publishes a package",
                }
            ]
        },
    )

    rules = load_rule_set(config)

    assert rules.classify("npm publish").needs_approval
    assert rules.classify("npm install").allowed


def test_an_added_rule_keeps_its_description_as_its_identity(tmp_path) -> None:
    # The description is what a grant is recorded against, so an added rule has to
    # have one or "always allow" cannot key on it.
    config = tmp_path / "permissions.json"
    _write(
        config,
        {"ask": [{"match": r"\bnpm\s+publish\b", "description": "publishes a package"}]},
    )

    rules = load_rule_set(config)
    decision = rules.classify("npm publish")

    assert decision.rule == "publishes a package"


# ── malformed input ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        "{not json",
        [],
        {"allow": "git push *"},
        {"ask": [{"match": "["}]},
        {"ask": [{"description": "no pattern"}]},
        {"disable": "not-a-list"},
    ],
)
def test_a_broken_config_leaves_the_defaults_in_place(tmp_path, payload) -> None:
    config = tmp_path / "permissions.json"
    config.write_text(json.dumps(payload) if not isinstance(payload, str) else payload, encoding="utf-8")

    rules = load_rule_set(config)

    assert rules.classify("rm -rf /").effect == "block"
    assert rules.classify("git push --force").needs_approval


def test_a_broken_rule_does_not_take_the_valid_ones_with_it(tmp_path) -> None:
    config = tmp_path / "permissions.json"
    _write(
        config,
        {
            "allow": ["git commit *", "["],
            "ask": [{"match": "[", "description": "broken"}],
        },
    )

    rules = load_rule_set(config)

    assert rules.classify("git commit -m x").allowed, "the valid entry still applies"
    assert rules.classify("rm -rf /").effect == "block"


# ── ordering ─────────────────────────────────────────────────────────


def test_block_is_checked_before_ask_by_default(tmp_path) -> None:
    # A command can trip both lists; the block has to win, or an ask rule could
    # become a way to make a blocked command approvable.
    config = tmp_path / "permissions.json"
    _write(config, {"ask": [{"match": r"rm\s+-rf\s+/", "description": "asks about rm -rf /"}]})

    rules = load_rule_set(config)

    assert rules.classify("rm -rf /").effect == "block"


def test_config_allow_is_consulted_before_the_ask_list(tmp_path) -> None:
    config = tmp_path / "permissions.json"
    _write(
        config,
        {
            "allow": ["docker compose *"],
            "ask": [{"match": r"docker\s+compose\s+down", "description": "stops containers"}],
        },
    )

    rules = load_rule_set(config)

    assert rules.classify("docker compose down").allowed, (
        "the config allow has to beat a configured ask, or it is unreachable"
    )


def test_a_decision_carries_the_rule_for_granting(tmp_path) -> None:
    config = tmp_path / "permissions.json"
    _write(config, {"allow": ["nothing *"]})
    rules = load_rule_set(config)

    allowed: Decision = rules.classify("ls")

    assert allowed.allowed
    assert allowed.rule == "", "an allowed decision has no rule to grant"
