"""Importing an agent definition, independent of the door it came through."""

from __future__ import annotations

import contextlib
import io
import json

import pytest

from nova.app import console
from nova.config.agent_import_service import (
    AgentExistsError,
    AgentKeyError,
    import_agent_definition,
)
from nova.config.service import ConfigService
from nova.db import database as db_module
from nova.db.config import DatabaseConfig
from nova.db.sqlite_repository import SqliteRepository
from nova.settings import get_settings

DEFINITION = """\
---
name: Code Reviewer
description: Reviews diffs for defects.
tools: Read, Grep, Glob
model: acme/reviewer-1
---

You review code.
"""


@contextlib.asynccontextmanager
async def _catalog():
    database = SqliteRepository(DatabaseConfig(path=":memory:"))
    await database.connect()
    previous = db_module._db
    db_module._db = database
    try:
        settings = get_settings()
        yield ConfigService(settings), settings
    finally:
        await database.close()
        db_module._db = previous


@pytest.mark.asyncio
async def test_import_writes_the_row_and_the_persona() -> None:
    async with _catalog() as (service, settings):
        outcome = await import_agent_definition(
            service, settings, content=DEFINITION, source_name="reviewer.md"
        )

        assert outcome.written is True
        assert outcome.replaced is False
        assert outcome.key == "code-reviewer"
        agent = await service.get_agent("code-reviewer")
        assert agent is not None
        assert agent["model"] == "reviewer-1"
        assert agent["provider"] == "acme"
        assert agent["posture"] == "read_only"
        assert agent["mode"] == "primary"
        identity = settings.home / "agents" / "code-reviewer" / "IDENTITY.md"
        assert identity.read_text(encoding="utf-8").strip() == "You review code."


@pytest.mark.asyncio
async def test_a_dry_run_touches_neither_catalog_nor_disk() -> None:
    async with _catalog() as (service, settings):
        outcome = await import_agent_definition(
            service, settings, content=DEFINITION, dry_run=True
        )

        assert outcome.written is False
        assert await service.get_agent(outcome.key) is None
        assert not (settings.home / "agents" / outcome.key).exists()


@pytest.mark.asyncio
async def test_an_existing_key_is_refused_without_update() -> None:
    async with _catalog() as (service, settings):
        await import_agent_definition(
            service, settings, content=DEFINITION, key="taken"
        )
        with pytest.raises(AgentExistsError):
            await import_agent_definition(
                service, settings, content=DEFINITION, key="taken"
            )


@pytest.mark.asyncio
async def test_an_update_keeps_what_the_definition_does_not_mention() -> None:
    """`save_agent` writes every column; a definition names only a few."""
    async with _catalog() as (service, settings):
        await service.save_agent_record(
            {
                "key": "reviewer",
                "name": "Old name",
                "description": "old",
                "model": "m",
                "provider": "p",
                "reasoning_effort": "high",
                "tools": json.dumps(["read"]),
                "workspace_dir": "/somewhere",
                "mode": "subagent",
                "posture": "read_only",
                "created_at": 1,
                "updated_at": 1,
            }
        )

        await import_agent_definition(
            service, settings, content=DEFINITION, key="reviewer", update=True
        )

        agent = await service.get_agent("reviewer")
        assert agent["name"] == "Code Reviewer"
        assert agent["workspace_dir"] == "/somewhere"
        assert agent["reasoning_effort"] == "high"
        assert agent["tools"] == json.dumps(["read"])
        assert agent["mode"] == "subagent", "an update must not downgrade it"
        identity = settings.home / "agents" / "reviewer" / "IDENTITY.md"
        assert "You review code." in identity.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_parents_make_a_subagent_and_unknown_ones_warn() -> None:
    async with _catalog() as (service, settings):
        outcome = await import_agent_definition(
            service,
            settings,
            content=DEFINITION,
            key="attached",
            parent_ids=["main", "ghost"],
        )

        assert any("ghost" in warning for warning in outcome.warnings)
        agent = await service.get_agent("attached")
        assert agent["mode"] == "subagent"
        assert await service.get_agent_parents("attached") == ["main"]


