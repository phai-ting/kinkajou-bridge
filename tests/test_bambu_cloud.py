from __future__ import annotations

from kinkajou_bridge.plugins.bambu.cloud import (
    bambu_api_base,
    browser_headers,
    normalize_cloud_token,
    parse_bound_devices,
    studio_headers,
)


def test_parse_bound_devices() -> None:
    devices = parse_bound_devices(
        {
            "message": "success",
            "devices": [
                {
                    "dev_id": "01P09C123",
                    "name": "Living Room",
                    "dev_product_name": "P1S",
                    "dev_access_code": "12345678",
                    "online": True,
                }
            ],
        }
    )
    assert len(devices) == 1
    assert devices[0].serial == "01P09C123"
    assert devices[0].name == "Living Room"
    assert devices[0].model == "P1S"
    assert devices[0].hints["access_code"] == "12345678"


def test_bambu_api_base_region() -> None:
    assert bambu_api_base("global").endswith("bambulab.com")
    assert bambu_api_base("cn").endswith("bambulab.cn")


def test_studio_headers() -> None:
    assert normalize_cloud_token("Bearer abc.def.ghi") == "abc.def.ghi"
    headers = studio_headers("abc.def.ghi")
    assert headers["User-Agent"].startswith("bambu_network_agent/")
    assert headers["X-BBL-Client-Name"] == "OrcaSlicer"
    assert headers["X-BBL-Client-Type"] == "slicer"
    assert headers["Authorization"] == "Bearer abc.def.ghi"
    # Alias kept for compatibility with earlier browser-header naming.
    assert browser_headers("abc.def.ghi")["Authorization"] == "Bearer abc.def.ghi"
