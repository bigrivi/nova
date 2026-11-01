"""Model and provider config: reads, mutations, and response builders.

Reads and writes stay unified here because both sides share the ``build_*``
helpers and ``refresh_settings``; splitting them would only add an import cycle.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from nova.config.service import (
    ConfigService,
    ConfigValidationError,
)
from nova.config.service import (
    McpServerConfig as ConfigMcpServerConfig,
)
from nova.config.service import (
    ModelCreateRequest as ConfigModelCreateRequest,
)
from nova.config.service import (
    ProviderCreateRequest as ConfigProviderCreateRequest,
)
from nova.mcp.manager import MCPManager
from nova.server.deps import get_settings, refresh_settings
from nova.registry.discovery import DiscoveryError, discover_models, resolve_base_url
from nova.server.schemas import (
    AvailableModelListResponse,
    McpServerCreateRequest,
    McpServerDeleteRequest,
    McpServerListResponse,
    McpServerRecord,
    McpServerUpdateRequest,
    McpSkippedTool,
    McpTestRequest,
    McpTestResponse,
    ModelCreateRequest,
    ModelDeleteRequest,
    ModelListResponse,
    ModelRecord,
    ModelUpdateRequest,
    ProviderCreateRequest,
    ProviderDeleteRequest,
    ProviderListResponse,
    ProviderPresetListResponse,
    ProviderPresetRecord,
    ProviderRecord,
    ProviderSyncResponse,
    ProviderUpdateRequest,
)
from nova.settings import Settings

router = APIRouter()


async def _sync_discovered_models(
    settings: Settings,
    *,
    provider_key: str,
    provider_type: str,
    base_url: str,
    api_key: str,
) -> str | None:
    """Pull the provider's catalogue into config.json.

    Returns a message when nothing was added, ``None`` on success. A provider
    that connected fine but could not be asked for its models must still exist:
    the failure belongs in a warning, not in a rolled-back write.
    """
    try:
        model_ids = await discover_models(
            provider_type=provider_type,
            base_url=resolve_base_url(provider_type, base_url),
            api_key=api_key,
        )
    except DiscoveryError as exc:
        return str(exc)
    if not model_ids:
        return "the provider listed no models"
    # The snapshot, not config.json: discovering a catalogue must not look like
    # the user configuring anything.
    from nova.registry.catalogue import record

    record(settings, provider_key, model_ids)
    return None


def build_model_list_response(settings: Settings) -> ModelListResponse:
    """Every selectable model, one contiguous block per provider.

    Contiguity matters to the clients: the pickers draw a header when the group
    changes, so a provider whose models arrived in two passes (configured, then
    discovered) would get its header twice and its rows scattered. One pass per
    provider keeps config order and makes the group label unique again.
    """
    from nova.llm.reasoning import resolve_effort_levels
    from nova.llm.tokenizer import resolve_context_window
    from nova.registry import catalogue as catalogue_module
    from nova.registry.catalogue import load as load_catalogue

    catalogue = load_catalogue(settings)
    facts_payload = load_catalogue(settings)
    items: list[ModelRecord] = []

    for provider_key, provider_config in settings.providers.items():
        configured: set[str] = set()
        for model_key, model_config in provider_config.models.items():
            configured.add(model_key)
            configured_name = str(model_config.get("name", "")).strip() or model_key
            if "tools" in model_config:
                tools_enabled = bool(model_config["tools"])
            elif "toolCalling" in model_config:
                tools_enabled = bool(model_config["toolCalling"])
            else:
                tools_enabled = True
            items.append(
                ModelRecord(
                    id=f"{provider_key}:{model_key}",
                    provider=provider_key,
                    provider_name=provider_config.name,
                    model=model_key,
                    label=configured_name,
                    tools=tools_enabled,
                    context=resolve_context_window(model_key, provider_key)[0],
                    efforts=resolve_effort_levels(
                        model_key,
                        provider_config.type,
                        model_config if isinstance(model_config, dict) else None,
                        catalogue_module.facts_for(
                            settings, provider_key, model_key, facts_payload
                        ),
                    ),
                )
            )

        # A model the provider advertises is selectable without being written
        # into config.json. A configured entry wins: it carries the label, the
        # tools flag and whatever limits the user pinned.
        for model_key, facts in catalogue.get(provider_key, {}).items():
            if model_key in configured:
                continue
            # The catalogue says this one cannot answer a chat turn: offering it
            # would be a picker entry that fails on the first message. A model
            # the user wrote into config is never hidden this way — that is a
            # declaration, not a suggestion.
            if isinstance(facts, dict) and facts.get("_hidden"):
                continue
            items.append(
                ModelRecord(
                    id=f"{provider_key}:{model_key}",
                    provider=provider_key,
                    provider_name=provider_config.name,
                    model=model_key,
                    label=model_key,
                    tools=True,
                    context=resolve_context_window(model_key, provider_key)[0],
                    efforts=resolve_effort_levels(
                        model_key,
                        provider_config.type,
                        None,
                        catalogue_module.facts_for(
                            settings, provider_key, model_key, facts_payload
                        ),
                    ),
                )
            )

    return ModelListResponse(items=items)


def build_provider_list_response(settings: Settings) -> ProviderListResponse:
    from nova.settings import _load_credentials

    credentials = _load_credentials(settings.home)
    items = [
        ProviderRecord(
            key=provider_key,
            name=provider_config.name,
            type=provider_config.type,
            base_url=str(provider_config.options.get("base_url", "") or ""),
            has_api_key=bool(provider_config.options.get("api_key")),
            authenticated=provider_key in credentials,
        )
        for provider_key, provider_config in settings.providers.items()
    ]
    return ProviderListResponse(items=items)


@router.get("/api/models", response_model=ModelListResponse)
async def models(settings: Settings = Depends(get_settings)) -> ModelListResponse:
    return build_model_list_response(settings)


@router.get("/api/providers", response_model=ProviderListResponse)
async def providers(settings: Settings = Depends(get_settings)) -> ProviderListResponse:
    return build_provider_list_response(settings)


@router.post("/api/registry/refresh", response_model=dict)
async def refresh_registry(
    settings: Settings = Depends(get_settings),
    force: bool = False,
) -> dict[str, int]:
    """Pull models.dev once: it feeds both the model facts and the presets.

    Called on every TUI launch, bounded by a daily cache so restarts are cheap.
    A failed fetch leaves both previous copies in place.
    """
    from nova.registry.catalogue import refresh_models_dev

    return {"facts": await refresh_models_dev(settings, force=force)}


@router.post("/api/providers/presets/refresh", response_model=dict)
async def refresh_provider_presets(
    settings: Settings = Depends(get_settings),
    force: bool = False,
) -> dict[str, int]:
    """Fetch the shared preset table, so a new vendor needs no release.

    Called on every TUI launch, but not forced: the cache decides whether that
    is a network request or not, so a fleet of restarts is one fetch a day.
    ``force=true`` is for a person who knows the table just changed.

    Bundled rows always win and a failed fetch changes nothing.
    """
    from nova.registry.presets import refresh

    added = await refresh(settings.home, force=force)
    return {"added": added}


@router.get(
    "/api/providers/{key}/available-models",
    response_model=AvailableModelListResponse,
)
async def available_models(
    key: str, settings: Settings = Depends(get_settings)
) -> AvailableModelListResponse:
    """Ask the provider what it serves. Nothing is stored and nothing is cached.

    The stored API key is used here rather than sent to the client, so the
    browser never sees a credential.
    """
    provider = settings.providers.get(key)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Provider '{key}' not found")
    try:
        items = await discover_models(
            provider_type=provider.type,
            base_url=resolve_base_url(
                provider.type, str(provider.options.get("base_url", "") or "")
            ),
            api_key=str(provider.options.get("api_key", "") or ""),
        )
    except DiscoveryError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return AvailableModelListResponse(provider=key, items=items)


@router.get("/api/providers/presets", response_model=ProviderPresetListResponse)
async def provider_presets(
    settings: Settings = Depends(get_settings),
) -> ProviderPresetListResponse:
    """What the add-provider form fills in when a vendor is picked."""
    from nova.registry.presets import load

    return ProviderPresetListResponse(
        items=[
            ProviderPresetRecord(
                id=preset.id,
                label=preset.label,
                type=preset.type,
                base_url=preset.base_url,
                key_env=preset.key_env,
                note=preset.note,
            )
            for preset in load(settings.home)
        ]
    )


@router.post("/api/config/providers", response_model=ModelListResponse)
async def add_provider(
    body: ProviderCreateRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
) -> ModelListResponse:
    # Ask the provider before saving anything. A key it rejects is a definite
    # no, and writing it first would leave a broken provider behind that the
    # user has to find and delete. Every other failure — unreachable host, no
    # /models endpoint, an empty catalogue — is not evidence about the key, so
    # those still save and only produce a warning.
    discovered = []
    warning: str | None = None
    try:
        discovered = await discover_models(
            provider_type=body.type,
            base_url=resolve_base_url(body.type, body.base_url),
            api_key=body.api_key,
        )
    except DiscoveryError as exc:
        if exc.status in (401, 403):
            raise HTTPException(
                status_code=401,
                detail=f"the provider rejected this API key: {exc}",
            ) from exc
        warning = str(exc)

    service = ConfigService(settings)
    try:
        service.add_provider(
            ConfigProviderCreateRequest(
                key=body.key,
                provider_type=body.type,
                name=body.name,
                base_url=body.base_url,
                api_key=body.api_key,
            )
        )
    except ConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Connecting a provider is the whole action: whatever it advertises becomes
    # selectable, so no second step is needed to make a model usable.
    if discovered:
        from nova.registry.catalogue import record

        record(settings, body.key, discovered)
    elif warning is None:
        warning = "the provider listed no models"

    response = build_model_list_response(refresh_settings(http_request))
    return response.model_copy(update={"warning": warning})


@router.post("/api/providers/sync-models", response_model=ProviderSyncResponse)
async def sync_all_provider_models(
    settings: Settings = Depends(get_settings),
) -> ProviderSyncResponse:
    """Refresh every provider's catalogue, the way a new session starts.

    Sequential on purpose: a handful of providers, one request each, and a
    failure on one must not cost the others their refresh. Never raises — the
    caller used this to make the model list fresher, not to learn that a
    provider is down.
    """
    from nova.registry.catalogue import record
    from nova.settings import _load_credentials

    credentials = _load_credentials(settings.home)
    synced: list[str] = []
    failed: dict[str, str] = {}
    for provider_key, provider in settings.providers.items():
        # A provider whose key lives in config.json was authored by hand. Its
        # model list is its owner's declaration, not something to poll: the
        # per-provider endpoint stays available for a manual refresh.
        if provider_key not in credentials:
            continue
        try:
            model_ids = await discover_models(
                provider_type=provider.type,
                base_url=resolve_base_url(
                    provider.type, str(provider.options.get("base_url", "") or "")
                ),
                api_key=str(provider.options.get("api_key", "") or ""),
            )
        except DiscoveryError as exc:
            failed[provider_key] = str(exc)
            continue
        if model_ids:
            record(settings, provider_key, model_ids)
            synced.append(provider_key)
        else:
            failed[provider_key] = "the provider listed no models"
    return ProviderSyncResponse(synced=synced, failed=failed)


@router.post(
    "/api/config/providers/{key}/sync-models", response_model=ModelListResponse
)
async def sync_provider_models(
    key: str,
    http_request: Request,
    settings: Settings = Depends(get_settings),
) -> ModelListResponse:
    """Re-read an existing provider's catalogue, e.g. after pulling a new model."""
    provider = settings.providers.get(key)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Provider '{key}' not found")
    warning = await _sync_discovered_models(
        settings,
        provider_key=key,
        provider_type=provider.type,
        base_url=str(provider.options.get("base_url", "") or ""),
        api_key=str(provider.options.get("api_key", "") or ""),
    )
    response = build_model_list_response(refresh_settings(http_request))
    return response.model_copy(update={"warning": warning})


