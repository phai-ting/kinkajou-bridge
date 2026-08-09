from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from kinkajou_bridge.models import (
    ConnectionState,
    PrintJob,
    PrintState,
    PrinterCapabilities,
    PrinterStatus,
    StreamInfo,
    Temperatures,
)

# Objects requested each poll cycle (Moonraker printer.objects.query).
QUERY_OBJECTS = (
    "webhooks",
    "print_stats",
    "display_status",
    "virtual_sdcard",
    "extruder",
    "heater_bed",
)


def normalize_base_url(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"http://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if any(ch.isspace() for ch in parsed.netloc):
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def map_print_state(
    *,
    print_stats_state: str | None,
    webhooks_state: str | None,
) -> PrintState:
    klippy = (webhooks_state or "").strip().lower()
    if klippy and klippy != "ready":
        if klippy in {"shutdown", "error"}:
            return PrintState.ERROR
        return PrintState.UNKNOWN

    state = (print_stats_state or "").strip().lower()
    if state == "printing":
        return PrintState.PRINTING
    if state == "paused":
        return PrintState.PAUSED
    if state == "complete":
        return PrintState.COMPLETE
    if state == "error":
        return PrintState.ERROR
    if state == "cancelled":
        return PrintState.CANCELLED
    if state in {"standby", "ready", ""}:
        return PrintState.IDLE
    return PrintState.UNKNOWN


def build_status(
    *,
    printer_id: str,
    printer_name: str,
    plugin_id: str,
    objects: dict[str, Any],
    stream_url: str | None,
    message: str | None = None,
) -> PrinterStatus:
    webhooks = objects.get("webhooks") if isinstance(objects.get("webhooks"), dict) else {}
    print_stats = (
        objects.get("print_stats") if isinstance(objects.get("print_stats"), dict) else {}
    )
    display_status = (
        objects.get("display_status") if isinstance(objects.get("display_status"), dict) else {}
    )
    virtual_sdcard = (
        objects.get("virtual_sdcard") if isinstance(objects.get("virtual_sdcard"), dict) else {}
    )
    extruder = objects.get("extruder") if isinstance(objects.get("extruder"), dict) else {}
    heater_bed = objects.get("heater_bed") if isinstance(objects.get("heater_bed"), dict) else {}

    print_state = map_print_state(
        print_stats_state=str(print_stats.get("state") or ""),
        webhooks_state=str(webhooks.get("state") or ""),
    )

    filename = print_stats.get("filename")
    job_name = str(filename) if filename else None

    progress_pct = _progress_percent(display_status, virtual_sdcard)
    elapsed = _as_int(print_stats.get("print_duration"))
    total_duration = _as_int(print_stats.get("total_duration"))
    remaining = None
    if elapsed is not None and progress_pct is not None and progress_pct > 0:
        remaining = max(0, int(round(elapsed * (100.0 - progress_pct) / progress_pct)))
    total = None
    if elapsed is not None and remaining is not None:
        total = elapsed + remaining
    elif total_duration is not None and total_duration > 0:
        total = total_duration

    info = print_stats.get("info") if isinstance(print_stats.get("info"), dict) else {}
    layer_current = _as_int(info.get("current_layer"))
    layer_total = _as_int(info.get("total_layer"))

    status_message = message
    klippy_state = str(webhooks.get("state") or "").lower()
    if klippy_state and klippy_state != "ready":
        status_message = (
            status_message
            or str(webhooks.get("message") or f"Klipper state: {webhooks.get('state')}")
        )

    return PrinterStatus(
        printer_id=printer_id,
        printer_name=printer_name,
        plugin_id=plugin_id,
        connection=ConnectionState.CONNECTED,
        print_state=print_state,
        job=PrintJob(
            name=job_name,
            progress=progress_pct,
            remaining_seconds=remaining,
            elapsed_seconds=elapsed,
            total_seconds=total,
            file_name=job_name,
            layer_current=layer_current,
            layer_total=layer_total,
        ),
        temperatures=Temperatures(
            nozzle_c=_as_float(extruder.get("temperature")),
            nozzle_target_c=_as_float(extruder.get("target")),
            bed_c=_as_float(heater_bed.get("temperature")),
            bed_target_c=_as_float(heater_bed.get("target")),
        ),
        capabilities=PrinterCapabilities(
            thumbnail=False,
            live_stream=bool(stream_url),
            control=False,
        ),
        stream=StreamInfo(
            available=bool(stream_url),
            url=stream_url,
            protocol="mjpeg" if stream_url else None,
            notes="URL only — Bridge does not re-encode the stream." if stream_url else None,
        ),
        message=status_message,
    )


def objects_query_path() -> str:
    return "/printer/objects/query?" + "&".join(QUERY_OBJECTS)


def _progress_percent(
    display_status: dict[str, Any],
    virtual_sdcard: dict[str, Any],
) -> float | None:
    for source in (display_status.get("progress"), virtual_sdcard.get("progress")):
        try:
            if source is None:
                continue
            value = float(source)
        except (TypeError, ValueError):
            continue
        if 0.0 <= value <= 1.0:
            return max(0.0, min(100.0, value * 100.0))
        if 0.0 <= value <= 100.0:
            return max(0.0, min(100.0, value))
    return None


def _as_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
