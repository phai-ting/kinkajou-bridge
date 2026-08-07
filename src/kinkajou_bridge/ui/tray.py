from __future__ import annotations

import logging
import threading
from typing import Any
from urllib.parse import quote

import uvicorn

from kinkajou_bridge.api import create_api
from kinkajou_bridge.app import BridgeApp
from kinkajou_bridge.asyncio_loop import uvicorn_loop_setting
from kinkajou_bridge.settings import Settings
from kinkajou_bridge.ui.browser import open_url

logger = logging.getLogger(__name__)


def run_tray(settings: Settings) -> int:
    """Start the API in a background thread and show a system tray icon."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise SystemExit(
            "Tray mode requires pystray and pillow. Install project dependencies first."
        ) from exc

    bridge = BridgeApp(settings)
    api = create_api(bridge)
    server = uvicorn.Server(
        uvicorn.Config(
            api,
            host=settings.host,
            port=settings.port,
            log_level="info",
            loop=uvicorn_loop_setting(),
        )
    )

    def _serve() -> None:
        server.run()

    thread = threading.Thread(target=_serve, name="kinkajou-api", daemon=True)
    thread.start()

    image = Image.new("RGB", (64, 64), color=(32, 32, 36))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 56, 56), fill=(79, 143, 217))

    def on_open_dashboard(_icon: Any, _item: Any) -> None:
        open_url(settings.dashboard_url)

    def on_open_setup(_icon: Any, _item: Any) -> None:
        open_url(settings.setup_url)

    def on_open_integrations(_icon: Any, _item: Any) -> None:
        open_url(f"{settings.setup_url}?kind=integration")

    def on_open_docs(_icon: Any, _item: Any) -> None:
        open_url(f"{settings.website_url.rstrip('/')}/bridge/")

    def on_open_printer(printer_id: str):
        def _handler(_icon: Any, _item: Any) -> None:
            open_url(
                f"{settings.setup_url}?kind=printer&id={quote(printer_id, safe='')}"
            )

        return _handler

    def on_quit(icon: Any, _item: Any) -> None:
        server.should_exit = True
        icon.stop()

    def menu_items():
        """Rebuild on each open so newly added printers appear without a restart."""
        yield pystray.MenuItem("Open dashboard", on_open_dashboard)
        yield pystray.MenuItem("Printers", on_open_setup)
        yield pystray.MenuItem("Documentation", on_open_docs)
        yield pystray.Menu.SEPARATOR

        try:
            bridge.store.load()
            printers = list(bridge.store.list())
        except Exception:
            logger.exception("Failed to load printers for tray menu")
            printers = []

        if not printers:
            yield pystray.MenuItem("No printers yet", None, enabled=False)
        else:
            for instance in printers:
                name = (instance.name or "").strip() or instance.id
                yield pystray.MenuItem(name, on_open_printer(instance.id))

        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem(
            f"API {settings.base_url}",
            None,
            enabled=False,
        )
        yield pystray.MenuItem("Quit", on_quit)

    menu = pystray.Menu(menu_items)
    icon = pystray.Icon("kinkajou-bridge", image, "Kinkajou Bridge", menu)
    logger.info("Tray mode listening on %s", settings.base_url)
    icon.run()
    return 0
