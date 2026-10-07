"""A remembered approval must be attributable to the session that gave it.

``ToolInvoker`` falls back to an empty string when it cannot resolve a session, so
a grant stored under ``""`` was shared by every id-less context: an approval the
user gave in one turn silently authorised the same rule in another.

The asymmetry is deliberate. Losing a grant costs a repeat prompt, which is
inconvenient. The alternative widens an authorisation the user never scoped, which
is a security hole that produces no error at all.
"""

from __future__ import annotations

from nova.tools.approval import ApprovalManager


def _manager_with_grant(session_id: str, rule: str = "tool:web_fetch") -> ApprovalManager:
    manager = ApprovalManager()
    manager.add_to_allowlist(rule, session_id=session_id)
    return manager


# ── a grant with no session is dropped ────────────────────────────────


def test_a_grant_without_a_session_is_not_recorded() -> None:
    manager = _manager_with_grant("")

    assert manager.allowlist_for("") == set()


def test_an_unrelated_session_gets_nothing() -> None:
    manager = _manager_with_grant("session-a")

    assert manager.allowlist_for("session-b") == set()
    assert manager.allowlist_for("session-a") == {"tool:web_fetch"}


def test_remembering_during_resolution_also_requires_a_session() -> None:
    """The ``resolve`` path, which is where a real "always allow" arrives.

    Covered separately because it is a different line of code from
    ``add_to_allowlist``, and the same hole existed in both.
    """
    manager = ApprovalManager()
    req = manager.pre_request("curl x", "", session_id="", rule="pipe remote")

    assert req, "the request is still made"
    manager.resolve(req, approved=True, remember=True)

    assert manager.allowlist_for("") == set()
    assert manager.allowlist_for("another") == set()


# ── named sessions stay isolated ──────────────────────────────────────


def test_two_sessions_do_not_share_a_grant() -> None:
    manager = _manager_with_grant("session-a")

    assert "tool:web_fetch" not in manager.allowlist_for("session-b")


def test_the_granting_session_keeps_working() -> None:
    """Isolation is only worth having if the intended session still benefits."""
    manager = _manager_with_grant("session-a")

    assert manager.allowlist_for("session-a") == {"tool:web_fetch"}
    assert manager.pre_request("x", "", session_id="session-a", rule="tool:web_fetch") == ""


def test_an_empty_rule_is_not_recorded_either() -> None:
    """A grant with nothing to key on would match every later command."""
    manager = ApprovalManager()
    manager.add_to_allowlist("", session_id="session-a")

    assert manager.allowlist_for("session-a") == set()


# ── the practical consequence ─────────────────────────────────────────


def test_a_repeat_in_a_nameless_context_asks_again() -> None:
    """The cost of the fix, stated as a test so it cannot be "fixed" back.

    Without a session there is nothing to scope the grant to, so the same call
    asks a second time. That is the intended trade.
    """
    manager = ApprovalManager()
    first = manager.pre_request("web_fetch", "", session_id="", rule="tool:web_fetch")
    assert first
    manager.resolve(first, approved=True, remember=True)

    second = manager.pre_request("web_fetch", "", session_id="", rule="tool:web_fetch")

    assert second, "an unscopable approval cannot become a standing grant"
    assert second != first
