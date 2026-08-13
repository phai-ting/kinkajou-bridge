from __future__ import annotations

from kinkajou_bridge.models import (
    ConnectionState,
    EventType,
    PrintJob,
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


def test_progress_matches_mc_percent_not_layer_ratio() -> None:
    base = PrinterStatus(printer_id="dev", printer_name="P1S", plugin_id="bambu")
    status = apply_print_snapshot(
        base,
        {
            "gcode_state": "RUNNING",
            "mc_percent": 13,
            "mc_remaining_time": 40,
            "layer_num": 42,
            "total_layer_num": 200,
        },
    )
    # Match Bambu Studio (mc_percent), not layer_num/total_layer_num (~21%).
    assert status.job.progress == 13.0


def test_early_job_remaining_fills_estimated_total() -> None:
    """At 0% Bambu often has remaining before gcode_start_time is usable."""
    status = apply_print_snapshot(
        PrinterStatus(printer_id="dev", printer_name="H2S", plugin_id="bambu"),
        {
            "gcode_state": "RUNNING",
            "mc_percent": 0,
            "mc_remaining_time": 358,
            "layer_num": 0,
            "total_layer_num": 850,
            "subtask_name": "figure.3mf",
        },
    )
    assert status.job.remaining_seconds == 358 * 60
    assert status.job.elapsed_seconds == 0
    assert status.job.total_seconds == 358 * 60


def test_stale_full_layers_do_not_force_100_percent() -> None:
    """After a finished job, layer_num==total must not pin the next print at 100%."""
    status = apply_print_snapshot(
        PrinterStatus(
            printer_id="dev",
            printer_name="P1S",
            plugin_id="bambu",
            print_state=PrintState.COMPLETE,
            job=PrintJob(progress=100.0, elapsed_seconds=10000, total_seconds=10000),
        ),
        {
            "gcode_state": "RUNNING",
            "mc_percent": 3,
            "mc_remaining_time": 90,
            "layer_num": 200,
            "total_layer_num": 200,
            "subtask_name": "next.3mf",
            "gcode_start_time": "1700000000",
        },
        now_ts=1700000120.0,
    )
    assert status.print_state == PrintState.PRINTING
    assert status.job.progress == 3.0
    assert status.job.remaining_seconds == status.job.total_seconds - status.job.elapsed_seconds
    assert status.job.progress < 50


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
    assert near_end.job.total_seconds == prior.job.total_seconds
    assert near_end.job.total_seconds != 0
    # Remaining follows total - elapsed (not Bambu's premature 0).
    assert near_end.job.remaining_seconds == (
        near_end.job.total_seconds - near_end.job.elapsed_seconds
    )
    assert near_end.job.remaining_seconds > 0


def test_remaining_not_zero_when_layers_remain() -> None:
    prior = apply_print_snapshot(
        PrinterStatus(printer_id="dev", printer_name="H2S", plugin_id="bambu"),
        {
            "gcode_state": "RUNNING",
            "mc_percent": 90,
            "mc_remaining_time": 30,
            "layer_num": 700,
            "total_layer_num": 850,
            "subtask_name": "figure.3mf",
            "gcode_start_time": "1700000000",
        },
        now_ts=1700001800.0,
    )
    assert prior.job.remaining_seconds == 1800

    # Bambu often reports 0 remaining before the last layer.
    stuck = apply_print_snapshot(
        prior,
        {
            "gcode_state": "RUNNING",
            "mc_percent": 92,
            "mc_remaining_time": 0,
            "layer_num": 720,
            "total_layer_num": 850,
            "subtask_name": "figure.3mf",
            "gcode_start_time": "1700000000",
        },
        now_ts=1700002000.0,
    )
    assert stuck.job.progress == 92
    assert stuck.job.layer_current == 720
    assert stuck.job.layer_total == 850
    assert stuck.job.remaining_seconds is not None
    assert stuck.job.remaining_seconds > 0
    # Must not jump back up above the last good ETA.
    assert stuck.job.remaining_seconds <= prior.job.remaining_seconds


def test_remaining_does_not_jump_up_when_bambu_hits_zero_with_total_slack() -> None:
    """Sticky high total + mc_remaining 0 must not revive a large ETA near the end."""
    prior = apply_print_snapshot(
        PrinterStatus(printer_id="dev", printer_name="H2S", plugin_id="bambu"),
        {
            "gcode_state": "RUNNING",
            "mc_percent": 40,
            "mc_remaining_time": 60,
            "subtask_name": "figure.3mf",
            "gcode_start_time": "1700000000",
            "layer_num": 300,
            "total_layer_num": 850,
        },
        now_ts=1700001200.0,  # elapsed 20m + remaining 60m = total 80m
    )
    assert prior.job.total_seconds == 4800

    almost_done = apply_print_snapshot(
        prior,
        {
            "gcode_state": "RUNNING",
            "mc_percent": 97,
            "mc_remaining_time": 2,
            "subtask_name": "figure.3mf",
            "gcode_start_time": "1700000000",
            "layer_num": 840,
            "total_layer_num": 850,
        },
        now_ts=1700000000.0 + 4600,  # ~76.7m elapsed; bambu says 2m left
    )
    assert almost_done.job.remaining_seconds == 120
    # Monotonic total stays high (slack vs elapsed+2m).
    assert almost_done.job.total_seconds >= almost_done.job.elapsed_seconds + 120

    zeroed = apply_print_snapshot(
        almost_done,
        {
            "gcode_state": "RUNNING",
            "mc_percent": 98,
            "mc_remaining_time": 0,
            "subtask_name": "figure.3mf",
            "gcode_start_time": "1700000000",
            "layer_num": 845,
            "total_layer_num": 850,
        },
        now_ts=1700000000.0 + 4650,
    )
    # Old bug: remaining became total-elapsed (~15m+). Must stay ≤ last good ETA.
    assert zeroed.job.remaining_seconds is not None
    assert zeroed.job.remaining_seconds <= 120
    assert zeroed.job.remaining_seconds > 0


def test_remaining_rejects_large_upward_bambu_jump_near_end() -> None:
    prior = apply_print_snapshot(
        PrinterStatus(printer_id="dev", printer_name="H2S", plugin_id="bambu"),
        {
            "gcode_state": "RUNNING",
            "mc_percent": 97,
            "mc_remaining_time": 2,
            "subtask_name": "figure.3mf",
            "gcode_start_time": "1700000000",
        },
        now_ts=1700004600.0,
    )
    assert prior.job.remaining_seconds == 120

    spiked = apply_print_snapshot(
        prior,
        {
            "gcode_state": "RUNNING",
            "mc_percent": 98,
            "mc_remaining_time": 15,
            "subtask_name": "figure.3mf",
            "gcode_start_time": "1700000000",
        },
        now_ts=1700004650.0,
    )
    assert spiked.job.remaining_seconds == 120


def test_active_print_timing_never_decreases() -> None:
    """Bambu remaining/percent can jitter; UI fields must stay monotonic mid-job."""
    first = apply_print_snapshot(
        PrinterStatus(printer_id="dev", printer_name="P1S", plugin_id="bambu"),
        {
            "gcode_state": "RUNNING",
            "mc_percent": 40,
            "mc_remaining_time": 60,
            "subtask_name": "benchy.3mf",
            "gcode_start_time": "1700000000",
        },
        now_ts=1700001200.0,  # elapsed 20m, remaining 60m → total 80m
    )
    assert first.job.progress == 40
    assert first.job.elapsed_seconds == 1200
    assert first.job.total_seconds == 1200 + 3600

    # Printer reports worse estimates / lower percent — keep prior highs.
    jitter = apply_print_snapshot(
        first,
        {
            "gcode_state": "RUNNING",
            "mc_percent": 35,
            "mc_remaining_time": 45,
            "subtask_name": "benchy.3mf",
            "gcode_start_time": "1700000000",
        },
        now_ts=1700001500.0,  # elapsed advanced to 25m
    )
    assert jitter.job.progress == 40  # not 35
    assert jitter.job.elapsed_seconds == 1500
    # Raw total would be 25m+45m=70m (< prior 80m); clamp keeps 80m.
    assert jitter.job.total_seconds == first.job.total_seconds
    # Remaining still follows Bambu's positive estimate (not total - elapsed).
    assert jitter.job.remaining_seconds == 45 * 60

    # Forward movement still allowed.
    later = apply_print_snapshot(
        jitter,
        {
            "gcode_state": "RUNNING",
            "mc_percent": 55,
            "mc_remaining_time": 50,
            "subtask_name": "benchy.3mf",
            "gcode_start_time": "1700000000",
        },
        now_ts=1700002400.0,  # elapsed 40m + remaining 50m = 90m total
    )
    assert later.job.progress == 55
    assert later.job.elapsed_seconds == 2400
    assert later.job.total_seconds == 2400 + 3000
    assert later.job.remaining_seconds == 3000


def test_prefers_positive_bambu_remaining_when_total_elapsed_would_zero() -> None:
    """Do not wipe a healthy mc_remaining_time just to keep total-elapsed in sync."""
    prior = apply_print_snapshot(
        PrinterStatus(printer_id="dev", printer_name="P1S", plugin_id="bambu"),
        {
            "gcode_state": "RUNNING",
            "mc_percent": 90,
            "mc_remaining_time": 30,
            "subtask_name": "benchy.3mf",
            "gcode_start_time": "1700000000",
        },
        now_ts=1700001800.0,  # 30m elapsed + 30m remaining
    )
    assert prior.job.remaining_seconds == 1800

    # Elapsed catches the old total while Bambu still reports ~28 minutes left.
    caught_up = prior.model_copy(
        update={
            "job": prior.job.model_copy(
                update={
                    "elapsed_seconds": prior.job.total_seconds,
                    "remaining_seconds": 0,
                }
            )
        }
    )
    fixed = apply_print_snapshot(
        caught_up,
        {
            "gcode_state": "RUNNING",
            "mc_percent": 92,
            "mc_remaining_time": 28,
            "subtask_name": "benchy.3mf",
            "gcode_start_time": "1700000000",
        },
        now_ts=1700000000.0 + (prior.job.total_seconds or 0),
    )
    assert fixed.job.remaining_seconds == 28 * 60
    assert fixed.job.elapsed_seconds is not None
    assert fixed.job.total_seconds == fixed.job.elapsed_seconds + fixed.job.remaining_seconds


def test_start_time_jitter_does_not_reset_job_when_progress_holds() -> None:
    first = apply_print_snapshot(
        PrinterStatus(printer_id="dev", printer_name="P1S", plugin_id="bambu"),
        {
            "gcode_state": "RUNNING",
            "mc_percent": 50,
            "mc_remaining_time": 40,
            "subtask_name": "benchy.3mf",
            "gcode_start_time": "1700000000",
        },
        now_ts=1700002400.0,
    )
    assert first.job.elapsed_seconds == 2400

    # Bambu moves start forward by 10 minutes; progress is still mid-job.
    jitter = apply_print_snapshot(
        first,
        {
            "gcode_state": "RUNNING",
            "mc_percent": 52,
            "mc_remaining_time": 38,
            "subtask_name": "benchy.3mf",
            "gcode_start_time": "1700000600",
        },
        now_ts=1700002400.0,
    )
    assert jitter.job.elapsed_seconds == 2400  # monotonic
    assert jitter.job.remaining_seconds == 38 * 60
    assert jitter.job.progress == 52


def test_new_print_resets_monotonic_clamp() -> None:
    done = apply_print_snapshot(
        PrinterStatus(printer_id="dev", printer_name="P1S", plugin_id="bambu"),
        {
            "gcode_state": "FINISH",
            "mc_percent": 100,
            "mc_remaining_time": 0,
            "subtask_name": "old.3mf",
        },
    )
    assert done.job.progress == 100

    nxt = apply_print_snapshot(
        done,
        {
            "gcode_state": "RUNNING",
            "mc_percent": 5,
            "mc_remaining_time": 100,
            "subtask_name": "new.3mf",
        },
    )
    assert nxt.job.progress == 5
    assert nxt.job.name == "new.3mf"


def test_new_print_clears_stale_completion_from_merge() -> None:
    """Partial RUNNING update must not keep the finished job's 100% forever."""
    finished = merge_print_payload(
        None,
        {
            "print": {
                "gcode_state": "FINISH",
                "mc_percent": 100,
                "mc_remaining_time": 0,
                "layer_num": 200,
                "total_layer_num": 200,
                "subtask_name": "benchy.3mf",
                "gcode_start_time": "1700000000",
            }
        },
    )
    done_status = apply_print_snapshot(
        PrinterStatus(printer_id="dev", printer_name="P1S", plugin_id="bambu"),
        finished,
    )
    assert done_status.print_state == PrintState.COMPLETE
    assert done_status.job.progress == 100

    started = merge_print_payload(finished, {"print": {"gcode_state": "RUNNING"}})
    assert "mc_percent" not in started
    assert "gcode_start_time" not in started
    assert "layer_num" not in started

    live = apply_print_snapshot(done_status, started, now_ts=1700005000.0)
    assert live.print_state == PrintState.PRINTING
    assert live.job.progress == 0.0
    assert live.job.elapsed_seconds is None or live.job.elapsed_seconds == 0

    with_fresh = merge_print_payload(
        started,
        {
            "print": {
                "mc_percent": 8,
                "mc_remaining_time": 90,
                "layer_num": 10,
                "total_layer_num": 200,
                "gcode_start_time": "1700004900",
            }
        },
    )
    progressing = apply_print_snapshot(live, with_fresh, now_ts=1700005000.0)
    assert progressing.job.progress == 8
    assert progressing.job.remaining_seconds == 5400
    assert progressing.job.elapsed_seconds == 100
    assert progressing.job.total_seconds == 100 + 5400


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
