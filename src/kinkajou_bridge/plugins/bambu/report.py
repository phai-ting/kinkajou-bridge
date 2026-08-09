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

# While a job is active, progress / elapsed / total must not jump backwards.
_ACTIVE_PRINT_STATES = frozenset(
    {
        PrintState.PREPARING,
        PrintState.PRINTING,
        PrintState.PAUSED,
    }
)

# Cleared when leaving idle/complete/failed for a new active job so stale
# completion telemetry (100%, old start time, last layer) cannot stick.
_STALE_JOB_KEYS = (
    "mc_percent",
    "percent",
    "mc_remaining_time",
    "gcode_start_time",
    "layer_num",
    "total_layer_num",
    "print_error",
)


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
    """Use Bambu ``mc_percent`` so overlays match Bambu Studio."""
    progress = _as_float(print_data.get("mc_percent"))
    if progress is None:
        progress = _as_float(print_data.get("percent"))
    if progress is not None:
        return max(0.0, min(100.0, progress))
    return None


def _reconcile_progress_with_timing(
    *,
    print_state: PrintState,
    progress: float | None,
    elapsed_seconds: int | None,
    remaining_seconds: int | None,
    total_seconds: int | None,
    layer_current: int | None,
    layer_total: int | None,
) -> float | None:
    """If timing says the job is early, do not keep a stale ~100% progress."""
    if print_state not in _ACTIVE_PRINT_STATES:
        return progress
    if progress is None or progress < 99.5:
        return progress

    early_by_remaining = remaining_seconds is not None and remaining_seconds > 120
    early_by_elapsed = (
        elapsed_seconds is not None
        and total_seconds is not None
        and total_seconds > 0
        and (elapsed_seconds / total_seconds) < 0.95
    )
    if not (early_by_remaining or early_by_elapsed):
        return progress

    if (
        layer_current is not None
        and layer_total is not None
        and layer_total > 0
        and layer_current / layer_total < 0.995
    ):
        return max(0.0, min(100.0, (layer_current / layer_total) * 100.0))
    if early_by_elapsed and total_seconds:
        return max(0.0, min(99.0, (elapsed_seconds / total_seconds) * 100.0))
    return 0.0


def _continuing_active_job(
    *,
    previous_state: PrintState,
    next_state: PrintState,
    previous_name: str | None,
    next_name: str | None,
    previous_start: float | None = None,
    next_start: float | None = None,
) -> bool:
    """True when telemetry should stay monotonic with the previous snapshot."""
    if next_state not in _ACTIVE_PRINT_STATES:
        return False
    if previous_state not in _ACTIVE_PRINT_STATES:
        return False
    if previous_name and next_name and previous_name != next_name:
        return False
    if (
        previous_start is not None
        and next_start is not None
        and abs(previous_start - next_start) > 0.5
    ):
        return False
    return True


def _monotonic_job_timing(
    *,
    previous: PrintJob,
    progress: float | None,
    elapsed_seconds: int | None,
    total_seconds: int | None,
) -> tuple[float | None, int | None, int | None]:
    """Never let progress / elapsed / total decrease for an in-progress job."""
    if previous.progress is not None:
        if progress is None:
            progress = previous.progress
        else:
            progress = max(progress, previous.progress)

    if previous.elapsed_seconds is not None:
        if elapsed_seconds is None:
            elapsed_seconds = previous.elapsed_seconds
        else:
            elapsed_seconds = max(elapsed_seconds, previous.elapsed_seconds)

    if previous.total_seconds is not None:
        if total_seconds is None:
            total_seconds = previous.total_seconds
        else:
            total_seconds = max(total_seconds, previous.total_seconds)

    # Keep total at least elapsed after clamping.
    if elapsed_seconds is not None and total_seconds is not None:
        total_seconds = max(total_seconds, elapsed_seconds)

    return progress, elapsed_seconds, total_seconds


def _not_on_last_layer(layer_current: int | None, layer_total: int | None) -> bool:
    return (
        layer_current is not None
        and layer_total is not None
        and layer_total > 0
        and layer_current < layer_total
    )


