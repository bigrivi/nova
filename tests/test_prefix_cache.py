"""Prefix-cache hit-rate simulation across LLM providers.

Real cache hits happen server-side and need a live key, so these tests verify
the *precondition* that guarantees them: across a growing multi-turn
conversation with a frozen system prompt, every request body's cacheable prefix
stays byte-stable and each turn strictly extends the previous one. A turn can
only read a prior cache entry when the bytes up to a written breakpoint are
identical, so prefix stability is exactly what the hit rate measures here.

Each provider gets a thin adapter (``_build_body`` + ``_content_units``); the
measurement machinery is shared and the provider is just a parameter:

* ``anthropic`` — explicit ``cache_control`` breakpoints on the last system
  block and the last message block; ``body["system"]`` + ``body["messages"]``.
* ``openai`` (Chat Completions) — automatic prefix cache routed by
  ``prompt_cache_key``; ``body["messages"]`` (system is the first message).
* ``openai_response`` (Responses API) — same routing key; ``body["input"]``.

Ollama and Faker are excluded: local inference / test double, no server-side
prefix cache to hit.

``hit_rate(turn) = cached_prefix_tokens / total_input_tokens``.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json

import pytest

from nova import Agent, AgentConfig
from nova.agent.core import AgentEvent
from nova.db import database as db_module
from nova.db.config import DatabaseConfig
from nova.db.sqlite_repository import SqliteRepository
from nova.llm.anthropic import AnthropicProvider
from nova.llm.openai import OpenAIProvider
from nova.llm.openai_response import OpenAIResponsesProvider
from nova.llm.provider import Done, LLMProvider, Message, ReasoningDelta, TextDelta
from nova.llm.tokenizer import estimate_tokens_by_type
from nova.memory.models import MemoryWriteRequest
from nova.memory.service import MemoryService
from nova.session import manager as session_manager_module

_PROVIDERS = ("anthropic", "openai", "openai_response")

_PROVIDER_MODELS = {
    "anthropic": "claude-opus-4-8",
    "openai": "gpt-5",
    "openai_response": "gpt-5",
}

_FROZEN_SYSTEM = (
    "You are Nova, a personal AI assistant.\n\n"
    "## Tools\nread, write, edit, shell, memory_save, memory_search\n\n"
    "## Rules\nBe concise. Use tools when useful. " + ("x" * 4000)
)


def _make_provider(name: str):
    if name == "anthropic":
        return AnthropicProvider(
            request_options={"thinking": {"type": "enabled", "budget_tokens": 1024}}
        )
    if name == "openai":
        return OpenAIProvider()
    if name == "openai_response":
        return OpenAIResponsesProvider(api_key="k")
    raise ValueError(f"unknown provider: {name}")


def _build_body(
    name: str,
    provider,
    messages: list,
    model: str,
    session_id: str = "ses_test",
    tools: list | None = None,
) -> dict:
    """Build the wire body for one turn, honouring each provider's own path."""
    if name == "anthropic":
        return provider._build_body(messages=messages, model=model, tools=tools)
    if name == "openai":
        formatted = provider._format_messages(messages)
        return provider._build_body(
            messages=formatted, model=model, tools=tools, session_id=session_id
        )
    if name == "openai_response":
        input_data = provider._format_input(messages)
        return provider._build_body(input_data, model, tools=tools, session_id=session_id)
    raise ValueError(f"unknown provider: {name}")


def _strip_volatile(value: object) -> object:
    """Deep-copy *value* with every ``cache_control`` marker removed.

    Markers are not part of the hash the cache is keyed on, so they must be
    ignored when comparing prefixes for byte-stability. Routing hints
    (``prompt_cache_key``) live at the body top level and are never read into
    content units in the first place.
    """
    if isinstance(value, dict):
        return {
            key: _strip_volatile(inner)
            for key, inner in value.items()
            if key != "cache_control"
        }
    if isinstance(value, list):
        return [_strip_volatile(item) for item in value]
    return value


