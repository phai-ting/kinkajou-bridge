from __future__ import annotations

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
from kinkajou_bridge.plugins.bambu.cloud import fetch_bound_devices
from kinkajou_bridge.plugins.base import VerifyResult

logger = logging.getLogger(__name__)


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
        except Exception as exc:
            logger.warning("Bambu cloud verify failed: %s", exc)
            return VerifyResult(
                ok=False,
                message=f"Could not reach Bambu Lab cloud: {exc}",
            )
        return VerifyResult(
            ok=True,
            message=f"Bambu Lab cloud OK — {len(devices)} printer(s) on this account.",
            details={"device_count": len(devices)},
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
    """Bambu Lab printer: service-bound cloud or standalone LAN."""

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
        self._event_queue: list[PrinterEvent] = []

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
        elif mode in {"service", "cloud"}:
            token = str(config.get("cloud_token", "")).strip()
            has_service = bool(config.get("_service_config") or config.get("_service_instance_id"))
            if mode == "service" and not has_service and not token:
                return VerifyResult(
                    ok=False,
                    message="Select a connected Bambu Lab service, or connect one first.",
                )
            if mode == "cloud" and not token and not has_service:
                return VerifyResult(ok=False, message="Cloud access token is required.")
        else:
            return VerifyResult(ok=False, message=f"Unknown connection mode: {mode}")

        return VerifyResult(
            ok=True,
            message="Configuration looks valid (live MQTT verification not implemented yet).",
            details={"mode": mode, "serial": serial},
        )

    async def connect(self, config: Mapping[str, Any]) -> None:
        self._config = dict(config)
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
                "connection": ConnectionState.CONNECTED,
                "print_state": PrintState.IDLE,
                "job": PrintJob(name=None, progress=None, remaining_seconds=None),
                "temperatures": Temperatures(
                    nozzle_c=None,
                    nozzle_target_c=None,
                    bed_c=None,
                    bed_target_c=None,
                ),
                "message": (
                    f"Session ready for {serial} via {mode_label}. "
                    "Live MQTT telemetry is not implemented yet — "
                    "values will populate once connected."
                ),
            }
        )
        self._event_queue.append(
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
                },
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
