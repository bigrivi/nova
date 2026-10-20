"""Gateway configuration, read from the ``gateway`` block or the environment."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PlatformConfig:
    enabled: bool = True
    options: dict[str, str] = field(default_factory=dict)


@dataclass
class GatewayConfig:
    nova_url: str = "http://127.0.0.1:8765"
    allowed_senders: set[str] = field(default_factory=set)
    platforms: dict[str, PlatformConfig] = field(default_factory=dict)

    def platform(self, name: str) -> PlatformConfig | None:
        return self.platforms.get(name)

    def enabled_platforms(self) -> list[str]:
        return [name for name, cfg in self.platforms.items() if cfg.enabled]


def _config_path() -> Path:
    home = Path(os.getenv("NOVA_HOME", Path.home() / ".nova")).expanduser()
    return home / "config.json"


def load_config(path: Path | str | None = None) -> GatewayConfig:
    """Read the ``gateway`` block, falling back to environment variables.

    A missing or malformed block yields an empty gateway rather than raising:
    a typo must not stop the process from starting. Platform options come from
    ``gateway.platforms.<name>``; a ``<NAME>_TOKEN`` env var is used when the
    block omits it.
    """
    payload: dict = {}
    config_path = Path(path) if path is not None else _config_path()
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    raw = payload.get("gateway") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        raw = {}

    nova_url = str(raw.get("nova_url") or os.getenv("NOVA_URL") or "http://127.0.0.1:8765")
    allowed = raw.get("allowed_senders")
    allowed_senders = {str(s) for s in allowed} if isinstance(allowed, list) else set()

    platforms: dict[str, PlatformConfig] = {}
    raw_platforms = raw.get("platforms")
    if isinstance(raw_platforms, dict):
        for name, value in raw_platforms.items():
            if not isinstance(value, dict):
                continue
            options = {
                str(k): str(v) for k, v in value.items() if k != "enabled"
            }
            platforms[str(name)] = PlatformConfig(
                enabled=bool(value.get("enabled", True)),
                options=options,
            )

    # Environment fallbacks: only fill a missing option, never overwrite config.
    env_fallbacks = {
        "telegram": {"token": "TELEGRAM_BOT_TOKEN"},
        "feishu": {"app_id": "FEISHU_APP_ID", "app_secret": "FEISHU_APP_SECRET"},
        "dingtalk": {"app_key": "DINGTALK_APP_KEY", "app_secret": "DINGTALK_APP_SECRET"},
        "wecom": {"corp_id": "WECOM_CORP_ID", "secret": "WECOM_SECRET"},
        "qq": {"app_id": "QQ_APP_ID", "token": "QQ_TOKEN"},
        "yuanbao": {"token": "YUANBAO_TOKEN"},
    }
    for name, mapping in env_fallbacks.items():
        cfg = platforms.get(name)
        if cfg is None:
            continue
        for key, env_name in mapping.items():
            if not cfg.options.get(key):
                value = os.getenv(env_name, "").strip()
                if value:
                    cfg.options[key] = value

    return GatewayConfig(
        nova_url=nova_url,
        allowed_senders=allowed_senders,
        platforms=platforms,
    )