@router.post("/api/config/models", response_model=ModelListResponse)
async def add_model(
    body: ModelCreateRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
) -> ModelListResponse:
    service = ConfigService(settings)
    try:
        service.add_model(
            ConfigModelCreateRequest(
                provider=body.provider,
                model=body.model,
                label=body.label,
                tools=body.tools,
            )
        )
    except ConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_model_list_response(refresh_settings(http_request))


@router.post("/api/config/providers/update", response_model=ModelListResponse)
async def update_provider(
    body: ProviderUpdateRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
) -> ModelListResponse:
    service = ConfigService(settings)
    try:
        service.update_provider(
            body.key,
            name=body.name,
            provider_type=body.type,
            base_url=body.base_url,
            api_key=body.api_key,
        )
    except ConfigValidationError as exc:
        message = str(exc)
        if "does not exist" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    return build_model_list_response(refresh_settings(http_request))


@router.post("/api/config/providers/delete", response_model=ModelListResponse)
async def delete_provider(
    body: ProviderDeleteRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
) -> ModelListResponse:
    service = ConfigService(settings)
    try:
        service.delete_provider(body.key)
    except ConfigValidationError as exc:
        message = str(exc)
        if "does not exist" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    return build_model_list_response(refresh_settings(http_request))


@router.post("/api/config/models/update", response_model=ModelListResponse)
async def update_model(
    body: ModelUpdateRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
) -> ModelListResponse:
    service = ConfigService(settings)
    try:
        service.update_model(
            body.provider,
            body.model,
            label=body.label,
            tools=body.tools,
        )
    except ConfigValidationError as exc:
        message = str(exc)
        if "does not exist" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    return build_model_list_response(refresh_settings(http_request))


