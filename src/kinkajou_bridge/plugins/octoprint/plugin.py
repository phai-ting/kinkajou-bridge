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
from kinkajou_bridge.plugins.octoprint.status import build_status, normalize_base_url

logger = logging.getLogger(__name__)

_EVENT_SENTINEL = object()
_POLL_INTERVAL_S = 2.0
_HTTP_TIMEOUT_S = 5.0
_CONNECT_WAIT_S = 8.0


class OctoPrintPlugin:
    """OctoPrint host integration (REST polling for printer + job status)."""

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
            printer_name="OctoPrint",
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
                message="OctoPrint URL must look like http://host or https://host.",
            )
        if not api_key:
            return VerifyResult(ok=False, message="API key is required.")

        try:
            async with httpx.AsyncClient(
                base_url=base_url,
                headers={"X-Api-Key": api_key, "Accept": "application/json"},
                timeout=_HTTP_TIMEOUT_S,
            ) as client:
                response = await client.get("/api/version")
        except httpx.TimeoutException:
            return VerifyResult(
                ok=False,
                message=f"Timed out reaching OctoPrint at {base_url}.",
            )
        except httpx.HTTPError as exc:
            return VerifyResult(
                ok=False,
                message=f"Could not reach OctoPrint at {base_url}: {exc}",
            )

        if response.status_code in {401, 403}:
            return VerifyResult(
                ok=False,
                message="OctoPrint rejected the API key (unauthorized).",
            )
        if response.status_code >= 400:
            return VerifyResult(
                ok=False,
                message=f"OctoPrint returned HTTP {response.status_code} for /api/version.",
            )

        try:
            payload = response.json()
        except ValueError:
            payload = {}
        server = payload.get("server") or payload.get("text") or "unknown"
        return VerifyResult(
            ok=True,
            message=f"Connected to OctoPrint ({server}) at {base_url}.",
            details={"base_url": base_url, "server": server, "api": payload.get("api")},
        )

    async def connect(self, config: Mapping[str, Any]) -> None:
        await self.disconnect()
        self._config = dict(config)
        self._stop = asyncio.Event()
        self._event_queue = asyncio.Queue()
        self._tracker = ReportTracker()
        self._connected_emitted = False
        self._session_active = True

        name = str(config.get("name") or "OctoPrint")
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
                "message": f"Connecting to OctoPrint at {base_url or 'unknown'}…",
            }
        )

        if not base_url or not api_key:
            self._session_active = False
            self._status = self._status.model_copy(
                update={
                    "connection": ConnectionState.ERROR,
                    "message": "OctoPrint URL and API key are required.",
                }
            )
            self._enqueue_error("OctoPrint URL and API key are required.")
            self._event_queue.put_nowait(_EVENT_SENTINEL)
            return

        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-Api-Key": api_key, "Accept": "application/json"},
            timeout=_HTTP_TIMEOUT_S,
        )
        self._poll_task = asyncio.create_task(
            self._poll_loop(),
            name=f"octoprint-poll-{printer_id}",
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
                logger.debug("OctoPrint poll task error during disconnect", exc_info=True)

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

        while not self._stop.is_set():
            try:
                printer_resp, job_resp = await asyncio.gather(
                    self._client.get("/api/printer"),
                    self._client.get("/api/job"),
                )
                if printer_resp.status_code in {401, 403} or job_resp.status_code in {401, 403}:
                    raise PermissionError("OctoPrint rejected the API key (unauthorized).")
                printer_resp.raise_for_status()
                job_resp.raise_for_status()
                printer_payload = printer_resp.json()
                job_payload = job_resp.json()

                previous = self._status
                next_status = build_status(
                    printer_id=printer_id,
                    printer_name=name,
                    plugin_id=self.id,
                    printer_payload=printer_payload if isinstance(printer_payload, dict) else {},
                    job_payload=job_payload if isinstance(job_payload, dict) else {},
                    stream_url=stream_url,
                    message=f"Live via OctoPrint at {base_url}",
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
                logger.warning("OctoPrint poll failed (%s): %s", base_url, exc)
                self._status = self._status.model_copy(
                    update={
                        "connection": ConnectionState.ERROR,
                        "message": (
                            f"OctoPrint unreachable at {base_url}: {exc}. "
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
