from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from nova.db import DataSourceProtocol, get_default_data_source
from nova.settings import Settings, _load_config_payload, _write_json


class ConfigValidationError(ValueError):
    pass


class _Unset:
    """Marks an argument the caller left out, as distinct from ``None``.

    ``None`` is a real choice here - clearing a stored reasoning level - so a
    plain default would conflate "not mentioned" with "remove it" and let a
    model-only update wipe the setting.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


_UNSET = _Unset()


_SUPPORTED_PROVIDER_TYPES: frozenset[str] = frozenset(
    {"ollama", "openai-compatible", "openai-response", "anthropic"}
)
_DEFAULT_BASE_URLS: dict[str, str] = {
    "ollama": "http://localhost:11434",
    "anthropic": "https://api.anthropic.com",
}


def _merge_secrets(
    stored: object, submitted: tuple[tuple[str, str], ...]
) -> tuple[tuple[str, str], ...]:
    """Fold submitted env/header rows into what is already stored.

    Three moves have to be distinguishable from one submission, and none of them
    can be a plain overwrite because the form cannot display a stored value:

    * a row the user deleted is a **removal** -- its key was not submitted;
    * a row the user left blank **keeps** the stored value, since the blank means
      "I cannot see this secret and I am not retyping it";
    * a row with a value **sets** it.

    Args:
        stored: The raw ``env``/``headers`` value from the config file, which may
            be absent, malformed, or of a foreign type.
        submitted: The ``(key, value)`` pairs the form sent, in user order.

    Returns:
        The merged pairs in submitted order, so a user who reorders rows in the
        form gets that order in the file.
    """
    existing: dict[str, str] = {}
    if isinstance(stored, dict):
        existing = {str(k): str(v) for k, v in stored.items()}
    submitted_keys = {key.strip() for key, _ in submitted if key.strip()}
    merged: dict[str, str] = {
        key: value for key, value in existing.items() if key in submitted_keys
    }
    for raw_key, value in submitted:
        key = raw_key.strip()
        if key and value:
            merged[key] = value
    return tuple(
        (key, merged[key])
        for key in (raw.strip() for raw, _ in submitted)
        if key in merged
    )


def normalize_mcp_name(name: str) -> str:
    """The identifier a server is stored and addressed under.

    Trimmed, and required: a blank name would key an entry nothing could later
    find to update or delete.
    """
    cleaned = (name or "").strip()
    if not cleaned:
        raise ConfigValidationError("MCP server name is required.")
    return cleaned


def validate_mcp_config(config: McpServerConfig) -> McpServerConfig:
    """Reject a server that names neither a command nor a URL, or both.

    This is the same either/or ``create_transport`` enforces, checked here so the
    error reaches the user as a 400 at save time rather than a silent skip when
    the manager tries to connect it at the next startup.
    """
    command = (config.command or "").strip()
    url = (config.url or "").strip()
    if command and url:
        raise ConfigValidationError(
            "An MCP server is either a local command or a remote URL, not both."
        )
    if not command and not url:
        raise ConfigValidationError(
            "An MCP server needs a command (local) or a URL (remote)."
        )
    if url and not (url.startswith("http://") or url.startswith("https://")):
        raise ConfigValidationError(
            "A remote MCP URL must start with http:// or https://."
        )
    args = tuple(a for a in config.args if a != "")
    env = tuple((k.strip(), v) for k, v in config.env if k.strip())
    headers = tuple((k.strip(), v) for k, v in config.headers if k.strip())
    return McpServerConfig(
        name=normalize_mcp_name(config.name),
        command=command,
        args=args if command else (),
        env=env if command else (),
        url=url,
        headers=headers if url else (),
    )


@dataclass(frozen=True)
class AgentCreateRequest:
    key: str
    name: str
    description: str = ""
    model: str = ""
    provider: str = ""
    tools: list[str] | None = None
    workspace_dir: str | None = None
    parent_ids: list[str] | None = None
    posture: str = "full"
    mode: str = "primary"


@dataclass(frozen=True)
class ProviderCreateRequest:
    key: str
    provider_type: str
    name: str
    base_url: str
    api_key: str


@dataclass(frozen=True)
class ModelCreateRequest:
    provider: str
    model: str
    label: str
    tools: bool


@dataclass(frozen=True)
class McpServerConfig:
    """One MCP server, in the shape the transport layer already understands.

    Exactly one of ``command`` (a local stdio subprocess) or ``url`` (a remote
    HTTP endpoint) is set -- the same either/or ``create_transport`` enforces, so
    a config that round-trips through here is one it can build.
    """

    name: str
    command: str = ""
    args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    url: str = ""
    headers: tuple[tuple[str, str], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        """The JSON object stored under ``mcp_servers[name]``.

        Only the keys that belong to the chosen transport are written: a stdio
        server with a stray empty ``url`` would make ``create_transport``'s
        command/url check ambiguous.
        """
        if self.command:
            payload: dict[str, Any] = {"command": self.command}
            if self.args:
                payload["args"] = list(self.args)
            if self.env:
                payload["env"] = dict(self.env)
            return payload
        payload = {"url": self.url}
        if self.headers:
            payload["headers"] = dict(self.headers)
        return payload


class ConfigService:
    def __init__(
        self, settings: Settings, data_source: DataSourceProtocol | None = None
    ) -> None:
        if settings.config_path is None:
            raise ConfigValidationError("Nova config path is not available.")
        self._settings = settings
        self._config_path = settings.config_path
        self._data_source = data_source

    async def _get_data_source(self) -> DataSourceProtocol:
        if self._data_source is None:
            self._data_source = await get_default_data_source()
        return self._data_source

    # ── Agent CRUD (DB-backed) ──────────────────────────────────────

    async def list_agents(self) -> list[dict]:
        data_source = await self._get_data_source()
        return await data_source.list_agents()

    async def get_agent(self, key: str) -> dict | None:
        data_source = await self._get_data_source()
        return await data_source.get_agent(key)

    async def save_agent(self, request: AgentCreateRequest) -> dict:
        data_source = await self._get_data_source()
        now = int(time.time() * 1000)
        mode = (
            "subagent"
            if (request.mode == "subagent" or request.parent_ids)
            else "primary"
        )
        agent = {
            "key": request.key,
            "name": request.name,
            "description": request.description,
            "model": request.model,
            "provider": request.provider,
            "tools": json.dumps(request.tools) if request.tools else None,
            "workspace_dir": request.workspace_dir,
            "mode": mode,
            "posture": request.posture,
            "created_at": now,
            "updated_at": now,
        }
        await data_source.save_agent(agent)

        if request.parent_ids:
            await data_source.set_agent_parents(request.key, request.parent_ids)

        return agent

    async def save_agent_record(self, agent: dict) -> None:
        """Write a complete agent row.

        Unlike :meth:`save_agent`, nothing is derived: the caller supplies every
        column. That is what a merge-style update needs, because ``save_agent``
        stamps the columns it builds and would blank whatever the caller's
        source (an imported definition) says nothing about.

        Args:
            agent: A full row, as stored (``tools`` as the JSON text the column
                holds).
        """
        data_source = await self._get_data_source()
        await data_source.save_agent(agent)

    async def get_agent_parents(self, child_key: str) -> list[str]:
        """Get all parent keys of an agent."""
        data_source = await self._get_data_source()
        return await data_source.get_agent_parents(child_key)

    async def set_agent_parents(self, child_key: str, parent_keys: list[str]) -> None:
        """Replace the parent set of an agent (many-to-many)."""
        data_source = await self._get_data_source()
        await data_source.set_agent_parents(child_key, parent_keys)

    async def update_agent_model(
        self,
        key: str,
        model: str,
        provider: str,
        reasoning_effort: str | _Unset | None = _UNSET,
    ) -> dict | None:
        """Point an agent at a model, and optionally at a reasoning level.

        The level is filtered against what the model declares before it is
        stored, so the default a new conversation starts from is always a level
        that model accepts. Passing ``None`` clears it; omitting the argument
        leaves the stored one alone, so a caller that only knows the model does
        not silently reset someone's choice.
        """
        data_source = await self._get_data_source()
        existing = await data_source.get_agent(key)
        if existing is None:
            return None
        now = int(time.time() * 1000)
        existing["model"] = model
        existing["provider"] = provider
        if not isinstance(reasoning_effort, _Unset):
            existing["reasoning_effort"] = self._fit_effort(
                provider, model, reasoning_effort
            )
        existing["updated_at"] = now
        await data_source.save_agent(existing)
        return existing

    @staticmethod
    def _fit_effort(provider: str, model: str, effort: str | None) -> str | None:
        """Keep *effort* only when the model declares it, else drop it."""
        from nova.llm.reasoning import fit_effort, resolve_effort_levels
        from nova.settings import get_settings

        if not effort:
            return None
        try:
            provider_config = get_settings().providers.get(provider)
        except Exception:
            return None
        if provider_config is None:
            return None
        models = provider_config.models
        return fit_effort(
            resolve_effort_levels(
                model,
                provider_config.type,
                models.get(model) if isinstance(models, dict) else None,
            ),
            effort,
        )

    async def get_agent_children(self, parent_key: str) -> list[str]:
        """Get all child keys of an agent."""
        data_source = await self._get_data_source()
        return await data_source.get_agent_children(parent_key)

    async def get_child_agents(self, parent_key: str) -> list[dict]:
        """Get all child agents of a parent agent (legacy, uses parent_id column)."""
        data_source = await self._get_data_source()
        return await data_source.get_child_agents(parent_key)

    async def delete_agent(self, key: str) -> bool:
        data_source = await self._get_data_source()
        return await data_source.delete_agent(key)

    @property
    def config_path(self) -> Path:
        return self._config_path

    def add_provider(self, request: ProviderCreateRequest) -> dict[str, Any]:
        payload = _load_config_payload(self._config_path)
        providers = payload.setdefault("providers", {})
        if not isinstance(providers, dict):
            raise ConfigValidationError(
                "Invalid Nova config: 'providers' must be an object."
            )

        provider_key = request.key.strip()
        if not provider_key:
            raise ConfigValidationError("Provider key is required.")
        if provider_key in providers:
            raise ConfigValidationError(f"Provider '{provider_key}' already exists.")

        provider_type = request.provider_type.strip()
        if provider_type not in _SUPPORTED_PROVIDER_TYPES:
            raise ConfigValidationError(
                f"Provider type must be one of: {', '.join(sorted(_SUPPORTED_PROVIDER_TYPES))}."
            )

        display_name = request.name.strip() or provider_key
        base_url = request.base_url.strip()
        api_key = request.api_key.strip()

        if provider_type in {"openai-compatible", "openai-response"} and not base_url:
            raise ConfigValidationError(
                f"Base URL is required for {provider_type} providers."
            )
        if not base_url:
            default_url = _DEFAULT_BASE_URLS.get(provider_type)
            if default_url:
                base_url = default_url

        options: dict[str, Any] = {"base_url": base_url}
        if (
            provider_type in {"openai-compatible", "openai-response", "anthropic"}
            and api_key
        ):
            options["api_key"] = api_key

        providers[provider_key] = {
            "type": provider_type,
            "name": display_name,
            "options": options,
            "models": {},
        }
        _write_json(self._config_path, payload)
        return payload

    def add_model(self, request: ModelCreateRequest) -> dict[str, Any]:
        payload = _load_config_payload(self._config_path)
        providers = payload.setdefault("providers", {})
        if not isinstance(providers, dict):
            raise ConfigValidationError(
                "Invalid Nova config: 'providers' must be an object."
            )

        provider_key = request.provider.strip()
        provider_payload = providers.get(provider_key)
        if not isinstance(provider_payload, dict):
            raise ConfigValidationError(f"Provider '{provider_key}' does not exist.")

        models = provider_payload.setdefault("models", {})
        if not isinstance(models, dict):
            raise ConfigValidationError(
                f"Invalid Nova config: provider '{provider_key}' models must be an object."
            )

        model_key = request.model.strip()
        if not model_key:
            raise ConfigValidationError("Model name is required.")
        if model_key in models:
            raise ConfigValidationError(
                f"Model '{model_key}' already exists under provider '{provider_key}'."
            )

        models[model_key] = {
            "name": request.label.strip() or model_key,
            "tools": request.tools,
        }
        _write_json(self._config_path, payload)
        return payload

    def update_provider(
        self,
        key: str,
        name: str | None = None,
        provider_type: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        payload = _load_config_payload(self._config_path)
        providers = payload.setdefault("providers", {})
        if not isinstance(providers, dict):
            raise ConfigValidationError(
                "Invalid Nova config: 'providers' must be an object."
            )

        provider_key = (key or "").strip()
        provider_payload = providers.get(provider_key)
        if not isinstance(provider_payload, dict):
            raise ConfigValidationError(f"Provider '{provider_key}' does not exist.")

        if name is not None:
            stripped_name = name.strip()
            if not stripped_name:
                raise ConfigValidationError("Provider name must not be empty.")
            provider_payload["name"] = stripped_name

        if provider_type is not None:
            stripped_type = provider_type.strip()
            if stripped_type not in _SUPPORTED_PROVIDER_TYPES:
                raise ConfigValidationError(
                    f"Provider type must be one of: {', '.join(sorted(_SUPPORTED_PROVIDER_TYPES))}."
                )
            provider_payload["type"] = stripped_type

        effective_type = str(provider_payload.get("type", "")).strip()
        options = provider_payload.get("options")
        if not isinstance(options, dict):
            options = {}
            provider_payload["options"] = options

        if base_url is not None:
            options["base_url"] = base_url.strip()

        if api_key is not None:
            if api_key == "":
                options.pop("api_key", None)
            else:
                stripped_key = api_key.strip()
                if stripped_key:
                    options["api_key"] = stripped_key

        if (
            effective_type in {"openai-compatible", "openai-response"}
            and not str(options.get("base_url", "")).strip()
        ):
            raise ConfigValidationError(
                f"Base URL is required for {effective_type} providers."
            )

        _write_json(self._config_path, payload)
        return payload

    def delete_provider(self, key: str) -> dict[str, Any]:
        payload = _load_config_payload(self._config_path)
        providers = payload.setdefault("providers", {})
        if not isinstance(providers, dict):
            raise ConfigValidationError(
                "Invalid Nova config: 'providers' must be an object."
            )

        provider_key = (key or "").strip()
        if provider_key not in providers:
            raise ConfigValidationError(f"Provider '{provider_key}' does not exist.")

        del providers[provider_key]
        _write_json(self._config_path, payload)
        return payload

    def update_model(
        self,
        provider: str,
        model: str,
        label: str | None = None,
        tools: bool | None = None,
    ) -> dict[str, Any]:
        payload = _load_config_payload(self._config_path)
        providers = payload.setdefault("providers", {})
        if not isinstance(providers, dict):
            raise ConfigValidationError(
                "Invalid Nova config: 'providers' must be an object."
            )

        provider_key = (provider or "").strip()
        provider_payload = providers.get(provider_key)
        if not isinstance(provider_payload, dict):
            raise ConfigValidationError(f"Provider '{provider_key}' does not exist.")

        models = provider_payload.setdefault("models", {})
        if not isinstance(models, dict):
            raise ConfigValidationError(
                f"Invalid Nova config: provider '{provider_key}' models must be an object."
            )

        model_key = (model or "").strip()
        model_payload = models.get(model_key)
        if not isinstance(model_payload, dict):
            raise ConfigValidationError(
                f"Model '{model_key}' does not exist under provider '{provider_key}'."
            )

        if label is not None:
            stripped_label = label.strip()
            if not stripped_label:
                raise ConfigValidationError("Model label must not be empty.")
            model_payload["name"] = stripped_label

        if tools is not None:
            model_payload["tools"] = tools

        _write_json(self._config_path, payload)
        return payload

    def delete_model(self, provider: str, model: str) -> dict[str, Any]:
        payload = _load_config_payload(self._config_path)
        providers = payload.setdefault("providers", {})
        if not isinstance(providers, dict):
            raise ConfigValidationError(
                "Invalid Nova config: 'providers' must be an object."
            )

        provider_key = (provider or "").strip()
        provider_payload = providers.get(provider_key)
        if not isinstance(provider_payload, dict):
            raise ConfigValidationError(f"Provider '{provider_key}' does not exist.")

        models = provider_payload.setdefault("models", {})
        if not isinstance(models, dict):
            raise ConfigValidationError(
                f"Invalid Nova config: provider '{provider_key}' models must be an object."
            )

        model_key = (model or "").strip()
        if model_key not in models:
            raise ConfigValidationError(
                f"Model '{model_key}' does not exist under provider '{provider_key}'."
            )

        del models[model_key]
        _write_json(self._config_path, payload)
        return payload

    # ── MCP server CRUD (JSON-backed) ───────────────────────────────
    #
    # The config shape is ``mcp_servers: {name: {command|url, ...}}`` -- the one
    # the transport layer reads at startup. These methods are the only writers,
    # so the JSON a human edits by hand and the JSON this writes stay the same
    # shape, and a server added here is one `create_transport` can build.
    #
    # A change here reaches a running agent on the next restart, not sooner: the
    # MCP manager connects its servers once at process start, and reconnecting a
    # live stdio subprocess mid-session is a risk the connection test exists to
    # make unnecessary. The UI says as much.

    def _mcp_servers(self, payload: dict[str, Any]) -> dict[str, Any]:
        servers = payload.setdefault("mcp_servers", {})
        if not isinstance(servers, dict):
            raise ConfigValidationError(
                "Invalid Nova config: 'mcp_servers' must be an object."
            )
        return servers

    def list_mcp_servers(self) -> dict[str, Any]:
        """Every configured server, by name, in its stored form."""
        payload = _load_config_payload(self._config_path)
        return dict(self._mcp_servers(payload))

    def add_mcp_server(self, config: McpServerConfig) -> dict[str, Any]:
        payload = _load_config_payload(self._config_path)
        servers = self._mcp_servers(payload)
        name = normalize_mcp_name(config.name)
        if name in servers:
            raise ConfigValidationError(f"MCP server '{name}' already exists.")
        servers[name] = validate_mcp_config(config).to_payload()
        _write_json(self._config_path, payload)
        return payload

    def update_mcp_server(self, name: str, config: McpServerConfig) -> dict[str, Any]:
        payload = _load_config_payload(self._config_path)
        servers = self._mcp_servers(payload)
        existing = normalize_mcp_name(name)
        if existing not in servers:
            raise ConfigValidationError(f"MCP server '{existing}' does not exist.")
        stored = servers[existing]
        if not isinstance(stored, dict):
            raise ConfigValidationError(f"MCP server '{existing}' is not an object.")
        renamed = normalize_mcp_name(config.name)
        if renamed != existing and renamed in servers:
            raise ConfigValidationError(f"MCP server '{renamed}' already exists.")
        validated = validate_mcp_config(config)
        # env/headers merge by key rather than replacing: the API never returns
        # their values, so an edit form cannot show what is already stored. A
        # blind overwrite would destroy a token whenever someone fixed a typo in
        # the command line. _merge_secrets reads a dropped row as a removal and a
        # blank value as "keep what you have", which is what those two moves mean.
        merged = replace(
            validated,
            env=tuple(_merge_secrets(stored.get("env"), validated.env)),
            headers=tuple(_merge_secrets(stored.get("headers"), validated.headers)),
        )
        del servers[existing]
        servers[renamed] = merged.to_payload()
        _write_json(self._config_path, payload)
        return payload

    def delete_mcp_server(self, name: str) -> dict[str, Any]:
        payload = _load_config_payload(self._config_path)
        servers = self._mcp_servers(payload)
        existing = normalize_mcp_name(name)
        if existing not in servers:
            raise ConfigValidationError(f"MCP server '{existing}' does not exist.")
        del servers[existing]
        _write_json(self._config_path, payload)
        return payload
