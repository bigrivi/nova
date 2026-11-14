"""Editing a question and answering it again.

The message keeps its place and its id; everything after it is dropped, and the
files the agent changed in the turns that followed are put back. What must not
happen quietly: a file the user edited after the agent is never overwritten
without being asked for, and the attachment references a message carried stay
with it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from nova.db.config import DatabaseConfig
from nova.db.sqlite.repository import SqliteRepository
from nova.server.session_service import SessionService
from nova.session.models import NewMessage
from nova.settings import get_settings
from nova.tools import checkpoints as capture


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.txt").write_text("one\n", encoding="utf-8")
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
        yield (
            SessionService(settings=get_settings(), data_source=database),
            session.id,
            database,
        )
    finally:
        await database.close()


async def _ask(database: SqliteRepository, session_id: str, text: str) -> str:
    """Add a user message and the assistant answer that followed it."""
    question = await database.add_message(
        NewMessage(session_id=session_id, role="user", content=text)
    )
    await database.add_message(
        NewMessage(session_id=session_id, role="assistant", content="an answer")
    )
    return question.id


@pytest.mark.asyncio
async def test_the_question_is_replaced_and_the_answers_after_it_are_dropped(
    service, repository: Path
):
    session_service, session_id, database = service
    await _ask(database, session_id, "the first question")
    second = await _ask(database, session_id, "the second question")

    report = await session_service.edit_message(
        session_id, second, "the second question, fixed"
    )

    assert report["message_id"] == second
    assert report["dropped_messages"] == 1
    messages = await session_service.list_messages(session_id)
    # Everything before the edited question stays, including the answer it
    # followed; the answer that came after it is gone.
    assert [item.content for item in messages.items] == [
        "the first question",
        "an answer",
        "the second question, fixed",
    ]


@pytest.mark.asyncio
async def test_the_files_the_agent_changed_are_put_back(service, repository: Path):
    session_service, session_id, database = service
    message_id = await _ask(database, session_id, "change a.txt")
    target = repository / "a.txt"
    capture.begin_turn(session_id, message_id, "change a.txt", str(repository))
    capture.record_write(target, "one\n", "two\n")
    target.write_text("two\n", encoding="utf-8")

    report = await session_service.edit_message(
        session_id, message_id, "change it back"
    )

    assert report["restored"] == [str(target)]
    assert target.read_text(encoding="utf-8") == "one\n"


@pytest.mark.asyncio
async def test_a_file_the_user_changed_after_the_agent_is_not_overwritten(
    service, repository: Path
):
    session_service, session_id, database = service
    message_id = await _ask(database, session_id, "change a.txt")
    target = repository / "a.txt"
    capture.begin_turn(session_id, message_id, "change a.txt", str(repository))
    capture.record_write(target, "one\n", "two\n")
    target.write_text("the user typed this\n", encoding="utf-8")

    report = await session_service.edit_message(session_id, message_id, "change it")

    assert report["restored"] == []
    assert report["skipped"] == [{"path": str(target), "reason": "changed-since"}]
    assert target.read_text(encoding="utf-8") == "the user typed this\n"


@pytest.mark.asyncio
async def test_force_restores_a_file_the_user_changed_after_the_agent(
    service, repository: Path
):
    session_service, session_id, database = service
    message_id = await _ask(database, session_id, "change a.txt")
    target = repository / "a.txt"
    capture.begin_turn(session_id, message_id, "change a.txt", str(repository))
    capture.record_write(target, "one\n", "two\n")
    target.write_text("the user typed this\n", encoding="utf-8")

    forced = await session_service.edit_message(
        session_id, message_id, "change it", force=True
    )

    assert forced["restored"] == [str(target)]
    assert target.read_text(encoding="utf-8") == "one\n"


@pytest.mark.asyncio
async def test_a_question_that_changed_no_file_is_edited_all_the_same(service):
    session_service, session_id, database = service
    message_id = await _ask(database, session_id, "just a question")

    report = await session_service.edit_message(
        session_id, message_id, "a better question"
    )

    assert report["restored"] == []
    assert report["skipped"] == []
    messages = await session_service.list_messages(session_id)
    assert messages.items[-1].content == "a better question"


@pytest.mark.asyncio
async def test_the_attachment_references_survive_the_edit(service):
    session_service, session_id, database = service
    question = await database.add_message(
        NewMessage(
            session_id=session_id,
            role="user",
            content="read this\nAttached file: `/tmp/notes.md`",
        )
    )

    await session_service.edit_message(session_id, question.id, "read that")

    messages = await session_service.list_messages(session_id)
    assert messages.items[-1].content == ("read that\nAttached file: `/tmp/notes.md`")


@pytest.mark.asyncio
async def test_an_answer_cannot_be_edited(service):
    session_service, session_id, database = service
    await _ask(database, session_id, "a question")
    messages = await session_service.list_messages(session_id)
    answer = next(item for item in messages.items if item.role == "assistant")

    with pytest.raises(ValueError):
        await session_service.edit_message(session_id, answer.id, "a different answer")


@pytest.mark.asyncio
async def test_a_message_of_another_session_is_not_found(service):
    session_service, session_id, database = service
    message_id = await _ask(database, session_id, "a question")

    with pytest.raises(FileNotFoundError):
        await session_service.edit_message(
            "another-session", message_id, "a different question"
        )


@pytest.mark.asyncio
async def test_an_empty_question_is_refused(service):
    session_service, session_id, database = service
    message_id = await _ask(database, session_id, "a question")

    with pytest.raises(ValueError):
        await session_service.edit_message(session_id, message_id, "   ")
