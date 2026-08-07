from __future__ import annotations

from unittest.mock import patch

import pytest

from kinkajou_bridge.models import DiscoveredDevice

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
    with patch(
        "kinkajou_bridge.plugins.bambu.plugin.fetch_bound_devices",
        return_value=list(SAMPLE_BAMBU_DEVICES),
    ) as mocked:
        yield mocked