@router.post("/api/config/models/delete", response_model=ModelListResponse)
async def delete_model(
    body: ModelDeleteRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
) -> ModelListResponse:
    service = ConfigService(settings)
    try:
        service.delete_model(body.provider, body.model)
    except ConfigValidationError as exc:
        message = str(exc)
        if "does not exist" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    return build_model_list_response(refresh_settings(http_request))


# ── MCP servers ──────────────────────────────────────────────────────
#
# A change here reaches a running agent on the next restart, not sooner (the MCP
# manager connects its servers once at startup). The /test route is what makes
# that acceptable: it connects the config as given, right now, so a user knows a
# server is reachable before committing it and waiting for the restart.


def _transport_of(payload: dict) -> str:
    return "http" if "url" in payload else "stdio"


async def _apply_mcp_change(http_request: Request) -> McpServerListResponse:
    """Reflect a just-written config in the running process, then return the list.

    Three steps, in an order that is not interchangeable. The config is reloaded
    first, because the MCP manager reads the cached settings and would otherwise
    reconnect with the servers this change exists to replace. The manager then
    reconnects, and the toolset cache is dropped with it -- a cached registry
    still holds the tools of the servers as they were, and it is keyed on the
    agent and model rather than on the MCP config, so nothing else would ever
    clear it.

    The effect is that the change is live for the next message in any session,
    including one already open, which is why the settings UI no longer tells the
    user to restart.
    """
    from nova.app.runtime import reload_mcp_servers

    refreshed = refresh_settings(http_request)
    await reload_mcp_servers()
    return await build_mcp_list_response(refreshed)


