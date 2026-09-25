"""Stable task payloads shared by tool results and the web client."""

from __future__ import annotations

import json

from nova.tasks.models import TaskRecord


def background_task_content(record: TaskRecord, message: str) -> str:
    """Serialize an explicit, durable marker for a background task result.

    Args:
        record: Task to describe.
        message: Short instruction or status message for the model.

    Returns:
        JSON text persisted with the tool result and parsed by the UI.
    """
    return json.dumps(
        {
            "background_task": record.to_dict(include_output=False),
            "message": message,
        },
        ensure_ascii=False,
    )
