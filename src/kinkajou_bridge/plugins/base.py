from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from kinkajou_bridge.models import (
    ConfigSchema,
    DiscoveredDevice,
    IntegrationStatus,
    PrinterEvent,
    PrinterStatus,
    ServiceStatus,
)


class VerifyResult(BaseModel):
    ok: bool
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class ServicePlugin(Protocol):
    """Contract for account / hub connections (auth + device discovery)."""

    id: str
    name: str
    config_schema: ConfigSchema

    async def verify(self, config: Mapping[str, Any]) -> VerifyResult:
        """Validate credentials without starting a long session."""

    async def connect(self, config: Mapping[str, Any]) -> None:
        """Establish a live service session."""

    async def disconnect(self) -> None:
        """Tear down the service session."""

    def get_status(self) -> ServiceStatus:
        """Return the latest service status snapshot."""

    def list_devices(self) -> Sequence[DiscoveredDevice]:
        """Return devices discoverable through this connected service."""


@runtime_checkable
class PrinterPlugin(Protocol):
    """Contract implemented by printer device plugins."""

    id: str
    name: str
    config_schema: ConfigSchema
    compatible_service_ids: Sequence[str]
    supports_standalone: bool

    async def verify(self, config: Mapping[str, Any]) -> VerifyResult:
        """Validate credentials / reachability without starting a long session."""

    async def connect(self, config: Mapping[str, Any]) -> None:
        """Establish a live session for one printer instance."""

    async def disconnect(self) -> None:
        """Tear down the session."""

    def get_status(self) -> PrinterStatus:
        """Return the latest normalized status snapshot."""

    def events(self) -> AsyncIterator[PrinterEvent]:
        """Yield normalized printer events for as long as the session is active."""


@runtime_checkable
class IntegrationPlugin(Protocol):
    """Contract for outbound tools that consume Bridge events (e.g. Streamer.bot)."""

    id: str
    name: str
    config_schema: ConfigSchema

    async def verify(self, config: Mapping[str, Any]) -> VerifyResult:
        """Validate configuration without starting a long session."""

    async def connect(self, config: Mapping[str, Any]) -> None:
        """Establish a live integration session."""

    async def disconnect(self) -> None:
        """Tear down the session."""

    def get_status(self) -> IntegrationStatus:
        """Return the latest integration status snapshot."""

    async def handle_event(self, event: PrinterEvent) -> None:
        """Handle a normalized printer event from Bridge."""
