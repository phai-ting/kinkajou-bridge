from __future__ import annotations

import asyncio
import logging
from typing import Any

from kinkajou_bridge.models import (
    DiscoveredDevice,
    IntegrationStatus,
    PrinterEvent,
    PrinterStatus,
    ServiceStatus,
)
from kinkajou_bridge.plugins.bambu import BambuCloudService, BambuPlugin
from kinkajou_bridge.plugins.base import IntegrationPlugin, PrinterPlugin, ServicePlugin
from kinkajou_bridge.plugins.octoprint import OctoPrintPlugin
from kinkajou_bridge.plugins.registry import (
    IntegrationRegistry,
    PrinterRegistry,
    ServiceRegistry,
)
from kinkajou_bridge.plugins.streamerbot import StreamerBotPlugin
from kinkajou_bridge.security import merge_config_preserving_secrets, redact_config
from kinkajou_bridge.settings import Settings
from kinkajou_bridge.storage import (
    InstanceStore,
    IntegrationInstance,
    IntegrationStore,
    PrinterInstance,
    ServiceInstance,
    ServiceStore,
)
from kinkajou_bridge.ui.state import UiStateStore

logger = logging.getLogger(__name__)


class BridgeApp:
    """Runtime orchestrator for services, printers, integrations, and API events."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.service_registry = ServiceRegistry()
        self.printer_registry = PrinterRegistry()
        self.integration_registry = IntegrationRegistry()
        # Back-compat alias
        self.registry = self.printer_registry
        self.store = InstanceStore(self.settings.instances_path)
        self.service_store = ServiceStore(self.settings.services_path)
        self.integration_store = IntegrationStore(self.settings.integrations_path)
        self.ui_state = UiStateStore(self.settings.ui_state_path)
        self._service_sessions: dict[str, ServicePlugin] = {}
        self._sessions: dict[str, PrinterPlugin] = {}
        self._integration_sessions: dict[str, IntegrationPlugin] = {}
        self._pump_tasks: dict[str, asyncio.Task[None]] = {}
        self._event_subscribers: list[asyncio.Queue[PrinterEvent]] = []
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.ui_state.load()
        self.service_registry.load_builtins([("bambu_cloud", BambuCloudService)])
        self.printer_registry.load_builtins(
            [
                ("bambu", BambuPlugin),
                ("octoprint", OctoPrintPlugin),
            ]
        )
        self.integration_registry.load_builtins([("streamerbot", StreamerBotPlugin)])
        try:
            self.service_registry.load_entry_points()
        except Exception:
            logger.exception("Service entry point discovery failed")
        try:
            self.printer_registry.load_entry_points()
            self.printer_registry.load_entry_points("kinkajou_bridge.plugins")
        except Exception:
            logger.exception("Printer entry point discovery failed")
        try:
            self.integration_registry.load_entry_points()
        except Exception:
            logger.exception("Integration entry point discovery failed")
        self.service_store.load()
        self.store.load()
        self.integration_store.load()
        self._migrate_legacy_cloud_tokens()
        self._migrate_legacy_streamerbot_settings()
        for service in self.service_store.list():
            if service.enabled:
                await self._start_service(service)
        for instance in self.store.list():
            if instance.enabled:
                await self._start_instance(instance)
        for integration in self.integration_store.list():
            if integration.enabled:
                await self._start_integration(integration)
        self._started = True
        logger.info(
            "Kinkajou Bridge started on %s:%s",
            self.settings.host,
            self.settings.port,
        )

    def should_show_welcome(self) -> bool:
        if self.store.list():
            return False
        state = self.ui_state.load()
        return not state.welcome_completed

    def should_open_ui_on_start(self) -> bool:
        return bool(self.settings.open_ui_on_start) and self.should_show_welcome()

    def mark_welcome_completed(self) -> None:
        self.ui_state.mark_welcome_completed()

    def ui_snapshot(self) -> dict[str, Any]:
        state = self.ui_state.load()
        return {
            "welcome_completed": state.welcome_completed or bool(self.store.list()),
            "printer_count": len(self.store.list()),
            "service_count": len(self.service_store.list()),
            "integration_count": len(self.integration_store.list()),
            "website_url": self.settings.website_url,
            "docs_url": f"{self.settings.website_url.rstrip('/')}/bridge/",
            "overlays_docs_url": (
                f"{self.settings.website_url.rstrip('/')}/bridge/user/overlays/"
            ),
            "api_base_url": self.settings.base_url,
        }

    async def stop(self) -> None:
        for instance_id in list(self._sessions):
            await self._stop_instance(instance_id)
        for service_id in list(self._service_sessions):
            await self._stop_service(service_id)
        for integration_id in list(self._integration_sessions):
            await self._stop_integration(integration_id)
        self._started = False

    def list_plugins(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for plugin_id in self.printer_registry.list_ids():
            result.append(self._printer_plugin_info(self.printer_registry.create(plugin_id)))
        for plugin_id in self.service_registry.list_ids():
            result.append(self._service_plugin_info(self.service_registry.create(plugin_id)))
        for plugin_id in self.integration_registry.list_ids():
            result.append(
                self._integration_plugin_info(self.integration_registry.create(plugin_id))
            )
        return result

    def list_printer_plugins(self) -> list[dict[str, Any]]:
        return [
            self._printer_plugin_info(self.printer_registry.create(plugin_id))
            for plugin_id in self.printer_registry.list_ids()
        ]

    def list_service_plugins(self) -> list[dict[str, Any]]:
        return [
            self._service_plugin_info(self.service_registry.create(plugin_id))
            for plugin_id in self.service_registry.list_ids()
        ]

    def list_integration_plugins(self) -> list[dict[str, Any]]:
        return [
            self._integration_plugin_info(self.integration_registry.create(plugin_id))
            for plugin_id in self.integration_registry.list_ids()
        ]

    def _printer_plugin_info(self, plugin: PrinterPlugin) -> dict[str, Any]:
        return {
            "id": plugin.id,
            "name": plugin.name,
            "kind": "printer",
            "compatible_service_ids": list(plugin.compatible_service_ids),
            "supports_standalone": bool(plugin.supports_standalone),
            "config_schema": plugin.config_schema.model_dump(mode="json"),
        }

    def _service_plugin_info(self, plugin: ServicePlugin) -> dict[str, Any]:
        return {
            "id": plugin.id,
            "name": plugin.name,
            "kind": "service",
            "config_schema": plugin.config_schema.model_dump(mode="json"),
        }

    def _integration_plugin_info(self, plugin: IntegrationPlugin) -> dict[str, Any]:
        return {
            "id": plugin.id,
            "name": plugin.name,
            "kind": "integration",
            "config_schema": plugin.config_schema.model_dump(mode="json"),
        }

    def list_printer_summaries(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for instance in self.store.list():
            status = self.get_status(instance.id)
            config = instance.config or {}
            summaries.append(
                {
                    "id": instance.id,
                    "name": instance.name,
                    "plugin_id": instance.plugin_id,
                    "enabled": instance.enabled,
                    "service_instance_id": instance.service_instance_id,
                    "identity": {
                        "serial": config.get("serial"),
                        "connection_mode": config.get("connection_mode"),
                        "host": config.get("host") or config.get("base_url"),
                    },
                    "status": None if status is None else status.model_dump(mode="json"),
                }
            )
        return summaries

    def list_service_summaries(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for instance in self.service_store.list():
            status = self.get_service_status(instance.id)
            public = self.public_service(instance)
            summaries.append(
                {
                    "id": instance.id,
                    "name": instance.name,
                    "plugin_id": instance.plugin_id,
                    "enabled": instance.enabled,
                    "config": public["config"],
                    "status": None if status is None else status.model_dump(mode="json"),
                }
            )
        return summaries

    def list_integration_summaries(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for instance in self.integration_store.list():
            status = self.get_integration_status(instance.id)
            public = self.public_integration(instance)
            summaries.append(
                {
                    "id": instance.id,
                    "name": instance.name,
                    "plugin_id": instance.plugin_id,
                    "enabled": instance.enabled,
                    "config": public["config"],
                    "status": None if status is None else status.model_dump(mode="json"),
                }
            )
        return summaries

    def public_printer(self, instance: PrinterInstance) -> dict[str, Any]:
        schema = None
        if instance.plugin_id in self.printer_registry.list_ids():
            schema = self.printer_registry.create(instance.plugin_id).config_schema
        return {
            "id": instance.id,
            "name": instance.name,
            "plugin_id": instance.plugin_id,
            "enabled": instance.enabled,
            "service_instance_id": instance.service_instance_id,
            "config": redact_config(instance.config, schema=schema),
        }

    def public_service(self, instance: ServiceInstance) -> dict[str, Any]:
        schema = None
        if instance.plugin_id in self.service_registry.list_ids():
            schema = self.service_registry.create(instance.plugin_id).config_schema
        return {
            "id": instance.id,
            "name": instance.name,
            "plugin_id": instance.plugin_id,
            "enabled": instance.enabled,
            "config": redact_config(instance.config, schema=schema),
        }

    def public_integration(self, instance: IntegrationInstance) -> dict[str, Any]:
        schema = None
        if instance.plugin_id in self.integration_registry.list_ids():
            schema = self.integration_registry.create(instance.plugin_id).config_schema
        return {
            "id": instance.id,
            "name": instance.name,
            "plugin_id": instance.plugin_id,
            "enabled": instance.enabled,
            "config": redact_config(instance.config, schema=schema),
        }

    def get_status(self, printer_id: str) -> PrinterStatus | None:
        session = self._sessions.get(printer_id)
        if session is not None:
            status = session.get_status()
            return status.model_copy(update={"printer_id": printer_id})
        instance = self.store.get(printer_id)
        if instance is None:
            return None
        return PrinterStatus(
            printer_id=instance.id,
            printer_name=instance.name,
            plugin_id=instance.plugin_id,
        )

    def get_service_status(self, service_id: str) -> ServiceStatus | None:
        session = self._service_sessions.get(service_id)
        if session is not None:
            status = session.get_status()
            return status.model_copy(update={"service_id": service_id})
        instance = self.service_store.get(service_id)
        if instance is None:
            return None
        return ServiceStatus(
            service_id=instance.id,
            service_name=instance.name,
            plugin_id=instance.plugin_id,
        )

    def get_integration_status(self, integration_id: str) -> IntegrationStatus | None:
        session = self._integration_sessions.get(integration_id)
        if session is not None:
            status = session.get_status()
            return status.model_copy(update={"integration_id": integration_id})
        instance = self.integration_store.get(integration_id)
        if instance is None:
            return None
        return IntegrationStatus(
            integration_id=instance.id,
            integration_name=instance.name,
            plugin_id=instance.plugin_id,
        )

    def list_service_devices(self, service_id: str) -> list[DiscoveredDevice]:
        session = self._service_sessions.get(service_id)
        if session is None:
            raise KeyError(f"Service not connected: {service_id}")
        return list(session.list_devices())

    async def add_service(
        self,
        name: str,
        plugin_id: str,
        config: dict[str, Any],
        enabled: bool = True,
    ) -> ServiceInstance:
        if plugin_id not in self.service_registry.list_ids():
            raise KeyError(f"Unknown service plugin: {plugin_id}")
        plugin = self.service_registry.create(plugin_id)
        verify = await plugin.verify(config)
        if not verify.ok:
            raise ValueError(verify.message or "Verification failed")
        instance = ServiceInstance(
            name=name,
            plugin_id=plugin_id,
            enabled=enabled,
            config=config,
        )
        self.service_store.upsert(instance)
        if enabled:
            await self._start_service(instance)
        return instance

    async def remove_service(self, service_id: str) -> bool:
        dependents = self.store.list_by_service(service_id)
        if dependents:
            names = ", ".join(p.name for p in dependents)
            raise ValueError(
                f"Cannot remove service while printers still reference it: {names}"
            )
        await self._stop_service(service_id)
        return self.service_store.delete(service_id)

    async def add_printer(
        self,
        name: str,
        plugin_id: str,
        config: dict[str, Any],
        enabled: bool = True,
        service_instance_id: str | None = None,
    ) -> PrinterInstance:
        if plugin_id not in self.printer_registry.list_ids():
            raise KeyError(f"Unknown printer plugin: {plugin_id}")
        plugin = self.printer_registry.create(plugin_id)
        if service_instance_id:
            service = self.service_store.get(service_instance_id)
            if service is None:
                raise ValueError(f"Unknown service instance: {service_instance_id}")
            if service.plugin_id not in plugin.compatible_service_ids:
                raise ValueError(
                    f"Printer plugin {plugin_id} is not compatible with service "
                    f"{service.plugin_id}"
                )
            if config.get("connection_mode") in {None, "cloud"}:
                config = {**config, "connection_mode": "service"}
        elif (
            str(config.get("connection_mode", "service")) == "service"
            and plugin.compatible_service_ids
            and not plugin.supports_standalone
        ):
            raise ValueError("A connected service is required for this printer.")

        serial = str(config.get("serial") or "").strip()
        if plugin_id == "bambu" and serial:
            self._ensure_unique_bambu_serial(serial)

        verify_config = self._config_with_service(config, service_instance_id)
        verify = await plugin.verify(verify_config)
        if not verify.ok:
            raise ValueError(verify.message or "Verification failed")
        instance = PrinterInstance(
            name=name,
            plugin_id=plugin_id,
            enabled=enabled,
            service_instance_id=service_instance_id,
            config=config,
        )
        self.store.upsert(instance)
        if enabled:
            await self._start_instance(instance)
        return instance

    async def remove_printer(self, printer_id: str) -> bool:
        await self._stop_instance(printer_id)
        return self.store.delete(printer_id)

    async def add_integration(
        self,
        name: str,
        plugin_id: str,
        config: dict[str, Any],
        enabled: bool = True,
    ) -> IntegrationInstance:
        if plugin_id not in self.integration_registry.list_ids():
            raise KeyError(f"Unknown integration plugin: {plugin_id}")
        # For now Streamer.bot is the only integration and is global (all printers).
        if plugin_id != "streamerbot":
            raise ValueError(
                "Only the Streamer.bot integration is supported right now."
            )
        plugin = self.integration_registry.create(plugin_id)
        verify = await plugin.verify(config)
        if not verify.ok:
            raise ValueError(verify.message or "Verification failed")

        existing = next(
            (i for i in self.integration_store.list() if i.plugin_id == "streamerbot"),
            None,
        )
        # Always use a fixed display name — only one Streamer.bot connection allowed.
        name = "Streamer.bot"
        if existing is not None:
            await self._stop_integration(existing.id)
            existing.name = name
            existing.enabled = enabled
            existing.config = {
                **merge_config_preserving_secrets(
                    existing.config, config, schema=plugin.config_schema
                ),
                "name": name,
            }
            instance = self.integration_store.upsert(existing)
        else:
            instance = IntegrationInstance(
                name=name,
                plugin_id=plugin_id,
                enabled=enabled,
                config={**config, "name": name},
            )
            self.integration_store.upsert(instance)
        if enabled:
            await self._start_integration(instance)
        return instance

    async def remove_integration(self, integration_id: str) -> bool:
        await self._stop_integration(integration_id)
        return self.integration_store.delete(integration_id)

    def subscribe_events(self) -> asyncio.Queue[PrinterEvent]:
        queue: asyncio.Queue[PrinterEvent] = asyncio.Queue()
        self._event_subscribers.append(queue)
        return queue

    def unsubscribe_events(self, queue: asyncio.Queue[PrinterEvent]) -> None:
        if queue in self._event_subscribers:
            self._event_subscribers.remove(queue)

    async def publish_event(self, event: PrinterEvent) -> None:
        enriched = self._enrich_event_for_integrations(event)
        for queue in list(self._event_subscribers):
            await queue.put(enriched)
        for integration_id, plugin in list(self._integration_sessions.items()):
            try:
                await plugin.handle_event(enriched)
            except Exception:
                logger.exception(
                    "Integration %s failed to handle event %s",
                    integration_id,
                    event.type.value,
                )

    def _enrich_event_for_integrations(self, event: PrinterEvent) -> PrinterEvent:
        """Attach printer/service context so Streamer.bot can handle any source."""
        instance = self.store.get(event.printer_id)
        if instance is None:
            return event
        extra: dict[str, Any] = {
            "plugin_id": instance.plugin_id,
            "service_instance_id": instance.service_instance_id,
            "connection_mode": (instance.config or {}).get("connection_mode"),
        }
        # Drop empty values so args stay clean.
        extra = {k: v for k, v in extra.items() if v not in (None, "")}
        payload = {**event.payload, **extra}
        return event.model_copy(
            update={
                "plugin_id": instance.plugin_id or event.plugin_id,
                "payload": payload,
            }
        )

    def _ensure_unique_bambu_serial(self, serial: str) -> None:
        needle = serial.strip().casefold()
        if not needle:
            return
        for existing in self.store.list():
            if existing.plugin_id != "bambu":
                continue
            existing_serial = str((existing.config or {}).get("serial") or "").strip()
            if existing_serial.casefold() == needle:
                raise ValueError(
                    f"A printer with serial {serial} is already configured "
                    f"({existing.name}). Remove it first or choose a different printer."
                )

    def _config_with_service(
        self,
        config: dict[str, Any],
        service_instance_id: str | None,
    ) -> dict[str, Any]:
        merged = dict(config)
        if not service_instance_id:
            return merged
        merged["_service_instance_id"] = service_instance_id
        service = self.service_store.get(service_instance_id)
        if service is not None:
            merged["_service_config"] = dict(service.config)
            for key, value in service.config.items():
                if key not in merged or merged[key] in (None, ""):
                    if key != "name":
                        merged[key] = value
        session = self._service_sessions.get(service_instance_id)
        get_creds = getattr(session, "get_credentials", None)
        if callable(get_creds):
            for key, value in get_creds().items():
                if key not in merged or merged[key] in (None, ""):
                    merged[key] = value
        return merged

    def _migrate_legacy_cloud_tokens(self) -> None:
        if "bambu_cloud" not in self.service_registry.list_ids():
            return
        existing_tokens = {
            str(s.config.get("cloud_token", "")).strip()
            for s in self.service_store.list()
            if s.plugin_id == "bambu_cloud"
        }
        for instance in list(self.store.list()):
            if instance.service_instance_id:
                continue
            config = dict(instance.config or {})
            mode = str(config.get("connection_mode", ""))
            token = str(config.get("cloud_token", "")).strip()
            if mode != "cloud" or not token:
                continue
            service: ServiceInstance | None = None
            if token in existing_tokens:
                service = next(
                    (
                        s
                        for s in self.service_store.list()
                        if s.plugin_id == "bambu_cloud"
                        and str(s.config.get("cloud_token", "")).strip() == token
                    ),
                    None,
                )
            if service is None:
                service = ServiceInstance(
                    name="Bambu Lab (migrated)",
                    plugin_id="bambu_cloud",
                    enabled=True,
                    config={"name": "Bambu Lab (migrated)", "cloud_token": token},
                )
                self.service_store.upsert(service)
                existing_tokens.add(token)
            config.pop("cloud_token", None)
            config["connection_mode"] = "service"
            instance.service_instance_id = service.id
            instance.config = config
            self.store.upsert(instance)
            logger.info("Migrated printer %s to service %s", instance.name, service.id)

    def _migrate_legacy_streamerbot_settings(self) -> None:
        """Create a Streamer.bot integration from legacy env settings if needed."""
        if not self.settings.streamerbot_enabled:
            return
        if "streamerbot" not in self.integration_registry.list_ids():
            return
        if any(i.plugin_id == "streamerbot" for i in self.integration_store.list()):
            return
        config: dict[str, Any] = {
            "name": "Streamer.bot",
            "host": self.settings.streamerbot_host,
            "port": self.settings.streamerbot_port,
            "endpoint": self.settings.streamerbot_endpoint,
        }
        if self.settings.streamerbot_password:
            config["password"] = self.settings.streamerbot_password
        instance = IntegrationInstance(
            name="Streamer.bot",
            plugin_id="streamerbot",
            enabled=True,
            config=config,
        )
        self.integration_store.upsert(instance)
        logger.info("Migrated legacy Streamer.bot settings to integration %s", instance.id)

    async def _start_service(self, instance: ServiceInstance) -> None:
        if instance.id in self._service_sessions:
            return
        plugin = self.service_registry.create(instance.plugin_id)
        await plugin.connect({**instance.config, "name": instance.name})
        self._service_sessions[instance.id] = plugin

    async def _stop_service(self, service_id: str) -> None:
        plugin = self._service_sessions.pop(service_id, None)
        if plugin is None:
            return
        await plugin.disconnect()

    async def _start_integration(self, instance: IntegrationInstance) -> None:
        if instance.id in self._integration_sessions:
            return
        plugin = self.integration_registry.create(instance.plugin_id)
        await plugin.connect({**instance.config, "name": instance.name})
        self._integration_sessions[instance.id] = plugin

    async def _stop_integration(self, integration_id: str) -> None:
        plugin = self._integration_sessions.pop(integration_id, None)
        if plugin is None:
            return
        await plugin.disconnect()

    async def _start_instance(self, instance: PrinterInstance) -> None:
        if instance.id in self._sessions:
            return
        if instance.service_instance_id and (
            instance.service_instance_id not in self._service_sessions
        ):
            service = self.service_store.get(instance.service_instance_id)
            if service is not None and service.enabled:
                await self._start_service(service)
        plugin = self.printer_registry.create(instance.plugin_id)
        connect_config = self._config_with_service(
            {**instance.config, "name": instance.name},
            instance.service_instance_id,
        )
        await plugin.connect(connect_config)
        self._sessions[instance.id] = plugin
        self._pump_tasks[instance.id] = asyncio.create_task(
            self._pump_events(instance.id, instance.name, plugin),
            name=f"printer-events-{instance.id}",
        )

    async def _stop_instance(self, instance_id: str) -> None:
        task = self._pump_tasks.pop(instance_id, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        plugin = self._sessions.pop(instance_id, None)
        if plugin is None:
            return
        await plugin.disconnect()
        async for event in plugin.events():
            await self.publish_event(event.model_copy(update={"printer_id": instance_id}))

    async def _pump_events(
        self,
        instance_id: str,
        instance_name: str,
        plugin: PrinterPlugin,
    ) -> None:
        try:
            async for event in plugin.events():
                normalized = event.model_copy(
                    update={
                        "printer_id": instance_id,
                        "printer_name": instance_name,
                    }
                )
                await self.publish_event(normalized)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Event pump failed for printer %s", instance_id)