async def build_mcp_list_response(settings: Settings) -> McpServerListResponse:
    """The configured servers, read fresh, with secret values withheld.

    Carries what the *agent* can reach from each server alongside what the server
    advertised, because the two can differ and the connection test only ever
    showed the second. A tool that connected fine and is nonetheless unreachable
    is otherwise indistinguishable from a model that simply chose not to call it.
    """
    service = ConfigService(settings)
    manager = MCPManager.get_shared()
    # Connecting here is what makes the load report meaningful: without it the
    # manager has never looked at the servers, and the page would say "unknown"
    # about the very thing it opened to find out. Idempotent and lock-guarded, so
    # the first agent to start pays nothing for having gone second.
    await manager.ensure_initialized()
    report = {entry.server: entry for entry in manager.load_report()}
    items: list[McpServerRecord] = []
    for name, payload in service.list_mcp_servers().items():
        if not isinstance(payload, dict):
            continue
        env_value = payload.get("env")
        env = env_value if isinstance(env_value, dict) else {}
        headers_value = payload.get("headers")
        headers = headers_value if isinstance(headers_value, dict) else {}
        loaded = report.get(name)
        items.append(
            McpServerRecord(
                name=name,
                transport=_transport_of(payload),
                command=str(payload.get("command", "")),
                args=[str(a) for a in payload.get("args", []) or []],
                url=str(payload.get("url", "")),
                env_keys=list(env.keys()),
                header_keys=list(headers.keys()),
                # Absent before an agent has built a toolset, which is not the
                # same as zero: nothing has looked yet.
                loaded_tools=list(loaded.names) if loaded else None,
                # None unless the server could not be reached, so the UI can treat
                # "no error" and "not looked yet" as different states.
                error=(loaded.error or None) if loaded else None,
                skipped_tools=(
                    [McpSkippedTool(**entry) for entry in loaded.skipped]
                    if loaded
                    else None
                ),
            )
        )
    items.sort(key=lambda record: record.name)
    return McpServerListResponse(items=items)


