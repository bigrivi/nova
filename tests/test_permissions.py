"""The permissions file: one location, two axes, created with its defaults.

Three things are worth pinning here, and none of them is obvious from reading the
loader.

The location used to be owned by ``shell_policy``. The tool axis then imported
``default_config_path`` from a *shell* module to find the same file, which meant a
non-shell concern's config path was a fact about the shell package. That is what
:mod:`nova.tools.permissions` exists to stop.

The file is created rather than left absent, because ``config.json`` already is
and a user looking for ``permissions.json`` found nothing -- with no way to tell
"not configured" from "configured and broken".

And the default is a security posture, not an empty object: everything is allowed.
Writing that out explicitly is the whole point, since an empty file reads as
"there is configuration here that is not taking effect".
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from nova.tools import permissions
from nova.tools.permissions import (
    DEFAULT_PAYLOAD,
    ensure_permissions_file,
    load_permissions,
    nova_home,
    permissions_path,
)

# ── location ─────────────────────────────────────────────────────────


def test_nova_home_follows_the_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("NOVA_HOME", str(tmp_path))

    assert nova_home() == tmp_path
    assert permissions_path() == tmp_path / "permissions.json"


def test_the_default_location_is_dot_nova() -> None:
    monkeypatch_free = os.environ.pop("NOVA_HOME", None)
    try:
        assert (
            permissions_path() == permissions.Path.home() / ".nova" / "permissions.json"
        )
    finally:
        if monkeypatch_free is not None:
            os.environ["NOVA_HOME"] = monkeypatch_free


def test_both_axes_read_the_same_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The reason this module exists: one path, read by two unrelated axes."""
    from nova.tools.shell.policy import default_config_path
    from nova.tools.tool_policy import load_tool_policy

    monkeypatch.setenv("NOVA_HOME", str(tmp_path))
    monkeypatch.delenv("NOVA_SHELL_RULES", raising=False)
    (tmp_path / "permissions.json").write_text(
        json.dumps({"shell": {"disable": []}, "tools": {"web_fetch": "ask"}}),
        encoding="utf-8",
    )

    assert default_config_path() == permissions_path()
    assert load_tool_policy(permissions_path()).effect_for("web_fetch") == "ask"


def test_the_shell_axis_can_still_be_pointed_elsewhere(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """``NOVA_SHELL_RULES`` overrides, for experimenting on one axis alone."""
    from nova.tools.shell.policy import default_config_path

    monkeypatch.setenv("NOVA_HOME", str(tmp_path))
    monkeypatch.setenv("NOVA_SHELL_RULES", str(tmp_path / "scratch.json"))

    assert default_config_path() == tmp_path / "scratch.json"


# ── parsing ──────────────────────────────────────────────────────────


def test_an_absent_file_yields_nothing() -> None:
    assert load_permissions("/nonexistent/permissions.json") == {}


@pytest.mark.parametrize("payload", ["{not json", "[]", '"a string"', "null"])
def test_a_malformed_file_yields_nothing(tmp_path, payload: str) -> None:
    # Failing closed here would take away the agent's tools and ask about every
    # command, with no way for the user to run anything. An empty payload leaves
    # both axes on their built-in defaults.
    path = tmp_path / "permissions.json"
    path.write_text(payload, encoding="utf-8")

    assert load_permissions(path) == {}


def test_no_argument_reads_the_default_location(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("NOVA_HOME", str(tmp_path))
    (tmp_path / "permissions.json").write_text(
        '{"tools": {"edit": "deny"}}', encoding="utf-8"
    )

    assert load_permissions()["tools"] == {"edit": "deny"}


# ── creation ─────────────────────────────────────────────────────────


def test_the_file_is_created_with_documented_defaults(tmp_path) -> None:
    path = ensure_permissions_file(tmp_path)

    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == DEFAULT_PAYLOAD


def test_the_default_payload_explains_both_axes() -> None:
    # The keys are the documentation. A default file that does not say what
    # `deny` does is a default file nobody can safely edit.
    assert "shell" in DEFAULT_PAYLOAD
    assert "tools" in DEFAULT_PAYLOAD
    for section in ("shell", "tools"):
        assert DEFAULT_PAYLOAD[section]["_readme"].strip()


def test_the_default_payload_does_not_promise_a_hot_reload() -> None:
    """The file used to claim edits applied without a restart. They do not.

    `default_rule_set()` caches per process and the tool policy is read once at
    tool-registration time, so both axes need a restart. The first draft of this
    payload said otherwise, which is the one claim in it a user would act on and
    be wrong.
    """
    text = json.dumps(DEFAULT_PAYLOAD).lower()

    assert "without a restart" not in text
    assert "restart" in DEFAULT_PAYLOAD["_readme"].lower()
    # And the cost of that restart should be stated where it bites: an approval
    # the user remembered is gone too.
    assert "lost on restart" in DEFAULT_PAYLOAD["tools"]["_readme"].lower()


def test_the_default_payload_states_the_evaluation_order() -> None:
    """Order is what makes the file usable, so it belongs in the file.

    A reader who adds an `allow` entry deserves to know it cannot reach a
    blocked command, without having to read the source to find that out.
    """
    readme = DEFAULT_PAYLOAD["shell"]["_readme"].lower()

    assert "block" in readme and "above" in readme


def test_the_default_payload_is_neutral_not_restrictive(tmp_path) -> None:
    """Every axis starts wide open, and says so.

    Pinning this matters because it is the opposite of what a permissions file
    looks like in Claude Code or OpenCode, where the shipped default denies a
    list of commands. Here the shipped default allows everything, and a user who
    assumed otherwise would be wrong in the unsafe direction.
    """
    from nova.tools.shell.policy import load_rule_set
    from nova.tools.tool_policy import load_tool_policy

    path = ensure_permissions_file(tmp_path)

    assert load_tool_policy(path).effect_for("write") == "allow"
    rules = load_rule_set(path)
    assert rules.block and rules.ask, "the built-in rules still apply"
    assert rules.allow == [], (
        "nothing is pre-approved, but nothing is pre-denied either"
    )


def test_an_existing_file_is_never_overwritten(tmp_path) -> None:
    path = tmp_path / "permissions.json"
    path.write_text('{"tools": {"edit": "deny"}}', encoding="utf-8")

    ensure_permissions_file(tmp_path)

    assert json.loads(path.read_text(encoding="utf-8")) == {"tools": {"edit": "deny"}}


def test_the_file_is_not_world_readable(tmp_path) -> None:
    """0600, like ``config.json``.

    This file holds the user's own safety policy. Anyone who can edit it can
    allow any command, so the permissions have to be at least as tight as the
    provider API keys two files away.
    """
    path = ensure_permissions_file(tmp_path)

    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, oct(mode)


def test_an_unwritable_home_does_not_stop_startup(tmp_path) -> None:
    """A read-only home is a reason the file is missing, not a reason to fail."""
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0o500)
    try:
        path = ensure_permissions_file(blocked)

        assert not path.exists()
    finally:
        blocked.chmod(0o700)
