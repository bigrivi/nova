"""Import one agent definition into the catalog.

One implementation, two front doors: ``POST /api/agents/import`` and
``nova agent-import``. Key derivation, conflict policy, what lands on disk, and
the warning list have to agree between them, so none of that lives in the route
or in the CLI.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from nova.config.agent_import import (
    AGENT_KEY_RE,
    AgentImportError,
    ParsedAgent,
    parse_agent_markdown,
    slugify_key,
)
from nova.config.service import AgentCreateRequest, ConfigService
from nova.settings import Settings


class AgentKeyError(AgentImportError):
    """The definition (or the caller's key) does not yield a usable agent key."""


class AgentExistsError(RuntimeError):
    """An agent with that key exists and the caller did not ask to replace it."""


@dataclass
class ImportOutcome:
    """What an import did, or would do for a dry run.

    Attributes:
        key: The agent key the definition maps to.
        agent: The row that was written (or would be).
        warnings: Everything the definition lost in translation.
        written: False for a dry run.
        replaced: True when an existing agent was overwritten.
    """

    key: str
    agent: dict
    warnings: list[str] = field(default_factory=list)
    written: bool = True
    replaced: bool = False


async def import_agent_definition(
    service: ConfigService,
    settings: Settings,
    *,
    content: str,
    source_name: str = "",
    key: str | None = None,
    parent_ids: list[str] | None = None,
    provider: str | None = None,
    model: str | None = None,
    update: bool = False,
    dry_run: bool = False,
) -> ImportOutcome:
    """Parse *content* and write the agent row plus its ``IDENTITY.md``.

    Args:
        service: Catalog service; the caller decides which database it points at.
        settings: Settings, for the agent directory under ``home``.
        content: The Markdown definition.
        source_name: File stem, used as the name when the frontmatter has none
            (opencode takes the agent name from the file name).
        key: Explicit key; otherwise derived from the name.
        parent_ids: Primary agents to attach; supplying any makes this a
            sub-agent. Keys that do not exist are dropped with a warning.
        provider: Provider override. A definition's model alias (``sonnet``)
            cannot be resolved without the local provider list, so the caller
            supplies the pair.
        model: Model override.
        update: Replace an existing agent instead of refusing.
        dry_run: Parse and resolve only; touches neither the database nor disk.

    Returns:
        The outcome, including the warnings the definition produced.

    Raises:
        AgentImportError: The Markdown cannot be parsed.
        AgentKeyError: The derived or supplied key is not a valid agent key.
        AgentExistsError: The key is taken and *update* is False.
    """
    parsed = parse_agent_markdown(content)
    if model or provider:
        # Explicit values win over the definition.
        parsed = replace(
            parsed,
            model=model or parsed.model,
            provider=provider or parsed.provider,
        )
    derived = (key or slugify_key(parsed.name or source_name)).strip()
    if not AGENT_KEY_RE.match(derived):
        raise AgentKeyError(
            f"'{derived}' is not a valid agent key (3-32 chars of [a-z0-9-]); "
            "pass an explicit key."
        )

    existing = await service.get_agent(derived)
    if existing is not None and not update:
        raise AgentExistsError(f"Agent '{derived}' already exists")

    warnings = list(parsed.warnings)
    resolved_parents, parent_warnings = await _resolve_parents(
        service, parent_ids or []
    )
    warnings.extend(parent_warnings)
    if not parsed.body.strip():
        if existing is None:
            warnings.append(
                "No prompt body found; the agent uses the default identity."
            )
        else:
            warnings.append("No prompt body found; the existing IDENTITY.md is kept.")
    if not parsed.model:
        warnings.append("No model/provider set; choose one before chatting.")
    elif not parsed.provider:
        warnings.append("No provider set for the model; pass --provider.")

    agent = await _write_agent(
        service,
        settings,
        parsed=parsed,
        key=derived,
        source_name=source_name,
        existing=existing,
        parent_ids=resolved_parents or None,
        dry_run=dry_run,
    )
    return ImportOutcome(
        key=derived,
        agent=agent,
        warnings=warnings,
        written=not dry_run,
        replaced=existing is not None,
    )


async def _resolve_parents(
    service: ConfigService, parents: list[str]
) -> tuple[list[str], list[str]]:
    """Keep the parent keys that exist; a typo must not create a dangling link."""
    kept: list[str] = []
    warnings: list[str] = []
    for parent in parents:
        if await service.get_agent(parent) is None:
            warnings.append(f"Unknown parent agent '{parent}'; ignored.")
            continue
        kept.append(parent)
    return kept, warnings


async def _write_agent(
    service: ConfigService,
    settings: Settings,
    *,
    parsed: ParsedAgent,
    key: str,
    source_name: str,
    existing: dict | None,
    parent_ids: list[str] | None,
    dry_run: bool,
) -> dict:
    """Persist (or describe) the row, merging an update over the current one."""
    name = parsed.name or (existing or {}).get("name") or key
    description = parsed.description or (existing or {}).get("description", "")
    if existing is None:
        request = AgentCreateRequest(
            key=key,
            name=name,
            description=description,
            model=parsed.model,
            provider=parsed.provider,
            posture=parsed.posture,
            mode=parsed.mode,
            parent_ids=parent_ids or None,
        )
        if dry_run:
            return _describe(request, existing=None)
        agent = await service.save_agent(request)
        _write_identity(settings, key, parsed.body)
        return agent

    # `save_agent` writes every column, so an update built only from the
    # definition would erase what it does not mention: the tool allowlist, the
    # workspace, the reasoning level, and a sub-agent's mode.
    merged = {
        **existing,
        "name": name,
        "description": description,
        "model": parsed.model or existing.get("model", ""),
        "provider": parsed.provider or existing.get("provider", ""),
        "posture": parsed.posture,
        "mode": "subagent" if parent_ids else existing.get("mode", "primary"),
        "updated_at": int(time.time() * 1000),
    }
    if dry_run:
        return merged
    await service.save_agent_record(merged)
    if parent_ids:
        await service.set_agent_parents(key, parent_ids)
    _write_identity(settings, key, parsed.body, keep_existing_if_empty=True)
    return merged


def _describe(request: AgentCreateRequest, existing: dict | None) -> dict:
    """The row a dry run would write, in the shape the API returns."""
    return {
        "key": request.key,
        "name": request.name,
        "description": request.description,
        "model": request.model,
        "provider": request.provider,
        "tools": None,
        "workspace_dir": None,
        "mode": "subagent" if request.parent_ids else request.mode,
        "posture": request.posture,
        "parents": list(request.parent_ids or []),
    }


def _write_identity(
    settings: Settings,
    key: str,
    body: str,
    *,
    keep_existing_if_empty: bool = False,
) -> None:
    """Write the persona next to the row; an empty body keeps the old file."""
    if not body.strip() and keep_existing_if_empty:
        return
    agent_dir: Path = settings.home / "agents" / key
    agent_dir.mkdir(parents=True, exist_ok=True)
    if body.strip():
        (agent_dir / "IDENTITY.md").write_text(body.rstrip() + "\n", encoding="utf-8")