def _config_of(body: McpServerCreateRequest, name: str) -> ConfigMcpServerConfig:
    return ConfigMcpServerConfig(
        name=name,
        command=body.command,
        args=tuple(body.args),
        env=tuple((pair.key, pair.value) for pair in body.env),
        url=body.url,
        headers=tuple((pair.key, pair.value) for pair in body.headers),
    )


@router.get("/api/mcp-servers", response_model=McpServerListResponse)
async def mcp_servers(
    settings: Settings = Depends(get_settings),
) -> McpServerListResponse:
    return await build_mcp_list_response(settings)


@router.post("/api/config/mcp/add", response_model=McpServerListResponse)
async def add_mcp_server(
    body: McpServerCreateRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
) -> McpServerListResponse:
    service = ConfigService(settings)
    try:
        service.add_mcp_server(_config_of(body, body.name))
    except ConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _apply_mcp_change(http_request)


@router.post("/api/config/mcp/update", response_model=McpServerListResponse)
async def update_mcp_server(
    body: McpServerUpdateRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
) -> McpServerListResponse:
    service = ConfigService(settings)
    try:
        service.update_mcp_server(body.original_name, _config_of(body, body.name))
    except ConfigValidationError as exc:
        message = str(exc)
        if "does not exist" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    return await _apply_mcp_change(http_request)


@router.post("/api/config/mcp/delete", response_model=McpServerListResponse)
async def delete_mcp_server(
    body: McpServerDeleteRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
) -> McpServerListResponse:
    service = ConfigService(settings)
    try:
        service.delete_mcp_server(body.name)
    except ConfigValidationError as exc:
        message = str(exc)
        if "does not exist" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    return await _apply_mcp_change(http_request)


@router.post("/api/config/mcp/test", response_model=McpTestResponse)
async def test_mcp_server(body: McpTestRequest) -> McpTestResponse:
    """Connect the given config now and report what it offered.

    Validation first, so an obviously malformed config fails fast with a clear
    message rather than a transport error; then the real connection, which is the
    only honest test of reachability. Nothing is written -- a test is a question,
    not a save.
    """
    from nova.config.service import validate_mcp_config
    from nova.mcp import probe_mcp_server

    try:
        config = validate_mcp_config(_config_of(body, body.name or "probe"))
    except ConfigValidationError as exc:
        return McpTestResponse(ok=False, error=str(exc))
    result = await probe_mcp_server(config.to_payload())
    return McpTestResponse(
        ok=result.ok,
        server_name=result.server_name,
        server_version=result.server_version,
        tool_count=result.tool_count,
        tool_names=result.tool_names,
        error=result.error,
    )
