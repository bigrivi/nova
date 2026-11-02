"""What each provider last said it serves.

Deliberately not in ``config.json``. Config is what the user *chose* — a provider
they connected, a model they pinned with limits or with tools turned off. This
file is a snapshot of someone else's catalogue: it can be refreshed, deleted, or
go stale without changing a single decision the user made.

The snapshot only carries ids. Per-model specs (context window, transport,
reasoning levels) still come from ``providers.<key>.models``; a model known only
from here runs on Nova's defaults until someone pins the real values in config.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nova.registry.discovery import DiscoveredModel
from nova.registry.presets import (
    derive_from_catalog,
    has_candidates,
    set_candidates,
    type_for_npm,
)
from nova.settings import Settings, _write_json

CACHE_NAME = "models.json"


def cache_path(settings: Settings):
    """Where the snapshot lives, beside the database and the logs."""
    return settings.home / CACHE_NAME


def _read(settings: Settings) -> dict[str, Any]:
    """The snapshot as stored, or ``{}`` when it is missing or unreadable.

    One place decides what a corrupt file means, so every operation above agrees
    instead of each deciding for itself that it is empty.
    """
    try:
        payload = json.loads(cache_path(settings).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load(settings: Settings) -> dict[str, dict[str, dict]]:
    """Every provider's last known models, id -> the spec it stated.

    An entry with no spec is ``{}``, not a missing row: the model still exists,
    it just arrived without a context window. The list form is what older caches
    hold and is read as "ids with no spec".
    """
    payload = _read(settings)

    known: dict[str, dict[str, dict]] = {}
    for provider, entry in payload.items():
        models = entry.get("models") if isinstance(entry, dict) else None
        if isinstance(models, list):
            known[str(provider)] = {
                str(item): {} for item in models if str(item).strip()
            }
        elif isinstance(models, dict):
            known[str(provider)] = {
                str(model_id): _normalise(entry) for model_id, entry in models.items()
            }
    return known


def _normalise(stored: object) -> dict[str, Any]:
    """Read an entry in the shape config.json uses, upgrading older ones.

    The snapshot speaks the same vocabulary as the config on purpose: what a
    provider said can be copied into an override without translating field
    names.
    """
    if not isinstance(stored, dict):
        return {}
    entry = dict(stored)

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
    Whatever this process already downloaded from models.dev is folded in
    before returning: these rows are the first moment it can apply.
    """
    payload = _read(settings)

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
        entry = _normalise(previous.get(model_id, {}))
        if stated:
            entry[LIMIT_KEY] = {"context": stated}
            entry[SOURCE_KEY] = "provider"
        stored[model_id] = entry

    payload[provider] = {
        "fetched_at": int(time.time()),
        "models": dict(sorted(stored.items())),
    }
    _write_json(cache_path(settings), payload)

    _merge_downloaded(settings)


def forget(settings: Settings, provider: str) -> bool:
    """Drop one provider's snapshot; return whether anything was removed.

    Deleting a provider has to delete its catalogue too. Leaving the row behind
    would resurrect the old model list the moment the same key is connected
    again, before any refresh has a chance to correct it.
    """
    payload = _read(settings)
    if provider not in payload:
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


@dataclass(frozen=True)
class _Download:
    """The catalogue this process fetched, and what it was fetched for.

    One value instead of three globals: the home it belongs to, the fingerprint
    that makes a second identical download free, and the parsed rows. A provider
    connected later in the session still needs them, because the merge can only
    fill rows that exist — and they exist only after discovery wrote them.
    """

    home: Path
    digest: str
    catalog: dict[str, Any]


_download: _Download | None = None


