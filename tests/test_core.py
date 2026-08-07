from __future__ import annotations

import pytest

from kinkajou_bridge.models import FieldType
from kinkajou_bridge.plugins.bambu import BambuCloudService, BambuPlugin
from kinkajou_bridge.plugins.registry import PrinterRegistry, ServiceRegistry


@pytest.mark.asyncio
async def test_bambu_verify_requires_lan_fields() -> None:
    plugin = BambuPlugin()
    result = await plugin.verify({"connection_mode": "lan", "serial": "ABC"})
    assert result.ok is False
    assert "IP" in result.message or "access" in result.message.lower()


@pytest.mark.asyncio
async def test_bambu_verify_lan_ok() -> None:
    plugin = BambuPlugin()
    result = await plugin.verify(
        {
            "connection_mode": "lan",
            "serial": "01P00C123456789",
            "host": "192.168.1.50",
            "access_code": "12345678",
            "name": "P1S",
        }
    )
    assert result.ok is True


@pytest.mark.asyncio
async def test_bambu_verify_service_requires_binding() -> None:
    plugin = BambuPlugin()
    result = await plugin.verify(
        {"connection_mode": "service", "serial": "01P00C123456789", "name": "P1S"}
    )
    assert result.ok is False


@pytest.mark.asyncio
async def test_bambu_verify_service_with_injected_config() -> None:
    plugin = BambuPlugin()
    result = await plugin.verify(
        {
            "connection_mode": "service",
            "serial": "01P00C123456789",
            "name": "P1S",
            "_service_instance_id": "svc-1",
            "_service_config": {"cloud_token": "tok"},
        }
    )
    assert result.ok is True


@pytest.mark.asyncio
async def test_bambu_connect_sets_status() -> None:
    import asyncio

    plugin = BambuPlugin()
    await plugin.connect(
        {
            "connection_mode": "lan",
            "serial": "01P00C123456789",
            "host": "192.168.1.50",
            "access_code": "12345678",
            "name": "Living Room",
        }
    )
    try:
        status = plugin.get_status()
        assert status.printer_name == "Living Room"
        assert status.connection.value == "connected"
        assert status.print_state.value == "idle"

        async def first_event():
            async for event in plugin.events():
                return event

        event = await asyncio.wait_for(first_event(), timeout=2)
        assert event.type.value == "printer.connected"
    finally:
        await plugin.disconnect()


@pytest.mark.asyncio
async def test_bambu_cloud_service_lists_devices() -> None:
    service = BambuCloudService()
    verify = await service.verify({"cloud_token": "abc", "name": "Bambu"})
    assert verify.ok is True
    await service.connect({"cloud_token": "abc", "name": "Bambu"})
    assert service.get_status().connection.value == "connected"
    devices = list(service.list_devices())
    assert len(devices) >= 1
    assert devices[0].serial
    assert devices[0].name


def test_bambu_schema_includes_hints() -> None:
    plugin = BambuPlugin()
    fields = {field.key: field for field in plugin.config_schema.fields}
    assert plugin.config_schema.hint
    assert fields["serial"].hint
    assert fields["serial"].hint_detail
    assert fields["host"].hint_detail
    assert fields["access_code"].hint_detail
    assert "LAN" in (fields["access_code"].hint or "")
    assert plugin.compatible_service_ids == ("bambu_cloud",)
    assert plugin.supports_standalone is True

    registry = PrinterRegistry()
    registry.load_builtins([("bambu", BambuPlugin)])
    plugin = registry.create("bambu")
    assert plugin.id == "bambu"
    assert plugin.config_schema.fields
    assert plugin.config_schema.fields[0].type == FieldType.SELECT


def test_service_registry_builtins() -> None:
    registry = ServiceRegistry()
    registry.load_builtins([("bambu_cloud", BambuCloudService)])
    service = registry.create("bambu_cloud")
    assert service.id == "bambu_cloud"
    assert service.config_schema.fields


