from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

import httpx

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
from kinkajou_bridge.plugins.bambu.report import ReportTracker
from kinkajou_bridge.plugins.moonraker.status import (
    build_status,
    normalize_base_url,
    objects_query_path,
)

logger = logging.getLogger(__name__)

_EVENT_SENTINEL = object()
_POLL_INTERVAL_S = 2.0
_HTTP_TIMEOUT_S = 5.0
_CONNECT_WAIT_S = 8.0


class MoonrakerPlugin:
    """Moonraker / Klipper host integration (REST polling for printer + job status)."""

    id = "moonraker"
    name = "Moonraker (Klipper)"
    compatible_service_ids: Sequence[str] = ()
    supports_standalone = True
    config_schema = ConfigSchema(
        id="moonraker",
        title="Moonraker (Klipper)",
        description=(
            "Connect to a Moonraker API on your network (Fluidd, Mainsail, and many Klipper hosts)."
        ),
        hint=(
            "Use the Moonraker URL (often port 7125) and an API key unless this PC is a "
            "trusted client in moonraker.conf."
        ),
        examples=[
            "Mainsail / Fluidd",
            "Snapmaker U1 / Artisan (Moonraker)",
            "Voron and other Klipper printers",
        ],
        test_connection=True,
        fields=[
            ConfigField(
                key="name",
                type=FieldType.STRING,
                label="Display name",
                required=True,
                placeholder="Shop Voron",
                hint="A friendly name shown in Kinkajou Bridge, Streamer.bot args, and overlays.",
            ),
            ConfigField(
                key="base_url",
                type=FieldType.STRING,
                label="Moonraker URL",
                required=True,
                placeholder="http://192.168.1.40:7125",
                hint="Base URL of Moonraker (include http:// or https://; often port 7125).",
                hint_detail=(
                    "Open Fluidd or Mainsail and copy the host/port Moonraker uses, "
                    "or use http://PRINTER_IP:7125.\n\n"
                    "Do not include a path like /printer/ — Bridge calls the API itself.\n\n"
                    "Prefer a DHCP reservation or hostname so the address does not change."
                ),
            ),
            ConfigField(
                key="api_key",
                type=FieldType.SECRET,
                label="API key (optional)",
                required=False,
                hint=(
                    "Moonraker API key for untrusted clients. Leave blank if this PC is trusted."
                ),
                hint_detail=(
                    "In Moonraker / Mainsail / Fluidd, copy the API key from authorization "
                    "settings when Bridge is not listed as a trusted client.\n\n"
                    "Trusted clients (configured in moonraker.conf) can omit the key.\n\n"
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

    def __init__(
        self,
        *,
        poll_interval_seconds: float = _POLL_INTERVAL_S,
        connect_wait_seconds: float = _CONNECT_WAIT_S,
    ) -> None:
        self._config: dict[str, Any] = {}
        self._poll_interval = poll_interval_seconds
        self._connect_wait = connect_wait_seconds
        self._status = PrinterStatus(
            printer_id="unassigned",
            printer_name="Moonraker",
            plugin_id=self.id,
            capabilities=PrinterCapabilities(thumbnail=False, live_stream=True, control=False),
        )
        self._event_queue: asyncio.Queue[Any] = asyncio.Queue()
        self._stop = asyncio.Event()
        self._poll_task: asyncio.Task[None] | None = None
        self._client: httpx.AsyncClient | None = None
        self._session_active = False
        self._tracker = ReportTracker()
        self._connected_emitted = False

    async def verify(self, config: Mapping[str, Any]) -> VerifyResult:
        base_url = normalize_base_url(str(config.get("base_url", "")).strip())
        api_key = str(config.get("api_key", "")).strip()
        if not base_url:
            return VerifyResult(
                ok=False,
                message="Moonraker URL must look like http://host:7125 or https://host.",
            )

        headers = {"Accept": "application/json"}
        if api_key:
            headers["X-Api-Key"] = api_key

        try:
            async with httpx.AsyncClient(
                base_url=base_url,
                headers=headers,
                timeout=_HTTP_TIMEOUT_S,
            ) as client:
                response = await client.get("/server/info")
        except httpx.TimeoutException:
            return VerifyResult(
                ok=False,
                message=f"Timed out reaching Moonraker at {base_url}.",
            )
        except httpx.HTTPError as exc:
            return VerifyResult(
                ok=False,
                message=f"Could not reach Moonraker at {base_url}: {exc}",
            )

        if response.status_code in {401, 403}:
            return VerifyResult(
                ok=False,
                message=(
                    "Moonraker rejected the request (unauthorized). "
                    "Add an API key or trust this PC in moonraker.conf."
                ),
            )
        if response.status_code >= 400:
            return VerifyResult(
                ok=False,
                message=f"Moonraker returned HTTP {response.status_code} for /server/info.",
            )

        try:
            payload = response.json()
        except ValueError:
            payload = {}
        result = payload.get("result") if isinstance(payload, dict) else {}
        if not isinstance(result, dict):
            result = {}
        version = result.get("moonraker_version") or result.get("klippy_connected")
        label = f"Moonraker {version}" if version not in {None, True, False} else "Moonraker"
        return VerifyResult(
            ok=True,
            message=f"Connected to {label} at {base_url}.",
            details={"base_url": base_url, "server": result},
        )

    async def connect(self, config: Mapping[str, Any]) -> None:
        await self.disconnect()
        self._config = dict(config)
        self._stop = asyncio.Event()
        self._event_queue = asyncio.Queue()
        self._tracker = ReportTracker()
        self._connected_emitted = False
        self._session_active = True

        name = str(config.get("name") or "Moonraker")
        base_url = normalize_base_url(str(config.get("base_url") or ""))
        api_key = str(config.get("api_key") or "").strip()
        stream_url = str(config.get("stream_url") or "").strip() or None
        printer_id = base_url or name

        self._status = self._status.model_copy(
            update={
                "printer_id": printer_id,
                "printer_name": name,
                "connection": ConnectionState.CONNECTING,
                "print_state": PrintState.UNKNOWN,
                "job": PrintJob(),
                "temperatures": Temperatures(),
                "stream": StreamInfo(
                    available=bool(stream_url),
                    url=stream_url,
                    protocol="mjpeg" if stream_url else None,
                    notes="URL only — Bridge does not re-encode the stream." if stream_url else None,
                ),
                "message": f"Connecting to Moonraker at {base_url or 'unknown'}…",
            }
        )

        if not base_url:
            self._session_active = False
            self._status = self._status.model_copy(
                update={
                    "connection": ConnectionState.ERROR,
                    "message": "Moonraker URL is required.",
                }
            )
            self._enqueue_error("Moonraker URL is required.")
            self._event_queue.put_nowait(_EVENT_SENTINEL)
            return

        headers = {"Accept": "application/json"}
        if api_key:
            headers["X-Api-Key"] = api_key

        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=_HTTP_TIMEOUT_S,
        )
        self._poll_task = asyncio.create_task(
            self._poll_loop(),
            name=f"moonraker-poll-{printer_id}",
        )

        deadline = time.monotonic() + self._connect_wait
        while time.monotonic() < deadline:
            if self._status.connection in {ConnectionState.CONNECTED, ConnectionState.ERROR}:
                break
            await asyncio.sleep(0.05)

    async def disconnect(self) -> None:
        was_active = self._session_active
        self._session_active = False
        self._stop.set()
        task = self._poll_task
        self._poll_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("Moonraker poll task error during disconnect", exc_info=True)

        client = self._client
        self._client = None
        if client is not None:
            await client.aclose()

        if was_active:
            self._status = self._status.model_copy(
                update={
                    "connection": ConnectionState.DISCONNECTED,
                    "print_state": PrintState.UNKNOWN,
                    "message": None,
                }
            )
            self._enqueue(
                PrinterEvent(
                    type=EventType.PRINTER_DISCONNECTED,
                    printer_id=self._status.printer_id,
                    printer_name=self._status.printer_name,
                    plugin_id=self.id,
                )
            )
            self._event_queue.put_nowait(_EVENT_SENTINEL)

    def get_status(self) -> PrinterStatus:
        return self._status

    async def events(self) -> AsyncIterator[PrinterEvent]:
        while True:
            item = await self._event_queue.get()
            if item is _EVENT_SENTINEL:
                break
            yield item

    async def _poll_loop(self) -> None:
        assert self._client is not None
        base_url = normalize_base_url(str(self._config.get("base_url") or ""))
        stream_url = str(self._config.get("stream_url") or "").strip() or None
        name = self._status.printer_name
        printer_id = self._status.printer_id
        query_path = objects_query_path()

        while not self._stop.is_set():
            try:
                response = await self._client.get(query_path)
                if response.status_code in {401, 403}:
                    raise PermissionError(
                        "Moonraker rejected the request (unauthorized). "
                        "Add an API key or trust this PC."
                    )
                response.raise_for_status()
                payload = response.json()
                result = payload.get("result") if isinstance(payload, dict) else {}
                objects = result.get("status") if isinstance(result, dict) else {}
                if not isinstance(objects, dict):
                    objects = {}

                previous = self._status
                next_status = build_status(
                    printer_id=printer_id,
                    printer_name=name,
                    plugin_id=self.id,
                    objects=objects,
                    stream_url=stream_url,
                    message=f"Live via Moonraker at {base_url}",
                )
                events = self._tracker.events_for_update(
                    printer_id=printer_id,
                    printer_name=name,
                    plugin_id=self.id,
                    previous_status=previous,
                    next_status=next_status,
                )
                self._status = next_status
                if not self._connected_emitted:
                    self._connected_emitted = True
                    self._enqueue(
                        PrinterEvent(
                            type=EventType.PRINTER_CONNECTED,
                            printer_id=printer_id,
                            printer_name=name,
                            plugin_id=self.id,
                            payload={
                                "base_url": base_url or None,
                                "connection_mode": "lan",
                            },
                        )
                    )
                for event in events:
                    self._enqueue(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Moonraker poll failed (%s): %s", base_url, exc)
                self._status = self._status.model_copy(
                    update={
                        "connection": ConnectionState.ERROR,
                        "message": (
                            f"Moonraker unreachable at {base_url}: {exc}. "
                            f"Retrying every {int(self._poll_interval)}s."
                        ),
                    }
                )

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_interval)
                break
            except TimeoutError:
                continue

    def _enqueue(self, event: PrinterEvent) -> None:
        self._event_queue.put_nowait(event)

    def _enqueue_error(self, message: str) -> None:
        self._enqueue(
            PrinterEvent(
                type=EventType.PRINTER_ERROR,
                printer_id=self._status.printer_id,
                printer_name=self._status.printer_name,
                plugin_id=self.id,
                payload={"error": message},
            )
        )
