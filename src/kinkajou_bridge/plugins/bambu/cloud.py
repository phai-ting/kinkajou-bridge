from __future__ import annotations

import logging
from typing import Any

import httpx

from kinkajou_bridge.models import DiscoveredDevice

logger = logging.getLogger(__name__)

BAMBU_API_GLOBAL = "https://api.bambulab.com"
BAMBU_API_CN = "https://api.bambulab.cn"

# Match the identity block used by working community clients (HA / Orca-style).
_AGENT_VERSION = "01.09.05.01"
_CLIENT_VERSION = "01.09.05.51"


def bambu_api_base(region: str | None = None) -> str:
    value = (region or "global").strip().lower()
    if value in {"cn", "china", "zh"}:
        return BAMBU_API_CN
    return BAMBU_API_GLOBAL


def normalize_cloud_token(cloud_token: str) -> str:
    token = cloud_token.strip().strip('"').strip("'")
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


def studio_headers(cloud_token: str) -> dict[str, str]:
    """Headers that resemble Bambu Studio / Orca network agent calls."""
    token = normalize_cloud_token(cloud_token)
    return {
        "User-Agent": f"bambu_network_agent/{_AGENT_VERSION}",
        "X-BBL-Client-Name": "OrcaSlicer",
        "X-BBL-Client-Type": "slicer",
        "X-BBL-Client-Version": _CLIENT_VERSION,
        "X-BBL-Language": "en-US",
        "X-BBL-OS-Type": "windows",
        "X-BBL-OS-Version": "10.0.0",
        "X-BBL-Agent-Version": _AGENT_VERSION,
        "X-BBL-Executable-info": "{}",
        "X-BBL-Agent-OS-Type": "windows",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "Authorization": f"Bearer {token}",
    }


# Keep the old name as an alias for tests / callers.
def browser_headers(cloud_token: str, *, region: str | None = None) -> dict[str, str]:
    _ = region
    return studio_headers(cloud_token)


def _raise_for_bambu_status(response: Any, *, url: str) -> None:
    status = getattr(response, "status_code", None)
    text = (getattr(response, "text", None) or "").strip()
    if status == 401:
        logger.warning(
            "Bambu cloud 401 for %s (body=%s)",
            url,
            text[:400] if text else "<empty>",
        )
        raise PermissionError(
            "Bambu Lab returned 401 Unauthorized. The access token may be expired or invalid, "
            "or the cloud region may be wrong. Copy a fresh `token` cookie from bambulab.com "
            "while logged in, then try again."
        )
    if status == 403 and "cloudflare" in text.lower():
        raise PermissionError(
            "Bambu Lab / Cloudflare blocked the request (403). Try again in a moment."
        )
    if status is not None and status >= 400:
        raise PermissionError(
            f"Bambu Lab request failed with HTTP {status}: {text[:240] or 'no body'}"
        )


def _get_json(url: str, headers: dict[str, str], *, timeout: float) -> Any:
    """GET JSON from Bambu cloud, preferring Chrome TLS impersonation when available."""
    auth_only = {"Authorization": headers["Authorization"]}
    attempts: list[tuple[str, dict[str, str]]] = [
        ("curl_cffi+chrome", auth_only),
        ("curl_cffi+studio", headers),
        ("httpx+studio", headers),
    ]

    last_error: Exception | None = None
    for label, attempt_headers in attempts:
        try:
            if label.startswith("curl_cffi"):
                from curl_cffi import requests as curl_requests

                response = curl_requests.get(
                    url,
                    headers=attempt_headers,
                    timeout=timeout,
                    impersonate="chrome",
                    allow_redirects=True,
                )
            else:
                with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                    response = client.get(url, headers=attempt_headers)

            _raise_for_bambu_status(response, url=url)
            logger.debug("Bambu cloud request succeeded via %s", label)
            return response.json()
        except ImportError:
            if label.startswith("curl_cffi"):
                logger.debug("curl_cffi unavailable; skipping %s", label)
                continue
            raise
        except PermissionError as exc:
            # Auth failures are definitive for that attempt; try the next profile
            # in case Cloudflare / header fingerprinting was the cause.
            last_error = exc
            logger.warning("Bambu cloud attempt %s failed: %s", label, exc)
            continue
        except Exception as exc:
            last_error = exc
            logger.warning("Bambu cloud attempt %s failed: %s", label, exc)
            continue

    if last_error is not None:
        raise last_error
    raise RuntimeError("Bambu cloud request failed with no attempts available")


def fetch_bound_devices(
    cloud_token: str,
    *,
    region: str | None = None,
    timeout: float = 20.0,
) -> list[DiscoveredDevice]:
    """List printers bound to a Bambu Lab cloud account.

    Uses ``GET /v1/iot-service/api/user/bind`` with a Bearer access token.
    """
    token = normalize_cloud_token(cloud_token)
    if not token:
        return []

    url = f"{bambu_api_base(region)}/v1/iot-service/api/user/bind"
    headers = studio_headers(token)
    payload = _get_json(url, headers, timeout=timeout)
    return parse_bound_devices(payload)


def parse_bound_devices(payload: Any) -> list[DiscoveredDevice]:
    """Normalize Bambu bind API JSON into DiscoveredDevice rows."""
    if not isinstance(payload, dict):
        return []
    raw_devices = payload.get("devices")
    if not isinstance(raw_devices, list):
        return []

    devices: list[DiscoveredDevice] = []
    for item in raw_devices:
        if not isinstance(item, dict):
            continue
        serial = str(item.get("dev_id") or item.get("device_id") or "").strip()
        if not serial:
            continue
        name = str(item.get("name") or item.get("device_name") or serial).strip()
        model = (
            str(item.get("dev_product_name") or item.get("dev_model_name") or "").strip()
            or None
        )
        hints: dict[str, str] = {}
        access_code = str(item.get("dev_access_code") or "").strip()
        if access_code:
            hints["access_code"] = access_code
        if item.get("online") is not None:
            hints["online"] = "true" if item.get("online") else "false"
        devices.append(
            DiscoveredDevice(
                id=serial,
                name=name,
                model=model,
                serial=serial,
                hints=hints,
            )
        )
    return devices
