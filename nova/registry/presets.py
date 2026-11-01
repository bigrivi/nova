"""Provider presets: the three values a user would otherwise have to look up.

A preset is not a capability and not a validation rule. It carries exactly what
the provider form asks for — wire type, base URL, and where that vendor's key
usually lives — so adding one can never change how an existing ``config.json``
is read.

The bundled table is data, not code: ``presets.json`` beside this
module, generated from Codewhale's provider registry and adjusted where Nova
differs (see the ``source`` block in that file). A vendor added to that file on
``main`` reaches installed copies through the daily fetch below, so shipping a
new provider does not need a release.

Model ids are deliberately absent. They change fastest of anything here, and
guessing one puts a wrong value in front of the user; discovery fills them in.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

BUNDLED_NAME = "presets.json"
# The bundled table is the floor: the local runtimes, which no public catalogue
# lists. Everything else is derived from models.dev, so a new vendor needs
# neither a release nor a hand-maintained row here.
CACHE_NAME = "provider_presets.cache.json"

_SUPPORTED_TYPES = {"ollama", "openai-compatible", "openai-response", "anthropic"}


@dataclass(frozen=True)
class ProviderPreset:
    """One vendor's transport facts, as offered by the connect form."""

    id: str
    """Stable config key; also the default provider key in the form."""

    label: str
    """Display name."""

    type: str
    """One of ``ollama``, ``openai-compatible``, ``openai-response``, ``anthropic``."""

    base_url: str
    """Where the form points the provider. Empty means the adapter's own default."""

    key_env: str | None = None
    """Environment variable this vendor conventionally reads, for the hint text."""

    note: str = ""
    """One line of orientation: local, subscription, or plain API key."""


def _is_local(base_url: str) -> bool:
    return any(
        base_url.startswith(prefix)
        for prefix in ("http://localhost", "http://127.0.0.1", "http://[::1]")
    )


def preset_from_json(raw: object) -> ProviderPreset | None:
    """Read one row, refusing anything that could not be offered safely.

    A remote table is not trusted with the vendors we ship, and it is not
    trusted with a plain-HTTP endpoint: a preset that points at a cleartext host
    would send the user's key over the wire the moment they connect it.
    """
    if not isinstance(raw, dict):
        return None
    provider_id = str(raw.get("id", "")).strip()
    label = str(raw.get("label", "")).strip()
    provider_type = str(raw.get("type", "")).strip()
    base_url = str(raw.get("base_url", "")).strip().rstrip("/")
    if not provider_id or not label or not provider_type:
        return None
    if provider_type not in _SUPPORTED_TYPES:
        return None
    if not base_url:
        return None
    if not base_url.startswith("https://") and not _is_local(base_url):
        return None
    key_env = raw.get("key_env")
    return ProviderPreset(
        id=provider_id,
        label=label,
        type=provider_type,
        base_url=base_url,
        key_env=str(key_env).strip() if key_env else None,
        note=str(raw.get("note", "")).strip(),
    )


