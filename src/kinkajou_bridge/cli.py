from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import uvicorn

from kinkajou_bridge import __version__
from kinkajou_bridge.api import create_api
from kinkajou_bridge.app import BridgeApp
from kinkajou_bridge.asyncio_loop import uvicorn_loop_setting
from kinkajou_bridge.settings import Settings
from kinkajou_bridge.single_instance import acquire_single_instance


def _configure_asyncio() -> None:
    """Prefer Selector on Windows so aiomqtt can use add_reader before uvicorn starts."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kinkajou-bridge",
        description="Kinkajou Bridge — local multi-printer hub for Project Kinkajou.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--host", help="API bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, help="API bind port (default 29067)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--service",
        action="store_true",
        help="Run headless (API only, no system tray). Default is system tray mode.",
    )
    mode.add_argument(
        "--tray",
        action="store_true",
        help="Run with a system tray icon (default).",
    )
    parser.add_argument(
        "--windows-service",
        action="store_true",
        help="Windows service helper commands (not fully implemented yet).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_asyncio()
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    settings = Settings()
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port

    if args.windows_service:
        from kinkajou_bridge.service.windows import run_service_cli

        return run_service_cli()

    # One Bridge process per machine/user session (skip for --windows-service above).
    instance_lock = acquire_single_instance(settings.data_dir)
    if instance_lock is None:
        logging.getLogger(__name__).info(
            "Kinkajou Bridge is already running — opening the existing UI."
        )
        from kinkajou_bridge.ui.browser import open_url

        open_url(settings.dashboard_url)
        return 0

    if args.service:
        bridge = BridgeApp(settings)
        api = create_api(bridge)
        uvicorn.run(
            api,
            host=settings.host,
            port=settings.port,
            log_level="info",
            loop=uvicorn_loop_setting(),
        )
        return 0

    from kinkajou_bridge.ui.tray import run_tray

    return run_tray(settings)


if __name__ == "__main__":
    sys.exit(main())
