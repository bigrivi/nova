import pytest

from nova.tools.todo_write import todo_write


def _todo(content: str, status: str, priority: str = "high") -> dict:
    return {"content": content, "status": status, "priority": priority}


@pytest.mark.asyncio
async def test_todo_write_renders_task_list_with_status_markers():
    result = await todo_write(
        todos=[
            {"content": "Inspect project structure", "status": "completed", "priority": "high"},
            {"content": "Implement weather endpoint", "status": "in_progress", "priority": "medium"},
        ]
    )

    assert result.success is True
    assert result.content == (
        "## Tasks\n\n"
        "1. ✅ [completed] Inspect project structure\n"
        "2. 🕒 [in_progress] Implement weather endpoint\n"
        "\n"
        "WARNING: 1 task(s) still open (1 in_progress, 0 pending). "
        "If the work is finished, call todo_write again marking them completed "
        "or cancelled BEFORE you write your final reply."
    )


@pytest.mark.asyncio
async def test_all_statuses_render_their_marker():
    result = await todo_write(todos=[
        _todo("first", "completed"),
        _todo("second", "in_progress"),
        _todo("third", "pending"),
        _todo("fourth", "cancelled"),
    ])

    assert "1. ✅ [completed] first" in result.content
    assert "2. 🕒 [in_progress] second" in result.content
    assert "3. ⚪ [pending] third" in result.content
    assert "4. ❌ [cancelled] fourth" in result.content


@pytest.mark.asyncio
async def test_closed_list_produces_no_warning():
    result = await todo_write(todos=[
        _todo("first", "completed"),
        _todo("second", "cancelled"),
    ])

    assert "WARNING" not in result.content


@pytest.mark.asyncio
async def test_trailing_in_progress_task_is_flagged():
    """The reported failure: the model's last call left one task in_progress."""
    result = await todo_write(todos=[
        _todo("weights", "completed"),
        _todo("search", "completed"),
        _todo("shortlist", "completed"),
        _todo("score", "completed"),
        _todo("conclusion", "in_progress"),
    ])

    assert "WARNING: 1 task(s) still open" in result.content
    assert "1 in_progress, 0 pending" in result.content
    assert "BEFORE you write your final reply" in result.content


@pytest.mark.asyncio
async def test_pending_tasks_count_towards_the_open_warning():
    result = await todo_write(todos=[
        _todo("a", "completed"),
        _todo("b", "in_progress"),
        _todo("c", "pending"),
        _todo("d", "pending"),
    ])

    assert "WARNING: 3 task(s) still open" in result.content
    assert "1 in_progress, 2 pending" in result.content


@pytest.mark.asyncio
async def test_more_than_one_in_progress_is_flagged():
    result = await todo_write(todos=[
        _todo("a", "in_progress"),
        _todo("b", "in_progress"),
    ])

    assert "2 tasks are in_progress at once" in result.content
    assert "allows only 1" in result.content


@pytest.mark.asyncio
async def test_single_in_progress_does_not_trigger_rule_four_warning():
    result = await todo_write(todos=[_todo("a", "in_progress")])

    assert "in_progress at once" not in result.content


@pytest.mark.asyncio
async def test_unrecognised_status_is_flagged_per_task():
    result = await todo_write(todos=[
        _todo("a", "completed"),
        _todo("b", "done"),
    ])

    assert "task 2 has unrecognised status 'done'" in result.content


@pytest.mark.asyncio
async def test_warnings_never_contain_a_bracketed_status_token():
    """The TUI parses this text for ``[completed]`` markers when call arguments
    are unavailable, so a warning carrying one would render as a phantom task."""
    result = await todo_write(todos=[
        _todo("a", "in_progress"),
        _todo("b", "in_progress"),
        _todo("c", "pending"),
        _todo("d", "bogus"),
    ])

    warning_lines = [
        line for line in result.content.split("\n") if line.startswith("WARNING")
    ]
    assert warning_lines
    for line in warning_lines:
        for token in ("[completed]", "[in_progress]", "[pending]", "[cancelled]"):
            assert token not in line


@pytest.mark.asyncio
async def test_empty_list_is_accepted_without_warnings():
    result = await todo_write(todos=[])

    assert result.success is True
    assert "WARNING" not in result.content


@pytest.mark.asyncio
async def test_missing_status_defaults_to_pending_and_counts_as_open():
    result = await todo_write(todos=[{"content": "a", "priority": "high"}])

    assert "⚪ [pending] a" in result.content
    assert "0 in_progress, 1 pending" in result.content
