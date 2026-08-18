from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from nova.constants import DEFAULT_AGENT_KEY


@dataclass
class Message:
    id: str
    session_id: str
    role: str
    content: str
    model: Optional[str] = None
    format: Optional[str] = None
    variant: Optional[str] = None
    summary: int = 0
    compacted: int = 0
    finish: Optional[str] = None
    error: Optional[str] = None
    cost: Optional[float] = None
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    time_created: int = field(default_factory=lambda: int(time.time() * 1000))
    tool_calls: Optional[list] = None
    tool_call_id: Optional[str] = None
    data: Optional[str] = None
    images: Optional[list[str]] = None
    reasoning_content: Optional[str] = None
    group_id: Optional[str] = None
    reasoning_elapsed_ms: Optional[int] = None


@dataclass
class Session:
    id: str
    agent_key: str = DEFAULT_AGENT_KEY
    title: Optional[str] = None
    parent_id: Optional[str] = None
    summary_goal: Optional[str] = None
    summary_accomplished: Optional[str] = None
    summary_remaining: Optional[str] = None
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at: int = field(default_factory=lambda: int(time.time() * 1000))
    compacted_at: Optional[int] = None
    message_count: int = 0
    turn_count: int = 0
    metadata: Optional[dict] = None


@dataclass
class MessageFilter:
    include_compacted: bool = False
    exclude_tool_role: bool = False
    only_non_summary: bool = False
    limit: Optional[int] = None
