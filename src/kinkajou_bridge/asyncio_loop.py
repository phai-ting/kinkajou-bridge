"""Event-loop helpers for Windows + aiomqtt compatibility."""

from __future__ import annotations

import asyncio


def new_selector_loop() -> asyncio.AbstractEventLoop:
    """Create a Selector event loop (supports ``add_reader`` for aiomqtt).

    Used as uvicorn ``Config(loop=...)`` import path. Uvicorn's default Windows
    factory returns ``ProactorEventLoop``, which cannot run aiomqtt.
    """
    return asyncio.SelectorEventLoop()


def uvicorn_loop_setting() -> str:
    """Import path for uvicorn ``Config(loop=...)``."""
    return "kinkajou_bridge.asyncio_loop:new_selector_loop"
