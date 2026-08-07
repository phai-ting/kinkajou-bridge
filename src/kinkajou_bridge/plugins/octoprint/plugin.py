from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any
from urllib.parse import urlparse

from kinkajou_bridge.models import (
    ConfigField,
    ConfigSchema,
    ConnectionState,
    EventType,
    FieldType,
    PrinterCapabilities,
    PrinterEvent,
    PrinterStatus,
    PrintJob,
    PrintState,
    StreamInfo,
    Temperatures,
)
from kinkajou_bridge.plugins.base import VerifyResult


class OctoPrintPlugin:
    """OctoPrint host integration stub (REST/websocket to be implemented)."""

    id = "octoprint"
    name = "OctoPrint"
    compatible_service_ids: Sequence[str] = ()
    supports_standalone = True
    config_schema = ConfigSchema(
        id="octoprint",
        title="OctoPrint",
        description="Connect to an OctoPrint instance on your network.",
        hint=(
            "OctoPrint is a standalone host — no cloud service required. "
            "Use the OctoPrint URL and an Application API key from OctoPrint settings."
        ),
        test_connection=True,
        fields=[
            ConfigField(
                key="name",
                type=FieldType.STRING,
                label="Display name",
                required=True,
                placeholder="Workshop Ender",
                hint="A friendly name shown in Kinkajou Bridge, Streamer.bot args, and overlays.",
            ),
            ConfigField(
                key="base_url",
                type=FieldType.STRING,
                label="OctoPrint URL",
                required=True,
                placeholder="http://192.168.1.40",
                hint="Base URL of the OctoPrint web UI (include http:// or https://).",
                hint_detail=(
                    "Open OctoPrint in a browser and copy the address from the bar "
                    "(for example http://octopi.local or http://192.168.1.40).\n\n"
                    "Do not include a trailing path like /api/ — "
                    "Bridge will call the API itself.\n\n"
                    "Prefer a DHCP reservation or hostname so the address does not change."
                ),
            ),
            ConfigField(
                key="api_key",
                type=FieldType.SECRET,
                label="API key",
                required=True,
                hint="OctoPrint Application API key (Settings → API).",
                hint_detail=(
                    "In OctoPrint: Settings → API → Application Keys / User API keys "
                    "(wording varies by version).\n\n"
                    "Create or copy a key with permission to read printer and job status.\n\n"
                    "Keep this private — it can control the printer if write access is granted."
                ),
            ),
            ConfigField(
                key="stream_url",
                type=FieldType.STRING,
                label="Stream / webcam URL (optional)",
                required=False,
                placeholder="http://192.168.1.40/webcam/?action=stream",
                hint="Optional MJPEG or other viewer URL for overlays (not re-encoded by Bridge).",
            ),
        ],
    )

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._status = PrinterStatus(
            printer_id="unassigned",
            printer_name="OctoPrint",
            plugin_id=self.id,
            capabilities=PrinterCapabilities(thumbnail=False, live_stream=True, control=False),
        )
        self._event_queue: list[PrinterEvent] = []

    async def verify(self, config: Mapping[str, Any]) -> VerifyResult:
        base_url = str(config.get("base_url", "")).strip()
        api_key = str(config.get("api_key", "")).strip()
        if not base_url:
            return VerifyResult(ok=False, message="OctoPrint URL is required.")
        parsed = urlparse(base_url if "://" in base_url else f"http://{base_url}")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return VerifyResult(
                ok=False,
                message="OctoPrint URL must look like http://host or https://host.",
            )
        if not api_key:
            return VerifyResult(ok=False, message="API key is required.")
        return VerifyResult(
            ok=True,
            message="Configuration looks valid (live OctoPrint API check not implemented yet).",
            details={"base_url": f"{parsed.scheme}://{parsed.netloc}"},
        )

    async def connect(self, config: Mapping[str, Any]) -> None:
        self._config = dict(config)
        name = str(config.get("name") or "OctoPrint")
        base_url = str(config.get("base_url") or "").strip()
        if base_url and "://" not in base_url:
            base_url = f"http://{base_url}"
        stream_url = str(config.get("stream_url") or "").strip() or None
        printer_id = base_url or name
        self._status = self._status.model_copy(
            update={
                "printer_id": printer_id,
                "printer_name": name,
                "connection": ConnectionState.CONNECTED,
                "print_state": PrintState.IDLE,
                "job": PrintJob(),
                "temperatures": Temperatures(),
                "stream": StreamInfo(
                    available=bool(stream_url),
                    url=stream_url,
                    protocol="mjpeg" if stream_url else None,
                    notes="URL only — Bridge does not re-encode the stream.",
                ),
                "message": (
                    f"Session ready for OctoPrint at {base_url or 'unknown'}. "
                    "Live REST/websocket telemetry is not implemented yet — "
                    "values will populate once connected."
                ),
            }
        )
        self._event_queue.append(
            PrinterEvent(
                type=EventType.PRINTER_CONNECTED,
                printer_id=printer_id,
                printer_name=name,
                plugin_id=self.id,
                payload={"base_url": base_url or None, "connection_mode": "lan"},
            )
        )

    async def disconnect(self) -> None:
        self._status = self._status.model_copy(
            update={
                "connection": ConnectionState.DISCONNECTED,
                "print_state": PrintState.UNKNOWN,
                "message": None,
            }
        )
        self._event_queue.append(
            PrinterEvent(
                type=EventType.PRINTER_DISCONNECTED,
                printer_id=self._status.printer_id,
                printer_name=self._status.printer_name,
                plugin_id=self.id,
            )
        )

    def get_status(self) -> PrinterStatus:
        return self._status

    async def events(self) -> AsyncIterator[PrinterEvent]:
        while self._event_queue:
            yield self._event_queue.pop(0)
