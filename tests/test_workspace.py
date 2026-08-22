from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from nova.db.config import DatabaseConfig
from nova.db.in_memory_repository import InMemoryRepository
from nova.db.sqlite_repository import SqliteRepository
from nova.prompt.builder import PromptBuilder, PromptConfig
from nova.server.fs_browse import list_directory
from nova.session.models import Session
from nova.tools.glob import glob as glob_fn
from nova.tools.grep import grep as grep_fn
from nova.tools.workspace_context import get_active_workspace, set_active_workspace


@pytest.fixture(autouse=True)
def _reset_active_workspace():
    set_active_workspace(None)
    yield
    set_active_workspace(None)


async def _roundtrip(repo) -> None:
    await repo.connect()
    try:
        await repo.save_session(Session(id="s1", workspace_dir="/tmp/ws-a"))
        got = await repo.get_session("s1")
        assert got is not None
        assert got["workspace_dir"] == "/tmp/ws-a"

        assert await repo.set_session_workspace("s1", "/tmp/ws-b") is True
        assert (await repo.get_session("s1"))["workspace_dir"] == "/tmp/ws-b"

        assert await repo.set_session_workspace("s1", None) is True
        assert (await repo.get_session("s1"))["workspace_dir"] is None

        assert await repo.set_session_workspace("missing", "/x") is False
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_sqlite_session_workspace_roundtrip(tmp_path: Path):
    await _roundtrip(SqliteRepository(DatabaseConfig(path=str(tmp_path / "ws.db"))))


@pytest.mark.asyncio
async def test_in_memory_session_workspace_roundtrip():
    await _roundtrip(InMemoryRepository())


@pytest.mark.asyncio
async def test_sqlite_migrates_missing_workspace_column(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    # Simulate an old DB whose sessions table predates workspace_dir.
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            agent_key TEXT NOT NULL DEFAULT 'main',
            title TEXT,
            parent_id TEXT,
            summary_goal TEXT,
            summary_accomplished TEXT,
            summary_remaining TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            compacted_at INTEGER,
            message_count INTEGER DEFAULT 0,
            turn_count INTEGER DEFAULT 0,
            metadata TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO sessions (id, agent_key, created_at, updated_at) VALUES ('old', 'main', 1, 1)"
    )
    conn.commit()
    conn.close()

    repo = SqliteRepository(DatabaseConfig(path=str(db_path)))
    await repo.connect()
    try:
        got = await repo.get_session("old")
        assert got is not None
        assert got["workspace_dir"] is None
        assert await repo.set_session_workspace("old", "/tmp/migrated") is True
        assert (await repo.get_session("old"))["workspace_dir"] == "/tmp/migrated"
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_glob_defaults_to_active_workspace(tmp_path: Path):
    (tmp_path / "alpha.txt").write_text("x")
    other = tmp_path / "other"
    other.mkdir()
    (other / "beta.txt").write_text("y")

    set_active_workspace(str(tmp_path))
    result = await glob_fn("*.txt")
    assert "alpha.txt" in result.content
    assert "beta.txt" not in result.content

    # Explicit path always wins over the active workspace.
    override = await glob_fn("*.txt", path=str(other))
    assert "beta.txt" in override.content
    assert "alpha.txt" not in override.content


@pytest.mark.asyncio
async def test_grep_defaults_to_active_workspace(tmp_path: Path):
    (tmp_path / "note.txt").write_text("needle here\n")
    set_active_workspace(str(tmp_path))
    result = await grep_fn("needle")
    assert "needle" in result.content


def test_active_workspace_contextvar_roundtrip():
    assert get_active_workspace() is None
    set_active_workspace("/tmp/ws")
    assert get_active_workspace() == "/tmp/ws"
    set_active_workspace("")
    assert get_active_workspace() is None


def test_prompt_builder_workspace_override():
    builder = PromptBuilder(PromptConfig(workspace_dir="/agent/dir"))
    out = builder.build(workspace_override="/session/dir")
    assert "- Workspace: /session/dir" in out
    fallback = builder.build()
    assert "- Workspace: /agent/dir" in fallback


def test_fs_browse_lists_directories_only(tmp_path: Path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "file.txt").write_text("x")
    listing = list_directory(str(tmp_path))
    names = {entry.name for entry in listing.entries}
    assert "sub" in names
    assert "file.txt" not in names
    assert listing.parent == str(tmp_path.parent)


def test_fs_browse_rejects_missing_and_non_dir(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        list_directory(str(tmp_path / "nope"))
    target = tmp_path / "f.txt"
    target.write_text("x")
    with pytest.raises(NotADirectoryError):
        list_directory(str(target))