def _content_units(name: str, body: dict) -> list[str]:
    """Flatten a request body into ordered, hash-relevant content units.

    Each tool schema, system block, and message content block becomes one
    canonical JSON string. Tool schemas come first: every provider renders tools
    ahead of the system prompt, so they are the head of the cached prefix.
    Prefix caches match on the byte prefix, so an ordered unit list whose common
    prefix we can measure is the right model.
    """
    if name == "anthropic":
        units: list[str] = []
        for tool in body.get("tools") or []:
            units.append(json.dumps(_strip_volatile(tool), sort_keys=True))
        system = _strip_volatile(body.get("system"))
        if isinstance(system, str):
            units.append(json.dumps({"type": "text", "text": system}, sort_keys=True))
        elif isinstance(system, list):
            units.extend(json.dumps(block, sort_keys=True) for block in system)
        for message in body.get("messages", []):
            clean = _strip_volatile(message)
            role = clean.get("role")
            content = clean.get("content")
            if isinstance(content, list):
                for block in content:
                    units.append(json.dumps({"role": role, "block": block}, sort_keys=True))
            else:
                units.append(json.dumps({"role": role, "content": content}, sort_keys=True))
        return units
    if name == "openai":
        units = []
        for tool in body.get("tools") or []:
            units.append(json.dumps(tool, sort_keys=True))
        for message in body.get("messages", []):
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    units.append(
                        json.dumps({"role": message.get("role"), "block": block}, sort_keys=True)
                    )
            else:
                units.append(json.dumps(message, sort_keys=True))
        return units
    if name == "openai_response":
        units = [json.dumps(tool, sort_keys=True) for tool in body.get("tools") or []]
        data = body.get("input", [])
        if isinstance(data, str):
            return units + [json.dumps({"type": "input_text", "text": data}, sort_keys=True)]
        return units + [json.dumps(item, sort_keys=True) for item in data]
    raise ValueError(f"unknown provider: {name}")


def _system_portion(name: str, body: dict) -> str:
    """Canonical bytes of the system portion of a request body."""
    if name == "anthropic":
        return json.dumps(_strip_volatile(body.get("system")), sort_keys=True)
    if name == "openai":
        first = (body.get("messages") or [None])[0]
        return json.dumps(first, sort_keys=True)
    if name == "openai_response":
        first = (body.get("input") or [None])[0]
        return json.dumps(first, sort_keys=True)
    raise ValueError(f"unknown provider: {name}")


def _common_prefix_len(earlier: list[str], later: list[str]) -> int:
    count = 0
    for left, right in zip(earlier, later):
        if left != right:
            break
        count += 1
    return count


def _unit_tokens(unit: str) -> int:
    return estimate_tokens_by_type(unit)


def _build_conversation_turns(num_turns: int, model: str) -> list[list[Message]]:
    """Return the message list as it grows over *num_turns* agent turns.

    Turn k is the full history sent on the k-th request: a frozen system message,
    then alternating user / assistant(+tool_call) / tool-result blocks. Assistant
    turns carry a signed thinking block so replay is exercised; each is tagged
    with *model* so the request's model matches (Anthropic replay is skipped on
    mismatch; the OpenAI providers ignore the tag).
    """
    history: list[Message] = [Message(role="system", content=_FROZEN_SYSTEM)]
    turns: list[list[Message]] = []
    for turn_index in range(num_turns):
        history.append(Message(role="user", content=f"user request number {turn_index}"))
        turns.append(copy.deepcopy(history))
        history.append(
            Message(
                role="assistant",
                content=f"working on {turn_index}",
                reasoning_content=f"thinking about {turn_index}",
                provider_meta={"thinking_signature": f"SIG{turn_index}"},
                model=model,
                tool_calls=[{"id": f"toolu_{turn_index}", "name": "read", "arguments": "{}"}],
            )
        )
        history.append(Message(role="tool", tool_call_id=f"toolu_{turn_index}", content=f"file {turn_index} contents"))
    return turns


def _hit_rates(provider_name: str, num_turns: int, model: str | None = None) -> list[float]:
    """Cache hit rate per turn for a frozen-system multi-turn conversation."""
    model = model or _PROVIDER_MODELS[provider_name]
    provider = _make_provider(provider_name)
    turns = _build_conversation_turns(num_turns, model=model)

    rates: list[float] = []
    written_units: list[str] = []  # cache entry written by the previous turn
    for messages in turns:
        body = _build_body(provider_name, provider, messages, model)
        units = _content_units(provider_name, body)
        total_tokens = sum(_unit_tokens(unit) for unit in units)
        cached = _common_prefix_len(written_units, units)
        cached_tokens = sum(_unit_tokens(unit) for unit in units[:cached])
        rates.append(cached_tokens / total_tokens if total_tokens else 0.0)
        written_units = units  # this turn writes a breakpoint at its own tail
    return rates


