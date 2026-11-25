"""Leaf modules extracted to novakit keep one behavior and one identity."""

import pytest

from novakit.agent import (
    AgentConfig,
    build_user_message,
    convert_to_llm_messages,
    count_user_turns,
)
from novakit.agent.compaction import CompactionError
from novakit.agent.overflow import (
    NON_OVERFLOW_PATTERNS,
    OVERFLOW_PATTERNS,
    is_context_overflow,
)
from novakit.session.models import Message


def test_agent_config_defaults_cover_nova_compat_fields() -> None:
    config = AgentConfig()
    assert (
        config.model,
        config.provider,
        config.max_iterations,
        config.max_tokens,
        config.temperature,
        config.tools,
        config.memory_review_interval,
        config.reasoning_effort,
        config.shell_review,
        config.permission_mode,
        config.shell_read_only,
    ) == (
        "gpt-4o",
        "ollama",
        100,
        8192,
        0.7,
        None,
        10,
        None,
        False,
        "ask",
        False,
    )


def test_agent_config_field_order_matches_nova() -> None:
    assert list(AgentConfig.__dataclass_fields__) == [
        "model",
        "provider",
        "max_iterations",
        "max_tokens",
        "temperature",
        "tools",
        "memory_review_interval",
        "reasoning_effort",
        "shell_review",
        "permission_mode",
        "shell_read_only",
    ]


def test_build_user_message_plain_text_defaults_display() -> None:
    text, images, display = build_user_message("hello", None)
    assert (text, images, display) == ("hello", [], "hello")


def test_build_user_message_prepends_document_text() -> None:
    attachments = [
        {"type": "document", "content": [{"type": "text", "text": "doc body"}]}
    ]
    text, _, display = build_user_message("question", attachments)
    assert text == "doc body\n\nquestion"
    assert display == "question"


def test_count_user_turns_handles_dicts_and_objects() -> None:
    assert count_user_turns([{"role": "user"}, {"role": "assistant"}]) == 1
    assert (
        count_user_turns(
            [
                Message(id="a", session_id="s", role="user", content="hi"),
                Message(id="b", session_id="s", role="user", content="again"),
            ]
        )
        == 2
    )


def test_convert_to_llm_messages_drops_orphan_tool_results() -> None:
    orphan = Message(
        id="t1", session_id="s", role="tool", content="stale", tool_call_id="missing"
    )
    call = Message(
        id="a1",
        session_id="s",
        role="assistant",
        content="",
        tool_calls=[{"id": "kept", "name": "read"}],
    )
    result = Message(
        id="t2", session_id="s", role="tool", content="ok", tool_call_id="kept"
    )
    converted = convert_to_llm_messages([orphan, call, result])
    assert [(m.role, m.content) for m in converted] == [
        ("assistant", ""),
        ("tool", "ok"),
    ]


def test_compaction_error_is_a_runtime_error() -> None:
    with pytest.raises(RuntimeError, match="boom"):
        raise CompactionError("boom")


def test_overflow_classifiers_match_provider_rejections() -> None:
    assert OVERFLOW_PATTERNS and NON_OVERFLOW_PATTERNS
    assert is_context_overflow("This model's maximum context length is exceeded")
    assert not is_context_overflow("ThrottlingException: Too many tokens")
    assert is_context_overflow(
        None, context_window=100, tokens_input=90, cache_read_tokens=20
    )
    assert not is_context_overflow(None, context_window=100, tokens_input=10)
