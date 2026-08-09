from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from kinkajou_bridge.models import ConnectionState, PrintState
from kinkajou_bridge.plugins.moonraker import MoonrakerPlugin
from kinkajou_bridge.plugins.moonraker.status import (
    build_status,
    map_print_state,
    normalize_base_url,
)

_RealAsyncClient = httpx.AsyncClient


def test_normalize_base_url() -> None:
    assert normalize_base_url("192.168.1.40:7125") == "http://192.168.1.40:7125"
    assert normalize_base_url("http://klipper.local/printer/") == "http://klipper.local"
    assert normalize_base_url("https://printer.local:443") == "https://printer.local:443"
    assert normalize_base_url("not a url") == ""


def test_map_print_state() -> None:
    assert map_print_state(print_stats_state="printing", webhooks_state="ready") == PrintState.PRINTING
    assert map_print_state(print_stats_state="paused", webhooks_state="ready") == PrintState.PAUSED
    assert map_print_state(print_stats_state="standby", webhooks_state="ready") == PrintState.IDLE
    assert map_print_state(print_stats_state="complete", webhooks_state="ready") == PrintState.COMPLETE
    assert map_print_state(print_stats_state="error", webhooks_state="ready") == PrintState.ERROR
    assert map_print_state(print_stats_state="standby", webhooks_state="shutdown") == PrintState.ERROR


def test_build_status_from_moonraker_objects() -> None:
    status = build_status(
        printer_id="http://192.168.1.40:7125",
        printer_name="Shop Voron",
        plugin_id="moonraker",
        objects={
            "webhooks": {"state": "ready", "message": "Printer is ready"},
            "print_stats": {
                "filename": "benchy.gcode",
                "state": "printing",
                "print_duration": 1000.0,
                "total_duration": 1100.0,
                "info": {"current_layer": 42, "total_layer": 200},
            },
            "display_status": {"progress": 0.25},
            "virtual_sdcard": {"progress": 0.25},
            "extruder": {"temperature": 205.0, "target": 210.0},
            "heater_bed": {"temperature": 60.0, "target": 60.0},
        },
        stream_url="http://192.168.1.40/webcam/?action=stream",
    )
    assert status.connection == ConnectionState.CONNECTED
    assert status.print_state == PrintState.PRINTING
    assert status.job.name == "benchy.gcode"
    assert status.job.progress == 25.0
    assert status.job.elapsed_seconds == 1000
    assert status.job.remaining_seconds == 3000
    assert status.job.layer_current == 42
    assert status.job.layer_total == 200
    assert status.temperatures.nozzle_c == 205.0
    assert status.stream.available is True


def test_moonraker_schema_includes_examples() -> None:
    schema = MoonrakerPlugin.config_schema
    assert "Snapmaker U1 / Artisan (Moonraker)" in schema.examples
    assert schema.id == "moonraker"


def _mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/server/info"):
            return httpx.Response(
                200,
                json={"result": {"moonraker_version": "0.9.0", "klippy_connected": True}},
            )
        if path.endswith("/printer/objects/query"):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "eventtime": 1.0,
                        "status": {
                            "webhooks": {"state": "ready", "message": "Printer is ready"},
                            "print_stats": {
                                "filename": "",
                                "state": "standby",
                                "print_duration": 0.0,
                                "total_duration": 0.0,
                                "info": {"current_layer": None, "total_layer": None},
                            },
                            "display_status": {"progress": 0.0},
                            "virtual_sdcard": {"progress": 0.0},
                            "extruder": {"temperature": 21.0, "target": 0.0},
                            "heater_bed": {"temperature": 21.5, "target": 0.0},
                        },
                    }
                },
            )
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


def _patch_async_client(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    def client_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs = {**kwargs, "transport": transport}
        return _RealAsyncClient(*args, **kwargs)

    monkeypatch.setattr(
        "kinkajou_bridge.plugins.moonraker.plugin.httpx.AsyncClient",
        client_factory,
    )


@pytest.mark.asyncio
async def test_moonraker_verify_live(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_async_client(monkeypatch, _mock_transport())

    plugin = MoonrakerPlugin(poll_interval_seconds=0.05, connect_wait_seconds=1.0)
    bad = await plugin.verify({"name": "MR", "base_url": "not a url"})
    assert bad.ok is False

    ok = await plugin.verify(
        {
            "name": "Shop Voron",
            "base_url": "http://192.168.1.40:7125",
            "api_key": "abc123",
        }
    )
    assert ok.ok is True
    assert "0.9.0" in ok.message


@pytest.mark.asyncio
async def test_moonraker_connect_polls_status(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_async_client(monkeypatch, _mock_transport())

    plugin = MoonrakerPlugin(poll_interval_seconds=0.05, connect_wait_seconds=1.0)
    await plugin.connect(
        {
            "name": "Shop Voron",
            "base_url": "http://192.168.1.40:7125",
            "api_key": "abc123",
            "stream_url": "http://192.168.1.40/webcam/?action=stream",
            "connection_mode": "lan",
        }
    )
    try:
        status = plugin.get_status()
        assert status.connection == ConnectionState.CONNECTED
        assert status.print_state == PrintState.IDLE
        assert status.printer_name == "Shop Voron"
        assert status.stream.available is True
        assert status.temperatures.nozzle_c == 21.0

        async def first_event():
            async for event in plugin.events():
                return event

        event = await asyncio.wait_for(first_event(), timeout=2)
        assert event.type.value == "printer.connected"
    finally:
        await plugin.disconnect()
        assert plugin.get_status().connection == ConnectionState.DISCONNECTED


@pytest.mark.asyncio
async def test_bridge_add_moonraker(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from kinkajou_bridge.app import BridgeApp
    from kinkajou_bridge.settings import Settings

    _patch_async_client(monkeypatch, _mock_transport())

    settings = Settings(data_dir=tmp_path)
    bridge = BridgeApp(settings)
    await bridge.start()
    try:
        instance = await bridge.add_printer(
            name="Moon",
            plugin_id="moonraker",
            config={
                "connection_mode": "lan",
                "name": "Moon",
                "base_url": "http://192.168.1.40:7125",
                "api_key": "secret-key",
            },
        )
        public = bridge.public_printer(instance)
        assert public["config"]["api_key"] == "***"
        summaries = bridge.list_printer_summaries()
        assert summaries[0]["identity"]["host"] == "http://192.168.1.40:7125"

        status = bridge.get_status(instance.id)
        assert status is not None
        assert status.connection == ConnectionState.CONNECTED
    finally:
        await bridge.stop()
