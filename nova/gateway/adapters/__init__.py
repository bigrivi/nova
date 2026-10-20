"""Platform adapter factory.

Only platforms present in the config and carrying the credentials their
adapter needs are built; a missing token disables that platform with a warning
rather than crashing the gateway.
"""

from __future__ import annotations

import logging

from nova.gateway.adapters.dingtalk import DingTalkAdapter
from nova.gateway.adapters.feishu import FeishuAdapter
from nova.gateway.adapters.qq import QQAdapter
from nova.gateway.adapters.telegram import TelegramAdapter
from nova.gateway.adapters.wechat import WeChatAdapter
from nova.gateway.adapters.wecom import WeComAdapter
from nova.gateway.adapters.yuanbao import YuanbaoAdapter
from nova.gateway.config import GatewayConfig
from nova.gateway.platform import PlatformAdapter

log = logging.getLogger(__name__)

_BUILDERS = {
    "telegram": lambda o: TelegramAdapter(token=o.get("token", "")),
    "feishu": lambda o: FeishuAdapter(
        app_id=o.get("app_id", ""), app_secret=o.get("app_secret", "")
    ),
    "dingtalk": lambda o: DingTalkAdapter(
        app_key=o.get("app_key", ""), app_secret=o.get("app_secret", "")
    ),
    "wecom": lambda o: WeComAdapter(
        corp_id=o.get("corp_id", ""), secret=o.get("secret", "")
    ),
    "qq": lambda o: QQAdapter(
        app_id=o.get("app_id", ""), token=o.get("token", "")
    ),
    "yuanbao": lambda o: YuanbaoAdapter(token=o.get("token", "")),
    "wechat": lambda o: WeChatAdapter(token=o.get("token", "")),
}

_REQUIRED = {
    "telegram": ("token",),
    "feishu": ("app_id", "app_secret"),
    "dingtalk": ("app_key", "app_secret"),
    "wecom": ("corp_id", "secret"),
    "qq": ("app_id", "token"),
    "yuanbao": ("token",),
    "wechat": (),
}


def build_adapters(config: GatewayConfig) -> dict[str, PlatformAdapter]:
    adapters: dict[str, PlatformAdapter] = {}
    for name in config.enabled_platforms():
        cfg = config.platform(name)
        if cfg is None:
            continue
        missing = [key for key in _REQUIRED.get(name, ()) if not cfg.options.get(key)]
        if missing:
            log.warning("gateway: %s disabled; missing %s", name, ", ".join(missing))
            continue
        builder = _BUILDERS.get(name)
        if builder is None:
            log.warning("gateway: unknown platform %s", name)
            continue
        adapters[name] = builder(cfg.options)
    return adapters
