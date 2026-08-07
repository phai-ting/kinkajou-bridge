from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from kinkajou_bridge.models import ConnectionState
from kinkajou_bridge.plugins.streamerbot import StreamerBotPlugin
from kinkajou_bridge.streamerbot.client import StreamerBotClient


@pytest.mark.asyncio
async def test_streamerbot_retries_until_connected() -> None:
    plugin = StreamerBotPlugin(reconnect_interval_seconds=0.05)
    attempts = {"n": 0}

    async def flaky_connect(self: StreamerBotClient) -> None:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionRefusedError("Streamer.bot not listening")
        self._ws = object()  # type: ignore[assignment]

    async def fake_close(self: StreamerBotClient) -> None:
        self._ws = None

    with (
        patch.object(StreamerBotClient, "connect", flaky_connect),
        patch.object(StreamerBotClient, "close", fake_close),
    ):
        await plugin.connect(
            {
                "host": "127.0.0.1",
                "port": 8080,
                "endpoint": "/",
            }
        )
        assert plugin.get_status().connection == ConnectionState.ERROR
        assert "Retrying every" in (plugin.get_status().message or "")

        for _ in range(80):
            if plugin.get_status().connection == ConnectionState.CONNECTED:
                break
            await asyncio.sleep(0.025)

        assert plugin.get_status().connection == ConnectionState.CONNECTED
        assert attempts["n"] >= 3
        assert plugin._reconnect_task is None or plugin._reconnect_task.done()

        await plugin.disconnect()
        assert plugin.get_status().connection == ConnectionState.DISCONNECTED
        assert plugin._client is None


@pytest.mark.asyncio
async def test_streamerbot_disconnect_cancels_reconnect() -> None:
    plugin = StreamerBotPlugin(reconnect_interval_seconds=60.0)

    async def always_fail(self: StreamerBotClient) -> None:
        raise OSError("down")

    with patch.object(StreamerBotClient, "connect", always_fail):
        await plugin.connect({"host": "127.0.0.1", "port": 8080, "endpoint": "/"})
        assert plugin.get_status().connection == ConnectionState.ERROR
        task = plugin._reconnect_task
        assert task is not None and not task.done()

        await plugin.disconnect()
        assert plugin._reconnect_task is None
        assert task.cancelled() or task.done()
