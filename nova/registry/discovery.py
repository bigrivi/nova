"""Ask a provider which models it serves, so the form can offer a list.

Nothing here is cached and nothing is written: the answer is a hint for the
add-model form, and a provider that is down must not look like a provider with
no models. That is why every failure carries a sentence a person can act on
rather than an empty list.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from nova.settings import _resolve_ollama_base_url, _resolve_openai_base_url

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_TIMEOUT_SECONDS = 10.0


class DiscoveryError(Exception):
    """A failed lookup, carrying the HTTP status the route should return."""

    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


def resolve_base_url(provider_type: str, configured: str) -> str:
    """The URL the runtime would use when the config leaves ``base_url`` empty."""
    if configured:
        return configured.rstrip("/")
    if provider_type == "ollama":
        return _resolve_ollama_base_url().rstrip("/")
    if provider_type == "anthropic":
        return "https://api.anthropic.com"
    return _resolve_openai_base_url().rstrip("/")


def _endpoint(provider_type: str, base_url: str) -> str:
    # Ollama speaks its native API at the root; the others follow their own
    # convention, and `base_url` already carries the prefix they expect.
    if provider_type == "ollama":
        return f"{base_url}/api/tags"
    if provider_type == "anthropic":
        return f"{base_url}/v1/models"
    return f"{base_url}/models"


def _headers(provider_type: str, api_key: str) -> dict[str, str]:
    if not api_key:
        return {}
    if provider_type == "anthropic":
        return {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION}
    return {"Authorization": f"Bearer {api_key}"}


#: Field names providers use for "how much fits in this model". OpenRouter
#: says ``context_length``, vLLM ``max_model_len``, most gateways one of the
#: others. A fact found here is what lets Nova plan compaction without the user
#: writing it into config.json.
_CONTEXT_FIELDS = (
    "context_length",
    "max_model_len",
    "max_input_tokens",
    "context_window",
    "input_token_limit",
)


@dataclass(frozen=True)
class DiscoveredModel:
    """One model a provider advertises, plus whatever it said about it."""

    id: str
    #: The context window the provider states, when it states one.
    context: int | None = None
    #: The raw entry, kept so a later fact can be read without a re-fetch.
    raw: dict = field(default_factory=dict, repr=False)


def _context_of(entry: dict) -> int | None:
    for name in _CONTEXT_FIELDS:
        value = entry.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if value > 0:
            return int(value)
    nested = entry.get("top_provider")
    if isinstance(nested, dict):
        value = nested.get("context_length")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return int(value)
    return None


def _models(provider_type: str, payload: object) -> list[DiscoveredModel]:
    """Read the ids — and any stated facts — out of this provider's envelope."""
    if not isinstance(payload, dict):
        raise DiscoveryError("the provider returned something that is not a model list")

    if provider_type == "ollama":
        entries = payload.get("models")
        key = "name"
    else:
        entries = payload.get("data")
        key = "id"

    if not isinstance(entries, list):
        raise DiscoveryError("the provider returned something that is not a model list")

    found: dict[str, DiscoveredModel] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get(key, "")).strip()
        if not model_id:
            continue
        found[model_id] = DiscoveredModel(
            id=model_id, context=_context_of(entry), raw=entry
        )
    return [found[model_id] for model_id in sorted(found)]


async def discover_models(
    *,
    provider_type: str,
    base_url: str,
    api_key: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[DiscoveredModel]:
    """Return the models this provider advertises, with the facts it states.

    Raises:
        DiscoveryError: when the provider cannot be reached, refuses the key, or
            answers with a shape this client cannot read. Each case names the
            thing the user has to fix.
    """
    url = _endpoint(provider_type, base_url)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=_headers(provider_type, api_key))
    except httpx.HTTPError as exc:
        raise DiscoveryError(f"could not reach {url} ({exc.__class__.__name__})") from exc

    if response.status_code in (401, 403):
        raise DiscoveryError(
            f"{url} rejected the API key ({response.status_code})", status=401
        )
    if response.status_code >= 400:
        raise DiscoveryError(
            f"{url} answered {response.status_code}: {response.text[:200].strip()}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise DiscoveryError(f"{url} did not answer with JSON") from exc

    return _models(provider_type, payload)
