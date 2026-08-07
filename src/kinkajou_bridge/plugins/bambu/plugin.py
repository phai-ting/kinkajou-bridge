from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from kinkajou_bridge.models import (
    ConfigField,
    ConfigSchema,
    ConnectionState,
    DiscoveredDevice,
    EventType,
    FieldType,
    PrinterCapabilities,
    PrinterEvent,
    PrinterStatus,
    PrintJob,
    PrintState,
    SelectOption,
    ServiceStatus,
    Temperatures,
)
from kinkajou_bridge.plugins.bambu.cloud import (
    fetch_bound_devices,
    fetch_user_id,
    normalize_cloud_token,
)
from kinkajou_bridge.plugins.bambu.mqtt_session import (
    cloud_endpoint,
    lan_endpoint,
    run_mqtt_session,
)
from kinkajou_bridge.plugins.bambu.report import (
    ReportTracker,
    apply_print_snapshot,
    merge_print_payload,
)
from kinkajou_bridge.plugins.base import VerifyResult

logger = logging.getLogger(__name__)

_EVENT_SENTINEL = object()
_CONNECT_TIMEOUT_S = 20.0


class BambuCloudService:
    """Bambu Lab cloud account connection (auth + device discovery)."""

    id = "bambu_cloud"
    name = "Bambu Lab"
    config_schema = ConfigSchema(
        id="bambu_cloud",
        title="Bambu Lab Cloud",
        description="Connect your Bambu Lab account once, then pick printers from the device list.",
        hint=(
            "Connect the Bambu Lab service with a cloud access token. After that, add printers "
            "via Cloud via service without re-entering the token for each machine."
        ),
        test_connection=True,
        fields=[
            ConfigField(
                key="name",
                type=FieldType.STRING,
                label="Display name",
                required=True,
                default="Bambu Lab",
                placeholder="Bambu Lab",
                hint="A friendly name for this account connection in Bridge.",
            ),
            ConfigField(
                key="cloud_token",
                type=FieldType.SECRET,
                label="Cloud access token",
                required=True,
                hint=(
                    "Used for Bambu cloud MQTT and device listing. A guided login flow will "
                    "replace raw tokens later."
                ),
                hint_detail=(
                    "For now, paste an access token from your Bambu account / developer tools "
                    "if you already have one.\n\n"
                    "A future Bridge update will walk you through signing in so you do not need "
                    "to copy tokens manually.\n\n"
                    "Keep this private — anyone with the token can access your "
                    "cloud-linked printers."
                ),
            ),
            ConfigField(
                key="region",
                type=FieldType.SELECT,
                label="Cloud region",
                required=True,
                default="global",
                hint="Use China if your Bambu account is on the CN cloud.",
                options=[
                    SelectOption(value="global", label="Global"),
                    SelectOption(value="cn", label="China"),
                ],
            ),
        ],
    )

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._devices: list[DiscoveredDevice] = []
        self._status = ServiceStatus(
            service_id="unassigned",
            service_name="Bambu Lab",
            plugin_id=self.id,
        )

    async def verify(self, config: Mapping[str, Any]) -> VerifyResult:
        token = str(config.get("cloud_token", "")).strip()
        if not token:
            return VerifyResult(ok=False, message="Cloud access token is required.")
        region = str(config.get("region") or "global")
        try:
            devices = fetch_bound_devices(token, region=region)
            user_id = fetch_user_id(token, region=region)
        except Exception as exc:
            logger.warning("Bambu cloud verify failed: %s", exc)
            return VerifyResult(
                ok=False,
                message=f"Could not reach Bambu Lab cloud: {exc}",
            )
        return VerifyResult(
            ok=True,
            message=(
                f"Bambu Lab cloud OK — {len(devices)} printer(s) on this account "
                f"(MQTT user u_{user_id})."
            ),
            details={"device_count": len(devices), "user_id": user_id},
        )

    async def connect(self, config: Mapping[str, Any]) -> None:
        self._config = dict(config)
        name = str(config.get("name") or "Bambu Lab")
        token = str(config.get("cloud_token") or "").strip()
        region = str(config.get("region") or "global")
        message = "Bambu Lab service connected."
        self._devices = []
        try:
            self._devices = fetch_bound_devices(token, region=region)
            message = (
                f"Bambu Lab connected — {len(self._devices)} printer(s) available "
                "via Cloud via service."
            )
        except Exception as exc:
            logger.warning("Bambu device listing failed on connect: %s", exc)
            message = (
                f"Bambu Lab connected, but device listing failed: {exc}. "
                "You can retry from the printer setup screen."
            )
        self._status = ServiceStatus(
            service_id=self.id,
            service_name=name,
            plugin_id=self.id,
            connection=ConnectionState.CONNECTED,
            message=message,
        )

    async def disconnect(self) -> None:
        self._status = self._status.model_copy(
            update={
                "connection": ConnectionState.DISCONNECTED,
                "message": None,
            }
        )
        self._config = {}
        self._devices = []

    def get_status(self) -> ServiceStatus:
        return self._status

    def list_devices(self) -> Sequence[DiscoveredDevice]:
        """Return printers bound to this Bambu Lab cloud account."""
        token = str(self._config.get("cloud_token") or "").strip()
        if not token:
            return []
        region = str(self._config.get("region") or "global")
        try:
            self._devices = fetch_bound_devices(token, region=region)
            self._status = self._status.model_copy(
                update={
                    "message": (
                        f"Bambu Lab connected — {len(self._devices)} printer(s) available "
                        "via Cloud via service."
                    )
                }
            )
        except Exception as exc:
            logger.warning("Bambu device listing failed: %s", exc)
            self._status = self._status.model_copy(
                update={"message": f"Device listing failed: {exc}"}
            )
            return list(self._devices)
        return list(self._devices)

    def get_credentials(self) -> dict[str, Any]:
        """Credentials injected into printer sessions bound to this service."""
        return {"cloud_token": self._config.get("cloud_token", "")}