def bundled_payload() -> dict:
    """The shipped table, including its provenance block."""
    try:
        payload = json.loads(
            Path(__file__).with_name(BUNDLED_NAME).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return {"presets": []}
    return payload if isinstance(payload, dict) else {"presets": []}


def _rows(payload: object) -> list:
    if isinstance(payload, dict):
        rows = payload.get("presets")
    else:
        rows = payload
    return rows if isinstance(rows, list) else []


def _parse_rows(payload: object) -> tuple[ProviderPreset, ...]:
    parsed: list[ProviderPreset] = []
    for row in _rows(payload):
        preset = preset_from_json(row)
        if preset is not None:
            parsed.append(preset)
    return tuple(parsed)


BUNDLED: tuple[ProviderPreset, ...] = _parse_rows(bundled_payload())


def cache_path(home: Path) -> Path:
    """Where the last fetched table lives, beside the model snapshot."""
    return home / CACHE_NAME


#: The catalogue's candidate rows, kept in memory only. Persisting all of them
#: would write a file full of vendors this person will never connect; the disk
#: copy exists for what they did connect.
_candidates: tuple[ProviderPreset, ...] = ()


def has_candidates() -> bool:
    """Whether this process has already derived the catalogue."""
    return bool(_candidates)


def set_candidates(derived: tuple[ProviderPreset, ...]) -> None:
    """Hold the derived rows for this process, without touching the disk."""
    global _candidates
    _candidates = derived


def load(home: Path | None = None) -> tuple[ProviderPreset, ...]:
    """What the connect form offers: the floor, then what is known.

    Bundled ids always win, then the ones remembered from earlier connections,
    then the in-memory candidates from this process's refresh. A row on disk is
    a vendor the user actually connected, so it survives a restart without the
    network; the rest are suggestions and cost nothing to lose.
    """
    known = {preset.id for preset in BUNDLED}
    ordered: list[ProviderPreset] = list(BUNDLED)

    if home is not None:
        try:
            payload = json.loads(cache_path(home).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
        for preset in _parse_rows(payload):
            if preset.id not in known:
                known.add(preset.id)
                ordered.append(preset)

    for preset in _candidates:
        if preset.id not in known:
            known.add(preset.id)
            ordered.append(preset)
    return tuple(ordered)


def remember(home: Path, preset: ProviderPreset) -> None:
    """Persist one row: a provider this person connected, and only that.

    Kept on disk so a config entry or a stored key still resolves after a
    restart with no network — the candidate list is not worth writing.
    """
    from nova.settings import _write_json

    try:
        payload = json.loads(cache_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = None
    rows = _rows(payload)
    kept = [
        row
        for row in rows
        if isinstance(row, dict) and str(row.get("id", "")) != preset.id
    ]
    kept.append(
        {
            "id": preset.id,
            "label": preset.label,
            "type": preset.type,
            "base_url": preset.base_url,
            "key_env": preset.key_env,
        }
    )
    _write_json(cache_path(home), {"presets": kept})


def cached_at(home: Path) -> int:
    """Unix time of the last successful fetch, ``0`` when there is no cache."""
    try:
        payload = json.loads(cache_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    fetched = payload.get("fetched_at") if isinstance(payload, dict) else None
    return int(fetched) if isinstance(fetched, int) else 0


def derive_from_catalog(catalog: object) -> tuple[ProviderPreset, ...]:
    """Build presets from models.dev: base URL, key env, and wire from `npm`.

    A provider is only offered when the catalogue states a base URL: without
    one, the form would save a provider that cannot be reached. The wire comes
    from the SDK package the catalogue assigns — `@ai-sdk/anthropic` is the only
    one that is not OpenAI-compatible — which is what makes this derivable at
    all.
    """
    if not isinstance(catalog, dict):
        return ()
    inner = catalog.get("providers")
    providers = inner if isinstance(inner, dict) else catalog

    derived: list[ProviderPreset] = []
    for provider_id, entry in providers.items():
        if not isinstance(entry, dict):
            continue
        api = str(entry.get("api") or "").strip().rstrip("/")
        if not api:
            continue
        env = entry.get("env")
        key_env = str(env[0]).strip() if isinstance(env, list) and env else None
        provider_type = (
            "anthropic"
            if str(entry.get("npm") or "") == "@ai-sdk/anthropic"
            else "openai-compatible"
        )
        preset = preset_from_json(
            {
                "id": str(provider_id).lower(),
                "label": str(entry.get("name") or provider_id).strip(),
                "type": provider_type,
                "base_url": api,
                "key_env": key_env,
            }
        )
        if preset is not None:
            derived.append(preset)
    return tuple(sorted(derived, key=lambda item: item.label.lower()))


def preset_ids() -> tuple[str, ...]:
    """The bundled preset ids, for tests and drift checks."""
    return tuple(preset.id for preset in BUNDLED)


def preset_for(provider_id: str, home: Path | None = None) -> ProviderPreset | None:
    """The preset a provider id names, or ``None`` for a custom provider."""
    for preset in load(home):
        if preset.id == provider_id:
            return preset
    return None
