from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class FieldType(StrEnum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    SECRET = "secret"
    SELECT = "select"


class SelectOption(BaseModel):
    value: str
    label: str


class ConfigField(BaseModel):
    key: str
    type: FieldType
    label: str
    required: bool = False
    default: Any | None = None
    placeholder: str | None = None
    description: str | None = None
    hint: str | None = None
    hint_detail: str | None = None
    help_url: str | None = None
    options: list[SelectOption] = Field(default_factory=list)
    visible_when: dict[str, str] = Field(default_factory=dict)


class ConfigSchema(BaseModel):
    """Declarative form schema rendered by the Kinkajou Bridge UI."""

    id: str
    title: str
    description: str = ""
    hint: str | None = None
    setup_help: list[str] = Field(default_factory=list)
    setup_help_url: str | None = None
    fields: list[ConfigField] = Field(default_factory=list)
    test_connection: bool = True
