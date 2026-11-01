"""What each provider last said it serves.

Deliberately not in ``config.json``. Config is what the user *chose* — a provider
they connected, a model they pinned with limits or with tools turned off. This
file is a snapshot of someone else's catalogue: it can be refreshed, deleted, or
go stale without changing a single decision the user made.

The snapshot only carries ids. Per-model facts (context window, tool support)
still come from ``providers.<key>.models``; a model known only from here runs on
Nova's defaults until someone pins the real values in config.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any

from nova.registry.discovery import DiscoveredModel
from nova.settings import Settings, _write_json

CACHE_NAME = "models.json"


def cache_path(settings: Settings):
    """Where the snapshot lives, beside the database and the logs."""
    return settings.home / CACHE_NAME


def load(settings: Settings) -> dict[str, dict[str, dict]]:
    """Every provider's last known models, id -> the facts it stated.

    An entry with no facts is ``{}``, not a missing row: the model still exists,
    it just arrived without a context window. The list form is what older caches
    hold and is read as "ids with no facts".
    """
    try:
        payload = json.loads(cache_path(settings).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}

    known: dict[str, dict[str, dict]] = {}
    for provider, entry in payload.items():
        models = entry.get("models") if isinstance(entry, dict) else None
        if isinstance(models, list):
            known[str(provider)] = {
                str(item): {} for item in models if str(item).strip()
            }
        elif isinstance(models, dict):
            known[str(provider)] = {
                str(model_id): _normalise(facts)
                for model_id, facts in models.items()
            }
    return known


def _normalise(facts: object) -> dict[str, Any]:
    """Read an entry in the shape config.json uses, upgrading older ones.

    The snapshot speaks the same vocabulary as the config on purpose: what a
    provider said can be copied into an override without translating field
    names.
    """
    if not isinstance(facts, dict):
        return {}
    entry = dict(facts)

    # Older snapshots used flat keys; keep them readable.
    legacy_context = entry.pop("context", None)
    legacy_efforts = entry.pop("efforts", None)
    legacy_source = entry.pop("context_source", None)
    if legacy_context is not None and "limit" not in entry:
        entry["limit"] = {"context": legacy_context}
    if legacy_efforts is not None and LEVELS_KEY not in entry:
        entry[LEVELS_KEY] = legacy_efforts
    if legacy_source is not None:
        entry.setdefault(SOURCE_KEY, legacy_source)

    if not isinstance(entry.get("limit"), dict):
        entry.pop("limit", None)
    return entry


def record(
    settings: Settings, provider: str, models: Sequence[DiscoveredModel | str]
) -> None:
    """Store what a provider advertised, replacing the previous snapshot.

    Facts the provider stated are kept so planning does not depend on the user
    writing a context window into ``config.json`` for every model they use.
    """
    payload: dict[str, Any] = {}
    try:
        existing = json.loads(cache_path(settings).read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            payload = existing
    except (OSError, ValueError):
        payload = {}

    previous = payload.get(provider, {}).get("models")
    previous = previous if isinstance(previous, dict) else {}

    stored: dict[str, dict[str, Any]] = {}
    for item in models:
        if isinstance(item, str):
            model_id, stated = item.strip(), None
        else:
            model_id, stated = item.id.strip(), item.context
        if not model_id:
            continue
        # Re-asking a provider must not erase what the catalogue already filled
        # in for a model that is still there.
        facts = _normalise(previous.get(model_id, {}))
        if stated:
            facts[LIMIT_KEY] = {"context": stated}
            facts[SOURCE_KEY] = "provider"
        stored[model_id] = facts

    payload[provider] = {
        "fetched_at": int(time.time()),
        "models": dict(sorted(stored.items())),
    }
    _write_json(cache_path(settings), payload)


def forget(settings: Settings, provider: str) -> bool:
    """Drop one provider's snapshot; return whether anything was removed.

    Deleting a provider has to delete its catalogue too. Leaving the row behind
    would resurrect the old model list the moment the same key is connected
    again, before any refresh has a chance to correct it.
    """
    try:
        payload = json.loads(cache_path(settings).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(payload, dict) or provider not in payload:
        return False
    payload.pop(provider)
    _write_json(cache_path(settings), payload)
    return True


#: Field names shared with config.json, so a discovered fact can be pasted into
#: an override unchanged.
LIMIT_KEY = "limit"
LEVELS_KEY = "reasoning_effort_levels"
SOURCE_KEY = "_context_source"
#: Set when the catalogue says this model cannot answer a chat turn. Nova hides
#: it rather than offering a picker entry that cannot work.
HIDDEN_KEY = "_hidden"

MODELS_DEV_ENV = "NOVA_MODELS_DEV_URL"
MODELS_DEV_URL = "https://models.dev/api.json"
MODELS_DEV_TTL_SECONDS = 24 * 60 * 60
MODELS_DEV_TIMEOUT_SECONDS = 20.0


def _models_dev_facts(entry: object) -> dict[str, Any]:
    """Project one models.dev row down to what Nova plans with."""
    if not isinstance(entry, dict):
        return {}
    facts: dict[str, Any] = {}

    limit = entry.get("limit")
    context = limit.get("context") if isinstance(limit, dict) else None
    if isinstance(context, int) and not isinstance(context, bool) and context > 0:
        facts[LIMIT_KEY] = {"context": context}
        facts[SOURCE_KEY] = "models.dev"

    if entry.get("reasoning") is True:
        options = entry.get("reasoning_options")
        levels: list[str] = []
        if isinstance(options, list):
            for option in options:
                if not isinstance(option, dict) or option.get("type") != "effort":
                    continue
                values = option.get("values")
                if isinstance(values, list):
                    levels = [
                        str(value).strip()
                        for value in values
                        if str(value).strip() and str(value).strip() != "default"
                    ]
        if levels:
            facts[LEVELS_KEY] = levels
    return facts


def is_chat_capable(entry: object) -> bool:
    """Whether the catalogue says this model can answer a chat turn.

    models.dev states no job type, so this reads what it does state: a
    deprecated status, or an output that cannot produce text, means the model
    is not something a conversation can use.
    """
    if not isinstance(entry, dict):
        return True
    if str(entry.get("status") or "") == "deprecated":
        return False
    modalities = entry.get("modalities")
    if isinstance(modalities, dict):
        output = modalities.get("output")
        if isinstance(output, list) and output and "text" not in output:
            return False
    return True


def merge_models_dev(settings: Settings, catalog: object) -> int:
    """Fill gaps in the snapshot from models.dev. Returns how many rows changed.

    A fact the provider stated is never overwritten: the running provider is the
    truth about itself, and the catalogue is a snapshot of what somebody else
    published. Facts are merged into the same per-model object the discovery
    pass writes, so there is one file to read and one place to look.
    """
    if not isinstance(catalog, dict):
        return 0
    inner = catalog.get("providers")
    providers = inner if isinstance(inner, dict) else catalog

    try:
        payload = json.loads(cache_path(settings).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    stored: dict[str, dict[str, Any]] = {}
    for provider, entry in payload.items():
        models = entry.get("models") if isinstance(entry, dict) else None
        if isinstance(models, dict):
            stored[str(provider)] = {
                str(k): (v if isinstance(v, dict) else {}) for k, v in models.items()
            }

    wanted = {model for models in stored.values() for model in models}
    for provider in settings.providers.values():
        wanted.update(provider.models)

    # models.dev may know a model under a different provider key, so an id that
    # every catalogue provider agrees on can still fill a gap.
    by_id: dict[str, list[dict[str, Any]]] = {}
    for provider_id, provider in providers.items():
        models = provider.get("models") if isinstance(provider, dict) else None
        if not isinstance(models, dict):
            continue
        for model_id, entry in models.items():
            if str(model_id) not in wanted:
                continue
            facts = _models_dev_facts(entry)
            hidden = not is_chat_capable(entry)
            if not facts and not hidden:
                continue
            target = stored.get(str(provider_id), {}).get(str(model_id))
            if target is not None:
                if facts:
                    _fill(target, facts)
                if hidden:
                    target[HIDDEN_KEY] = True
                else:
                    target.pop(HIDDEN_KEY, None)
            if facts:
                by_id.setdefault(str(model_id), []).append(facts)

    for model_id, candidates in by_id.items():
        if not candidates or any(item != candidates[0] for item in candidates):
            continue
        for provider, models in stored.items():
            if model_id in models:
                _fill(models[model_id], candidates[0])

    if not stored:
        return 0

    merged: dict[str, Any] = {
        # One timestamp for the catalogue side, so the daily TTL does not reset
        # every time a provider is asked what it serves.
        "_meta": {"models_dev_at": int(time.time())},
        **{
            provider: {
                "fetched_at": int(payload.get(provider, {}).get("fetched_at", 0)),
                "models": models,
            }
            for provider, models in stored.items()
        },
    }
    _write_json(cache_path(settings), merged)
    return sum(1 for models in stored.values() for facts in models.values() if facts)


def _fill(target: dict[str, Any], facts: dict[str, Any]) -> bool:
    """Add what is missing; never replace a fact the provider stated.

    models.dev may overwrite its own earlier value — the catalogue moves — but a
    window the provider stated is the provider's to change.
    """
    changed = False
    for key, value in facts.items():
        if key == SOURCE_KEY:
            if not isinstance(target.get(LIMIT_KEY), dict):
                continue
            if target.get(SOURCE_KEY) == "provider":
                continue
            if target.get(SOURCE_KEY) != value:
                target[key] = value
                changed = True
            continue
        if key == LIMIT_KEY:
            current = target.get(LIMIT_KEY)
            if isinstance(current, dict) and current.get("context"):
                # The provider's own number, or an earlier catalogue value the
                # catalogue is allowed to correct.
                if target.get(SOURCE_KEY) != "models.dev":
                    continue
                if current.get("context") == value.get("context"):
                    continue
            target[key] = value
            changed = True
            continue
        if key not in target:
            target[key] = value
            changed = True
    return changed


async def refresh_models_dev(settings: Settings, *, force: bool = False) -> int:
    """Fetch models.dev once and refresh both derived surfaces.

    Merges the model facts into the snapshot and rewrites the derived provider
    presets. Never raises: both are fallbacks, and a failed fetch leaves the
    previous copies in place.
    """
    import os

    import httpx

    from nova.registry.presets import has_candidates

    # The TTL exists to keep restarts from hammering models.dev. It must not
    # skip a process that has no candidates yet: those live in memory only, so
    # a fresh process would otherwise offer the floor for a whole day.
    if (
        not force
        and has_candidates()
        and int(time.time()) - cached_at(settings) < MODELS_DEV_TTL_SECONDS
    ):
        return 0
    url = os.getenv(MODELS_DEV_ENV, "").strip() or MODELS_DEV_URL
    try:
        async with httpx.AsyncClient(timeout=MODELS_DEV_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
        if response.status_code >= 400:
            return 0
        catalog = response.json()
    except (httpx.HTTPError, ValueError):
        return 0

    # One download, two uses: the facts Nova plans with, and the vendors the
    # connect form offers. The second stays in memory — persisting every vendor
    # in the catalogue would write a file of providers this person never
    # connects; only what they connect is worth keeping on disk.
    from nova.registry.presets import derive_from_catalog, set_candidates

    set_candidates(derive_from_catalog(catalog))
    return merge_models_dev(settings, catalog)


def facts_for(
    settings: Settings, provider: str, model: str, payload: dict | None = None
) -> dict[str, Any]:
    """Facts for one model: the provider's own row first, then an agreed id."""
    data = payload if payload is not None else load(settings)
    entry = data.get(provider)
    if isinstance(entry, dict):
        facts = entry.get(model)
        if isinstance(facts, dict):
            return facts

    matches = [
        models[model]
        for models in data.values()
        if isinstance(models, dict) and isinstance(models.get(model), dict)
    ]
    matches = [match for match in matches if match]
    if matches and all(match == matches[0] for match in matches):
        return matches[0]
    return {}


def cached_at(settings: Settings) -> int:
    """When models.dev was last merged, ``0`` when it never was."""
    try:
        payload = json.loads(cache_path(settings).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    meta = payload.get("_meta") if isinstance(payload, dict) else None
    stamp = meta.get("models_dev_at") if isinstance(meta, dict) else None
    return int(stamp) if isinstance(stamp, int) else 0
