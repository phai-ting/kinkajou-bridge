from __future__ import annotations

import asyncio
import sys
from unittest.mock import patch

import pytest

from kinkajou_bridge.models import DiscoveredDevice

# aiomqtt requires SelectorEventLoop on Windows (add_reader).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

SAMPLE_BAMBU_DEVICES = [
    DiscoveredDevice(
        id="01P09CTEST0001",
        name="Living Room P1S",
        model="P1S",
        serial="01P09CTEST0001",
    )
]


@pytest.fixture(autouse=True)
def mock_bambu_cloud_api():
    """Keep unit tests offline — Bambu cloud listing hits the real HTTP API otherwise."""
    with (
        patch(
            "kinkajou_bridge.plugins.bambu.plugin.fetch_bound_devices",
            return_value=list(SAMPLE_BAMBU_DEVICES),
        ),
        patch(
            "kinkajou_bridge.plugins.bambu.plugin.fetch_user_id",
            return_value="1234567890",
        ),
        patch(
            "kinkajou_bridge.plugins.bambu.cloud.fetch_bound_devices",
            return_value=list(SAMPLE_BAMBU_DEVICES),
        ),
        patch(
            "kinkajou_bridge.plugins.bambu.cloud.fetch_user_id",
            return_value="1234567890",
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def mock_bambu_mqtt_session():
    """Simulate a successful MQTT link without talking to a printer."""

    async def _fake_session(endpoint, *, on_message, on_connection, should_stop, **_kwargs):
        import asyncio

        if on_connection is not None:
            result = on_connection(True, None)
            if asyncio.iscoroutine(result):
                await result
        # Deliver one idle snapshot so status can populate if callers wait.
        if on_message is not None:
            result = on_message(
                {
                    "print": {
                        "gcode_state": "IDLE",
                        "mc_percent": 0,
                        "mc_remaining_time": 0,
                        "nozzle_temper": 25.0,
                        "bed_temper": 25.0,
                    }
                }
            )
            if asyncio.iscoroutine(result):
                await result
        while not should_stop():
            await asyncio.sleep(0.05)

    with patch(
        "kinkajou_bridge.plugins.bambu.plugin.run_mqtt_session",
        side_effect=_fake_session,
    ):
        yield
