from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ConnectionState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class PrintState(StrEnum):
    UNKNOWN = "unknown"
    IDLE = "idle"
    PREPARING = "preparing"
    PRINTING = "printing"
    PAUSED = "paused"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    FAILED = "failed"
    ERROR = "error"


class Temperatures(BaseModel):
    nozzle_c: float | None = None
    nozzle_target_c: float | None = None
    bed_c: float | None = None
    bed_target_c: float | None = None
    chamber_c: float | None = None


class PrintJob(BaseModel):
    name: str | None = None
    progress: float | None = Field(default=None, ge=0, le=100)
    remaining_seconds: int | None = None
    elapsed_seconds: int | None = None
    total_seconds: int | None = None
    layer_current: int | None = None
    layer_total: int | None = None
    file_name: str | None = None


class StreamInfo(BaseModel):
    available: bool = False
    url: str | None = None
    snapshot_url: str | None = None
    protocol: str | None = None
    notes: str | None = None


class PrinterCapabilities(BaseModel):
    thumbnail: bool = False
    live_stream: bool = False
    control: bool = False


class PrinterStatus(BaseModel):
    printer_id: str
    printer_name: str
    plugin_id: str
    connection: ConnectionState = ConnectionState.DISCONNECTED
    print_state: PrintState = PrintState.UNKNOWN
    job: PrintJob = Field(default_factory=PrintJob)
    temperatures: Temperatures = Field(default_factory=Temperatures)
    capabilities: PrinterCapabilities = Field(default_factory=PrinterCapabilities)
    stream: StreamInfo = Field(default_factory=StreamInfo)
    message: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ServiceStatus(BaseModel):
    service_id: str
    service_name: str
    plugin_id: str
    connection: ConnectionState = ConnectionState.DISCONNECTED
    message: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DiscoveredDevice(BaseModel):
    id: str
    name: str
    model: str | None = None
    serial: str | None = None
    hints: dict[str, str] = Field(default_factory=dict)


class IntegrationStatus(BaseModel):
    integration_id: str
    integration_name: str
    plugin_id: str
    connection: ConnectionState = ConnectionState.DISCONNECTED
    message: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
