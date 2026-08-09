from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from kinkajou_bridge.models import EventType, PrinterEvent
from kinkajou_bridge.plugins.streamerbot import StreamerBotPlugin
from kinkajou_bridge.streamerbot.actions import ROUTER_ACTION_NAME, user_action_name


def test_user_action_names() -> None:
    assert user_action_name(EventType.PRINT_STARTED) == "Kinkajou - Print Started"
    assert user_action_name(EventType.PRINTER_CONNECTED) == "Kinkajou - Printer Connected"
    assert user_action_name(EventType.LAYER_CHANGED) == "Kinkajou - Print Layer Changed"
    assert user_action_name(EventType.PROGRESS) == "Kinkajou - Print Progress"
    assert user_action_name("print.finished") == "Kinkajou - Print Finished"


@pytest.mark.asyncio
async def test_handle_event_calls_router_action() -> None:
    plugin = StreamerBotPlugin()
    client = AsyncMock()
    client._ws = object()
    client.do_action = AsyncMock()
    plugin._client = client

    event = PrinterEvent(
        type=EventType.PRINT_STARTED,
        printer_id="p1",
        printer_name="H2S",
        plugin_id="bambu",
        payload={"progress": 0},
    )
    await plugin.handle_event(event)

    client.do_action.assert_awaited_once()
    kwargs = client.do_action.await_args.kwargs
    assert kwargs["name"] == ROUTER_ACTION_NAME
    assert kwargs["args"]["event_type"] == "print.started"
    assert kwargs["args"]["event_name"] == "Kinkajou - Print Started"
    assert kwargs["args"]["printer_id"] == "p1"
    assert kwargs["args"]["progress"] == 0