def _rescue_premature_zero_remaining(
    *,
    print_state: PrintState,
    remaining_seconds: int | None,
    elapsed_seconds: int | None,
    total_seconds: int | None,
    progress: float | None,
    layer_current: int | None,
    layer_total: int | None,
    previous: PrintJob,
) -> tuple[int | None, int | None]:
    """If layers remain, a 0 remaining estimate is not believable — recover one."""
    if print_state not in _ACTIVE_PRINT_STATES:
        return remaining_seconds, total_seconds
    if remaining_seconds is None or remaining_seconds > 0:
        return remaining_seconds, total_seconds
    if not _not_on_last_layer(layer_current, layer_total):
        return remaining_seconds, total_seconds

    rescued: int | None = None
    if previous.remaining_seconds is not None and previous.remaining_seconds > 0:
        rescued = previous.remaining_seconds
    if (
        rescued is None
        and total_seconds is not None
        and elapsed_seconds is not None
    ):
        derived = max(0, total_seconds - elapsed_seconds)
        if derived > 0:
            rescued = derived
    if (
        rescued is None
        and elapsed_seconds is not None
        and progress is not None
        and 0.5 < progress < 100.0
    ):
        rescued = max(60, int(round(elapsed_seconds * (100.0 - progress) / progress)))

    if rescued is None or rescued <= 0:
        # Prefer unknown over a confident-looking 0m while layers remain.
        return None, total_seconds

    if elapsed_seconds is not None:
        total_seconds = max(total_seconds or 0, elapsed_seconds + rescued)
    return rescued, total_seconds


def _job_identity(print_data: dict[str, Any]) -> tuple[str | None, float | None]:
    return _job_name(print_data), _as_float(print_data.get("gcode_start_time"))