def _catalogue_spec(
    entry: object, provider_npm: object = None, provider_api: object = None
) -> dict[str, Any]:
    """Project one models.dev row down to the spec Nova plans with."""
    if not isinstance(entry, dict):
        return {}
    spec: dict[str, Any] = {}

    limit = entry.get("limit")
    context = limit.get("context") if isinstance(limit, dict) else None
    if isinstance(context, int) and not isinstance(context, bool) and context > 0:
        spec[LIMIT_KEY] = {"context": context}
        spec[SOURCE_KEY] = "models.dev"

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
            spec[LEVELS_KEY] = levels

    # A model may speak a different transport than its provider: models.dev
    # says so per row, and the base URL usually moves with it. Recorded only
    # when it differs, so the snapshot stays quiet for the common case.
    sub = entry.get("provider")
    if isinstance(sub, dict):
        npm = str(sub.get("npm") or "").strip()
        if npm and npm != str(provider_npm or "").strip():
            spec["type"] = type_for_npm(npm)
        api = str(sub.get("api") or "").strip().rstrip("/")
        if api and api != str(provider_api or "").strip().rstrip("/"):
            spec["base_url"] = api
    return spec


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

    payload = _read(settings)

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
        provider_npm = provider.get("npm") if isinstance(provider, dict) else None
        provider_api = provider.get("api") if isinstance(provider, dict) else None
        for model_id, entry in models.items():
            if str(model_id) not in wanted:
                continue
            spec = _catalogue_spec(entry, provider_npm, provider_api)
            hidden = not is_chat_capable(entry)
            if not spec and not hidden:
                continue
            target = stored.get(str(provider_id), {}).get(str(model_id))
            if target is not None:
                if spec:
                    _fill(target, spec)
                if hidden:
                    target[HIDDEN_KEY] = True
                else:
                    target.pop(HIDDEN_KEY, None)
            if spec:
                by_id.setdefault(str(model_id), []).append(spec)

    for model_id, candidates in by_id.items():
        if not candidates or any(item != candidates[0] for item in candidates):
            continue
        for models in stored.values():
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
    return sum(1 for models in stored.values() for spec in models.values() if spec)


def _fill(target: dict[str, Any], spec: dict[str, Any]) -> bool:
    """Add what is missing; never replace a fact the provider stated.

    models.dev may overwrite its own earlier value — the catalogue moves — but a
    window the provider stated is the provider's to change.
    """
    changed = False
    for key, value in spec.items():
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


def _merge_downloaded(settings: Settings) -> int:
    """Fill the snapshot as it stands from the catalogue this process fetched.

    Fetching again would cost the same memory a second time — parsing a
    catalogue this size leaves roughly 11 MB resident that the allocator does
    not take back — so the parsed copy is kept and reused instead.
    """
    if _download is None or _download.home != settings.home:
        return 0
    return merge_models_dev(settings, _download.catalog)


async def refresh_models_dev(settings: Settings, *, force: bool = False) -> int:
    """Fetch models.dev once and refresh both derived surfaces.

    Merges the model specs into the snapshot and rewrites the derived provider
    presets. Never raises: both are fallbacks, and a failed fetch leaves the
    previous copies in place.
    """
    import os

    import httpx

    global _download

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
        digest = hashlib.blake2b(response.content).hexdigest()
        if _download is not None and digest == _download.digest:
            if _download.home == settings.home:
                # Same bytes as the copy in hand: reuse it rather than paying
                # for another parse. The merge still runs, because the snapshot
                # may have moved on since (a provider connected, a row recorded).
                return merge_models_dev(settings, _download.catalog)
            return 0
        catalog = response.json()
    except (httpx.HTTPError, ValueError):
        return 0
    if not isinstance(catalog, dict):
        return 0

    # One download, two uses: the specs Nova plans with, and the vendors the
    # connect form offers. The second stays in memory — persisting every vendor
    # in the catalogue would write a file of providers this person never
    # connects; only what they connect is worth keeping on disk.
    _download = _Download(settings.home, digest, catalog)
    set_candidates(derive_from_catalog(catalog))
    return merge_models_dev(settings, catalog)


def spec_for(
    settings: Settings, provider: str, model: str, payload: dict | None = None
) -> dict[str, Any]:
    """The spec for one model: the provider's own row first, then an agreed id."""
    data = payload if payload is not None else load(settings)
    entry = data.get(provider)
    if isinstance(entry, dict):
        spec = entry.get(model)
        if isinstance(spec, dict):
            return spec

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
    meta = _read(settings).get("_meta")
    stamp = meta.get("models_dev_at") if isinstance(meta, dict) else None
    return int(stamp) if isinstance(stamp, int) else 0
