"""Model and provider config: reads, mutations, and response builders.

Reads and writes stay unified here because both sides share the ``build_*``
helpers and ``refresh_settings``; splitting them would only add an import cycle.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Request

from nova.config.service import (
    ConfigNotFound,
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
from nova.registry.discovery import (
    DiscoveredModel,
    DiscoveryError,
    discover_models,
    resolve_base_url,
)
from nova.server.deps import get_settings, refresh_settings
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


def _mutated(http_request: Request, change: Callable[[], object]) -> ModelListResponse:
    """Run a config change, then answer with the list as it now stands.

    Two rules every mutating route used to repeat: a refused change is a 400 or
    a 404 depending on what it was, and the list has to be read after the
    settings reload — never before. Both live here so a route is a mapping.
    """
    try:
        change()
    except ConfigNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_model_list_response(refresh_settings(http_request))


def _user_agent_of(options: dict) -> str | None:
    """The identity this provider expects, when it is not Nova's own."""
    value = str(options.get("user_agent") or "").strip()
    return value or None


async def _sync_discovered_models(
    settings: Settings,
    *,
    provider_key: str,
    provider_type: str,
    base_url: str,
    api_key: str,
    user_agent: str | None = None,
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
            user_agent=user_agent,
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
    """The wire form of what the picker may offer; the policy lives in the registry."""
    from nova.registry.selection import selectable_models

    return ModelListResponse(
        items=[
            ModelRecord(
                id=f"{row.provider}:{row.model}",
                provider=row.provider,
                provider_name=row.provider_name,
                model=row.model,
                label=row.label,
                tools=row.tools,
                context=row.context,
                efforts=row.efforts,
            )
            for row in selectable_models(settings)
        ]
    )


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
    """Pull models.dev once: it feeds both the model specs and the presets.

    Called on every TUI launch, bounded by a daily cache so restarts are cheap.
    A failed fetch leaves both previous copies in place.
    """
    from nova.registry.catalogue import refresh_models_dev

    return {"rows": await refresh_models_dev(settings, force=force)}


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
    if not provider.pollable:
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{key}' is a custom endpoint: Nova does not read its model "
                "list. Add the models you use under this provider instead."
            ),
        )
    try:
        items = await discover_models(
            provider_type=provider.type,
            base_url=resolve_base_url(
                provider.type, str(provider.options.get("base_url", "") or "")
            ),
            api_key=str(provider.options.get("api_key", "") or ""),
            user_agent=_user_agent_of(provider.options),
        )
    except DiscoveryError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return AvailableModelListResponse(provider=key, items=items)


@router.get("/api/providers/presets", response_model=ProviderPresetListResponse)
async def provider_presets(
    settings: Settings = Depends(get_settings),
) -> ProviderPresetListResponse:
    """What the add-provider form fills in when a vendor is picked.

    Also carries the endpoints the user declared themselves. They are not
    presets — Nova knows nothing about them — but the form has to list them or
    the only way back to one would be editing config.json by hand.
    """
    from nova.registry.presets import load

    presets = load(settings.home)
    known = {preset.id for preset in presets}
    items = [
        ProviderPresetRecord(
            id=preset.id,
            label=preset.label,
            type=preset.type,
            base_url=preset.base_url,
            key_env=preset.key_env,
            note=preset.note,
        )
        for preset in presets
    ]
    for key, provider in settings.providers.items():
        if key in known:
            continue
        items.append(
            ProviderPresetRecord(
                id=key,
                label=provider.name,
                type=provider.type,
                base_url=str(provider.options.get("base_url", "") or ""),
                key_env=None,
                custom=True,
            )
        )
    return ProviderPresetListResponse(items=items)


async def _probe(
    body: ProviderCreateRequest, extra: dict
) -> tuple[list[DiscoveredModel], str | None]:
    """Ask a vendor what it serves, before anything is written.

    A key it rejects is a definite no: saving first would leave a broken
    provider behind for the user to find and delete. Every other failure —
    unreachable host, no ``/models`` endpoint, an empty catalogue — is not
    evidence about the key, so it becomes a warning and the provider still saves.
    """
    try:
        discovered = await discover_models(
            provider_type=body.type,
            base_url=resolve_base_url(body.type, body.base_url),
            api_key=body.api_key,
            # A gateway that fingerprints clients must see the same identity on
            # the probe as on every later request.
            user_agent=_user_agent_of(extra),
        )
    except DiscoveryError as exc:
        if exc.status in (401, 403):
            # The provider's own words, not a guess about which field it
            # disliked: a 401 can be a bad key or a client it will not serve.
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return [], str(exc)
    return discovered, None


