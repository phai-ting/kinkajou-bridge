# Streamer.bot — Kinkajou Bridge

Bridge calls a single Streamer.bot action named **`Kinkajou Bridge`**. That action
routes to your own handlers (for example `Kinkajou - Print Started`) so re-importing
this export does not overwrite your automation.

Docs: https://kinkajou.dev/bridge/streamerbot-actions/

## Import

1. In Streamer.bot, open **Import**.
2. Drag in [`KinkajouBridge.sb`](KinkajouBridge.sb), or paste its contents.
3. Import the **`Kinkajou Bridge`** action (overwrite is fine — this is the router only).

## Your actions

Create empty (or full) actions only for events you care about, named exactly:

| User action | Event |
| --- | --- |
| `Kinkajou - Printer Connected` | `printer.connected` |
| `Kinkajou - Printer Disconnected` | `printer.disconnected` |
| `Kinkajou - Printer Error` | `printer.error` |
| `Kinkajou - Printer Status` | `printer.status` |
| `Kinkajou - Print Started` | `print.started` |
| `Kinkajou - Print Paused` | `print.paused` |
| `Kinkajou - Print Resumed` | `print.resumed` |
| `Kinkajou - Print Finished` | `print.finished` |
| `Kinkajou - Print Failed` | `print.failed` |
| `Kinkajou - Print Cancelled` | `print.cancelled` |
| `Kinkajou - Print Layer Changed` | `print.layer_changed` |
| `Kinkajou - Print Progress` | `print.progress` |

Missing handlers are skipped quietly.

## Arguments

Bridge passes (among others): `event_name`, `event_type`, `printer_id`,
`printer_name`, `plugin_id`, plus job fields such as `progress` and
`remaining_seconds` when available.

## Source

[`KinkajouBridgeRouter.cs`](KinkajouBridgeRouter.cs) is the C# used by the export.
If you change the source, rebuild the `.sb` with:

```bash
python streamerbot/build_export.py
```
