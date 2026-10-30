"""Remembered approvals: they survive the process, and only inside their workspace."""

from __future__ import annotations

import json
import stat

import pytest

from nova.tools import grants
from nova.tools.approval import ApprovalManager
from nova.tools.workspace_context import set_active_workspace


@pytest.fixture(autouse=True)
def _reset_workspace():
    set_active_workspace(None)
    yield
    set_active_workspace(None)


def _ask(
    manager: ApprovalManager, session: str = "s1", family: str = "git push *"
) -> str:
    return manager.pre_request(
        "git push origin main",
        "pushing",
        session_id=session,
        rule="pushing",
        family=family,
    )


def test_a_remembered_approval_is_written_for_the_workspace(tmp_path):
    set_active_workspace(str(tmp_path))
    manager = ApprovalManager()

    request = _ask(manager)
    assert request
    manager.resolve(request, True, remember=True)

    path = grants.grants_path(str(tmp_path))
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["workspace"] == str(tmp_path)
    assert payload["grants"][0]["rule"] == "pushing"
    assert payload["grants"][0]["family"] == "git push *"
    # Same posture as the policy file: it can authorise a command.
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_saved_approval_answers_in_a_new_process(tmp_path):
    set_active_workspace(str(tmp_path))
    first = ApprovalManager()
    first.resolve(_ask(first), True, remember=True)

    # A fresh manager is what a restarted backend has; the session id is new too,
    # because the user did not resume anything.
    second = ApprovalManager()
    assert _ask(second, session="s2") == ""


def test_another_workspace_does_not_inherit_the_grant(tmp_path):
    here = tmp_path / "here"
    there = tmp_path / "there"
    here.mkdir()
    there.mkdir()

    set_active_workspace(str(here))
    manager = ApprovalManager()
    manager.resolve(_ask(manager), True, remember=True)

    set_active_workspace(str(there))
    assert _ask(ApprovalManager(), session="s2")


def test_approving_once_is_not_saved(tmp_path):
    set_active_workspace(str(tmp_path))
    manager = ApprovalManager()

    manager.resolve(_ask(manager), True, remember=False)

    assert grants.load(str(tmp_path)) == set()
    assert _ask(ApprovalManager(), session="s2")


def test_no_workspace_keeps_the_grant_in_memory_only(tmp_path):
    manager = ApprovalManager()
    request = _ask(manager)
    manager.resolve(request, True, remember=True)

    # No file anywhere: without a workspace there is nothing to scope it to.
    assert grants.load(str(tmp_path)) == set()
    assert _ask(manager) == ""
    assert _ask(ApprovalManager(), session="s2")


def test_a_malformed_file_reads_as_empty(tmp_path):
    path = grants.grants_path(str(tmp_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    assert grants.load(str(tmp_path)) == set()
    assert grants.entries(str(tmp_path)) == []


def test_entries_are_newest_first_and_capped(tmp_path):
    for index in range(3):
        grants.add(str(tmp_path), f"rule-{index}", "", "")

    listed = grants.entries(str(tmp_path))

    assert [entry["rule"] for entry in listed] == ["rule-2", "rule-1", "rule-0"]


def test_adding_the_same_grant_twice_keeps_one(tmp_path):
    grants.add(str(tmp_path), "pushing", "git push *", "")

    grants.add(str(tmp_path), "pushing", "git push *", "")

    assert len(grants.entries(str(tmp_path))) == 1


def test_clear_revokes_everything(tmp_path):
    grants.add(str(tmp_path), "pushing")

    grants.clear(str(tmp_path))

    assert grants.load(str(tmp_path)) == set()