@router.post("/api/config/providers", response_model=ModelListResponse)
async def add_provider(
    body: ProviderCreateRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
) -> ModelListResponse:
    extra = dict(body.options or {})
    # A custom endpoint is the user's own declaration, so it is not polled: its
    # models are added by hand. The flag is the whole rule; see ProviderConfig.
    discovered, warning = ([], None) if body.custom else await _probe(body, extra)

    service = ConfigService(settings)
    try:
        service.add_provider(
            ConfigProviderCreateRequest(
                key=body.key,
                provider_type=body.type,
                name=body.name,
                base_url=body.base_url,
                api_key=body.api_key,
                custom=body.custom,
            ),
            extra_options=extra,
        )
    except ConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Connecting a provider is the whole action: whatever it advertises becomes
    # selectable, so no second step is needed to make a model usable.
    if discovered:
        from nova.registry.catalogue import record

        record(settings, body.key, discovered)
    elif warning is None and not body.custom:
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
        # A custom endpoint is the user's own declaration, not a catalogue:
        # whatever it lists is a snapshot someone else publishes, and nothing
        # promised this endpoint even has one. A config entry Nova did not
        # write a key for is authored by hand and equally not ours to poll.
        if not provider.pollable or provider_key not in credentials:
            continue
        try:
            model_ids = await discover_models(
                provider_type=provider.type,
                base_url=resolve_base_url(
                    provider.type, str(provider.options.get("base_url", "") or "")
                ),
                api_key=str(provider.options.get("api_key", "") or ""),
                user_agent=_user_agent_of(provider.options),
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
    """Re-read an existing provider's catalogue, e.g. after pulling a new model.

    Refused for a custom endpoint: its model list is the user's declaration, and
    nothing promised it serves one at all.
    """
    provider = settings.providers.get(key)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Provider '{key}' not found")
    if not provider.pollable:
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{key}' is a custom endpoint: Nova does not read its model "
                "list. Add the models you use under this provider instead."
            ),
        )
    warning = await _sync_discovered_models(
        settings,
        provider_key=key,
        provider_type=provider.type,
        base_url=str(provider.options.get("base_url", "") or ""),
        api_key=str(provider.options.get("api_key", "") or ""),
        user_agent=_user_agent_of(provider.options),
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
    return _mutated(
        http_request,
        lambda: service.add_model(
            ConfigModelCreateRequest(
                provider=body.provider,
                model=body.model,
                label=body.label,
                tools=body.tools,
            )
        ),
    )


@router.post("/api/config/providers/update", response_model=ModelListResponse)
async def update_provider(
    body: ProviderUpdateRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
) -> ModelListResponse:
    service = ConfigService(settings)
    return _mutated(
        http_request,
        lambda: service.update_provider(
            body.key,
            name=body.name,
            provider_type=body.type,
            base_url=body.base_url,
            api_key=body.api_key,
        ),
    )


@router.post("/api/config/providers/delete", response_model=ModelListResponse)
async def delete_provider(
    body: ProviderDeleteRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
) -> ModelListResponse:
    service = ConfigService(settings)
    return _mutated(http_request, lambda: service.delete_provider(body.key))


@router.post("/api/config/models/update", response_model=ModelListResponse)
async def update_model(
    body: ModelUpdateRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
) -> ModelListResponse:
    service = ConfigService(settings)
    return _mutated(
        http_request,
        lambda: service.update_model(
            body.provider,
            body.model,
            label=body.label,
            tools=body.tools,
        ),
    )


@router.post("/api/config/models/delete", response_model=ModelListResponse)
async def delete_model(
    body: ModelDeleteRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
) -> ModelListResponse:
    service = ConfigService(settings)
    return _mutated(
        http_request, lambda: service.delete_model(body.provider, body.model)
    )


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
