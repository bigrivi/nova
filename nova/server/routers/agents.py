"""Agent configuration routes."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException

from nova.config.service import AgentCreateRequest, ConfigService
from nova.constants import DEFAULT_AGENT_KEY
from nova.server.deps import get_settings
from nova.settings import Settings

router = APIRouter()

_AGENT_KEY_PATTERN = re.compile(r"^[a-z0-9-]{3,32}$")


@router.get("/api/agents")
async def list_agents(settings: Settings = Depends(get_settings)):
    service = ConfigService(settings)
    agents = await service.list_agents()
    return {"items": agents}


@router.get("/api/agents/{key}")
async def get_agent(key: str, settings: Settings = Depends(get_settings)):
    service = ConfigService(settings)
    agent = await service.get_agent(key)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{key}' not found")
    return agent


@router.post("/api/agents")
async def create_agent(
    body: AgentCreateRequest, settings: Settings = Depends(get_settings)
):
    if not _AGENT_KEY_PATTERN.match(body.key):
        raise HTTPException(
            status_code=400, detail="Agent key must be 3-32 chars: [a-z0-9-]"
        )
    service = ConfigService(settings)
    existing = await service.get_agent(body.key)
    if existing:
        raise HTTPException(
            status_code=409, detail=f"Agent '{body.key}' already exists"
        )
    agent_dir = settings.home / "agents" / body.key
    agent_dir.mkdir(parents=True, exist_ok=True)
    agent = await service.save_agent(body)
    return agent


@router.delete("/api/agents/{key}")
async def delete_agent(key: str, settings: Settings = Depends(get_settings)):
    if key == DEFAULT_AGENT_KEY:
        raise HTTPException(
            status_code=400, detail=f"Cannot delete '{DEFAULT_AGENT_KEY}' agent"
        )
    service = ConfigService(settings)
    deleted = await service.delete_agent(key)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Agent '{key}' not found")
    return {"status": "deleted", "key": key}


@router.patch("/api/agents/{key}")
async def update_agent(
    key: str, body: dict, settings: Settings = Depends(get_settings)
):
    service = ConfigService(settings)
    model = body.get("model")
    provider = body.get("provider")
    if not model or not provider:
        raise HTTPException(status_code=400, detail="model and provider are required")
    agent = await service.update_agent_model(key, model, provider)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{key}' not found")
    return agent
