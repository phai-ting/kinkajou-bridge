"""Normalize Bambu MQTT ``print`` reports into Bridge status and events."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from kinkajou_bridge.models import (
    ConnectionState,
    EventType,
    PrinterEvent,
    PrinterStatus,
    PrintJob,
    PrintState,
    Temperatures,
)

_GCODE_STATE_MAP: dict[str, PrintState] = {
    "IDLE": PrintState.IDLE,
    "PREPARE": PrintState.PREPARING,
    "SLICING": PrintState.PREPARING,
    "INIT": PrintState.PREPARING,
    "RUNNING": PrintState.PRINTING,
    "PAUSE": PrintState.PAUSED,
    "FINISH": PrintState.COMPLETE,
    "FAILED": PrintState.FAILED,
    "OFFLINE": PrintState.UNKNOWN,
}


def map_gcode_state(value: Any) -> PrintState:
    token = str(value or "").strip().upper()
    return _GCODE_STATE_MAP.get(token, PrintState.UNKNOWN)


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    if number is None:
        return None
    return int(number)


def _job_name(print_data: dict[str, Any]) -> str | None:
    for key in ("subtask_name", "gcode_file", "task_name"):
        raw = print_data.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        # Prefer basename for cache/ paths.
        if "/" in text or "\\" in text:
            text = text.replace("\\", "/").rsplit("/", 1)[-1]
        return text
    return None


def _progress_from_report(print_data: dict[str, Any]) -> float | None:
    """Prefer ``mc_percent``, but don't freeze if layers advance while percent stalls."""
    progress = _as_float(print_data.get("mc_percent"))
    if progress is None:
        progress = _as_float(print_data.get("percent"))
    if progress is not None:
        progress = max(0.0, min(100.0, progress))

    layer_current = _as_int(print_data.get("layer_num"))
    layer_total = _as_int(print_data.get("total_layer_num"))
    layer_progress: float | None = None
    if (
        layer_current is not None
        and layer_total is not None
        and layer_total > 0
        and layer_current >= 0
    ):
        layer_progress = max(0.0, min(100.0, (layer_current / layer_total) * 100.0))

    if progress is None:
        return layer_progress
    if layer_progress is None:
        return progress
    # When Bambu's mc_percent plateaus, layer ratio often continues to climb.
    return max(progress, layer_progress)


def merge_print_payload(
    previous: dict[str, Any] | None,
    message: dict[str, Any] | Any,
) -> dict[str, Any]:
    """Merge a (possibly partial) MQTT JSON message into the last print snapshot."""
    base = dict(previous or {})
    if not isinstance(message, dict):
        return base
    print_data = message.get("print")
    if not isinstance(print_data, dict):
        return base
    merged = dict(base)
    merged.update(print_data)
    return merged


def apply_print_snapshot(
    status: PrinterStatus,
    print_data: dict[str, Any],
    *,
    connected: bool = True,
    now_ts: float | None = None,
) -> PrinterStatus:
    """Build an updated PrinterStatus from a merged Bambu ``print`` object."""
    print_state = map_gcode_state(print_data.get("gcode_state"))
    progress = _progress_from_report(print_data)
    prev_job = status.job

    # Bambu reports remaining time in minutes.
    remaining_minutes = _as_float(print_data.get("mc_remaining_time"))
    remaining_seconds: int | None = None
    if remaining_minutes is not None:
        remaining_seconds = max(0, int(round(remaining_minutes * 60)))

    elapsed_seconds: int | None = None
    total_seconds: int | None = None
    start = _as_float(print_data.get("gcode_start_time"))
    if start is not None and start > 1_000_000:
        clock = time.time() if now_ts is None else now_ts
        elapsed_seconds = max(0, int(clock - start))
        if remaining_seconds is not None and remaining_seconds > 0:
            total_seconds = elapsed_seconds + remaining_seconds
        elif progress is not None and progress >= 100:
            total_seconds = elapsed_seconds
        elif remaining_seconds == 0 and progress is not None and progress < 100:
            # Bambu often reports 0 remaining before 100% — keep a sane total.
            prior = prev_job.total_seconds
            total_seconds = (
                prior
                if prior is not None and prior >= elapsed_seconds
                else elapsed_seconds
            )
        elif remaining_seconds is not None:
            total_seconds = elapsed_seconds + remaining_seconds
    elif progress is not None and remaining_seconds is not None and progress > 0:
        frac_left = 1.0 - (progress / 100.0)
        if remaining_seconds <= 0 and progress < 100:
            # remaining/frac would become 0 and wipe the estimate near the end.
            elapsed_seconds = prev_job.elapsed_seconds
            total_seconds = prev_job.total_seconds
        elif frac_left > 0.001:
            total_seconds = int(round(remaining_seconds / frac_left))
            elapsed_seconds = max(0, total_seconds - remaining_seconds)
            if total_seconds <= 0:
                elapsed_seconds = prev_job.elapsed_seconds
                total_seconds = prev_job.total_seconds
        elif progress >= 100:
            elapsed_seconds = prev_job.elapsed_seconds
            total_seconds = (
                (elapsed_seconds or 0) + remaining_seconds
                if elapsed_seconds is not None
                else remaining_seconds or prev_job.total_seconds
            )

    layer_current = _as_int(print_data.get("layer_num"))
    layer_total = _as_int(print_data.get("total_layer_num"))
    name = _job_name(print_data)
    file_name = None
    gcode_file = print_data.get("gcode_file")
    if gcode_file is not None and str(gcode_file).strip():
        file_name = str(gcode_file).replace("\\", "/").rsplit("/", 1)[-1]

    temps = Temperatures(
        nozzle_c=_as_float(print_data.get("nozzle_temper")),
        nozzle_target_c=_as_float(print_data.get("nozzle_target_temper")),
        bed_c=_as_float(print_data.get("bed_temper")),
        bed_target_c=_as_float(print_data.get("bed_target_temper")),
        chamber_c=_as_float(print_data.get("chamber_temper")),
    )

    job = PrintJob(
        name=name,
        progress=progress,
        remaining_seconds=remaining_seconds,
        elapsed_seconds=elapsed_seconds,
        total_seconds=total_seconds,
        layer_current=layer_current,
        layer_total=layer_total,
        file_name=file_name,
    )

    connection = ConnectionState.CONNECTED if connected else status.connection
    message = None
    if print_state == PrintState.FAILED:
        err = print_data.get("print_error")
        if err not in (None, 0, "0"):
            message = f"Print error code: {err}"

    return status.model_copy(
        update={
            "connection": connection,
            "print_state": print_state,
            "job": job,
            "temperatures": temps,
            "message": message,
            "updated_at": datetime.now(UTC),
        }
    )


