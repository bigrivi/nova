"""Model and provider config: reads, mutations, and response builders.

Reads and writes stay unified here because both sides share the ``build_*``
helpers and ``refresh_settings``; splitting them would only add an import cycle.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from nova.config.service import (
    ConfigService,
    ConfigValidationError,
    ModelCreateRequest as ConfigModelCreateRequest,
    ProviderCreateRequest as ConfigProviderCreateRequest,
)
from nova.server.deps import get_settings, refresh_settings
from nova.server.schemas import (
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
