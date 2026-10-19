import pytest
from nova.learning.user_model import UserModel, UserProfile


@pytest.mark.asyncio
async def test_load_missing_returns_empty(tmp_path):
    um = UserModel(str(tmp_path / "test.db"))
    await um.connect()
    profile = await um.load("u1")
    assert profile.user_id == "u1"
    assert profile.preferences == []
    await um.close()


@pytest.mark.asyncio
async def test_update_and_load(tmp_path):
    um = UserModel(str(tmp_path / "test.db"))
    await um.connect()
    from nova.learning.skill_extractor import TurnContext
    turn = TurnContext(session_id="s1", messages=[], tool_call_count=5, user_id="u1")
    await um.update("u1", turn)
    profile = await um.load("u1")
    assert "complex tasks" in profile.preferences
    await um.close()


@pytest.mark.asyncio
async def test_render_bounded(tmp_path):
    um = UserModel(str(tmp_path / "test.db"))
    profile = UserProfile(user_id="u1", preferences=["a" * 600])
    text = um.render(profile)
    assert len(text) <= 500


def test_render_includes_preferences():
    from nova.learning.user_model import UserModel, UserProfile
    um = UserModel(":memory:")
    profile = UserProfile(user_id="u1", preferences=["Python", "pandas"])
    text = um.render(profile)
    assert "Python" in text
    assert "pandas" in text
    assert "[User model]" in text