class BambuPlugin:
    """Bambu Lab printer: service-bound cloud or standalone LAN with live MQTT."""

    id = "bambu"
    name = "Bambu Lab Printer"
    compatible_service_ids: Sequence[str] = ("bambu_cloud",)
    supports_standalone = True
    config_schema = ConfigSchema(
        id="bambu",
        title="Bambu Lab Printer",
        description="Add a Bambu printer from a connected Bambu Lab service or via LAN.",
        hint=(
            "Prefer Cloud via service after connecting the Bambu Lab service. "
            "Use LAN mode only if the printer is in LAN Only / Developer Mode."
        ),
        test_connection=True,
        fields=[
            ConfigField(
                key="connection_mode",
                type=FieldType.SELECT,
                label="Connection source",
                required=True,
                default="service",
                hint=(
                    "From Bambu Lab uses a connected cloud service. "
                    "LAN needs the printer's IP and access code."
                ),
                options=[
                    SelectOption(value="service", label="From Bambu Lab (cloud)"),
                    SelectOption(value="lan", label="Local / LAN"),
                ],
            ),
            ConfigField(
                key="name",
                type=FieldType.STRING,
                label="Display name",
                required=True,
                placeholder="Living Room P1S",
                hint="A friendly name shown in Kinkajou Bridge, Streamer.bot args, and overlays.",
            ),
            ConfigField(
                key="serial",
                type=FieldType.STRING,
                label="Printer serial",
                required=True,
                placeholder="01P09C123456789",
                hint="Unique device ID for this printer (not your Bambu account email).",
                hint_detail=(
                    "On the printer: Settings → Device → Device info (wording varies by model) "
                    "and look for Serial / Device SN.\n\n"
                    "In Bambu Studio or Bambu Handy: open the printer’s device page; the serial "
                    "is listed in device details.\n\n"
                    "When adding via Cloud via service, pick a printer from your connected "
                    "Bambu Lab account instead of typing the serial."
                ),
                help_url="https://kinkajou.dev/bridge/",
            ),
            ConfigField(
                key="host",
                type=FieldType.STRING,
                label="Printer IP",
                required=True,
                placeholder="192.168.1.50",
                visible_when={"connection_mode": "lan"},
                hint="Only needed for LAN mode. Use the printer’s local network address.",
                hint_detail=(
                    "On the printer touchscreen: open network / Wi‑Fi settings and note the IP "
                    "address (often looks like 192.168.x.x).\n\n"
                    "Prefer a DHCP reservation so the IP does not change."
                ),
            ),
            ConfigField(
                key="access_code",
                type=FieldType.SECRET,
                label="LAN access code",
                required=True,
                visible_when={"connection_mode": "lan"},
                hint=(
                    "Only needed for LAN mode. This is the printer LAN access code, "
                    "not your Bambu password."
                ),
                hint_detail=(
                    "On the printer: Settings → Network / LAN (wording varies) and find "
                    "Access Code / LAN Access Code. It is typically an 8-character code.\n\n"
                    "If you re-bind the printer or change LAN settings, the code may change — "
                    "update it here if the connection stops working."
                ),
            ),
        ],
    )

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._status = PrinterStatus(
            printer_id="unassigned",
            printer_name="Bambu",
            plugin_id=self.id,
            capabilities=PrinterCapabilities(thumbnail=True, live_stream=True, control=False),
        )
        self._event_queue: asyncio.Queue[Any] = asyncio.Queue()
        self._mqtt_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._mqtt_ready = asyncio.Event()
        self._print_snapshot: dict[str, Any] = {}
        self._tracker = ReportTracker()
        self._session_active = False

    def _enqueue(self, event: PrinterEvent) -> None:
        self._event_queue.put_nowait(event)

    def _resolve_endpoint(self, config: Mapping[str, Any]):
        serial = str(config.get("serial") or "").strip()
        mode = str(config.get("connection_mode", "service"))
        if mode == "lan":
            return lan_endpoint(
                host=str(config.get("host") or "").strip(),
                serial=serial,
                access_code=str(config.get("access_code") or "").strip(),
            )
        token = normalize_cloud_token(str(config.get("cloud_token") or ""))
        region = str(config.get("region") or "global")
        service_cfg = config.get("_service_config")
        if isinstance(service_cfg, dict):
            if not token:
                token = normalize_cloud_token(str(service_cfg.get("cloud_token") or ""))
            if not config.get("region") and service_cfg.get("region"):
                region = str(service_cfg.get("region") or "global")
        user_id = str(config.get("_cloud_user_id") or "").strip()
        if not user_id:
            user_id = fetch_user_id(token, region=region)
        return cloud_endpoint(
            serial=serial,
            cloud_token=token,
            user_id=user_id,
            region=region,
        )

    async def verify(self, config: Mapping[str, Any]) -> VerifyResult:
        mode = str(config.get("connection_mode", "service"))
        serial = str(config.get("serial", "")).strip()
        if not serial:
            return VerifyResult(ok=False, message="Printer serial is required.")
        if mode == "lan":
            if not str(config.get("host", "")).strip():
                return VerifyResult(ok=False, message="Printer IP is required for LAN mode.")
            if not str(config.get("access_code", "")).strip():
                return VerifyResult(ok=False, message="LAN access code is required.")
            return VerifyResult(
                ok=True,
                message="LAN configuration looks valid. Bridge will open MQTT on connect.",
                details={"mode": mode, "serial": serial},
            )
        if mode in {"service", "cloud"}:
            token = normalize_cloud_token(str(config.get("cloud_token", "")))
            has_service = bool(config.get("_service_config") or config.get("_service_instance_id"))
            if mode == "service" and not has_service and not token:
                return VerifyResult(
                    ok=False,
                    message="Select a connected Bambu Lab service, or connect one first.",
                )
            if mode == "cloud" and not token and not has_service:
                return VerifyResult(ok=False, message="Cloud access token is required.")
            if not token and isinstance(config.get("_service_config"), dict):
                token = normalize_cloud_token(
                    str(config["_service_config"].get("cloud_token") or "")
                )
            region = str(config.get("region") or "global")
            if isinstance(config.get("_service_config"), dict) and not config.get("region"):
                region = str(config["_service_config"].get("region") or region)
            if token:
                try:
                    user_id = fetch_user_id(token, region=region)
                except Exception as exc:
                    return VerifyResult(
                        ok=False,
                        message=f"Could not resolve Bambu cloud user for MQTT: {exc}",
                    )
                return VerifyResult(
                    ok=True,
                    message=f"Cloud configuration OK for MQTT (user u_{user_id}).",
                    details={"mode": mode, "serial": serial, "user_id": user_id},
                )
            return VerifyResult(
                ok=True,
                message="Configuration looks valid.",
                details={"mode": mode, "serial": serial},
            )
        return VerifyResult(ok=False, message=f"Unknown connection mode: {mode}")

    async def connect(self, config: Mapping[str, Any]) -> None:
        await self.disconnect()
        self._config = dict(config)
        self._stop = asyncio.Event()
        self._mqtt_ready = asyncio.Event()
        self._event_queue = asyncio.Queue()
        self._print_snapshot = {}
        self._tracker = ReportTracker()
        self._session_active = True

        name = str(config.get("name") or config.get("serial") or "Bambu")
        serial = str(config.get("serial") or "unknown")
        mode = str(config.get("connection_mode", "service"))
        host = str(config.get("host") or "").strip()
        if mode == "lan":
            mode_label = f"LAN ({host})" if host else "LAN"
        elif mode == "service" or config.get("_service_instance_id"):
            mode_label = "Bambu Lab cloud"
        else:
            mode_label = "Cloud (legacy)"

        self._status = self._status.model_copy(
            update={
                "printer_id": serial,
                "printer_name": name,
                "connection": ConnectionState.CONNECTING,
                "print_state": PrintState.UNKNOWN,
                "job": PrintJob(),
                "temperatures": Temperatures(),
                "message": f"Connecting MQTT for {serial} via {mode_label}…",
            }
        )

        try:
            endpoint = self._resolve_endpoint(config)
        except Exception as exc:
            self._session_active = False
            self._status = self._status.model_copy(
                update={
                    "connection": ConnectionState.ERROR,
                    "message": f"MQTT setup failed: {exc}",
                }
            )
            self._enqueue(
                PrinterEvent(
                    type=EventType.PRINTER_ERROR,
                    printer_id=serial,
                    printer_name=name,
                    plugin_id=self.id,
                    payload={"error": str(exc)},
                )
            )
            self._event_queue.put_nowait(_EVENT_SENTINEL)
            raise

        self._mqtt_task = asyncio.create_task(
            self._mqtt_loop(endpoint),
            name=f"bambu-mqtt-{serial}",
        )
        try:
            await asyncio.wait_for(self._mqtt_ready.wait(), timeout=_CONNECT_TIMEOUT_S)
        except TimeoutError as exc:
            await self.disconnect()
            raise TimeoutError(
                f"Timed out waiting for Bambu MQTT ({endpoint.label}). "
                "Check network, serial, and credentials."
            ) from exc

        if self._status.connection == ConnectionState.ERROR:
            message = self._status.message or "MQTT connection failed"
            await self.disconnect()
            raise ConnectionError(message)

        self._enqueue(
            PrinterEvent(
                type=EventType.PRINTER_CONNECTED,
                printer_id=serial,
                printer_name=name,
                plugin_id=self.id,
                payload={
                    "mode": mode,
                    "serial": serial,
                    "host": host or None,
                    "service_instance_id": config.get("_service_instance_id"),
                    "mqtt": endpoint.label,
                },
            )
        )

    async def _mqtt_loop(self, endpoint) -> None:
        async def on_connection(ok: bool, error: str | None) -> None:
            if ok:
                self._status = self._status.model_copy(
                    update={
                        "connection": ConnectionState.CONNECTED,
                        "message": f"Live MQTT via {endpoint.label}",
                    }
                )
                self._mqtt_ready.set()
                return
            if not self._mqtt_ready.is_set():
                self._status = self._status.model_copy(
                    update={
                        "connection": ConnectionState.ERROR,
                        "message": f"MQTT connect failed: {error}",
                    }
                )
                self._mqtt_ready.set()
                return
            self._status = self._status.model_copy(
                update={
                    "connection": ConnectionState.CONNECTING,
                    "message": f"MQTT reconnecting ({endpoint.label}): {error}",
                }
            )
        async def on_message(data: dict[str, Any]) -> None:
            self._print_snapshot = merge_print_payload(self._print_snapshot, data)
            if "print" not in data and not self._print_snapshot:
                return
            previous = self._status
            next_status = apply_print_snapshot(
                previous,
                self._print_snapshot,
                connected=True,
            )
            next_status = next_status.model_copy(
                update={
                    "printer_id": previous.printer_id,
                    "printer_name": previous.printer_name,
                    "message": f"Live MQTT via {endpoint.label}",
                }
            )
            events = self._tracker.events_for_update(
                printer_id=previous.printer_id,
                printer_name=previous.printer_name,
                plugin_id=self.id,
                previous_status=previous,
                next_status=next_status,
            )
            self._status = next_status
            for event in events:
                self._enqueue(event)

        try:
            await run_mqtt_session(
                endpoint,
                on_message=on_message,
                on_connection=on_connection,
                should_stop=lambda: self._stop.is_set(),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Bambu MQTT loop crashed: %s", exc)
            self._status = self._status.model_copy(
                update={
                    "connection": ConnectionState.ERROR,
                    "message": f"MQTT session ended: {exc}",
                }
            )
            self._mqtt_ready.set()

    async def disconnect(self) -> None:
        was_active = self._session_active
        self._session_active = False
        self._stop.set()
        task = self._mqtt_task
        self._mqtt_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("MQTT task ended with error during disconnect", exc_info=True)

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
