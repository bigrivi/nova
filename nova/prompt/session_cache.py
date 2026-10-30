"""The system prompt, frozen for the life of a session.

The system prompt is the cached prefix every provider matches against, so it has
to be byte-identical from one turn to the next. Nova builds a fresh ``Agent`` per
request, which meant the prompt was re-rendered every turn: the memory index, the
sub-agent roster and the project instructions were all re-read, and any change in
them rewrote the prefix and invalidated the whole conversation behind it.

Freezing it per session is the same trade-off the CLI agents make: a memory or a
sub-agent created mid-conversation shows up in the *next* session's prompt, not
in the current one. That is deliberate -- the alternative is re-billing the
conversation every time the model saves something.

Keyed by session, agent and workspace because those are the three inputs that
change the rendered text; a new session (or a workspace switch) is a miss, which
is exactly when a rebuild is wanted.
"""

from __future__ import annotations

from collections import OrderedDict

#: Bound: a long-running server sees many sessions, and one prompt is ~14KB.
MAX_ENTRIES = 256

PromptKey = tuple[str, str, str]

_cache: OrderedDict[PromptKey, str] = OrderedDict()


def prompt_key(session_id: str, agent_key: str, workspace: str) -> PromptKey:
    """The cache key for one session's prompt."""
    return (session_id, agent_key, workspace)


def get_session_prompt(key: PromptKey) -> str | None:
    """The prompt built for *key*, or None when this process has not built it."""
    prompt = _cache.get(key)
    if prompt is not None:
        _cache.move_to_end(key)
    return prompt


def remember_session_prompt(key: PromptKey, prompt: str) -> None:
    """Record *prompt* for *key*, evicting the least recently used entry."""
    _cache[key] = prompt
    _cache.move_to_end(key)
    while len(_cache) > MAX_ENTRIES:
        _cache.popitem(last=False)


def forget_session(session_id: str) -> None:
    """Drop every entry for *session_id* (a deleted session needs no prompt)."""
    for key in [item for item in _cache if item[0] == session_id]:
        _cache.pop(key, None)


def reset() -> None:
    """Clear the cache. Only tests should need this."""
    _cache.clear()
