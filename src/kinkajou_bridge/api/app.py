from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from kinkajou_bridge.app import BridgeApp
from kinkajou_bridge.models import DiscoveredDevice, IntegrationStatus, PrinterStatus, ServiceStatus
from kinkajou_bridge.ui.browser import open_url_when_ready

logger = logging.getLogger(__name__)


def _ui_root() -> Path:
    return Path(str(files("kinkajou_bridge.ui"))) / "static"


def _overlays_root() -> Path:
    return Path(str(files("kinkajou_bridge.ui"))) / "overlays"


def create_api(bridge: BridgeApp) -> FastAPI:
    ui_root = _ui_root()
    overlays_root = _overlays_root()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await bridge.start()
        if bridge.should_open_ui_on_start():
            open_url_when_ready(
                bridge.settings.welcome_url,
                bridge.settings.health_url,
            )
        try:
            yield
        finally:
            await bridge.stop()

    api = FastAPI(
        title="Kinkajou Bridge API",
        version="0.1.0",
        description="Local HTTP/WebSocket API for Project Kinkajou Bridge.",
        lifespan=lifespan,
    )

    # Allow hosted OBS Browser Sources (and local preview) to call the local API.
    api.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if ui_root.exists():
        api.mount("/ui/static", StaticFiles(directory=ui_root), name="ui-static")

    # Same-origin OBS overlays (avoids Chromium "local network / other apps" prompts
    # that appear when a remote page calls http://127.0.0.1).
    if overlays_root.exists():
        api.mount(
            "/bridge",
            StaticFiles(directory=overlays_root, html=True),
            name="overlays",
        )

    def require_token(authorization: str | None = Header(default=None)) -> None:
        token = bridge.settings.api_token
        if not token:
            return
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="Unauthorized")

    def _page(name: str) -> HTMLResponse:
        path = ui_root / name
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"UI page missing: {name}")
        return HTMLResponse(path.read_text(encoding="utf-8"))

    @api.get("/")
    async def root() -> RedirectResponse:
        if bridge.should_show_welcome():
            return RedirectResponse(url="/ui/welcome")
        return RedirectResponse(url="/ui/")

    @api.get("/ui")
    @api.get("/ui/")
    async def ui_dashboard() -> HTMLResponse:
        return _page("dashboard.html")

    @api.get("/ui/welcome")
    async def ui_welcome() -> HTMLResponse:
        return _page("welcome.html")

    @api.get("/ui/setup")
    async def ui_setup() -> HTMLResponse:
        return _page("setup.html")

    @api.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "kinkajou-bridge"}

    @api.get("/v1/ui/state")
    async def ui_state() -> dict[str, Any]:
        return bridge.ui_snapshot()

    @api.post("/v1/ui/welcome/complete")
    async def ui_welcome_complete() -> dict[str, Any]:
        bridge.mark_welcome_completed()
        return bridge.ui_snapshot()

    @api.get("/v1/plugins", dependencies=[Depends(require_token)])
    async def list_plugins() -> list[dict[str, Any]]:
        return bridge.list_plugins()

    @api.get("/v1/printers/plugins", dependencies=[Depends(require_token)])
    async def list_printer_plugins() -> list[dict[str, Any]]:
        return bridge.list_printer_plugins()

    @api.get("/v1/services/plugins", dependencies=[Depends(require_token)])
    async def list_service_plugins() -> list[dict[str, Any]]:
        return bridge.list_service_plugins()

    @api.get("/v1/services", dependencies=[Depends(require_token)])
    async def list_services() -> list[dict[str, Any]]:
        return bridge.list_service_summaries()

    @api.get("/v1/services/{service_id}", dependencies=[Depends(require_token)])
    async def get_service(service_id: str) -> ServiceStatus:
        status = bridge.get_service_status(service_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Service not found")
        return status

    @api.get("/v1/services/{service_id}/devices", dependencies=[Depends(require_token)])
    async def list_service_devices(service_id: str) -> list[DiscoveredDevice]:
        try:
            return bridge.list_service_devices(service_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @api.post("/v1/services", dependencies=[Depends(require_token)])
    async def create_service(body: dict[str, Any]) -> dict[str, Any]:
        try:
            instance = await bridge.add_service(
                name=str(body["name"]),
                plugin_id=str(body["plugin_id"]),
                config=dict(body.get("config") or {}),
                enabled=bool(body.get("enabled", True)),
            )
            return bridge.public_service(instance)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @api.delete("/v1/services/{service_id}", dependencies=[Depends(require_token)])
    async def delete_service(service_id: str) -> dict[str, bool]:
        try:
            deleted = await bridge.remove_service(service_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="Service not found")
        return {"deleted": True}

    @api.get("/v1/integrations/plugins", dependencies=[Depends(require_token)])
    async def list_integration_plugins() -> list[dict[str, Any]]:
        return bridge.list_integration_plugins()

    @api.get("/v1/integrations", dependencies=[Depends(require_token)])
    async def list_integrations() -> list[dict[str, Any]]:
        return bridge.list_integration_summaries()

    @api.get("/v1/integrations/{integration_id}", dependencies=[Depends(require_token)])
    async def get_integration(integration_id: str) -> IntegrationStatus:
        status = bridge.get_integration_status(integration_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Integration not found")
        return status

    @api.post("/v1/integrations", dependencies=[Depends(require_token)])
    async def create_integration(body: dict[str, Any]) -> dict[str, Any]:
        try:
            instance = await bridge.add_integration(
                name=str(body["name"]),
                plugin_id=str(body["plugin_id"]),
                config=dict(body.get("config") or {}),
                enabled=bool(body.get("enabled", True)),
            )
            return bridge.public_integration(instance)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @api.delete("/v1/integrations/{integration_id}", dependencies=[Depends(require_token)])
    async def delete_integration(integration_id: str) -> dict[str, bool]:
        deleted = await bridge.remove_integration(integration_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Integration not found")
        return {"deleted": True}

    @api.get("/v1/printers", dependencies=[Depends(require_token)])
    async def list_printers() -> list[dict[str, Any]]:
        return bridge.list_printer_summaries()

    @api.get("/v1/printers/{printer_id}", dependencies=[Depends(require_token)])
    async def get_printer(printer_id: str) -> dict[str, Any]:
        status = bridge.get_status(printer_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Printer not found")
        return status.model_dump(mode="json")

    @api.get("/v1/printers/{printer_id}/status", dependencies=[Depends(require_token)])
    async def get_printer_status(printer_id: str) -> PrinterStatus:
        status = bridge.get_status(printer_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Printer not found")
        return status

    @api.get("/v1/printers/{printer_id}/stream", dependencies=[Depends(require_token)])
    async def get_stream(printer_id: str) -> dict[str, Any]:
        status = bridge.get_status(printer_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Printer not found")
        return status.stream.model_dump(mode="json")

    @api.get("/v1/printers/{printer_id}/thumbnail", dependencies=[Depends(require_token)])
    async def get_thumbnail(printer_id: str) -> JSONResponse:
        status = bridge.get_status(printer_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Printer not found")
        if not status.capabilities.thumbnail:
            raise HTTPException(status_code=404, detail="Thumbnail not available")
        raise HTTPException(
            status_code=501,
            detail="Thumbnail retrieval is not implemented for this plugin yet.",
        )

    @api.post("/v1/printers", dependencies=[Depends(require_token)])
    async def create_printer(body: dict[str, Any]) -> dict[str, Any]:
        try:
            service_id = body.get("service_instance_id")
            instance = await bridge.add_printer(
                name=str(body["name"]),
                plugin_id=str(body["plugin_id"]),
                config=dict(body.get("config") or {}),
                enabled=bool(body.get("enabled", True)),
                service_instance_id=None if service_id in (None, "") else str(service_id),
            )
            return bridge.public_printer(instance)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @api.delete("/v1/printers/{printer_id}", dependencies=[Depends(require_token)])
    async def delete_printer(printer_id: str) -> dict[str, bool]:
        deleted = await bridge.remove_printer(printer_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Printer not found")
        return {"deleted": True}

    @api.websocket("/v1/events")
    async def events_ws(websocket: WebSocket) -> None:
        token = bridge.settings.api_token
        if token:
            provided = websocket.query_params.get("token")
            auth = websocket.headers.get("authorization")
            if provided != token and auth != f"Bearer {token}":
                await websocket.close(code=4401)
                return
        await websocket.accept()
        queue = bridge.subscribe_events()
        try:
            while True:
                get_task = asyncio.create_task(queue.get())
                recv_task = asyncio.create_task(websocket.receive_text())
                done, pending = await asyncio.wait(
                    {get_task, recv_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if recv_task in done:
                    try:
                        recv_task.result()
                    except WebSocketDisconnect:
                        break
                if get_task in done:
                    event = get_task.result()
                    await websocket.send_json(event.model_dump(mode="json"))
        except WebSocketDisconnect:
            pass
        finally:
            bridge.unsubscribe_events(queue)

    return api
