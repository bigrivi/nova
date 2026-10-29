"""A real turn that writes a file, then a rewind that puts it back.

The unit tests cover the store; this one covers the wiring the feature lives or
dies by: the agent opening a checkpoint for the turn, `write` reporting into it,
and `ChatService.rewind` restoring the file and dropping the turn's messages.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nova import checkpoints
from nova.agent.core import AgentEvent
from nova.llm.provider import Done, ToolCall
from nova.server.chat_service import ChatService
from nova.settings import get_settings
from tests.test_agent_chat_stream import ScriptedProvider, isolated_agent


def _write_then_finish(target: Path, body: str) -> ScriptedProvider:
    return ScriptedProvider(
        [
            [
                ToolCall(
                    id="call-1",
                    name="write",
                    arguments=json.dumps({"content": body, "filePath": str(target)}),
                )
            ],
            [Done(content="wrote it")],
        ]
    )


async def _run_turn(agent, prompt: str, workspace: Path) -> str:
    session_id = ""
    async for event, data in agent.chat_stream(prompt, workspace_dir=str(workspace)):
        if event == AgentEvent.SESSION and isinstance(data, str):
            session_id = data
    return session_id


@pytest.mark.asyncio
async def test_a_turn_that_writes_is_rewindable(tmp_path):
    target = tmp_path / "notes.md"
    target.write_text("before\n", encoding="utf-8")
    provider = _write_then_finish(target, "after\n")

    async with isolated_agent(provider, permission_mode="dontAsk") as (
        agent,
        database,
    ):
        await agent.register_all_tools()
        # The workspace is what makes the write an inside-the-workspace edit
        # instead of one the permission gate would ask about.
        session_id = await _run_turn(agent, "edit the notes", tmp_path)

        assert target.read_text(encoding="utf-8") == "after\n"
        summaries = checkpoints.list_checkpoints(session_id)
        assert len(summaries) == 1
        assert summaries[0].files == 1
        checkpoint_id = summaries[0].checkpoint_id

        service = ChatService(settings=get_settings())
        result = await service.rewind(session_id, checkpoint_id)

        assert result["restored"] == [str(target)]
        assert result["chat_truncated"] is True
        assert result["dropped_messages"] >= 1
        assert target.read_text(encoding="utf-8") == "before\n"

        remaining = await database.get_messages(session_id)
        assert [message.role for message in remaining] == []
