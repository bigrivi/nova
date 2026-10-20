import json

from nova.gateway.adapters import build_adapters
from nova.gateway.config import load_config


def test_absent_gateway_block_yields_empty_config(tmp_path):
    config = load_config(tmp_path / "missing.json")
    assert config.nova_url == "http://127.0.0.1:8765"
    assert config.enabled_platforms() == []


def test_reads_platform_options(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "gateway": {
                    "nova_url": "http://localhost:9999",
                    "platforms": {
                        "telegram": {"token": "T", "enabled": True},
                        "feishu": {"app_id": "A", "app_secret": "S", "enabled": False},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.nova_url == "http://localhost:9999"
    assert config.platform("telegram").options["token"] == "T"
    assert config.enabled_platforms() == ["telegram"]


def test_missing_credentials_disable_platform(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"gateway": {"platforms": {"telegram": {"enabled": True}}}}),
        encoding="utf-8",
    )
    config = load_config(path)
    adapters = build_adapters(config)
    assert adapters == {}