def _prefix_coverage(provider_name: str, num_turns: int, model: str | None = None) -> list[float]:
    """Per-turn fraction of the *previous* turn's cache entry still reused.

    A value of 1.0 means the current request's prefix reaches the entire entry
    the previous turn wrote (no mid-history mutation). Below 1.0 means an earlier
    block changed and truncated the reusable prefix. This isolates cache
    stability from the token-volume confound that a hit-*rate* comparison across
    models suffers (a thinking-preserving model carries far more thinking tokens).

    Turn 0 has no prior entry and is omitted.
    """
    model = model or _PROVIDER_MODELS[provider_name]
    provider = _make_provider(provider_name)
    turns = _build_conversation_turns(num_turns, model=model)

    coverage: list[float] = []
    written_units: list[str] = []
    for messages in turns:
        units = _content_units(provider_name, _build_body(provider_name, provider, messages, model))
        if written_units:
            cached = _common_prefix_len(written_units, units)
            coverage.append(cached / len(written_units))
        written_units = units
    return coverage


@pytest.mark.parametrize("provider_name", _PROVIDERS)
def test_frozen_system_prefix_is_byte_identical_every_turn(provider_name: str):
    model = _PROVIDER_MODELS[provider_name]
    provider = _make_provider(provider_name)
    systems = [
        _system_portion(provider_name, _build_body(provider_name, provider, messages, model))
        for messages in _build_conversation_turns(5, model=model)
    ]
    assert all(system == systems[0] for system in systems)


@pytest.mark.parametrize("provider_name", _PROVIDERS)
def test_each_turn_strictly_extends_the_previous_prefix(provider_name: str):
    model = _PROVIDER_MODELS[provider_name]
    provider = _make_provider(provider_name)
    turns = _build_conversation_turns(5, model=model)
    previous_units: list[str] = []
    for messages in turns:
        units = _content_units(provider_name, _build_body(provider_name, provider, messages, model))
        # Every unit of the previous turn reappears unchanged as this turn's prefix.
        assert units[: len(previous_units)] == previous_units
        previous_units = units


@pytest.mark.parametrize("provider_name", _PROVIDERS)
def test_first_turn_is_a_full_cache_miss(provider_name: str):
    # Nothing was written before turn 1, so its hit rate must be zero.
    assert _hit_rates(provider_name, 4)[0] == 0.0


@pytest.mark.parametrize("provider_name", _PROVIDERS)
def test_hit_rate_climbs_and_dominates(provider_name: str):
    rates = _hit_rates(provider_name, 6)
    # Monotonic non-decreasing: each turn reuses at least as much as the last.
    assert all(later >= earlier for earlier, later in zip(rates, rates[1:]))
    # By the final turn the vast majority of input is served from cache; only
    # the single newest turn's blocks are processed fresh.
    assert rates[-1] > 0.85


_SAMPLE_TOOLS = [
    {"type": "function", "function": {
        "name": "read",
        "description": "Read a file",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "shell",
        "description": "Run a shell command",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
    }},
]


@pytest.mark.parametrize("provider_name", _PROVIDERS)
def test_tools_head_of_prefix_stable_across_turns(provider_name: str):
    """The tool-schema head of the prefix survives growing history.

    Tools render ahead of the system prompt in every provider, so they are the
    first units of the cached prefix. The registry itself is built once per
    agent (ToolsetBuilder at agent-build time; only register/register_direct
    ever write registry.tools, and get_schema is a pure function of insertion
    order), so with the same schema list each turn's units must strictly extend
    the previous turn's — the tools head included.
    """
    model = _PROVIDER_MODELS[provider_name]
    provider = _make_provider(provider_name)
    turns = _build_conversation_turns(4, model=model)
    bodies = [
        _build_body(provider_name, provider, messages, model, tools=_SAMPLE_TOOLS)
        for messages in turns
    ]
    assert all(body.get("tools") for body in bodies)
    units = [_content_units(provider_name, body) for body in bodies]
    previous: list[str] = []
    for turn_units in units:
        assert turn_units[: len(previous)] == previous
        previous = turn_units


