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
    # Drop path/query so callers always append /api/...
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def map_print_state(*, state_text: str | None, flags: dict[str, Any] | None) -> PrintState:
    flags = flags or {}
    text = (state_text or "").strip().lower()

    if flags.get("error") or text in {"error", "closed with error"} or "error" in text:
        return PrintState.ERROR
    if flags.get("cancelling") or "cancel" in text:
        return PrintState.CANCELLED
    if flags.get("paused") or flags.get("pausing") or text == "paused" or "paused" in text:
        return PrintState.PAUSED
    if flags.get("printing") or flags.get("resuming") or text == "printing":
        return PrintState.PRINTING
    if flags.get("finishing") or "finish" in text:
        return PrintState.COMPLETE
    if flags.get("operational") or text in {"operational", "ready"}:
        return PrintState.IDLE
    if "offline" in text or flags.get("closedOrError"):
        return PrintState.UNKNOWN
    return PrintState.UNKNOWN


def build_status(
    *,
    printer_id: str,
    printer_name: str,
    plugin_id: str,
    printer_payload: dict[str, Any],
    job_payload: dict[str, Any],
    stream_url: str | None,
    message: str | None = None,
) -> PrinterStatus:
    state = printer_payload.get("state") or {}
    flags = state.get("flags") if isinstance(state, dict) else {}
    if not isinstance(flags, dict):
        flags = {}
    state_text = None
    if isinstance(state, dict):
        state_text = state.get("text")
    if not state_text:
        state_text = job_payload.get("state")

    print_state = map_print_state(state_text=str(state_text or ""), flags=flags)

    temps_raw = printer_payload.get("temperature") or {}
    tool0 = temps_raw.get("tool0") if isinstance(temps_raw, dict) else None
    bed = temps_raw.get("bed") if isinstance(temps_raw, dict) else None
    if not isinstance(tool0, dict):
        tool0 = {}
    if not isinstance(bed, dict):
        bed = {}

    job = job_payload.get("job") if isinstance(job_payload.get("job"), dict) else {}
    file_info = job.get("file") if isinstance(job.get("file"), dict) else {}
    progress = (
        job_payload.get("progress") if isinstance(job_payload.get("progress"), dict) else {}
    )

    job_name = file_info.get("display") or file_info.get("name")
    completion = progress.get("completion")
    try:
        progress_pct = float(completion) if completion is not None else None
    except (TypeError, ValueError):
        progress_pct = None
    if progress_pct is not None:
        progress_pct = max(0.0, min(100.0, progress_pct))

    print_time = progress.get("printTime")
    print_time_left = progress.get("printTimeLeft")
    estimated = job.get("estimatedPrintTime")

    def _as_int(value: Any) -> int | None:
        try:
            if value is None:
                return None
            return int(float(value))
        except (TypeError, ValueError):
            return None

    elapsed = _as_int(print_time)
    remaining = _as_int(print_time_left)
    total = _as_int(estimated)
    if total is None and elapsed is not None and remaining is not None:
        total = elapsed + remaining

    offline = "offline" in str(state_text or "").lower() or (
        bool(flags.get("closedOrError")) and not flags.get("operational")
    )
    connection = ConnectionState.CONNECTED
    status_message = message
    if offline:
        status_message = status_message or "OctoPrint is reachable, but the printer is offline."

    return PrinterStatus(
        printer_id=printer_id,
        printer_name=printer_name,
        plugin_id=plugin_id,
        connection=connection,
        print_state=print_state,
        job=PrintJob(
            name=str(job_name) if job_name else None,
            progress=progress_pct,
            remaining_seconds=remaining,
            elapsed_seconds=elapsed,
            total_seconds=total,
            file_name=str(file_info.get("name")) if file_info.get("name") else None,
        ),
        temperatures=Temperatures(
            nozzle_c=_as_float(tool0.get("actual")),
            nozzle_target_c=_as_float(tool0.get("target")),
            bed_c=_as_float(bed.get("actual")),
            bed_target_c=_as_float(bed.get("target")),
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


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
