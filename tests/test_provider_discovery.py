"""Discovery talks to someone else's server, so every failure path is pinned.

The form shows whatever message comes back, which means a wrong one sends the
user to fix the wrong thing: "no models" and "your key is bad" are not the same
problem, and neither is "the host is down".
"""

from __future__ import annotations

import httpx
import pytest

from nova.registry import discovery as provider_discovery
from nova.registry.discovery import DiscoveryError, discover_models, resolve_base_url


class _FakeClient:
    """Stands in for httpx.AsyncClient, recording the one request we make."""

    def __init__(
        self, *, response: httpx.Response | None = None, error: Exception | None = None
    ):
        self._response = response
        self._error = error
        self.requested_url = ""
        self.requested_headers: dict[str, str] = {}

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def get(
        self, url: str, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        self.requested_url = url
        self.requested_headers = headers or {}
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def _patch_client(monkeypatch, client: _FakeClient) -> _FakeClient:
    monkeypatch.setattr(
        provider_discovery.httpx, "AsyncClient", lambda **_kwargs: client
    )
    return client


@pytest.mark.asyncio
async def test_openai_compatible_reads_data_and_sends_a_bearer(monkeypatch) -> None:
    client = _patch_client(
        monkeypatch,
        _FakeClient(
            response=httpx.Response(
                200, json={"data": [{"id": "b-model"}, {"id": "a-model"}]}
            )
        ),
    )

    items = await discover_models(
        provider_type="openai-compatible",
        base_url="https://api.example.com/v1",
        api_key="sk-test",
    )

    assert [model.id for model in items] == ["a-model", "b-model"]
    assert client.requested_url == "https://api.example.com/v1/models"
    assert client.requested_headers["Authorization"] == "Bearer sk-test"


@pytest.mark.asyncio
async def test_ollama_reads_the_native_tags_endpoint(monkeypatch) -> None:
    client = _patch_client(
        monkeypatch,
        _FakeClient(
            response=httpx.Response(
                200, json={"models": [{"name": "qwen2.5:7b"}, {"name": "llama3"}]}
            )
        ),
    )

    items = await discover_models(
        provider_type="ollama",
        base_url="http://localhost:11434",
        api_key="",
    )

    assert [model.id for model in items] == ["llama3", "qwen2.5:7b"]
    assert client.requested_url == "http://localhost:11434/api/tags"
    assert client.requested_headers == {}


@pytest.mark.asyncio
async def test_anthropic_sends_its_own_auth_headers(monkeypatch) -> None:
    client = _patch_client(
        monkeypatch,
        _FakeClient(response=httpx.Response(200, json={"data": [{"id": "claude-x"}]})),
    )

    await discover_models(
        provider_type="anthropic",
        base_url="https://api.anthropic.com",
        api_key="sk-ant",
    )

    assert client.requested_url == "https://api.anthropic.com/v1/models"
    assert client.requested_headers["x-api-key"] == "sk-ant"
    assert "anthropic-version" in client.requested_headers


@pytest.mark.asyncio
async def test_rejected_key_is_not_reported_as_an_empty_list(monkeypatch) -> None:
    _patch_client(monkeypatch, _FakeClient(response=httpx.Response(401, json={})))

    with pytest.raises(DiscoveryError) as caught:
        await discover_models(
            provider_type="openai-compatible",
            base_url="https://api.example.com/v1",
            api_key="wrong",
        )

    assert caught.value.status == 401
    assert "refused the credentials" in str(caught.value)


@pytest.mark.asyncio
async def test_unreachable_host_says_so(monkeypatch) -> None:
    _patch_client(
        monkeypatch, _FakeClient(error=httpx.ConnectError("connection refused"))
    )

    with pytest.raises(DiscoveryError) as caught:
        await discover_models(
            provider_type="openai-compatible",
            base_url="http://127.0.0.1:9/v1",
            api_key="",
        )

    assert caught.value.status == 502
    assert "could not reach" in str(caught.value)


@pytest.mark.asyncio
async def test_unknown_envelope_is_not_silently_empty(monkeypatch) -> None:
    _patch_client(
        monkeypatch, _FakeClient(response=httpx.Response(200, json={"models": []}))
    )

    with pytest.raises(DiscoveryError):
        await discover_models(
            provider_type="openai-compatible",
            base_url="https://api.example.com/v1",
            api_key="sk-test",
        )


def test_empty_base_url_falls_back_to_the_adapter_default(monkeypatch) -> None:
    monkeypatch.delenv("NOVA_OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)

    assert resolve_base_url("ollama", "") == "http://localhost:11434"
    assert resolve_base_url("anthropic", "") == "https://api.anthropic.com"
    assert resolve_base_url("openai-compatible", "") == "https://api.openai.com/v1"
    # An explicit value wins and loses its trailing slash.
    assert resolve_base_url("ollama", "http://host:1/") == "http://host:1"


@pytest.mark.asyncio
async def test_a_client_identity_is_sent_when_configured(monkeypatch) -> None:
    """Some gateways answer 401 to anyone but their own client."""
    client = _patch_client(
        monkeypatch,
        _FakeClient(response=httpx.Response(200, json={"data": [{"id": "m"}]})),
    )

    await discover_models(
        provider_type="openai-compatible",
        base_url="https://gw.example/v1",
        api_key="sk",
        user_agent="claude-cli/2.0.0 (external, cli)",
    )

    assert client.requested_headers["User-Agent"] == "claude-cli/2.0.0 (external, cli)"
    assert client.requested_headers["Authorization"] == "Bearer sk"
