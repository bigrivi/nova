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
from nova.server.deps import get_settings, refresh_settings
from nova.server.schemas import (
    McpServerCreateRequest,
    McpServerDeleteRequest,
    McpServerListResponse,
    McpServerRecord,
    McpServerUpdateRequest,
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
    ProviderRecord,
    ProviderUpdateRequest,
)
from nova.settings import Settings

router = APIRouter()


def build_model_list_response(settings: Settings) -> ModelListResponse:
    from nova.llm.reasoning import resolve_effort_levels

    items: list[ModelRecord] = []
    for provider_key, provider_config in settings.providers.items():
        for model_key, model_config in provider_config.models.items():
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
                    efforts=resolve_effort_levels(
                        model_key,
                        provider_config.type,
                        model_config if isinstance(model_config, dict) else None,
                    ),
                )
            )
    return ModelListResponse(items=items)


def build_provider_list_response(settings: Settings) -> ProviderListResponse:
    items = [
        ProviderRecord(
            key=provider_key,
            name=provider_config.name,
            type=provider_config.type,
            base_url=str(provider_config.options.get("base_url", "") or ""),
            has_api_key=bool(provider_config.options.get("api_key")),
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


@router.post("/api/config/providers", response_model=ModelListResponse)
async def add_provider(
    body: ProviderCreateRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
) -> ModelListResponse:
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
    return build_model_list_response(refresh_settings(http_request))


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


def build_mcp_list_response(settings: Settings) -> McpServerListResponse:
    """The configured servers, read fresh, with secret values withheld."""
    service = ConfigService(settings)
    items: list[McpServerRecord] = []
    for name, payload in service.list_mcp_servers().items():
        if not isinstance(payload, dict):
            continue
        env_value = payload.get("env")
        env = env_value if isinstance(env_value, dict) else {}
        headers_value = payload.get("headers")
        headers = headers_value if isinstance(headers_value, dict) else {}
        items.append(
            McpServerRecord(
                name=name,
                transport=_transport_of(payload),
                command=str(payload.get("command", "")),
                args=[str(a) for a in payload.get("args", []) or []],
                url=str(payload.get("url", "")),
                env_keys=list(env.keys()),
                header_keys=list(headers.keys()),
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
    return build_mcp_list_response(settings)


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
    return build_mcp_list_response(refresh_settings(http_request))


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
    return build_mcp_list_response(refresh_settings(http_request))


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
    return build_mcp_list_response(refresh_settings(http_request))


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
