
import pytest

from nova.learning.skill_extractor import SkillExtractor, TurnContext


@pytest.mark.asyncio
async def test_no_extraction_below_threshold(tmp_path):
    class MockLLM:
        async def chat_stream(self, messages, model="gpt-4o", **kw):
            from nova.llm.provider import Done, TextDelta
            yield TextDelta(content='{"action": "create", "name": "x", "content": "y"}')
            yield Done(content='{"action": "create", "name": "x", "content": "y"}')
    ext = SkillExtractor(tmp_path / "skills", min_tool_calls=4, llm=MockLLM())
    turn = TurnContext(session_id="s1", messages=[], tool_call_count=2)
    result = await ext.maybe_extract(turn)
    assert result is None
    assert not (tmp_path / "skills").exists() or not any((tmp_path / "skills").iterdir())


@pytest.mark.asyncio
async def test_extraction_above_threshold_writes_skill(tmp_path):
    class MockLLM:
        async def chat_stream(self, messages, model="gpt-4o", **kw):
            from nova.llm.provider import Done, TextDelta
            yield TextDelta(content='{"action": "create", "name": "csv-agg", "content": "# CSV Aggregator\\nDo stuff."}')
            yield Done(content='{"action": "create", "name": "csv-agg", "content": "# CSV Aggregator\\nDo stuff."}')
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
            from nova.llm.provider import Done, TextDelta
            yield TextDelta(content='{"action": "create", "name": "v-skill", "content": "# V Skill"}')
            yield Done(content='{"action": "create", "name": "v-skill", "content": "# V Skill"}')
    ext = SkillExtractor(tmp_path / "skills", min_tool_calls=4, llm=MockLLM())
    turn = TurnContext(session_id="s1", messages=[], tool_call_count=5)
    await ext.maybe_extract(turn)
    text = (tmp_path / "skills" / "v-skill" / "SKILL.md").read_text()
    assert "version: 1" in text


@pytest.mark.asyncio
async def test_improve_bumps_version(tmp_path):
    class MockLLM:
        async def chat_stream(self, messages, model="gpt-4o", **kw):
            from nova.llm.provider import Done, TextDelta
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


@pytest.mark.asyncio
async def test_similar_name_merges_instead_of_creating(tmp_path):
    skills = tmp_path / "skills"
    (skills / "csv-aggregate-to-json").mkdir(parents=True)
    (skills / "csv-aggregate-to-json" / "SKILL.md").write_text(
        "version: 1\n\n# CSV Aggregate\nread csv group by column output json", encoding="utf-8"
    )

    class MockLLM:
        async def chat_stream(self, messages, model="gpt-4o", **kw):
            from nova.llm.provider import Done, TextDelta
            body = '{"action": "create", "name": "csv-aggregation-json", "content": "# CSV Aggregate\\nread csv group by column output json"}'
            yield TextDelta(content=body)
            yield Done(content=body)

    ext = SkillExtractor(skills, min_tool_calls=1, llm=MockLLM())
    turn = TurnContext(session_id="s1", messages=[], tool_call_count=5)
    result = await ext.maybe_extract(turn)
    # Either merged into the existing skill or skipped as a duplicate; never a new dir.
    dirs = [p.name for p in skills.iterdir() if p.is_dir()]
    assert dirs == ["csv-aggregate-to-json"]
    if result is not None:
        assert result.name == "csv-aggregate-to-json"


@pytest.mark.asyncio
async def test_identical_content_is_a_no_op(tmp_path):
    skills = tmp_path / "skills"
    (skills / "same-skill").mkdir(parents=True)
    original = "version: 1\n\n# Same\nread csv group by column output json"
    (skills / "same-skill" / "SKILL.md").write_text(original, encoding="utf-8")

    class MockLLM:
        async def chat_stream(self, messages, model="gpt-4o", **kw):
            from nova.llm.provider import Done, TextDelta
            body = '{"action": "update", "name": "same-skill", "content": "# Same\\nread csv group by column output json"}'
            yield TextDelta(content=body)
            yield Done(content=body)

    ext = SkillExtractor(skills, min_tool_calls=1, llm=MockLLM())
    turn = TurnContext(session_id="s1", messages=[], tool_call_count=5)
    result = await ext.maybe_extract(turn)
    assert result is None
    assert (skills / "same-skill" / "SKILL.md").read_text() == original


@pytest.mark.asyncio
async def test_none_action_is_a_no_op(tmp_path):
    class MockLLM:
        async def chat_stream(self, messages, model="gpt-4o", **kw):
            from nova.llm.provider import Done, TextDelta
            yield TextDelta(content='{"action": "none"}')
            yield Done(content='{"action": "none"}')

    ext = SkillExtractor(tmp_path / "skills", min_tool_calls=1, llm=MockLLM())
    turn = TurnContext(session_id="s1", messages=[], tool_call_count=5)
    result = await ext.maybe_extract(turn)
    assert result is None
    assert not (tmp_path / "skills").exists() or not any((tmp_path / "skills").iterdir())


@pytest.mark.asyncio
async def test_create_with_references(tmp_path):
    class MockLLM:
        async def chat_stream(self, messages, model="gpt-4o", **kw):
            from nova.llm.provider import Done, TextDelta
            body = '{"action": "create", "name": "csv-analysis", "content": "# CSV Analysis", "references": {"csv.md": "# CSV notes"}}'
            yield TextDelta(content=body)
            yield Done(content=body)

    ext = SkillExtractor(tmp_path / "skills", min_tool_calls=1, llm=MockLLM())
    turn = TurnContext(session_id="s1", messages=[], tool_call_count=5)
    result = await ext.maybe_extract(turn)
    assert result is not None
    ref = tmp_path / "skills" / "csv-analysis" / "references" / "csv.md"
    assert ref.exists()
    assert "CSV notes" in ref.read_text()
