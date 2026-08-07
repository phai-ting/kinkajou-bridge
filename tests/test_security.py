from __future__ import annotations

from kinkajou_bridge.models import ConfigField, ConfigSchema, FieldType
from kinkajou_bridge.security import REDACTED, is_sensitive_key, redact_config


def test_redact_config_uses_schema_secrets() -> None:
    schema = ConfigSchema(
        id="demo",
        title="Demo",
        fields=[
            ConfigField(key="name", type=FieldType.STRING, label="Name"),
            ConfigField(key="cloud_token", type=FieldType.SECRET, label="Token"),
        ],
    )
    result = redact_config(
        {"name": "Bambu", "cloud_token": "super-secret", "_service_config": {"x": 1}},
        schema=schema,
    )
    assert result["name"] == "Bambu"
    assert result["cloud_token"] == REDACTED
    assert "_service_config" not in result


def test_redact_config_fallback_key_names() -> None:
    result = redact_config({"host": "1.2.3.4", "access_code": "abcd1234", "password": "x"})
    assert result["host"] == "1.2.3.4"
    assert result["access_code"] == REDACTED
    assert result["password"] == REDACTED


def test_is_sensitive_key() -> None:
    assert is_sensitive_key("cloud_token")
    assert is_sensitive_key("lan_access_code")
    assert is_sensitive_key("_internal")
    assert not is_sensitive_key("serial")
    assert not is_sensitive_key("host")
