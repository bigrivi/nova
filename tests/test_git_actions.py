"""Commit planning and review: which files count, and what happens without a model."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import pytest_asyncio

from nova.db.config import DatabaseConfig
from nova.db.sqlite_repository import SqliteRepository
from nova.server import git_actions
from nova.server.chat_service import ChatService
from nova.settings import get_settings
from nova.tools import checkpoints as capture


def _git(repository: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    for args in (
        ("init",),
        ("config", "user.email", "t@example.com"),
        ("config", "user.name", "T"),
    ):
        _git(root, *args)
    (root / "touched.txt").write_text("one\n", encoding="utf-8")
    (root / "untouched.txt").write_text("one\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "first")
    return root


@pytest_asyncio.fixture
async def service(repository: Path):
    database = SqliteRepository(DatabaseConfig(path=":memory:"))
    await database.connect()
    from nova.session.manager import SessionContext

    session = SessionContext.create()
    session.title = "s"
    session.workspace_dir = str(repository)
    await database.save_session(session)
    try:
        yield ChatService(settings=get_settings(), data_source=database), session.id
    finally:
        await database.close()


@pytest.fixture
def fake_model(monkeypatch):
    """Stub the one-shot call and the provider builder; records the prompt."""

    seen: list[str] = []

    async def fake_stream(llm, *, messages, model, **kwargs):
        seen.append(messages[0]["content"])
        return "feat(git): add commit planning\n"

    monkeypatch.setattr(git_actions, "stream_text_once", fake_stream)
    monkeypatch.setattr("nova.app.runtime.build_llm", lambda *a, **k: object())
    return seen


@pytest.mark.asyncio
async def test_plan_includes_only_paths_the_session_touched(
    service, repository: Path, fake_model
):
    chat_service, session_id = service
    (repository / "touched.txt").write_text("two\n", encoding="utf-8")
    (repository / "untouched.txt").write_text("two\n", encoding="utf-8")
    capture.begin_turn(session_id, "m1", "edit", str(repository))
    capture.record_write(repository / "touched.txt", "one\n", "two\n")

    plan = await git_actions.plan_commit(chat_service, session_id)

    assert [entry["path"] for entry in plan["files"]] == ["touched.txt"]
    assert plan["message"] == "feat(git): add commit planning"
    assert "touched.txt" in fake_model[0]


@pytest.mark.asyncio
async def test_plan_refuses_when_nothing_it_touched_changed(
    service, repository: Path, fake_model
):
    chat_service, session_id = service
    (repository / "untouched.txt").write_text("two\n", encoding="utf-8")

    with pytest.raises(git_actions.NothingToCommit):
        await git_actions.plan_commit(chat_service, session_id)


@pytest.mark.asyncio
async def test_plan_falls_back_when_the_model_returns_nothing(
    service, repository: Path, monkeypatch
):
    chat_service, session_id = service
    (repository / "touched.txt").write_text("two\n", encoding="utf-8")
    capture.begin_turn(session_id, "m1", "edit", str(repository))
    capture.record_write(repository / "touched.txt", "one\n", "two\n")

    async def no_answer(llm, **kwargs):
        return None

    monkeypatch.setattr(git_actions, "stream_text_once", no_answer)
    monkeypatch.setattr("nova.app.runtime.build_llm", lambda *a, **k: object())

    plan = await git_actions.plan_commit(chat_service, session_id)

    # The user already agreed to commit these files; a failed model call must not
    # strand them.
    assert plan["message"] == "chore: update files"


@pytest.mark.asyncio
async def test_review_reports_the_model_text(service, repository: Path, monkeypatch):
    chat_service, session_id = service
    (repository / "touched.txt").write_text("two\n", encoding="utf-8")

    async def fake_stream(llm, *, messages, model, **kwargs):
        return "touched.txt:1 — off by one — wrong value"

    monkeypatch.setattr(git_actions, "stream_text_once", fake_stream)
    monkeypatch.setattr("nova.app.runtime.build_llm", lambda *a, **k: object())

    result = await git_actions.review_changes(chat_service, session_id)

    assert "off by one" in result["review"]
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_review_of_a_clean_tree_does_not_call_the_model(service, monkeypatch):
    chat_service, session_id = service

    async def explode(llm, **kwargs):
        raise AssertionError("model must not be called for an empty diff")

    monkeypatch.setattr(git_actions, "stream_text_once", explode)

    result = await git_actions.review_changes(chat_service, session_id)

    assert result["review"] == "No changes to review."


@pytest.mark.asyncio
async def test_plan_without_a_workspace_is_refused(service):
    chat_service, _session_id = service
    from nova.session.manager import SessionContext

    data_source = await chat_service._get_data_source()
    bare = SessionContext.create()
    bare.title = "no-workspace"
    await data_source.save_session(bare)

    with pytest.raises(ValueError):
        await git_actions.plan_commit(chat_service, bare.id)