def _starting_new_active_job(
    previous: dict[str, Any],
    incoming: dict[str, Any],
) -> bool:
    """True when this MQTT update begins a new active print after a finished/idle job."""
    prev_state = map_gcode_state(previous.get("gcode_state"))
    next_token = incoming.get("gcode_state", previous.get("gcode_state"))
    next_state = map_gcode_state(next_token)
    if next_state not in _ACTIVE_PRINT_STATES:
        return False
    if prev_state not in _ACTIVE_PRINT_STATES:
        return True

    prev_name, prev_start = _job_identity(previous)
    # Prefer incoming identity fields, fall back to previous for partial updates.
    merged_name = _job_name({**previous, **incoming})
    next_start = _as_float(incoming.get("gcode_start_time"))
    if next_start is None:
        next_start = prev_start

    if prev_name and merged_name and prev_name != merged_name:
        return True
    if (
        prev_start is not None
        and next_start is not None
        and abs(prev_start - next_start) > 0.5
        and "gcode_start_time" in incoming
    ):
        return True
    return False


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
    if _starting_new_active_job(base, print_data):
        for key in _STALE_JOB_KEYS:
            merged.pop(key, None)
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
    starting_fresh_job = (
        print_state in _ACTIVE_PRINT_STATES
        and status.print_state not in _ACTIVE_PRINT_STATES
    )

    # After Complete/Idle, merged MQTT snapshots often still carry 100% / 0 remaining
    # until Bambu sends fresh fields. Do not treat that as the new job's progress.
    if starting_fresh_job:
        if progress is None:
            progress = 0.0
        elif progress >= 99.5:
            layer_current = _as_int(print_data.get("layer_num"))
            layer_total = _as_int(print_data.get("total_layer_num"))
            if (
                layer_current is not None
                and layer_total is not None
                and layer_total > 0
                and layer_current / layer_total < 0.995
            ):
                progress = max(0.0, min(100.0, (layer_current / layer_total) * 100.0))
            else:
                progress = 0.0

    # Bambu reports remaining time in minutes.
    remaining_minutes = _as_float(print_data.get("mc_remaining_time"))
    remaining_seconds: int | None = None
    if remaining_minutes is not None:
        remaining_seconds = max(0, int(round(remaining_minutes * 60)))
    if starting_fresh_job and remaining_seconds == 0 and (progress or 0) < 100:
        remaining_seconds = None

    elapsed_seconds: int | None = None
    total_seconds: int | None = None
    start = _as_float(print_data.get("gcode_start_time"))
    if starting_fresh_job and start is not None and now_ts is not None:
        # Ignore absurd leftover start times from the previous job.
        if now_ts - start > 7 * 24 * 3600 and (progress or 0) < 50:
            start = None
    if start is not None and start > 1_000_000:
        clock = time.time() if now_ts is None else now_ts
        elapsed_seconds = max(0, int(clock - start))
        if remaining_seconds is not None and remaining_seconds > 0:
            total_seconds = elapsed_seconds + remaining_seconds
        elif progress is not None and progress >= 100:
            total_seconds = elapsed_seconds
        elif remaining_seconds == 0 and progress is not None and progress < 100:
            # Bambu often reports 0 remaining before 100% — keep a sane total.
            prior = prev_job.total_seconds if not starting_fresh_job else None
            total_seconds = (
                prior
                if prior is not None and prior >= elapsed_seconds
                else elapsed_seconds
            )
        elif remaining_seconds is not None:
            total_seconds = elapsed_seconds + remaining_seconds
    elif remaining_seconds is not None and remaining_seconds > 0:
        # No usable start clock yet (common in the first moments of a job).
        if progress is None or progress <= 0:
            elapsed_seconds = 0 if elapsed_seconds is None else elapsed_seconds
            total_seconds = elapsed_seconds + remaining_seconds
        else:
            frac_left = 1.0 - (progress / 100.0)
            if remaining_seconds <= 0 and progress < 100:
                # remaining/frac would become 0 and wipe the estimate near the end.
                if starting_fresh_job:
                    elapsed_seconds = None
                    total_seconds = None
                else:
                    elapsed_seconds = prev_job.elapsed_seconds
                    total_seconds = prev_job.total_seconds
            elif frac_left > 0.001:
                total_seconds = int(round(remaining_seconds / frac_left))
                elapsed_seconds = max(0, total_seconds - remaining_seconds)
                if total_seconds <= 0:
                    elapsed_seconds = (
                        None if starting_fresh_job else prev_job.elapsed_seconds
                    )
                    total_seconds = (
                        None if starting_fresh_job else prev_job.total_seconds
                    )
            elif progress >= 100:
                if starting_fresh_job:
                    elapsed_seconds = None
                    total_seconds = remaining_seconds
                else:
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

    continuing = _continuing_active_job(
        previous_state=status.print_state,
        next_state=print_state,
        previous_name=prev_job.name,
        next_name=name,
    )
    # New print often keeps gcode_state=RUNNING; a sharply lower elapsed can mean
    # a new start — but Bambu also revises gcode_start_time mid-job. Only treat it
    # as a new job when progress also reset (or the name changed above).
    if (
        continuing
        and elapsed_seconds is not None
        and prev_job.elapsed_seconds is not None
        and elapsed_seconds + 300 < prev_job.elapsed_seconds
    ):
        prev_progress = prev_job.progress
        if (
            progress is None
            or prev_progress is None
            or progress + 15 < prev_progress
        ):
            continuing = False

    if continuing:
        progress, elapsed_seconds, total_seconds = _monotonic_job_timing(
            previous=prev_job,
            progress=progress,
            elapsed_seconds=elapsed_seconds,
            total_seconds=total_seconds,
        )

    # Prefer Bambu's remaining estimate when it is positive. Deriving remaining
    # only from total - elapsed zeroes the ETA whenever start/total estimates
    # jitter while mc_remaining_time is still healthy.
    reported_remaining = remaining_seconds
    if (
        print_state in _ACTIVE_PRINT_STATES
        and reported_remaining is not None
        and reported_remaining > 0
    ):
        remaining_seconds = reported_remaining
        if elapsed_seconds is not None:
            total_seconds = max(
                total_seconds or 0,
                elapsed_seconds + remaining_seconds,
            )
        elif total_seconds is None:
            # Start time not reported yet — treat remaining as the est. total.
            elapsed_seconds = 0
            total_seconds = remaining_seconds
    elif (
        print_state in _ACTIVE_PRINT_STATES
        and total_seconds is not None
        and elapsed_seconds is not None
    ):
        remaining_seconds = max(0, total_seconds - elapsed_seconds)

    remaining_seconds, total_seconds = _rescue_premature_zero_remaining(
        print_state=print_state,
        remaining_seconds=remaining_seconds,
        elapsed_seconds=elapsed_seconds,
        total_seconds=total_seconds,
        progress=progress,
        layer_current=layer_current,
        layer_total=layer_total,
        previous=prev_job,
    )

    progress = _reconcile_progress_with_timing(
        print_state=print_state,
        progress=progress,
        elapsed_seconds=elapsed_seconds,
        remaining_seconds=remaining_seconds,
        total_seconds=total_seconds,
        layer_current=layer_current,
        layer_total=layer_total,
    )

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
