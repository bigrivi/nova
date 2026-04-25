import pytest

from nova.tools.todo_write import todo_write


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
        "2. 🕒 [in_progress] Implement weather endpoint"
    )
