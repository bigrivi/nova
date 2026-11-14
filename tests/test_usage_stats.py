"""Token and cost totals: what the /stats panel is built from.

Tokens are what the provider reported, summed. Cost is an estimate priced from
the catalogue, and a model the catalogue cannot price is "unknown", not free.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio

from nova.db.config import DatabaseConfig
from nova.db.sqlite.repository import SqliteRepository
from nova.registry import pricing
from nova.server.session_service import SessionService
from nova.session.manager import SessionContext
from nova.session.models import NewMessage
from nova.settings import Settings


def _settings_with_prices(
    monkeypatch, home: Path, prices: dict[str, dict[str, float]]
) -> Settings:
    """Settings whose catalogue knows *prices* for the given models."""
    monkeypatch.setenv("NOVA_HOME", str(home))
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text("{}", encoding="utf-8")
    (home / "models.json").write_text(
        json.dumps(
            {
                "catalogue": {
                    "models": {model: {"cost": cost} for model, cost in prices.items()}
                }
            }
        ),
        encoding="utf-8",
    )
    return Settings.load_config()


@pytest_asyncio.fixture
async def service(monkeypatch, tmp_path: Path):
    database = SqliteRepository(DatabaseConfig(path=":memory:"))
    await database.connect()
    session = SessionContext.create()
    session.title = "s"
    await database.save_session(session)
    settings = _settings_with_prices(
        monkeypatch,
        tmp_path / "home",
        {"priced-model": {"input": 1.0, "output": 2.0, "cache_read": 0.5}},
    )
    try:
        yield (
            SessionService(settings=settings, data_source=database),
            session.id,
            database,
        )
    finally:
        await database.close()


async def _turn(database: SqliteRepository, session_id: str, model: str) -> None:
    """One user/assistant exchange on *model*, with tokens reported."""
    await database.add_message(
        NewMessage(session_id=session_id, role="user", content="hello")
    )
    await database.add_message(
        NewMessage(
            session_id=session_id,
            role="assistant",
            content="hi",
            model=model,
            tokens_input=1_000_000,
            tokens_output=500_000,
            cache_read_tokens=200_000,
        )
    )


@pytest.mark.asyncio
async def test_tokens_are_summed_and_priced(service):
    session_service, session_id, database = service
    await _turn(database, session_id, "priced-model")

    stats = await session_service.usage(session_id)

    assert stats["scope"] == "session"
    assert stats["tokens"] == {
        "input": 1_000_000,
        "output": 500_000,
        "cache_read": 200_000,
        "total": 1_500_000,
    }
    # 1M input at $1/M + 0.5M output at $2/M + 0.2M cached at $0.5/M
    assert stats["cost"]["total"] == pytest.approx(1.0 + 1.0 + 0.1)
    assert stats["cost"]["priced"] is True
    assert stats["cost"]["unpriced_models"] == 0
    assert [row["model"] for row in stats["by_model"]] == ["priced-model"]


@pytest.mark.asyncio
async def test_a_model_the_catalogue_cannot_price_is_unknown_not_free(service):
    session_service, session_id, database = service
    await _turn(database, session_id, "unpriced-model")

    stats = await session_service.usage(session_id)

    assert stats["tokens"]["input"] == 1_000_000
    assert stats["cost"]["priced"] is False
    assert stats["cost"]["unpriced_models"] == 1
    assert stats["cost"]["total"] == 0.0


@pytest.mark.asyncio
async def test_every_session_can_be_counted_together(service):
    session_service, session_id, database = service
    await _turn(database, session_id, "priced-model")
    other = SessionContext.create()
    other.title = "other"
    await database.save_session(other)
    await _turn(database, other.id, "priced-model")

    stats = await session_service.usage()

    assert stats["scope"] == "all"
    assert stats["tokens"]["input"] == 2_000_000
    assert stats["session"] is None


@pytest.mark.asyncio
async def test_an_unknown_session_is_not_found(service):
    session_service, _session_id, _database = service

    with pytest.raises(FileNotFoundError):
        await session_service.usage("no-such-session")


def test_the_cheapest_stated_price_wins(monkeypatch, tmp_path: Path):
    """The same model is priced differently by different providers; a message
    records only the model, so the estimate takes the lowest price."""
    home = tmp_path / "home"
    monkeypatch.setenv("NOVA_HOME", str(home))
    home.mkdir(parents=True)
    (home / "config.json").write_text("{}", encoding="utf-8")
    (home / "models.json").write_text(
        json.dumps(
            {
                "expensive": {
                    "models": {"m": {"cost": {"input": 10.0, "output": 20.0}}}
                },
                "cheap": {"models": {"m": {"cost": {"input": 1.0, "output": 2.0}}}},
            }
        ),
        encoding="utf-8",
    )
    settings = Settings.load_config()

    assert pricing.model_prices(settings, "m") == {"input": 1.0, "output": 2.0}


def test_an_unpriceable_model_has_no_estimate(monkeypatch, tmp_path: Path):
    settings = _settings_with_prices(monkeypatch, tmp_path / "home", {})

    assert pricing.model_prices(settings, "unknown") is None
    assert pricing.estimate_cost(settings, "unknown", 10, 20) is None


def test_an_explicit_settings_object_prices_a_turn(monkeypatch, tmp_path: Path):
    """The agent prices a turn through get_settings(); passing a settings
    object directly has to work the same way."""
    settings = _settings_with_prices(
        monkeypatch, tmp_path / "home", {"m": {"input": 1.0, "output": 1.0}}
    )

    assert pricing.estimate_cost(settings, "m", 1_000_000, 0) == pytest.approx(1.0)
