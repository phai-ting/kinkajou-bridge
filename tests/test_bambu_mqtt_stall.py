from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from kinkajou_bridge.plugins.bambu.mqtt_session import MqttEndpoint, run_mqtt_session


def _endpoint() -> MqttEndpoint:
    return MqttEndpoint(
        host="127.0.0.1",
        port=8883,
        username="bblp",
        password="12345678",
        serial="01P00CTEST",
        tls_insecure=True,
        label="LAN (127.0.0.1)",
    )


@pytest.mark.asyncio
async def test_mqtt_session_reconnects_after_stall() -> None:
    """No report within stall_timeout forces a reconnect cycle."""
    stop = asyncio.Event()
    connection_events: list[tuple[bool, str | None]] = []
    sessions_started = 0

    class _EmptyMessages:
        def __aiter__(self) -> "_EmptyMessages":
            return self

        async def __anext__(self) -> Any:
            # Block until cancelled / timed out by wait_for in the session.
            await asyncio.sleep(3600)
            raise StopAsyncIteration

    class _FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            nonlocal sessions_started
            sessions_started += 1
            self.messages = _EmptyMessages()

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def subscribe(self, *args: Any, **kwargs: Any) -> None:
            return None

        async def publish(self, *args: Any, **kwargs: Any) -> None:
            return None

    async def on_connection(ok: bool, error: str | None) -> None:
        connection_events.append((ok, error))
        # After first stall reconnect attempt, stop the session.
        if not ok and error and "stalled" in error and sessions_started >= 1:
            stop.set()

    with patch(
        "kinkajou_bridge.plugins.bambu.mqtt_session._client_for",
        side_effect=lambda endpoint: _FakeClient(),
    ):
        await asyncio.wait_for(
            run_mqtt_session(
                _endpoint(),
                on_message=lambda _data: None,
                on_connection=on_connection,
                should_stop=stop.is_set,
                stall_timeout_s=0.05,
                pushall_interval_s=60.0,
                reconnect_base_s=0.01,
            ),
            timeout=2.0,
        )

    assert sessions_started >= 1
    assert any(ok for ok, _ in connection_events)
    assert any((not ok) and err and "stalled" in err for ok, err in connection_events)
