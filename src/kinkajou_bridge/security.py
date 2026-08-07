from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from kinkajou_bridge.models import ConfigSchema, FieldType

REDACTED = "***"

# Fallback names when schema is unavailable (third-party / legacy configs).
_SENSITIVE_KEY_FRAGMENTS = (
    "token",
    "password",
    "secret",
    "access_code",
    "accesscode",
    "api_key",
    "apikey",
    "auth",
    "credential",
    "cookie",
)


def secret_keys_from_schema(schema: ConfigSchema | None) -> set[str]:
    if schema is None:
        return set()
    return {field.key for field in schema.fields if field.type == FieldType.SECRET}


def is_sensitive_key(key: str, secret_keys: Iterable[str] | None = None) -> bool:
    if key.startswith("_"):
        return True
    if secret_keys is not None and key in secret_keys:
        return True
    lowered = key.lower().replace("-", "_")
    return any(fragment in lowered for fragment in _SENSITIVE_KEY_FRAGMENTS)


def redact_config(
    config: Mapping[str, Any] | None,
    *,
    schema: ConfigSchema | None = None,
    secret_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return a copy of config safe for API responses.

    Secret / internal values that are set become ``\"***\"``; empty secrets are omitted.
    Non-secret fields are passed through unchanged.
    """
    if not config:
        return {}
    keys = set(secret_keys or ()) | secret_keys_from_schema(schema)
    redacted: dict[str, Any] = {}
    for key, value in config.items():
        if key.startswith("_"):
            continue
        if is_sensitive_key(key, keys):
            if value not in (None, ""):
                redacted[key] = REDACTED
            continue
        redacted[key] = value
    return redacted


def merge_config_preserving_secrets(
    existing: Mapping[str, Any] | None,
    incoming: Mapping[str, Any],
    *,
    schema: ConfigSchema | None = None,
) -> dict[str, Any]:
    """Merge update config, keeping prior secrets when the client sends blank or ``***``."""
    keys = secret_keys_from_schema(schema)
    merged = dict(incoming)
    prior = dict(existing or {})
    for key in keys | {k for k in prior if is_sensitive_key(k, keys)}:
        new_value = merged.get(key)
        if new_value in (None, "", REDACTED) and key in prior and prior[key] not in (None, ""):
            merged[key] = prior[key]
    return merged
