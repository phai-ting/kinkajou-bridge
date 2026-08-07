from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from kinkajou_bridge.models import ConnectionState, PrintState
from kinkajou_bridge.plugins.octoprint import OctoPrintPlugin
from kinkajou_bridge.plugins.octoprint.status import build_status, map_print_state, normalize_base_url

_RealAsyncClient = httpx.AsyncClient


def test_normalize_base_url() -> None:
    assert normalize_base_url("192.168.1.40") == "http://192.168.1.40"
    assert normalize_base_url("http://octopi.local/api/") == "http://octopi.local"
    assert normalize_base_url("https://printer.local:443") == "https://printer.local:443"
    assert normalize_base_url("not a url") == ""


def test_map_print_state() -> None:
    assert map_print_state(state_text="Printing", flags={"printing": True}) == PrintState.PRINTING
    assert map_print_state(state_text="Paused", flags={"paused": True}) == PrintState.PAUSED
    assert map_print_state(state_text="Operational", flags={"operational": True}) == PrintState.IDLE
    assert map_print_state(state_text="Finishing", flags={"finishing": True}) == PrintState.COMPLETE
    assert map_print_state(state_text="Error", flags={"error": True}) == PrintState.ERROR


def test_build_status_from_octoprint_payloads() -> None:
    status = build_status(
        printer_id="http://192.168.1.40",
        printer_name="Workshop",
        plugin_id="octoprint",
        printer_payload={
            "state": {"text": "Printing", "flags": {"printing": True, "operational": True}},
            "temperature": {
                "tool0": {"actual": 205.0, "target": 210.0},
                "bed": {"actual": 60.0, "target": 60.0},
            },
        },
        job_payload={
            "job": {
                "file": {"name": "benchy.gcode", "display": "benchy.gcode"},
                "estimatedPrintTime": 3600,
            },
            "progress": {"completion": 42.5, "printTime": 1000, "printTimeLeft": 2000},
            "state": "Printing",
        },
        stream_url="http://192.168.1.40/webcam/?action=stream",
    )
    assert status.connection == ConnectionState.CONNECTED
    assert status.print_state == PrintState.PRINTING
    assert status.job.name == "benchy.gcode"
    assert status.job.progress == 42.5
    assert status.job.elapsed_seconds == 1000
    assert status.job.remaining_seconds == 2000
    assert status.temperatures.nozzle_c == 205.0
    assert status.stream.available is True


def _mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/api/version"):
            return httpx.Response(
                200,
                json={"api": "0.1", "server": "1.9.3", "text": "OctoPrint 1.9.3"},
            )
        if path.endswith("/api/printer"):
            return httpx.Response(
                200,
                json={
                    "state": {
                        "text": "Operational",
                        "flags": {"operational": True, "ready": True},
                    },
                    "temperature": {
                        "tool0": {"actual": 21.0, "target": 0.0},
                        "bed": {"actual": 21.5, "target": 0.0},
                    },
                },
            )
        if path.endswith("/api/job"):
            return httpx.Response(
                200,
                json={
                    "job": {"file": {"name": None}},
                    "progress": {
                        "completion": None,
                        "printTime": None,
                        "printTimeLeft": None,
                    },
                    "state": "Operational",
                },
            )
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


def _patch_async_client(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    def client_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs = {**kwargs, "transport": transport}
        return _RealAsyncClient(*args, **kwargs)

    monkeypatch.setattr(
        "kinkajou_bridge.plugins.octoprint.plugin.httpx.AsyncClient",
        client_factory,
    )


@pytest.mark.asyncio
async def test_octoprint_verify_live(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_async_client(monkeypatch, _mock_transport())

    plugin = OctoPrintPlugin(poll_interval_seconds=0.05, connect_wait_seconds=1.0)
    bad = await plugin.verify({"name": "OP", "base_url": "not-a-url"})
    assert bad.ok is False

    missing_key = await plugin.verify({"name": "OP", "base_url": "http://192.168.1.40"})
    assert missing_key.ok is False

    ok = await plugin.verify(
        {
            "name": "Workshop",
            "base_url": "http://192.168.1.40",
            "api_key": "abc123",
        }
    )
    assert ok.ok is True
    assert "1.9.3" in ok.message


@pytest.mark.asyncio
async def test_octoprint_connect_polls_status(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_async_client(monkeypatch, _mock_transport())

    plugin = OctoPrintPlugin(poll_interval_seconds=0.05, connect_wait_seconds=1.0)
    await plugin.connect(
        {
            "name": "Workshop",
            "base_url": "http://192.168.1.40",
            "api_key": "abc123",
            "stream_url": "http://192.168.1.40/webcam/?action=stream",
            "connection_mode": "lan",
        }
    )
    try:
        status = plugin.get_status()
        assert status.connection == ConnectionState.CONNECTED
        assert status.print_state == PrintState.IDLE
        assert status.printer_name == "Workshop"
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
async def test_bridge_add_octoprint(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from kinkajou_bridge.app import BridgeApp
    from kinkajou_bridge.settings import Settings

    _patch_async_client(monkeypatch, _mock_transport())

    settings = Settings(data_dir=tmp_path)
    bridge = BridgeApp(settings)
    await bridge.start()
    try:
        instance = await bridge.add_printer(
            name="Octo",
            plugin_id="octoprint",
            config={
                "connection_mode": "lan",
                "name": "Octo",
                "base_url": "http://192.168.1.40",
                "api_key": "secret-key",
            },
        )
        public = bridge.public_printer(instance)
        assert public["config"]["api_key"] == "***"
        summaries = bridge.list_printer_summaries()
        assert summaries[0]["identity"]["host"] == "http://192.168.1.40"

        status = bridge.get_status(instance.id)
        assert status is not None
        assert status.connection == ConnectionState.CONNECTED
    finally:
        await bridge.stop()
