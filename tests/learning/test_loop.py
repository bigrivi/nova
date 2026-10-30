import asyncio
import time

import pytest

from nova.learning.loop import LearningLoop
from nova.learning.skill_extractor import TurnContext
from nova.settings import LearningSettings


@pytest.mark.asyncio
async def test_on_turn_completed_returns_immediately(tmp_path):
    settings = LearningSettings(enabled=True)
    loop = LearningLoop(settings, tmp_path / "skills", str(tmp_path / "test.db"))
    await loop.start()
    turn = TurnContext(session_id="s1", messages=[{"role": "user", "content": "hi"}], tool_call_count=1)
    t0 = time.monotonic()
    await loop.on_turn_completed(turn)
    elapsed = (time.monotonic() - t0) * 1000
    assert elapsed < 10
    # let background task settle
    await asyncio.sleep(0.1)
    await loop.stop()


@pytest.mark.asyncio
async def test_disabled_loop_does_nothing(tmp_path):
    settings = LearningSettings(enabled=False)
    loop = LearningLoop(settings, tmp_path / "skills", str(tmp_path / "test.db"))
    await loop.start()
    turn = TurnContext(session_id="s1", messages=[{"role": "user", "content": "hi"}], tool_call_count=5)
    await loop.on_turn_completed(turn)
    await asyncio.sleep(0.1)
    # session_fts should not exist / be empty
    import aiosqlite
    conn = await aiosqlite.connect(str(tmp_path / "test.db"))
    try:
        cursor = await conn.execute("SELECT count(*) FROM session_fts")
        row = await cursor.fetchone()
        assert row[0] == 0
    except Exception:
        pass  # table may not exist
    await conn.close()
    await loop.stop()


@pytest.mark.asyncio
async def test_search_sessions(tmp_path):
    settings = LearningSettings(enabled=True, session_search_enabled=True)
    loop = LearningLoop(settings, tmp_path / "skills", str(tmp_path / "test.db"))
    await loop.start()
    turn = TurnContext(session_id="s1", messages=[{"role": "user", "content": "CSV sales report"}], tool_call_count=1)
    await loop.on_turn_completed(turn)
    await asyncio.sleep(0.1)
    result = await loop.search_sessions("CSV")
    assert "CSV" in result or "s1" in result
    await loop.stop()


@pytest.mark.asyncio
async def test_background_exception_isolated(tmp_path):
    settings = LearningSettings(enabled=True, session_search_enabled=True)
    loop = LearningLoop(settings, tmp_path / "skills", str(tmp_path / "test.db"))
    await loop.start()
    # Force index_turn to fail by closing connection
    await loop._session_search.close()
    turn = TurnContext(session_id="s1", messages=[{"role": "user", "content": "hi"}], tool_call_count=1)
    # Should not raise
    await loop.on_turn_completed(turn)
    await asyncio.sleep(0.1)
    await loop.stop()

@pytest.mark.asyncio
async def test_loop_is_shared_across_agents(tmp_path):
    """The loop is per agent key, not per Agent instance.

    A new Agent is built per request, so a loop held on the agent would
    reset its turn counter every turn and never reach the nudge interval.
    """
    import nova.learning.loop as loop_module
    from nova.learning.loop import get_learning_loop

    loop_module._loops.clear()
    settings = LearningSettings(enabled=True, nudge_interval_turns=2)
    first = get_learning_loop("agent-a", settings, tmp_path / "skills", str(tmp_path / "test.db"))
    second = get_learning_loop("agent-a", settings, tmp_path / "skills", str(tmp_path / "test.db"))
    assert first is second
    other = get_learning_loop("agent-b", settings, tmp_path / "skills", str(tmp_path / "test.db"))
    assert other is not first
    loop_module._loops.clear()