def test_default_port_is_kinkajou_taxonomy_id() -> None:
    from kinkajou_bridge.settings import Settings

    assert Settings().port == 29067


@pytest.mark.asyncio
async def test_bridge_rejects_duplicate_bambu_serial(tmp_path) -> None:
    from kinkajou_bridge.app import BridgeApp
    from kinkajou_bridge.settings import Settings

    settings = Settings(data_dir=tmp_path)
    bridge = BridgeApp(settings)
    await bridge.start()
    try:
        await bridge.add_printer(
            name="First P1S",
            plugin_id="bambu",
            config={
                "connection_mode": "lan",
                "serial": "01P00CDUPE000001",
                "host": "192.168.1.50",
                "access_code": "12345678",
            },
        )
        with pytest.raises(ValueError, match="already configured"):
            await bridge.add_printer(
                name="Second P1S",
                plugin_id="bambu",
                config={
                    "connection_mode": "lan",
                    "serial": "01P00CDUPE000001",
                    "host": "192.168.1.51",
                    "access_code": "87654321",
                },
            )
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_bridge_add_printer_lan(tmp_path) -> None:
    from kinkajou_bridge.app import BridgeApp
    from kinkajou_bridge.settings import Settings

    settings = Settings(data_dir=tmp_path)
    bridge = BridgeApp(settings)
    await bridge.start()
    try:
        instance = await bridge.add_printer(
            name="Test P1S",
            plugin_id="bambu",
            config={
                "connection_mode": "lan",
                "serial": "01P00C123456789",
                "host": "192.168.1.50",
                "access_code": "12345678",
            },
        )
        status = bridge.get_status(instance.id)
        assert status is not None
        assert status.printer_name == "Test P1S"
        plugins = bridge.list_plugins()
        assert any(p["id"] == "bambu" and p["kind"] == "printer" for p in plugins)
        assert any(p["id"] == "bambu_cloud" and p["kind"] == "service" for p in plugins)
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_bridge_service_then_printer(tmp_path) -> None:
    from kinkajou_bridge.app import BridgeApp
    from kinkajou_bridge.settings import Settings

    settings = Settings(data_dir=tmp_path)
    bridge = BridgeApp(settings)
    await bridge.start()
    try:
        service = await bridge.add_service(
            name="My Bambu",
            plugin_id="bambu_cloud",
            config={"cloud_token": "test-token", "name": "My Bambu"},
        )
        assert bridge.get_service_status(service.id) is not None
        devices = bridge.list_service_devices(service.id)
        assert len(devices) >= 1
        assert devices[0].serial

        printer = await bridge.add_printer(
            name="Cloud P1S",
            plugin_id="bambu",
            service_instance_id=service.id,
            config={
                "connection_mode": "service",
                "serial": "01P00C999999999",
            },
        )
        assert printer.service_instance_id == service.id
        status = bridge.get_status(printer.id)
        assert status is not None
        assert status.connection.value == "connected"

        with pytest.raises(ValueError, match="still reference"):
            await bridge.remove_service(service.id)
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_legacy_cloud_token_migration(tmp_path) -> None:
    from kinkajou_bridge.app import BridgeApp
    from kinkajou_bridge.settings import Settings
    from kinkajou_bridge.storage import InstanceStore, PrinterInstance

    settings = Settings(data_dir=tmp_path)
    store = InstanceStore(settings.instances_path)
    store.load()
    store.upsert(
        PrinterInstance(
            name="Legacy",
            plugin_id="bambu",
            config={
                "connection_mode": "cloud",
                "serial": "01P00CLEGACY0001",
                "cloud_token": "legacy-token",
                "name": "Legacy",
            },
        )
    )

    bridge = BridgeApp(settings)
    await bridge.start()
    try:
        services = bridge.service_store.list()
        assert len(services) == 1
        assert services[0].plugin_id == "bambu_cloud"
        printers = bridge.store.list()
        assert len(printers) == 1
        assert printers[0].service_instance_id == services[0].id
        assert printers[0].config.get("connection_mode") == "service"
        assert "cloud_token" not in printers[0].config
        assert bridge.get_status(printers[0].id) is not None
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_streamerbot_integration_and_event_fanout(tmp_path, monkeypatch) -> None:
    from kinkajou_bridge.app import BridgeApp
    from kinkajou_bridge.models import EventType, PrinterEvent
    from kinkajou_bridge.settings import Settings
    from tests.test_octoprint import _mock_transport, _patch_async_client

    _patch_async_client(monkeypatch, _mock_transport())

    settings = Settings(data_dir=tmp_path)
    bridge = BridgeApp(settings)
    await bridge.start()
    try:
        plugins = bridge.list_integration_plugins()
        assert any(p["id"] == "streamerbot" for p in plugins)

        instance = await bridge.add_integration(
            name="Streamer.bot",
            plugin_id="streamerbot",
            config={
                "host": "127.0.0.1",
                "port": 8080,
                "endpoint": "/",
                "password": "secret",
            },
        )
        public = bridge.public_integration(instance)
        assert public["config"]["password"] == "***"
        assert "secret" not in str(public)

        status = bridge.get_integration_status(instance.id)
        assert status is not None
        # Streamer.bot is unlikely to be running in tests — soft-fail to error/disconnected.
        assert status.connection.value in {"connected", "error", "disconnected"}

        # Add printers from different sources — events from both must reach Streamer.bot path.
        bambu = await bridge.add_printer(
            name="Bambu LAN",
            plugin_id="bambu",
            config={
                "connection_mode": "lan",
                "serial": "01P00CBAMBU00001",
                "host": "192.168.1.50",
                "access_code": "12345678",
            },
        )
        octo = await bridge.add_printer(
            name="Octo",
            plugin_id="octoprint",
            config={
                "connection_mode": "lan",
                "name": "Octo",
                "base_url": "http://192.168.1.40",
                "api_key": "key",
            },
        )

        received: list[PrinterEvent] = []

        class RecordingIntegration:
            id = "recorder"
            name = "Recorder"

            async def handle_event(self, event: PrinterEvent) -> None:
                received.append(event)

            async def disconnect(self) -> None:
                return None

        bridge._integration_sessions["recorder"] = RecordingIntegration()  # type: ignore[assignment]
        for printer_id, printer_name in (
            (bambu.id, "Bambu LAN"),
            (octo.id, "Octo"),
        ):
            await bridge.publish_event(
                PrinterEvent(
                    type=EventType.PRINTER_CONNECTED,
                    printer_id=printer_id,
                    printer_name=printer_name,
                    plugin_id="test",
                    payload={},
                )
            )
        assert len(received) == 2
        assert {e.printer_id for e in received} == {bambu.id, octo.id}
        bambu_event = next(e for e in received if e.printer_id == bambu.id)
        assert bambu_event.payload.get("plugin_id") == "bambu"
        assert bambu_event.payload.get("connection_mode") == "lan"
        del bridge._integration_sessions["recorder"]
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_legacy_streamerbot_settings_migration(tmp_path) -> None:
    from kinkajou_bridge.app import BridgeApp
    from kinkajou_bridge.settings import Settings

    settings = Settings(
        data_dir=tmp_path,
        streamerbot_enabled=True,
        streamerbot_host="10.0.0.5",
        streamerbot_port=9090,
        streamerbot_endpoint="/ws",
        streamerbot_password="migrated-secret",
    )
    bridge = BridgeApp(settings)
    await bridge.start()
    try:
        integrations = bridge.integration_store.list()
        assert len(integrations) == 1
        assert integrations[0].plugin_id == "streamerbot"
        assert integrations[0].config["host"] == "10.0.0.5"
        assert integrations[0].config["port"] == 9090
        assert integrations[0].config["endpoint"] == "/ws"
        assert integrations[0].config["password"] == "migrated-secret"
        public = bridge.public_integration(integrations[0])
        assert public["config"]["password"] == "***"
    finally:
        await bridge.stop()