def test_preserving_model_never_mutates_the_cached_prefix():
    # Every turn's prefix reaches the whole entry the previous turn wrote: the
    # replayed thinking keeps all history byte-stable, so nothing truncates.
    assert all(coverage == 1.0 for coverage in _prefix_coverage("anthropic", 6, model="claude-opus-4-8"))


def test_legacy_model_truncates_the_cached_prefix_once_history_has_thinking():
    # A legacy model replays only the newest assistant turn's thinking. The
    # first coverage point still reaches 1.0 because turn 0 wrote only
    # system+user (no assistant to mutate). From the next point on, the
    # previously-last assistant loses its thinking block when a newer turn
    # arrives, mutating a historical block and cutting the reusable prefix short.
    coverage = _prefix_coverage("anthropic", 6, model="claude-3-7-sonnet-20250219")
    assert coverage[0] == 1.0
    assert all(value < 1.0 for value in coverage[1:])


def test_openai_chat_build_body_sets_prompt_cache_key_from_session():
    provider = OpenAIProvider()
    body = provider._build_body(
        [{"role": "user", "content": "hi"}], model="gpt-5", session_id="ses_abc",
    )
    assert body["prompt_cache_key"] == "ses_abc"


def test_openai_chat_build_body_omits_prompt_cache_key_without_session():
    provider = OpenAIProvider()
    body = provider._build_body([{"role": "user", "content": "hi"}], model="gpt-5")
    assert "prompt_cache_key" not in body


def test_openai_chat_build_body_prompt_caching_disabled():
    # Gateways that reject the unknown field can opt out via request_options.
    provider = OpenAIProvider(request_options={"prompt_caching": False})
    body = provider._build_body(
        [{"role": "user", "content": "hi"}], model="gpt-5", session_id="ses_abc",
    )
    assert "prompt_cache_key" not in body


def test_openai_chat_build_body_cache_flag_not_leaked_into_body_params():
    # prompt_caching is consumed, never forwarded as an API param.
    provider = OpenAIProvider(request_options={"prompt_caching": True})
    body = provider._build_body(
        [{"role": "user", "content": "hi"}], model="gpt-5", session_id="ses_abc",
    )
    assert "prompt_caching" not in body
    assert body["prompt_cache_key"] == "ses_abc"


# ---------------------------------------------------------------------------
# Seam test: the real agent chain, not synthetic messages
# ---------------------------------------------------------------------------

@contextlib.asynccontextmanager
async def _isolated_agent(provider: LLMProvider, **agent_kwargs):
    """A real Agent over an in-memory SQLite store (mirrors the chat_stream
    tests' fixture so this file stays self-contained)."""
    database = SqliteRepository(DatabaseConfig(path=":memory:"))
    await database.connect()
    previous_db = db_module._db
    previous_manager = session_manager_module._manager
    db_module._db = database
    session_manager_module._manager = None
    try:
        agent = Agent(config=AgentConfig(**agent_kwargs), llm_provider=provider)
        yield agent, database
    finally:
        await database.close()
        db_module._db = previous_db
        session_manager_module._manager = previous_manager


class _CapturingProvider(LLMProvider):
    """Scripted stand-in that records the exact messages the agent hands it."""

    def __init__(self, scripts: list[list[object]]):
        self._scripts = scripts
        self._index = 0
        self.seen_messages: list[list[Message]] = []
        self.seen_session_ids: list[str | None] = []
        self.seen_tools: list = []

    async def chat(self, messages, model="m", stream=False, tools=None, **kwargs):
        return Done(content="summary")

    async def chat_stream(self, messages, model="m", tools=None, **kwargs):
        self.seen_messages.append(copy.deepcopy(messages))
        self.seen_session_ids.append(kwargs.get("session_id"))
        self.seen_tools.append(copy.deepcopy(tools))
        script = self._scripts[min(self._index, len(self._scripts) - 1)]
        self._index += 1
        for item in script:
            await asyncio.sleep(0)
            yield item

    async def count_tokens(self, text: str, model=None) -> int:
        return len(text)

    def get_max_tokens(self, model: str) -> int:
        return 128000