@pytest.mark.asyncio
async def test_an_unusable_key_is_reported() -> None:
    async with _catalog() as (service, settings):
        with pytest.raises(AgentKeyError):
            await import_agent_definition(
                service, settings, content=DEFINITION, key="No Spaces Allowed"
            )


@pytest.mark.asyncio
async def test_provider_and_model_overrides_win() -> None:
    async with _catalog() as (service, settings):
        await import_agent_definition(
            service,
            settings,
            content=DEFINITION,
            key="overridden",
            provider="opencode-go",
            model="deepseek-v4.1-flash",
        )
        agent = await service.get_agent("overridden")
        assert (agent["provider"], agent["model"]) == (
            "opencode-go",
            "deepseek-v4.1-flash",
        )


# ── the console door ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_console_import_reports_and_writes(tmp_path) -> None:
    definition = tmp_path / "reviewer.md"
    definition.write_text(DEFINITION, encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()

    async with _catalog() as (service, settings):
        code = await console.import_agent(
            str(definition), settings=settings, out=out, err=err
        )
        assert code == console.EXIT_OK
        assert "Imported 'code-reviewer'" in out.getvalue()
        assert await service.get_agent("code-reviewer") is not None


@pytest.mark.asyncio
async def test_console_dry_run_writes_nothing(tmp_path) -> None:
    definition = tmp_path / "reviewer.md"
    definition.write_text(DEFINITION, encoding="utf-8")
    out = io.StringIO()

    async with _catalog() as (service, settings):
        code = await console.import_agent(
            str(definition), settings=settings, dry_run=True, out=out
        )
        assert code == console.EXIT_OK
        assert "Would import" in out.getvalue()
        assert await service.get_agent("code-reviewer") is None


@pytest.mark.asyncio
async def test_console_conflict_asks_for_a_decision(tmp_path) -> None:
    definition = tmp_path / "reviewer.md"
    definition.write_text(DEFINITION, encoding="utf-8")
    err = io.StringIO()

    async with _catalog() as (service, settings):
        await import_agent_definition(
            service, settings, content=DEFINITION, key="code-reviewer"
        )
        code = await console.import_agent(
            str(definition), settings=settings, out=io.StringIO(), err=err
        )

    assert code == console.EXIT_NEEDS_INPUT
    assert "--update" in err.getvalue()


@pytest.mark.asyncio
async def test_strict_refuses_a_lossy_definition(tmp_path) -> None:
    definition = tmp_path / "lossy.md"
    definition.write_text(
        "---\nname: Lossy\ndescription: d\ntemperature: 0.4\n---\nBody.\n",
        encoding="utf-8",
    )
    err = io.StringIO()

    async with _catalog() as (service, settings):
        code = await console.import_agent(
            str(definition), settings=settings, strict=True, out=io.StringIO(), err=err
        )
        assert code == console.EXIT_NEEDS_INPUT
        assert "temperature" in err.getvalue()
        assert await service.get_agent("lossy") is None, "strict must not write"


@pytest.mark.asyncio
async def test_console_reports_an_unreadable_file(tmp_path) -> None:
    err = io.StringIO()
    async with _catalog() as (_service, settings):
        code = await console.import_agent(
            str(tmp_path / "absent.md"), settings=settings, err=err
        )
    assert code == console.EXIT_ERROR
    assert "Cannot read" in err.getvalue()


@pytest.mark.asyncio
async def test_an_alias_without_overrides_reports_the_missing_provider() -> None:
    async with _catalog() as (service, settings):
        outcome = await import_agent_definition(
            service, settings, content=DEFINITION.replace("acme/reviewer-1", "sonnet")
        )

        assert any("--provider" in warning for warning in outcome.warnings)
