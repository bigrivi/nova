import pytest
import asyncio
from nova.learning.session_search import SessionSearch


@pytest.mark.asyncio
async def test_index_and_search(tmp_path):
    ss = SessionSearch(str(tmp_path / "test.db"))
    await ss.connect()
    await ss.index_turn("s1", [{"content": "CSV sales report by date"}])
    await ss.index_turn("s2", [{"content": "Excel monthly summary"}])
    hits = await ss.search("CSV")
    assert len(hits) >= 1
    assert hits[0].session_id == "s1"
    await ss.close()


@pytest.mark.asyncio
async def test_search_empty_query(tmp_path):
    ss = SessionSearch(str(tmp_path / "test.db"))
    await ss.connect()
    hits = await ss.search("")
    assert hits == []
    await ss.close()


@pytest.mark.asyncio
async def test_search_no_match(tmp_path):
    ss = SessionSearch(str(tmp_path / "test.db"))
    await ss.connect()
    await ss.index_turn("s1", [{"content": "hello world"}])
    hits = await ss.search("zzzznonexistent")
    assert hits == []
    await ss.close()


@pytest.mark.asyncio
async def test_index_empty_content_skipped(tmp_path):
    ss = SessionSearch(str(tmp_path / "test.db"))
    await ss.connect()
    await ss.index_turn("s1", [{"content": ""}])
    hits = await ss.search("anything")
    assert hits == []
    await ss.close()


@pytest.mark.asyncio
async def test_summarize_with_mock_llm(tmp_path):
    ss = SessionSearch(str(tmp_path / "test.db"))
    await ss.connect()
    await ss.index_turn("s1", [{"content": "CSV sales report"}])
    hits = await ss.search("CSV")
    class MockLLM:
        async def chat_stream(self, messages, model="gpt-4o", **kw):
            from nova.llm.provider import TextDelta, Done
            yield TextDelta(content="Summary: CSV sales report found.")
            yield Done(content="Summary: CSV sales report found.")
    result = await ss.summarize(hits, "CSV", MockLLM())
    assert "Summary" in result
    await ss.close()


@pytest.mark.asyncio
async def test_summarize_empty_hits(tmp_path):
    ss = SessionSearch(str(tmp_path / "test.db"))
    await ss.connect()
    class MockLLM:
        async def chat_stream(self, messages, model="gpt-4o", **kw):
            from nova.llm.provider import TextDelta, Done
            yield TextDelta(content="no")
            yield Done(content="no")
    result = await ss.summarize([], "q", MockLLM())
    assert "No matching" in result
    await ss.close()