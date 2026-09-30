"""Session route: the model and reasoning level a conversation runs with.

A session records its own route so reopening it restores the model it actually
used, rather than whatever the agent happens to point at today. The level is
filtered against what the model declares on the way in, so a GET never hands
back a level the model would reject.
"""

from __future__ import annotations

import json

import httpx
import pytest
import pytest_asyncio

from nova.db.config import DatabaseConfig
from nova.db.database import close_db, init_db
from nova.server import create_app
from nova.settings import Settings

GATEWAY = {
    "type": "openai-compatible",
    "name": "gw",
    "options": {"base_url": "http://gw.invalid", "api_key": "k"},
    "models": {
        "gpt-5.5": {
            "name": "gpt-5.5",
            "reasoning_effort_levels": ["low", "medium", "high"],
        },
        "plain-model": {"name": "plain-model"},
    },
}


@pytest_asyncio.fixture
async def client(monkeypatch, tmp_path):
    """An ASGI client on this test's own event loop.

    The sync TestClient spins up a second loop in a worker thread, which
    deadlocks when awaited from inside an async test.
    """
    home = tmp_path / ".nova"
    home.mkdir()
    (home / "config.json").write_text(
        json.dumps({"providers": {"gw": GATEWAY}}), encoding="utf-8"
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    app = create_app(settings=Settings.load_config())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as test_client:
        yield test_client


async def make_session(client, title: str) -> str:
    """Create a session the way a turn does, since there is no create route."""
    import uuid

    from nova.session.models import Session

    service = client._transport.app.state.chat_service
    data_source = await service._get_data_source()
    session = Session(id=str(uuid.uuid4()), title=title)
    await data_source.save_session(session)
    return session.id


@pytest_asyncio.fixture
async def session_id(client):
    return await make_session(client, "route test")


async def put_route(client, session_id, **body):
    return await client.put(f"/api/sessions/{session_id}/route", json=body)


async def get_route(client, session_id):
    return await client.get(f"/api/sessions/{session_id}/route")


@pytest.mark.asyncio
class TestRouteEndpoint:
    async def test_route_round_trips(self, client, session_id):
        assert (
            await put_route(
                client,
                session_id,
                provider="gw",
                model="gpt-5.5",
                reasoning_effort="high",
            )
        ).status_code == 200

        body = (await get_route(client, session_id)).json()
        assert body == {
            "provider": "gw",
            "model": "gpt-5.5",
            "reasoning_effort": "high",
        }

    async def test_an_undeclared_level_is_dropped_on_write(self, client, session_id):
        """Validated on the way in, not only at agent build time.

        Otherwise a GET would hand back a level the model rejects, and the
        reopened session would fail on its first turn.
        """
        await put_route(
            client,
            session_id,
            provider="gw",
            model="gpt-5.5",
            reasoning_effort="xhigh",
        )
        assert (await get_route(client, session_id)).json()["reasoning_effort"] is None

    async def test_a_model_that_declares_nothing_records_no_level(
        self, client, session_id
    ):
        await put_route(
            client,
            session_id,
            provider="gw",
            model="plain-model",
            reasoning_effort="high",
        )
        body = (await get_route(client, session_id)).json()
        assert body["model"] == "plain-model"
        assert body["reasoning_effort"] is None

    async def test_an_unknown_provider_keeps_the_level_unfiltered(
        self, client, session_id
    ):
        """A provider the settings do not know cannot be validated.

        Dropping the level there would silently discard a legitimate choice for
        a gateway configured elsewhere, so the write stands and the agent build
        is the second gate.
        """
        await put_route(
            client,
            session_id,
            provider="elsewhere",
            model="gpt-5.5",
            reasoning_effort="high",
        )
        assert (await get_route(client, session_id)).json()[
            "reasoning_effort"
        ] == "high"

    async def test_a_level_without_a_model_is_rejected(self, client, session_id):
        """The write replaces the whole route, so half a route is not a route.

        Accepting it would record an effort belonging to no model, which is the
        exact state the single-statement write exists to prevent.
        """
        await put_route(
            client, session_id, provider="gw", model="gpt-5.5", reasoning_effort="low"
        )
        response = await put_route(client, session_id, reasoning_effort="medium")
        assert response.status_code == 422

        body = (await get_route(client, session_id)).json()
        assert body == {
            "provider": "gw",
            "model": "gpt-5.5",
            "reasoning_effort": "low",
        }, "a rejected write must leave the route untouched"

    async def test_switching_model_clears_a_level_the_new_model_declines(
        self, client, session_id
    ):
        """The two move together, so the old level cannot outlive its model."""
        await put_route(
            client, session_id, provider="gw", model="gpt-5.5", reasoning_effort="high"
        )
        await put_route(client, session_id, provider="gw", model="plain-model")

        body = (await get_route(client, session_id)).json()
        assert body["model"] == "plain-model"
        assert body["reasoning_effort"] is None

    async def test_clearing_the_route_is_allowed(self, client, session_id):
        """An empty body means 'fall back to the agent', which a new chat does."""
        await put_route(
            client, session_id, provider="gw", model="gpt-5.5", reasoning_effort="high"
        )
        await put_route(client, session_id)
        assert (await get_route(client, session_id)).json() == {
            "provider": None,
            "model": None,
            "reasoning_effort": None,
        }

    async def test_missing_session_is_a_404(self, client):
        assert (await get_route(client, "no-such-session")).status_code == 404
        assert (
            await put_route(client, "no-such-session", provider="gw", model="gpt-5.5")
        ).status_code == 404

    async def test_a_session_keeps_its_own_route(self, client, session_id):
        """Two conversations on the same model run at different levels."""
        other = await make_session(client, "other")
        await put_route(
            client, session_id, provider="gw", model="gpt-5.5", reasoning_effort="low"
        )
        await put_route(
            client, other, provider="gw", model="gpt-5.5", reasoning_effort="high"
        )

        assert (await get_route(client, session_id)).json()["reasoning_effort"] == "low"
        assert (await get_route(client, other)).json()["reasoning_effort"] == "high"

    async def test_the_model_list_carries_the_declared_levels(self, client):
        """The picker can only offer what the catalog reports."""
        items = {
            item["id"]: item
            for item in (await client.get("/api/models")).json()["items"]
        }
        assert items["gw:gpt-5.5"]["efforts"] == ["low", "medium", "high"]
        assert items["gw:plain-model"]["efforts"] == []


@pytest.mark.asyncio
class TestRouteStorage:
    """The columns have to exist on an existing database, not just a new one."""

    async def test_columns_are_added_to_a_database_created_before_them(
        self, monkeypatch, tmp_path
    ):
        """An existing install upgrades in place rather than losing its history."""
        import sqlite3

        home = tmp_path / ".nova"
        home.mkdir()
        (home / "config.json").write_text(
            json.dumps({"providers": {"gw": GATEWAY}}), encoding="utf-8"
        )
        db_path = home / "nova.db"
        with sqlite3.connect(db_path) as raw:
            raw.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT)")
            raw.execute(
                "INSERT INTO sessions (id, title) VALUES ('old', 'before the change')"
            )

        monkeypatch.setenv("NOVA_HOME", str(home))
        settings = Settings.load_config()
        await init_db(DatabaseConfig(path=settings.database_path))
        try:
            with sqlite3.connect(db_path) as raw:
                columns = {row[1] for row in raw.execute("PRAGMA table_info(sessions)")}
                title = raw.execute(
                    "SELECT title FROM sessions WHERE id = 'old'"
                ).fetchone()[0]

            # Every migrated column, not just the new ones: the migration is a
            # dict keyed by table, so a second entry for `sessions` would drop
            # the earlier columns and this is the only thing that would notice.
            assert {
                "workspace_dir",
                "pinned",
                "project_id",
                "provider",
                "model",
                "reasoning_effort",
            } <= columns
            assert title == "before the change", "the migration must not rewrite rows"
        finally:
            await close_db()

    async def test_route_survives_a_reopen(self, client, session_id):
        """Written through one connection, read back through the next."""
        from nova.db.sqlite_repository import SqliteRepository

        await put_route(
            client, session_id, provider="gw", model="gpt-5.5", reasoning_effort="high"
        )

        source = SqliteRepository(
            DatabaseConfig(path=client._transport.app.state.settings.database_path)
        )
        session = await source.get_session(session_id)
        assert session["provider"] == "gw"
        assert session["model"] == "gpt-5.5"
        assert session["reasoning_effort"] == "high"
        await source.close()

    async def test_the_agent_gains_a_reasoning_effort_column(
        self, monkeypatch, tmp_path
    ):
        """An install that predates the column upgrades in place."""
        import sqlite3

        home = tmp_path / ".nova"
        home.mkdir()
        (home / "config.json").write_text(
            json.dumps({"providers": {"gw": GATEWAY}}), encoding="utf-8"
        )
        db_path = home / "nova.db"
        with sqlite3.connect(db_path) as raw:
            # The real schema minus the column being added, so the migration is
            # the only thing that has to supply it.
            raw.execute(
                "CREATE TABLE agents ("
                "key TEXT PRIMARY KEY, name TEXT NOT NULL,"
                " description TEXT DEFAULT '', model TEXT NOT NULL,"
                " provider TEXT NOT NULL, tools TEXT, workspace_dir TEXT,"
                " mode TEXT DEFAULT 'primary', posture TEXT DEFAULT 'full',"
                " created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)"
            )
            raw.execute(
                "INSERT INTO agents (key, name, model, provider, created_at, updated_at)"
                " VALUES ('main', 'Nova', 'gpt-5.5', 'gw', 0, 0)"
            )

        monkeypatch.setenv("NOVA_HOME", str(home))
        await init_db(DatabaseConfig(path=Settings.load_config().database_path))
        try:
            with sqlite3.connect(db_path) as raw:
                columns = {row[1] for row in raw.execute("PRAGMA table_info(agents)")}
                model = raw.execute(
                    "SELECT model FROM agents WHERE key = 'main'"
                ).fetchone()[0]
            assert "reasoning_effort" in columns
            assert model == "gpt-5.5", "the migration must not rewrite rows"
        finally:
            await close_db()