def _state_transition_event(
    previous: PrintState,
    current: PrintState,
) -> EventType | None:
    if previous == current:
        return None
    if current == PrintState.PRINTING:
        if previous == PrintState.PAUSED:
            return EventType.PRINT_RESUMED
        return EventType.PRINT_STARTED
    if current == PrintState.PAUSED:
        return EventType.PRINT_PAUSED
    if current == PrintState.COMPLETE:
        return EventType.PRINT_FINISHED
    if current == PrintState.FAILED:
        return EventType.PRINT_FAILED
    if current == PrintState.CANCELLED:
        return EventType.PRINT_CANCELLED
    return None


@dataclass
class ReportTracker:
    """Tracks last emitted state for throttled event generation."""

    last_print_state: PrintState = PrintState.UNKNOWN
    last_progress: float | None = None
    last_layer: int | None = None
    last_progress_emit_at: float = 0.0
    progress_interval_s: float = 5.0
    _seen_status: bool = False

    def events_for_update(
        self,
        *,
        printer_id: str,
        printer_name: str,
        plugin_id: str,
        previous_status: PrinterStatus,
        next_status: PrinterStatus,
        now: float | None = None,
    ) -> list[PrinterEvent]:
        now = time.monotonic() if now is None else now
        events: list[PrinterEvent] = []
        payload = {
            "print_state": next_status.print_state.value,
            "progress": next_status.job.progress,
            "remaining_seconds": next_status.job.remaining_seconds,
            "layer_current": next_status.job.layer_current,
            "layer_total": next_status.job.layer_total,
            "job_name": next_status.job.name,
        }

        transition = _state_transition_event(
            self.last_print_state if self._seen_status else previous_status.print_state,
            next_status.print_state,
        )
        # On first real telemetry, avoid firing "started" just because we left UNKNOWN/IDLE
        # from the stub session — only emit when we already had a known prior state, or
        # when entering an active/terminal state from idle after we've seen status.
        if transition is not None:
            if self._seen_status or next_status.print_state in {
                PrintState.PRINTING,
                PrintState.PAUSED,
                PrintState.PREPARING,
                PrintState.COMPLETE,
                PrintState.FAILED,
                PrintState.CANCELLED,
            }:
                # Skip PRINT_STARTED on the very first snapshot if printer is already mid-job
                # unless we treat first printing sighting as started (useful for Streamer.bot).
                events.append(
                    PrinterEvent(
                        type=transition,
                        printer_id=printer_id,
                        printer_name=printer_name,
                        plugin_id=plugin_id,
                        payload=payload,
                    )
                )

        layer = next_status.job.layer_current
        if (
            layer is not None
            and self.last_layer is not None
            and layer != self.last_layer
            and next_status.print_state == PrintState.PRINTING
        ):
            events.append(
                PrinterEvent(
                    type=EventType.LAYER_CHANGED,
                    printer_id=printer_id,
                    printer_name=printer_name,
                    plugin_id=plugin_id,
                    payload=payload,
                )
            )

        progress = next_status.job.progress
        should_progress = False
        if next_status.print_state in {PrintState.PRINTING, PrintState.PREPARING}:
            if progress is not None:
                if self.last_progress is None:
                    should_progress = True
                elif abs(progress - self.last_progress) >= 1.0:
                    should_progress = True
                elif now - self.last_progress_emit_at >= self.progress_interval_s:
                    should_progress = True
        if should_progress:
            events.append(
                PrinterEvent(
                    type=EventType.PROGRESS,
                    printer_id=printer_id,
                    printer_name=printer_name,
                    plugin_id=plugin_id,
                    payload=payload,
                )
            )
            self.last_progress_emit_at = now
            self.last_progress = progress

        self.last_print_state = next_status.print_state
        if layer is not None:
            self.last_layer = layer
        self._seen_status = True
        return events
