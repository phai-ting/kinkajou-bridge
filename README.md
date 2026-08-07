# Kinkajou Bridge

Local multi-printer hub for Streamer.bot and other tools. Part of
[Project Kinkajou](https://kinkajou.dev).

Documentation: https://kinkajou.dev/bridge/

## Status

Early scaffold:

- Service, printer, and integration plugin contracts (entry points supported)
- Built-in Bambu Lab cloud service + printer (MQTT); OctoPrint printer (REST polling); Streamer.bot integration
- Local HTTP API (`/v1/...`) and event WebSocket
- Tray mode by default; `--service` for headless API-only

## Requirements

- [uv](https://docs.astral.sh/uv/)
- Python **3.13** preferred (project requires `>=3.12`)

## Setup

```powershell
cd D:\Development\workspace_kinkajou\Kinkajou-Bridge
uv sync
```

## Run

```powershell
# System tray + API (default)
uv run kinkajou-bridge

# Headless API only (no tray) — useful for Windows Service / background runs
uv run kinkajou-bridge --service
```

UI routes:

| Path | Purpose |
| --- | --- |
| `/ui/welcome` | First-run greeting |
| `/ui/setup?kind=service` | Connect a service |
| `/ui/setup?kind=printer` | Add a printer |
| `/ui/setup?kind=integration` | Add an integration (e.g. Streamer.bot) |
| `/ui/` | Dashboard |

### Override host / port

Default port **29067** is the NCBI taxonomy ID for the kinkajou (*Potos flavus*). Override if needed:

```powershell
# CLI
uv run kinkajou-bridge --port 9000

# Environment
$env:KINKAJOU_BRIDGE_PORT = "9000"
uv run kinkajou-bridge
```

## Tests / lint

```powershell
uv run pytest
uv run ruff check src tests
```

## API sketch

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness |
| `GET` | `/v1/plugins` | All plugins (`kind`: `service` \| `printer` \| `integration`) |
| `GET` | `/v1/services/plugins` | Service plugins + schemas |
| `GET` | `/v1/services` | Connected service instances |
| `POST` | `/v1/services` | Connect a service |
| `GET` | `/v1/services/{id}/devices` | Devices discovered via a service |
| `GET` | `/v1/printers/plugins` | Printer plugins + schemas |
| `GET` | `/v1/printers` | Printer instances |
| `GET` | `/v1/printers/{id}/status` | Live status snapshot |
| `GET` | `/v1/integrations/plugins` | Integration plugins + schemas |
| `GET` | `/v1/integrations` | Integration instances |
| `POST` | `/v1/integrations` | Add an integration |
| `WS` | `/v1/events` | Push events |

Default bind: `127.0.0.1:29067` (overridable). Optional auth via `KINKAJOU_BRIDGE_API_TOKEN`.
Secret config fields are redacted (`***`) in API responses.

## Extending (third-party modules)

Ship a Python package that registers entry points:

| Group | Plugin kind |
| --- | --- |
| `kinkajou_bridge.services` | Account / hub (`ServicePlugin`) |
| `kinkajou_bridge.printers` | Device session (`PrinterPlugin`) |
| `kinkajou_bridge.integrations` | Outbound consumer (`IntegrationPlugin`) |

A single package can register into one or more groups. Configure Streamer.bot from the UI
(`/ui/setup?kind=integration`) rather than env vars; legacy
`KINKAJOU_BRIDGE_STREAMERBOT_*` settings still migrate into an integration on first start.

## Packaging

PyInstaller is available in the dev group for embedding a Python runtime in the
Windows tray/service build (spec to be added when the app is closer to shippable).