@pytest.mark.asyncio
class TestAgentDefault:
    """The agent row is the default a brand-new conversation starts from.

    Without it every new chat reopens on the provider's own default and the
    level picked in the previous one is gone.
    """

    async def test_a_level_is_stored_on_the_agent(self, client):
        response = await client.patch(
            "/api/agents/main",
            json={
                "provider": "gw",
                "model": "gpt-5.5",
                "reasoning_effort": "high",
            },
        )
        assert response.status_code == 200
        assert response.json()["reasoning_effort"] == "high"
        assert (await client.get("/api/agents/main")).json()[
            "reasoning_effort"
        ] == "high"

    async def test_an_undeclared_level_is_dropped_on_write(self, client):
        """Same rule as the session route: never store what the model refuses."""
        await client.patch(
            "/api/agents/main",
            json={"provider": "gw", "model": "gpt-5.5", "reasoning_effort": "xhigh"},
        )
        assert (await client.get("/api/agents/main")).json()["reasoning_effort"] is None

    async def test_a_model_that_declares_nothing_stores_no_level(self, client):
        await client.patch(
            "/api/agents/main",
            json={"provider": "gw", "model": "plain-model", "reasoning_effort": "high"},
        )
        assert (await client.get("/api/agents/main")).json()["reasoning_effort"] is None

    async def test_a_model_only_update_leaves_the_level_alone(self, client):
        """The point of the sentinel: a model swap must not reset the choice.

        The picker always sends both, but a caller that only knows the model
        would otherwise silently clear someone's default.
        """
        await client.patch(
            "/api/agents/main",
            json={"provider": "gw", "model": "gpt-5.5", "reasoning_effort": "low"},
        )
        await client.patch(
            "/api/agents/main", json={"provider": "gw", "model": "gpt-5.5"}
        )

        agent = (await client.get("/api/agents/main")).json()
        assert agent["reasoning_effort"] == "low"
        assert agent["model"] == "gpt-5.5"

    async def test_an_explicit_null_clears_the_level(self, client):
        await client.patch(
            "/api/agents/main",
            json={"provider": "gw", "model": "gpt-5.5", "reasoning_effort": "low"},
        )
        await client.patch(
            "/api/agents/main",
            json={"provider": "gw", "model": "gpt-5.5", "reasoning_effort": None},
        )
        assert (await client.get("/api/agents/main")).json()["reasoning_effort"] is None

    async def test_the_agent_and_a_session_hold_their_own_level(
        self, client, session_id
    ):
        """A default is not a lock: the conversation still picks its own."""
        await client.patch(
            "/api/agents/main",
            json={"provider": "gw", "model": "gpt-5.5", "reasoning_effort": "low"},
        )
        await put_route(
            client, session_id, provider="gw", model="gpt-5.5", reasoning_effort="high"
        )
        assert (await client.get("/api/agents/main")).json()[
            "reasoning_effort"
        ] == "low"
        assert (await get_route(client, session_id)).json()[
            "reasoning_effort"
        ] == "high"

    async def test_an_unknown_agent_is_a_404(self, client):
        response = await client.patch(
            "/api/agents/nope",
            json={"provider": "gw", "model": "gpt-5.5", "reasoning_effort": "high"},
        )
        assert response.status_code == 404


