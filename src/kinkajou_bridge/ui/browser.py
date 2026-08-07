from __future__ import annotations

import logging
import threading
import time
import webbrowser
from urllib.request import urlopen

logger = logging.getLogger(__name__)


def open_url(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:
        logger.exception("Failed to open URL: %s", url)


def open_url_when_ready(url: str, health_url: str, timeout_seconds: float = 15.0) -> None:
    """Open a browser URL after the local API becomes reachable."""

    def _wait_and_open() -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                with urlopen(health_url, timeout=0.5) as response:  # noqa: S310 - local health check
                    if 200 <= response.status < 300:
                        open_url(url)
                        return
            except Exception:
                time.sleep(0.2)
        logger.warning("Timed out waiting for %s; opening %s anyway", health_url, url)
        open_url(url)

    threading.Thread(target=_wait_and_open, name="open-ui", daemon=True).start()
