"""Reasoning effort: the levels a model offers, and how each wire format spells them.

The level list is **only** what ``config.json`` declares. Nothing is inferred
from the model id, deliberately: a gateway alias like ``mimo-v2.5`` or
``big-pickle`` gives no clue about which ladder it serves, and a wrong guess is
a 400 from the provider rather than a missing control. A model with no
``reasoning_effort_levels`` therefore has no control in the UI, which is the
honest answer.

Two responsibilities stay apart on purpose:

* :func:`resolve_effort_levels` answers "what may the user pick?" and is pure
  metadata read from config.
* :func:`apply_effort` answers "what does the request body look like?" and owns
  the one place that knows each provider's spelling.
"""

from __future__ import annotations

from typing import Optional

# Config key an operator sets on a model to declare its levels, e.g.
#   "models": {"gpt-5.5": {"reasoning_effort_levels": ["low", "medium", "high"]}}
LEVELS_CONFIG_KEY = "reasoning_effort_levels"

# Provider types whose request body can carry a level at all. Anthropic has no
# effort concept (only thinking budgets) and Ollama/faker have none, so a
# declaration on those is ignored rather than silently sent and rejected.
EFFORT_PROVIDER_TYPES: frozenset[str] = frozenset(
    {"openai-compatible", "openai-response"}
)


def _levels_from_config(model_config: Optional[dict]) -> Optional[list[str]]:
    """Read the declared levels, or None when the model declares none.

    A bare string is accepted as a one-level list so a single-value declaration
    does not have to be wrapped in an array.
    """
    raw = (model_config or {}).get(LEVELS_CONFIG_KEY)
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return None
    levels = [str(item).strip() for item in raw if str(item).strip()]
    return levels or None


def resolve_effort_levels(
    model: str,
    provider_type: str,
    model_config: Optional[dict] = None,
) -> list[str]:
    """Return the reasoning levels *model* declares, or ``[]`` when it declares none.

    Args:
        model: Model key as written in config.json. Unused today, kept so the
            signature matches the sibling context-window resolver and so a future
            per-model override has a place to read from.
        provider_type: ``openai-compatible`` / ``openai-response`` / ... Only
            provider types that can carry a level are considered.
        model_config: The model's config entry.

    Returns:
        Levels in declared order, deduplicated. Empty means "offer no control".
    """
    if provider_type not in EFFORT_PROVIDER_TYPES:
        return []
    declared = _levels_from_config(model_config)
    if declared is None:
        return []
    return list(dict.fromkeys(declared))


def fit_effort(levels: list[str], effort: Optional[str]) -> Optional[str]:
    """Return *effort* when the model declared it, otherwise ``None``.

    Applied to every value that reaches the model - the per-turn selection, a
    value restored from an older session, a hand-edited one - so anything the
    model does not declare is dropped rather than sent and rejected.
    """
    if not effort or not levels:
        return None
    return effort if effort in levels else None


def apply_effort(
    body: dict,
    effort: Optional[str],
    provider_type: str,
) -> dict:
    """Write *effort* into a request body in *provider_type*'s spelling.

    Chat Completions takes a flat ``reasoning_effort``; the Responses API nests
    it under ``reasoning``. Anything already present in *body* wins, so a
    hand-written ``reasoning_effort`` in config.json still overrides the
    per-turn selection.
    """
    if not effort:
        return body
    if provider_type == "openai-compatible":
        body.setdefault("reasoning_effort", effort)
    elif provider_type == "openai-response":
        body.setdefault("reasoning", {"effort": effort})
    return body


__all__: list[str] = [
    "EFFORT_PROVIDER_TYPES",
    "LEVELS_CONFIG_KEY",
    "apply_effort",
    "fit_effort",
    "resolve_effort_levels",
]