class TestEffortPrecedence:
    """Which level a run uses, from the four places one can come from."""

    @staticmethod
    def resolve(requested=None, session=None, agent=None, config=None):
        from types import SimpleNamespace

        from nova.app.runtime import _resolve_effort

        settings = SimpleNamespace(
            providers={
                "gw": SimpleNamespace(
                    type="openai-compatible",
                    models={
                        "gpt-5.5": {
                            "reasoning_effort_levels": ["low", "medium", "high"],
                            **({"reasoning_effort": config} if config else {}),
                        }
                    },
                )
            }
        )
        return _resolve_effort(
            settings=settings,
            provider="gw",
            model="gpt-5.5",
            requested=requested,
            session_effort=session,
            agent_effort=agent,
        )

    def test_the_request_wins(self):
        assert self.resolve("high", "low", "medium", "low") == "high"

    def test_the_session_beats_the_agent_default(self):
        assert self.resolve(None, "high", "low") == "high"

    def test_the_agent_default_beats_the_model_config(self):
        assert self.resolve(None, None, "high", "low") == "high"

    def test_the_model_config_is_the_floor(self):
        assert self.resolve(None, None, None, "medium") == "medium"

    def test_nothing_anywhere_means_no_level(self):
        assert self.resolve() is None

    def test_a_level_for_a_different_model_is_skipped_not_returned(self):
        """Falls through to the next candidate rather than stopping on a bad one."""
        assert self.resolve(None, "xhigh", "low") == "low"

    def test_a_model_declaring_no_levels_gets_none(self):
        from types import SimpleNamespace

        from nova.app.runtime import _resolve_effort

        settings = SimpleNamespace(
            providers={
                "gw": SimpleNamespace(type="openai-compatible", models={"m": {}})
            }
        )
        assert (
            _resolve_effort(
                settings=settings,
                provider="gw",
                model="m",
                requested="high",
                session_effort="high",
                agent_effort="high",
            )
            is None
        )