@pytest.mark.parametrize("provider_name", _PROVIDERS)
@pytest.mark.asyncio
async def test_real_agent_chain_prefix_stable_across_turns(provider_name: str):
    """Prefix stability through the real agent chain.

    Drives two real turns through ``Agent.chat_stream`` on an in-memory SQLite
    store: the genuine PromptBuilder system prompt, genuine persistence, the
    genuine ``_convert_to_llm_messages`` round-trip, and genuine session_id
    threading. A real memory write lands between the turns; Phase 1 requires
    the system prompt to stay frozen anyway. The captured per-turn messages are
    then fed to the real provider body builder, which must show turn 2 strictly
    extending turn 1.
    """
    model = _PROVIDER_MODELS[provider_name]
    scripts = [
        [ReasoningDelta(content="thinking one"), TextDelta(content="answer one"),
         Done(content="answer one", provider_meta={"thinking_signature": "SIG0"})],
        [TextDelta(content="answer two"),
         Done(content="answer two", provider_meta={"thinking_signature": "SIG1"})],
    ]
    capturer = _CapturingProvider(scripts)
    async with _isolated_agent(capturer, model=model) as (agent, database):
        session_id = None
        async for event, data in agent.chat_stream("first question"):
            if event == AgentEvent.SESSION:
                session_id = data
        assert session_id

        record, created = await MemoryService(data_source=database).save(
            MemoryWriteRequest(key="seam-probe", content="probe value",
                               summary="probe", scope="user", memory_type="fact")
        )
        assert created and record.key == "seam-probe"

        # The persistence round-trip keeps everything replay needs.
        loaded = await agent.session.get_messages(session_id=session_id)
        assistants = [m for m in loaded if m.role == "assistant"]
        assert len(assistants) == 1
        assert assistants[0].reasoning_content == "thinking one"
        assert assistants[0].provider_meta == {"thinking_signature": "SIG0"}
        assert assistants[0].model == model

        async for _event, _data in agent.chat_stream(
            "second question", session_id=session_id
        ):
            pass

    assert len(capturer.seen_messages) == 2
    assert capturer.seen_session_ids == [session_id, session_id]
    # The agent must hand the provider the same tool set every turn: tools are
    # the head of the cached prefix. (In this fixture the registry is empty, so
    # both are None; stability — not presence — is what the agent guarantees.
    # Presence with real schemas is covered by test_tools_head_of_prefix.)
    assert capturer.seen_tools[0] == capturer.seen_tools[1]

    real = _make_provider(provider_name)
    body1 = _build_body(
        provider_name, real, capturer.seen_messages[0], model,
        tools=capturer.seen_tools[0],
    )
    body2 = _build_body(
        provider_name, real, capturer.seen_messages[1], model,
        tools=capturer.seen_tools[1],
    )
    # The memory write between turns must not rebuild the system prompt.
    assert _system_portion(provider_name, body1) == _system_portion(
        provider_name, body2
    )
    units1 = _content_units(provider_name, body1)
    units2 = _content_units(provider_name, body2)
    assert units2[: len(units1)] == units1


# ---------------------------------------------------------------------------
# Cache-hit observability: Done -> reader -> per-turn log
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reader_absorbs_cache_read_tokens():
    from nova.agent.llm_stream import TurnStreamReader

    async def _emit(*args, **kwargs) -> None:
        return None

    async def _stop() -> None:
        return None

    async def _chunks():
        yield Done(content="hi", cache_read_tokens=77)

    reader = TurnStreamReader(emit=_emit, stop_if_aborted=_stop)
    [event async for event in reader.consume(_chunks())]
    assert reader.cache_read_tokens == 77


@pytest.mark.asyncio
async def test_core_logs_cache_read_per_turn(caplog):
    import logging

    scripts = [[TextDelta(content="hi"), Done(content="hi", cache_read_tokens=1234)]]
    capturer = _CapturingProvider(scripts)
    async with _isolated_agent(capturer, model="gpt-5") as (agent, _db):
        caplog.set_level(logging.INFO, logger="nova.agent.core")
        async for _event, _data in agent.chat_stream("hello"):
            pass
    assert "cache_read=1234" in caplog.text
