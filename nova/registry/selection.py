"""What the model picker may offer, resolved once.

Two sources describe a provider's models: what the user wrote into
``config.json`` and what the provider last advertised. A configured entry wins —
it carries the label, the tools flag and any limits somebody pinned — and a
discovered model is offered only when the catalogue has not marked it unusable.

This module is the seam for that policy. The server maps these rows to its wire
record; tests read them without touching HTTP, sorting or grouping.
"""

from __future__ import annotations

from dataclasses import dataclass

from nova.llm.reasoning import resolve_effort_levels
from nova.llm.tokenizer import resolve_context_window
from nova.registry import catalogue as catalogue_module
from nova.settings import Settings


@dataclass(frozen=True)
class SelectableModel:
    """One row a model picker can show, with the spec already resolved."""

    provider: str
    provider_name: str
    model: str
    label: str
    tools: bool
    context: int
    efforts: list[str]


def _tools_enabled(model_config: dict) -> bool:
    if "tools" in model_config:
        return bool(model_config["tools"])
    if "toolCalling" in model_config:
        return bool(model_config["toolCalling"])
    return True


def selectable_models(settings: Settings) -> list[SelectableModel]:
    """Every selectable model, one contiguous block per provider.

    Contiguity matters to the clients: the pickers draw a header when the group
    changes, so a provider whose models arrived in two passes (configured, then
    discovered) would get its header twice and its rows scattered. One pass per
    provider keeps config order and makes the group label unique again.
    """
    stored = catalogue_module.load(settings)
    rows: list[SelectableModel] = []

    for provider_key, provider_config in settings.providers.items():
        for model_key, model_config in provider_config.models.items():
            spec = catalogue_module.spec_for(settings, provider_key, model_key, stored)
            rows.append(
                SelectableModel(
                    provider=provider_key,
                    provider_name=provider_config.name,
                    model=model_key,
                    label=str(model_config.get("name", "")).strip() or model_key,
                    tools=_tools_enabled(model_config),
                    context=resolve_context_window(model_key, provider_key)[0],
                    # The model's own route decides whether effort exists at
                    # all: an OpenAI-transport model under an Anthropic provider
                    # does have levels.
                    efforts=resolve_effort_levels(
                        model_key,
                        str(model_config.get("type") or spec.get("type") or "")
                        or provider_config.type,
                        model_config,
                        spec,
                    ),
                )
            )

        for model_key, spec in stored.get(provider_key, {}).items():
            if model_key in provider_config.models:
                continue
            # The catalogue says this one cannot answer a chat turn: offering it
            # would be a picker entry that fails on the first message. A model
            # the user wrote into config is never hidden this way — that is a
            # declaration, not a suggestion.
            if isinstance(spec, dict) and spec.get(catalogue_module.HIDDEN_KEY):
                continue
            rows.append(
                SelectableModel(
                    provider=provider_key,
                    provider_name=provider_config.name,
                    model=model_key,
                    label=model_key,
                    tools=True,
                    context=resolve_context_window(model_key, provider_key)[0],
                    efforts=resolve_effort_levels(
                        model_key,
                        str(spec.get("type") or "") or provider_config.type,
                        None,
                        spec,
                    ),
                )
            )
    return rows
