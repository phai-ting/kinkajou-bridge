from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from kinkajou_bridge.models import (
    ConfigField,
    ConfigSchema,
    ConnectionState,
    FieldType,
    IntegrationStatus,
    PrinterEvent,
)
from kinkajou_bridge.plugins.base import VerifyResult
from kinkajou_bridge.streamerbot.client import StreamerBotClient

logger = logging.getLogger(__name__)


class StreamerBotPlugin:
    """Outbound Streamer.bot integration (DoAction on printer events)."""

    id = "streamerbot"
    name = "Streamer.bot"
    config_schema = ConfigSchema(
        id="streamerbot",
        title="Streamer.bot",
        description=(
            "Forward events from every printer in Bridge to Streamer.bot — "
            "across all cloud services and standalone / LAN printers — "
            "via its local WebSocket API."
        ),
        setup_help=[
            "In Streamer.bot, open Servers/Clients → WebSocket Server.",
            "Confirm the server is running (Start), or enable Auto Start so it comes up with Streamer.bot.",
            "Copy Address into Host (use 127.0.0.1 when Bridge runs on the same PC — even if Address is 0.0.0.0).",
            "Copy Port and Endpoint into the matching fields (defaults are often 8080 and /).",
            "If Authentication is enabled, copy the Password; leave it blank otherwise.",
        ],
        setup_help_url="https://docs.streamer.bot/api/websocket/guide/configuration",
        test_connection=True,
        fields=[
            ConfigField(
                key="host",
                type=FieldType.STRING,
                label="Host",
                required=True,
                default="127.0.0.1",
                placeholder="127.0.0.1",
                hint="Usually localhost when Streamer.bot runs on the same PC.",
            ),
            ConfigField(
                key="port",
                type=FieldType.NUMBER,
                label="Port",
                required=True,
                default=8080,
                placeholder="8080",
                hint="Streamer.bot WebSocket Server port (default 8080).",
            ),
            ConfigField(
                key="endpoint",
                type=FieldType.STRING,
                label="Endpoint path",
                required=True,
                default="/",
                placeholder="/",
                hint="WebSocket path from Streamer.bot settings (often `/`).",
            ),
            ConfigField(
                key="password",
                type=FieldType.SECRET,
                label="Password",
                required=False,
                hint="Optional WebSocket password if configured in Streamer.bot.",
            ),
        ],
    )

    def __init__(self) -> None:
        self._client: StreamerBotClient | None = None
        self._status = IntegrationStatus(
            integration_id="unassigned",
            integration_name="Streamer.bot",
            plugin_id=self.id,
        )

    async def verify(self, config: Mapping[str, Any]) -> VerifyResult:
        host = str(config.get("host", "")).strip()
        if not host:
            return VerifyResult(ok=False, message="Host is required.")
        try:
            port = int(config.get("port", 8080))
        except (TypeError, ValueError):
            return VerifyResult(ok=False, message="Port must be a number.")
        if port < 1 or port > 65535:
            return VerifyResult(ok=False, message="Port must be between 1 and 65535.")
        return VerifyResult(
            ok=True,
            message="Configuration looks valid (live WebSocket check happens on connect).",
            details={"host": host, "port": port},
        )

    async def connect(self, config: Mapping[str, Any]) -> None:
        name = "Streamer.bot"
        host = str(config.get("host") or "127.0.0.1").strip()
        port = int(config.get("port") or 8080)
        endpoint = str(config.get("endpoint") or "/")
        password = str(config.get("password") or "").strip() or None
        self._status = IntegrationStatus(
            integration_id=self.id,
            integration_name=name,
            plugin_id=self.id,
            connection=ConnectionState.CONNECTING,
            message=f"Connecting to ws://{host}:{port}{endpoint}…",
        )
        client = StreamerBotClient(
            host=host,
            port=port,
            endpoint=endpoint,
            password=password,
        )
        try:
            await client.connect()
        except Exception as exc:
            logger.warning("Streamer.bot connect failed: %s", exc)
            self._client = None
            self._status = self._status.model_copy(
                update={
                    "connection": ConnectionState.ERROR,
                    "message": (
                        f"Could not connect to Streamer.bot at {client.url}: {exc}. "
                        "Bridge will keep the integration; start Streamer.bot and restart "
                        "Bridge or re-save to retry."
                    ),
                }
            )
            return
        self._client = client
        self._status = self._status.model_copy(
            update={
                "connection": ConnectionState.CONNECTED,
                "message": (
                    f"Connected to {client.url}. Events from all printers "
                    "(every service and standalone host) forward as Kinkajou.* actions."
                ),
            }
        )

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
        self._status = self._status.model_copy(
            update={
                "connection": ConnectionState.DISCONNECTED,
                "message": None,
            }
        )

    def get_status(self) -> IntegrationStatus:
        return self._status

    async def handle_event(self, event: PrinterEvent) -> None:
        if self._client is None or self._client._ws is None:
            return
        action_name = f"Kinkajou.{event.type.value}"
        try:
            args: dict[str, Any] = {
                "printer_id": event.printer_id,
                "printer_name": event.printer_name,
                "plugin_id": event.plugin_id,
                "event_type": event.type.value,
                **event.payload,
            }
            await self._client.do_action(name=action_name, args=args)
        except Exception:
            logger.exception(
                "Failed to forward event to Streamer.bot action %s", action_name
            )
            self._status = self._status.model_copy(
                update={
                    "connection": ConnectionState.ERROR,
                    "message": f"Failed to send DoAction {action_name}",
                }
            )
