from __future__ import annotations

from kinkajou_bridge.models import (
    ConnectionState,
    EventType,
    PrinterStatus,
    PrintState,
)
from kinkajou_bridge.plugins.bambu.report import (
    ReportTracker,
    apply_print_snapshot,
    map_gcode_state,
    merge_print_payload,
)


def test_map_gcode_state() -> None:
    assert map_gcode_state("RUNNING") == PrintState.PRINTING
    assert map_gcode_state("PAUSE") == PrintState.PAUSED
    assert map_gcode_state("FINISH") == PrintState.COMPLETE
    assert map_gcode_state("PREPARE") == PrintState.PREPARING
    assert map_gcode_state("nope") == PrintState.UNKNOWN


def test_merge_partial_print_payload() -> None:
    full = merge_print_payload(
        None,
        {
            "print": {
                "gcode_state": "RUNNING",
                "mc_percent": 10,
                "nozzle_temper": 220,
                "subtask_name": "benchy.3mf",
            }
        },
    )
    merged = merge_print_payload(full, {"print": {"mc_percent": 25}})
    assert merged["gcode_state"] == "RUNNING"
    assert merged["mc_percent"] == 25
    assert merged["nozzle_temper"] == 220
    assert merged["subtask_name"] == "benchy.3mf"


def test_apply_print_snapshot_running_minutes_to_seconds() -> None:
    base = PrinterStatus(
        printer_id="dev",
        printer_name="P1S",
        plugin_id="bambu",
        connection=ConnectionState.CONNECTED,
    )
    status = apply_print_snapshot(
        base,
        {
            "gcode_state": "RUNNING",
            "mc_percent": 50,
            "mc_remaining_time": 30,  # minutes
            "subtask_name": "box.3mf",
            "layer_num": 40,
            "total_layer_num": 80,
            "nozzle_temper": 220.5,
            "nozzle_target_temper": 220,
            "bed_temper": 60,
            "bed_target_temper": 65,
            "chamber_temper": 35,
            "gcode_file": "cache/box.gcode",
        },
    )
    assert status.print_state == PrintState.PRINTING
    assert status.job.progress == 50
    assert status.job.remaining_seconds == 1800
    assert status.job.total_seconds == 3600
    assert status.job.elapsed_seconds == 1800
    assert status.job.name == "box.3mf"
    assert status.job.file_name == "box.gcode"
    assert status.job.layer_current == 40
    assert status.job.layer_total == 80
    assert status.temperatures.nozzle_c == 220.5
    assert status.temperatures.bed_target_c == 65


def test_progress_uses_layer_ratio_when_mc_percent_stalls() -> None:
    base = PrinterStatus(printer_id="dev", printer_name="P1S", plugin_id="bambu")
    status = apply_print_snapshot(
        base,
        {
            "gcode_state": "RUNNING",
            "mc_percent": 33,
            "mc_remaining_time": 40,
            "layer_num": 120,
            "total_layer_num": 200,
        },
    )
    # Layer ratio is 60%; take max so a stuck mc_percent does not freeze the UI.
    assert status.job.progress == 60.0


def test_elapsed_from_gcode_start_time() -> None:
    base = PrinterStatus(printer_id="dev", printer_name="P1S", plugin_id="bambu")
    status = apply_print_snapshot(
        base,
        {
            "gcode_state": "RUNNING",
            "mc_percent": 25,
            "mc_remaining_time": 30,
            "gcode_start_time": "1700000000",
        },
        now_ts=1700000900.0,
    )
    assert status.job.elapsed_seconds == 900
    assert status.job.total_seconds == 900 + 1800


def test_total_not_zeroed_when_remaining_hits_zero_before_100() -> None:
    prior = apply_print_snapshot(
        PrinterStatus(printer_id="dev", printer_name="P1S", plugin_id="bambu"),
        {
            "gcode_state": "RUNNING",
            "mc_percent": 90,
            "mc_remaining_time": 10,
        },
    )
    assert prior.job.total_seconds and prior.job.total_seconds > 0

    near_end = apply_print_snapshot(
        prior,
        {
            "gcode_state": "RUNNING",
            "mc_percent": 97,
            "mc_remaining_time": 0,
        },
    )
    assert near_end.job.remaining_seconds == 0
    assert near_end.job.total_seconds == prior.job.total_seconds
    assert near_end.job.total_seconds != 0


def test_apply_print_snapshot_idle() -> None:
    base = PrinterStatus(printer_id="dev", printer_name="P1S", plugin_id="bambu")
    status = apply_print_snapshot(
        base,
        {"gcode_state": "IDLE", "mc_percent": 0, "mc_remaining_time": 0},
    )
    assert status.print_state == PrintState.IDLE
    assert status.job.remaining_seconds == 0


def test_report_tracker_emits_transitions_and_throttles_progress() -> None:
    tracker = ReportTracker(progress_interval_s=5.0)
    previous = PrinterStatus(
        printer_id="dev",
        printer_name="P1S",
        plugin_id="bambu",
        print_state=PrintState.IDLE,
    )
    printing = apply_print_snapshot(
        previous,
        {
            "gcode_state": "RUNNING",
            "mc_percent": 10,
            "mc_remaining_time": 40,
            "layer_num": 1,
            "total_layer_num": 100,
        },
    )
    events = tracker.events_for_update(
        printer_id="dev",
        printer_name="P1S",
        plugin_id="bambu",
        previous_status=previous,
        next_status=printing,
        now=100.0,
    )
    types = [e.type for e in events]
    assert EventType.PRINT_STARTED in types
    assert EventType.PROGRESS in types

    # Same percent soon after — no progress event
    same = apply_print_snapshot(
        printing,
        {
            "gcode_state": "RUNNING",
            "mc_percent": 10,
            "mc_remaining_time": 39,
            "layer_num": 1,
            "total_layer_num": 100,
        },
    )
    events2 = tracker.events_for_update(
        printer_id="dev",
        printer_name="P1S",
        plugin_id="bambu",
        previous_status=printing,
        next_status=same,
        now=101.0,
    )
    assert events2 == []

    # +1% triggers progress
    bumped = apply_print_snapshot(
        same,
        {
            "gcode_state": "RUNNING",
            "mc_percent": 11,
            "mc_remaining_time": 38,
            "layer_num": 2,
            "total_layer_num": 100,
        },
    )
    events3 = tracker.events_for_update(
        printer_id="dev",
        printer_name="P1S",
        plugin_id="bambu",
        previous_status=same,
        next_status=bumped,
        now=102.0,
    )
    types3 = [e.type for e in events3]
    assert EventType.PROGRESS in types3
    assert EventType.LAYER_CHANGED in types3

    paused = apply_print_snapshot(
        bumped,
        {"gcode_state": "PAUSE", "mc_percent": 11, "mc_remaining_time": 38},
    )
    events4 = tracker.events_for_update(
        printer_id="dev",
        printer_name="P1S",
        plugin_id="bambu",
        previous_status=bumped,
        next_status=paused,
        now=103.0,
    )
    assert any(e.type == EventType.PRINT_PAUSED for e in events4)
