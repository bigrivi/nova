from __future__ import annotations

import time
from dataclasses import dataclass, field

from nova.constants import DEFAULT_AGENT_KEY


@dataclass
class Message:
    id: str
    session_id: str
    role: str
    content: str
    model: str | None = None
    format: str | None = None
    variant: str | None = None
    summary: int = 0
    compacted: int = 0
    finish: str | None = None
    error: str | None = None
    cost: float | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    # The effort this turn actually ran with, next to the model it ran on. Pure
    # provenance: it is never read back to make a decision, only to answer "why
    # was this turn slow" after the session has moved on.
    reasoning_effort: str | None = None
    time_created: int = field(default_factory=lambda: int(time.time() * 1000))
    tool_calls: list | None = None
    tool_call_id: str | None = None
    data: str | None = None
    images: list[str] | None = None
    reasoning_content: str | None = None
    group_id: str | None = None
    reasoning_elapsed_ms: int | None = None
    # Opaque per-vendor state that must be handed back verbatim on the next
    # request (e.g. Anthropic thinking signatures). Never business data, never
    # surfaced to the UI. reasoning_content must not be rewritten when
    # provider_meta is present - the signature is over that text.
    provider_meta: dict | None = None


@dataclass
class Session:
    id: str
    agent_key: str = DEFAULT_AGENT_KEY
    title: str | None = None
    parent_id: str | None = None
    workspace_dir: str | None = None
    pinned: bool = False
    summary_goal: str | None = None
    summary_accomplished: str | None = None
    summary_remaining: str | None = None
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at: int = field(default_factory=lambda: int(time.time() * 1000))
    compacted_at: int | None = None
    message_count: int = 0
    turn_count: int = 0
    metadata: dict | None = None
    project_id: str | None = None
    # The route this session is being run with. Written on every turn and on
    # every model change, so reopening the session restores the model it was
    # actually using instead of whatever the agent points at today.
    # reasoning_effort is only meaningful alongside the model it was picked for.
    provider: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None


@dataclass
class MessageFilter:
    include_compacted: bool = False
    exclude_tool_role: bool = False
    only_non_summary: bool = False
    limit: int | None = None
