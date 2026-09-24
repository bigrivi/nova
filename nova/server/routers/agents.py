"""Agent configuration routes."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nova.config.agent_import import (
    AgentImportError,
    parse_agent_markdown,
    slugify_key,
)
from nova.config.service import AgentCreateRequest, ConfigService
from nova.constants import DEFAULT_AGENT_KEY
from nova.server.deps import get_settings
from nova.settings import Settings

router = APIRouter()

_AGENT_KEY_PATTERN = re.compile(r"^[a-z0-9-]{3,32}$")


class AgentImportRequest(BaseModel):
    content: str
    key: str | None = None
    parent_ids: list[str] | None = None


def _annotate(agent: dict, parents: list[str] | None = None) -> dict:
    mode = agent.get("mode") or "primary"
    is_sub = mode == "subagent"
    kind = "sub" if is_sub else "main"
    editable_fields = ["name", "description", "provider", "model", "tools", "mode"]
    if is_sub:
        editable_fields += ["posture", "parents"]
    result = {**agent, "mode": mode, "kind": kind, "editable_fields": editable_fields}
    result["parents"] = parents if parents is not None else []
    return result


@router.get("/api/agents")
async def list_agents(settings: Settings = Depends(get_settings)):
    service = ConfigService(settings)
    agents = await service.list_agents()
    items = [
        _annotate(agent, await service.get_agent_parents(agent["key"]))
        for agent in agents
    ]
    return {"items": items}


@router.get("/api/agents/{key}")
async def get_agent(key: str, settings: Settings = Depends(get_settings)):
    service = ConfigService(settings)
    agent = await service.get_agent(key)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{key}' not found")
    return _annotate(agent, await service.get_agent_parents(key))


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
    return _annotate(agent, await service.get_agent_parents(body.key))


@router.post("/api/agents/import")
async def import_agent(
    body: AgentImportRequest, settings: Settings = Depends(get_settings)
):
    try:
        parsed = parse_agent_markdown(body.content)
    except AgentImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    key = slugify_key(body.key or parsed.name)
    if not _AGENT_KEY_PATTERN.match(key):
        raise HTTPException(
            status_code=400,
            detail=(
                "Could not derive a valid agent key (3-32 chars [a-z0-9-]); "
                "pass an explicit key."
            ),
        )

    service = ConfigService(settings)
    if await service.get_agent(key):
        raise HTTPException(status_code=409, detail=f"Agent '{key}' already exists")

    request = AgentCreateRequest(
        key=key,
        name=parsed.name or key,
        description=parsed.description,
        model=parsed.model,
        provider=parsed.provider,
        tools=None,
        posture=parsed.posture,
        mode=parsed.mode,
        parent_ids=body.parent_ids or None,
    )
    agent_dir = settings.home / "agents" / key
    agent_dir.mkdir(parents=True, exist_ok=True)
    agent = await service.save_agent(request)

    warnings = list(parsed.warnings)
    if parsed.body.strip():
        (agent_dir / "IDENTITY.md").write_text(
            parsed.body.rstrip() + "\n", encoding="utf-8"
        )
    else:
        warnings.append("No prompt body found; the agent uses the default identity.")
    if not parsed.model or not parsed.provider:
        warnings.append("No model/provider set; choose one before chatting.")

    annotated = _annotate(agent, await service.get_agent_parents(key))
    return {"agent": annotated, "warnings": warnings}


@router.put("/api/agents/{key}/parents")
async def set_agent_parents(
    key: str, body: dict, settings: Settings = Depends(get_settings)
):
    service = ConfigService(settings)
    if await service.get_agent(key) is None:
        raise HTTPException(status_code=404, detail=f"Agent '{key}' not found")
    parents = body.get("parents")
    if not isinstance(parents, list) or any(not isinstance(p, str) for p in parents):
        raise HTTPException(status_code=400, detail="parents must be a list of agent keys")
    if key in parents:
        raise HTTPException(status_code=400, detail="An agent cannot be its own parent")
    await service.set_agent_parents(key, parents)
    return {"status": "ok", "key": key, "parents": parents}


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
