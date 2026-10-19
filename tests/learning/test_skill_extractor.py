import pytest
from pathlib import Path
from nova.learning.skill_extractor import SkillExtractor, TurnContext


@pytest.mark.asyncio
async def test_no_extraction_below_threshold(tmp_path):
    class MockLLM:
        async def chat_stream(self, messages, model="gpt-4o", **kw):
            from nova.llm.provider import TextDelta, Done
            yield TextDelta(content='{"name": "x", "content": "y"}')
            yield Done(content='{"name": "x", "content": "y"}')
    ext = SkillExtractor(tmp_path / "skills", min_tool_calls=4, llm=MockLLM())
    turn = TurnContext(session_id="s1", messages=[], tool_call_count=2)
    result = await ext.maybe_extract(turn)
    assert result is None
    assert not (tmp_path / "skills").exists() or not any((tmp_path / "skills").iterdir())


@pytest.mark.asyncio
async def test_extraction_above_threshold_writes_skill(tmp_path):
    class MockLLM:
        async def chat_stream(self, messages, model="gpt-4o", **kw):
            from nova.llm.provider import TextDelta, Done
            yield TextDelta(content='{"name": "csv-agg", "content": "# CSV Aggregator\\nDo stuff."}')
            yield Done(content='{"name": "csv-agg", "content": "# CSV Aggregator\\nDo stuff."}')
    ext = SkillExtractor(tmp_path / "skills", min_tool_calls=4, llm=MockLLM())
    turn = TurnContext(session_id="s1", messages=[{"role": "user", "content": "task"}], tool_call_count=5)
    result = await ext.maybe_extract(turn)
    assert result is not None
    assert result.name == "csv-agg"
    skill_path = tmp_path / "skills" / "csv-agg" / "SKILL.md"
    assert skill_path.exists()
    assert "CSV Aggregator" in skill_path.read_text()


@pytest.mark.asyncio
async def test_no_llm_returns_none(tmp_path):
    ext = SkillExtractor(tmp_path / "skills", min_tool_calls=4, llm=None)
    turn = TurnContext(session_id="s1", messages=[], tool_call_count=5)
    result = await ext.maybe_extract(turn)
    assert result is None


@pytest.mark.asyncio
async def test_extraction_failure_does_not_raise(tmp_path):
    class BadLLM:
        async def chat_stream(self, messages, model="gpt-4o", **kw):
            raise RuntimeError("boom")
            yield
    ext = SkillExtractor(tmp_path / "skills", min_tool_calls=4, llm=BadLLM())
    turn = TurnContext(session_id="s1", messages=[], tool_call_count=5)
    result = await ext.maybe_extract(turn)
    assert result is None

@pytest.mark.asyncio
async def test_new_skill_is_version_stamped(tmp_path):
    class MockLLM:
        async def chat_stream(self, messages, model="gpt-4o", **kw):
            from nova.llm.provider import TextDelta, Done
            yield TextDelta(content='{"name": "v-skill", "content": "# V Skill"}')
            yield Done(content='{"name": "v-skill", "content": "# V Skill"}')
    ext = SkillExtractor(tmp_path / "skills", min_tool_calls=4, llm=MockLLM())
    turn = TurnContext(session_id="s1", messages=[], tool_call_count=5)
    await ext.maybe_extract(turn)
    text = (tmp_path / "skills" / "v-skill" / "SKILL.md").read_text()
    assert "version: 1" in text


@pytest.mark.asyncio
async def test_improve_bumps_version(tmp_path):
    class MockLLM:
        async def chat_stream(self, messages, model="gpt-4o", **kw):
            from nova.llm.provider import TextDelta, Done
            yield TextDelta(content="# Revised Skill\nnow with weekly grouping")
            yield Done(content="# Revised Skill\nnow with weekly grouping")
    skills = tmp_path / "skills"
    (skills / "s").mkdir(parents=True)
    (skills / "s" / "SKILL.md").write_text("version: 1\n\n# Original Skill", encoding="utf-8")
    ext = SkillExtractor(skills, min_tool_calls=4, llm=MockLLM())
    await ext.improve("s", "add weekly grouping", session_id="sess")
    text = (skills / "s" / "SKILL.md").read_text()
    assert "version: 2" in text
    assert "weekly" in text
