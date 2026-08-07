from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

import websockets
from websockets.asyncio.client import ClientConnection

logger = logging.getLogger(__name__)

EventHandler = Callable[[dict[str, Any]], Awaitable[None] | None]


class StreamerBotClient:
    """Minimal Streamer.bot WebSocket client (DoAction + subscribe stubs)."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        endpoint: str = "/",
        password: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        self.password = password
        self._ws: ClientConnection | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._handlers: list[EventHandler] = []
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}{self.endpoint}"

    def on_event(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    async def connect(self) -> None:
        extra_headers = {}
        if self.password:
            extra_headers["Authorization"] = f"Bearer {self.password}"
        logger.info("Connecting to Streamer.bot at %s", self.url)
        self._ws = await websockets.connect(self.url, additional_headers=extra_headers or None)
        self._reader_task = asyncio.create_task(self._read_loop(), name="streamerbot-reader")

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def do_action(
        self,
        name: str | None = None,
        action_id: str | None = None,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not name and not action_id:
            raise ValueError("Either name or action_id is required")
        action: dict[str, Any] = {}
        if name:
            action["name"] = name
        if action_id:
            action["id"] = action_id
        return await self._request(
            {
                "request": "DoAction",
                "action": action,
                "args": args or {},
            }
        )

    async def subscribe(self, events: dict[str, list[str]]) -> dict[str, Any]:
        return await self._request({"request": "Subscribe", "events": events})

    async def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._ws is None:
            raise RuntimeError("Streamer.bot client is not connected")
        request_id = str(uuid4())
        payload = {**payload, "id": request_id}
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        await self._ws.send(json.dumps(payload))
        return await asyncio.wait_for(future, timeout=10)

    async def _read_loop(self) -> None:
        assert self._ws is not None
        try:
            async for message in self._ws:
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from Streamer.bot: %s", message)
                    continue
                request_id = data.get("id")
                if request_id and request_id in self._pending:
                    future = self._pending.pop(request_id)
                    if not future.done():
                        future.set_result(data)
                    continue
                for handler in self._handlers:
                    result = handler(data)
                    if asyncio.iscoroutine(result):
                        await result
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Streamer.bot read loop ended")
