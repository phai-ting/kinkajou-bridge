from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EventType(StrEnum):
    PRINTER_CONNECTED = "printer.connected"
    PRINTER_DISCONNECTED = "printer.disconnected"
    PRINTER_ERROR = "printer.error"
    PRINT_STARTED = "print.started"
    PRINT_PAUSED = "print.paused"
    PRINT_RESUMED = "print.resumed"
    PRINT_FINISHED = "print.finished"
    PRINT_FAILED = "print.failed"
    PRINT_CANCELLED = "print.cancelled"
    LAYER_CHANGED = "print.layer_changed"
    PROGRESS = "print.progress"
    STATUS = "printer.status"


class PrinterEvent(BaseModel):
    type: EventType
    printer_id: str
    printer_name: str
    plugin_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
