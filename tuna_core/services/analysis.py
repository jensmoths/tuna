from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from tuna_blackbox import analyze_csv_log, decode_blackbox_log
from tuna_blackbox.analysis_views import recording_summary

ANALYSIS_FIXTURE_SCENARIOS = ("clean", "propwash", "noisy", "unusable")


def _log_row(conn: sqlite3.Connection, log_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM blackbox_logs WHERE id = ?", (log_id,)).fetchone()
    if row is None:
        raise ValueError(f"Blackbox Log {log_id} does not exist")
    return row


def _recording_index(path: str | Path) -> int | None:
    match = re.search(r"\.(\d+)\.csv$", Path(path).name)
    return int(match.group(1)) if match else None


def _decoded_recording_paths(source_path: str | Path, selected_csv: str | Path) -> list[Path]:
    source = Path(source_path)
    selected = Path(selected_csv)
    paths = sorted(selected.parent.glob(f"{source.stem}*.csv"))
    if selected not in paths and selected.exists():
        paths.append(selected)
    siblings = [path for path in paths if path != selected]
    return siblings + [selected]


def decode_imported_log(conn: sqlite3.Connection, log_id: int, *, output_dir: str | Path, decoder_command: str = "blackbox_decode") -> dict[str, object]:
    row = _log_row(conn, log_id)
    output = Path(output_dir) / f"log-{log_id}.csv"
    csv_path = decode_blackbox_log(row["managed_path"], output, decoder_command=decoder_command)
    recording_paths = _decoded_recording_paths(row["managed_path"], csv_path)
    recordings = []
    for path in recording_paths:
        conn.execute(
            "INSERT INTO decoded_logs (log_id, csv_path, decoder_command) VALUES (?, ?, ?)",
            (log_id, str(path), decoder_command),
        )
        recordings.append({"csv_path": str(path), "recording_index": _recording_index(path)})
    conn.commit()
    return {"log_id": log_id, "csv_path": str(csv_path), "recordings": recordings}


def analyze_imported_log(conn: sqlite3.Connection, log_id: int, *, csv_path: str | Path | None = None) -> dict[str, object]:
    if csv_path is None:
        decoded = conn.execute(
            "SELECT csv_path FROM decoded_logs WHERE log_id = ? ORDER BY decoded_at DESC, id DESC LIMIT 1",
            (log_id,),
        ).fetchone()
        if decoded is None:
            raise ValueError(f"Blackbox Log {log_id} has no decoded CSV; run decode first or pass csv_path")
        csv_path = decoded["csv_path"]

    summary = analyze_csv_log(csv_path)
    conn.execute(
        "INSERT INTO log_analyses (log_id, analysis_json) VALUES (?, ?)",
        (log_id, json.dumps(summary, sort_keys=True)),
    )
    conn.commit()
    return summary


def record_analysis_fixture(conn: sqlite3.Connection, log_id: int, analysis: dict[str, Any]) -> dict[str, object]:
    _log_row(conn, log_id)
    conn.execute(
        "INSERT INTO log_analyses (log_id, analysis_json) VALUES (?, ?)",
        (log_id, json.dumps(analysis, sort_keys=True)),
    )
    conn.commit()
    return analysis


def analysis_fixture_scenario(name: str) -> dict[str, Any]:
    if name not in ANALYSIS_FIXTURE_SCENARIOS:
        raise ValueError(f"Unknown analysis fixture scenario: {name}")
    payload = _base_fixture(name)
    if name == "clean":
        payload["tracking"]["roll"]["mean_abs_error"] = 2.8
        payload["tracking"]["pitch"]["mean_abs_error"] = 3.1
        payload["tuning_evidence"]["pid_response"]["axes"]["roll"]["classifications"] = ["well_controlled"]
        payload["tuning_evidence"]["capture_plan"]["need_more_data"] = False
    elif name == "propwash":
        payload["warnings"].append("Fixture propwash oscillation detected after throttle chop")
        payload["tracking"]["roll"]["mean_abs_error"] = 9.5
        payload["propwash_analysis"] = {
            "available": True,
            "summary": {"segment_count": 2, "max_gyro_mean_abs_delta": 185.0, "max_tracking_error": 24.0},
            "segments": [
                {"axis": "roll", "start_time_seconds": 18.2, "end_time_seconds": 19.1, "tracking_error": 24.0},
                {"axis": "pitch", "start_time_seconds": 31.4, "end_time_seconds": 32.0, "tracking_error": 18.5},
            ],
        }
        payload["tuning_evidence"]["pid_response"]["axes"]["roll"]["classifications"] = ["propwash_oscillation", "underdamped"]
        payload["tuning_evidence"]["pid_response"]["summary"] = "Fixture shows propwash oscillation with moderate noise margin."
    elif name == "noisy":
        payload["warnings"].append("Fixture D-term noise is high above 250 Hz")
        payload["quality"]["reason"] = "usable with noise caution"
        payload["filter_analysis"]["axes"]["roll"]["bands"]["250-500Hz"]["attenuation_ratio"] = 0.82
        payload["pid_term_analysis"]["axes"]["roll"]["dterm_noise"]["spike_count"] = 36
        payload["pid_term_analysis"]["axes"]["roll"]["flags"] = ["dterm_noise"]
        payload["noise_peaks"] = {
            "available": True,
            "peaks": [{"signal": "axisD[0]", "frequency_hz": 310.0, "magnitude": 0.86}],
            "warnings": ["D-term high-frequency peak near 310 Hz"],
        }
        payload["tuning_evidence"]["filter_diagnosis"]["axes"]["roll"]["classification"] = "too_light"
        payload["tuning_evidence"]["capture_plan"]["need_more_data"] = True
    elif name == "unusable":
        payload["row_count"] = 120
        payload["duration_seconds"] = 0.85
        payload["quality"] = {"usable": False, "reason": "fixture capture too short"}
        payload["warnings"] = ["Fixture Blackbox Log is too short for tuning analysis"]
        payload["activity"]["detected_active_rows"] = 20
        payload["flight"]["detected_active_rows"] = 20
        payload["analysis_capabilities"]["limitations"].append({"feature": "tuning_evidence", "reason": "capture too short"})
        payload["tuning_evidence"]["capture_plan"]["need_more_data"] = True
        payload["tuning_evidence"]["capture_plan"]["reason"] = "Need a longer Blackbox Log with relevant maneuvers."
    return payload


def _base_fixture(name: str) -> dict[str, Any]:
    axes = {
        axis: {
            "mean_abs_error": 4.0,
            "max_abs_error": 15.0,
        }
        for axis in ("roll", "pitch", "yaw")
    }
    return {
        "csv_path": f"fixture://analysis/{name}",
        "row_count": 4200,
        "duration_seconds": 42.0,
        "quality": {"usable": True, "reason": "fixture evidence"},
        "warnings": [],
        "analysis_capabilities": {"warnings": [], "limitations": []},
        "activity": {"detected_active_rows": 3900, "motor_saturation_samples": 0},
        "flight": {"detected_active_rows": 3900, "active_window": {"start_time_seconds": 3.0, "end_time_seconds": 40.0}},
        "blackbox_settings": {
            "debug_mode": "GYRO_SCALED",
            "rollPID": [45, 80, 40],
            "pitchPID": [47, 82, 42],
            "yawPID": [45, 80, 0],
            "dterm_lowpass_hz": 100,
            "gyro_lowpass_hz": 150,
        },
        "tracking": axes,
        "segments": {"propwash": []},
        "propwash_analysis": {"available": True, "summary": {"segment_count": 0, "max_gyro_mean_abs_delta": 0.0, "max_tracking_error": 0.0}, "segments": []},
        "filter_analysis": {
            "axes": {
                axis: {"available": True, "bands": {"250-500Hz": {"attenuation_ratio": 0.28, "attenuation_db": -11.0}}}
                for axis in ("roll", "pitch", "yaw")
            },
            "warnings": [],
        },
        "noise_peaks": {"available": True, "peaks": [], "warnings": []},
        "rpm_analysis": {"available": True, "possible_harmonic_matches": [], "warnings": []},
        "motor_analysis": {"summary": {"motor_count": 4, "total_near_max_samples": 0, "imbalance_score": 12.0}, "warnings": []},
        "pid_term_analysis": {
            "axes": {
                axis: {
                    "samples": 4200,
                    "flags": [],
                    "terms": {
                        "P": {"mean_abs": 8.0, "max_abs": 42.0},
                        "I": {"mean_abs": 12.0, "max_abs": 58.0},
                        "D": {"mean_abs": 5.0, "max_abs": 24.0},
                    },
                    "dterm_noise": {"spike_count": 2},
                    "throttle_coupling": {"dterm_spikes_near_throttle_changes": 0},
                }
                for axis in ("roll", "pitch", "yaw")
            }
        },
        "step_response": {
            "axes": {
                axis: {"summary": {"mean_latency_seconds": 0.035, "mean_rise_time_seconds": 0.12, "mean_overshoot_fraction": 0.08, "mean_settling_error_fraction": 0.05, "bounce_back_events": 0}}
                for axis in ("roll", "pitch", "yaw")
            }
        },
        "tuning_evidence": {
            "filter_diagnosis": {
                "available": True,
                "summary": "Fixture filters look acceptable.",
                "axes": {axis: {"classification": "acceptable"} for axis in ("roll", "pitch", "yaw")},
            },
            "pid_response": {
                "available": True,
                "summary": "Fixture response is usable for Loop decisions.",
                "axes": {axis: {"classifications": []} for axis in ("roll", "pitch", "yaw")},
            },
            "capture_plan": {"need_more_data": False, "reason": "Fixture evidence is sufficient for exploratory workflow testing."},
        },
    }


def latest_analysis(conn: sqlite3.Connection, log_id: int) -> tuple[int, str, dict[str, Any]]:
    row = conn.execute(
        "SELECT id, analyzed_at, analysis_json FROM log_analyses WHERE log_id = ? ORDER BY analyzed_at DESC, id DESC LIMIT 1",
        (log_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Blackbox Log {log_id} has no analysis")
    return int(row["id"]), str(row["analyzed_at"]), json.loads(row["analysis_json"])


def list_recordings(conn: sqlite3.Connection, log_id: int, *, sort: str = "decoded", limit: int | None = None) -> dict[str, Any]:
    _log_row(conn, log_id)
    decoded_rows = conn.execute(
        "SELECT id, csv_path, decoder_command, decoded_at FROM decoded_logs WHERE log_id = ? ORDER BY id",
        (log_id,),
    ).fetchall()
    analyses = conn.execute(
        "SELECT id, analyzed_at, analysis_json FROM log_analyses WHERE log_id = ? ORDER BY analyzed_at DESC, id DESC",
        (log_id,),
    ).fetchall()
    analyses_by_csv: dict[str, tuple[Any, dict[str, Any]]] = {}
    for row in analyses:
        analysis = json.loads(row["analysis_json"])
        csv_path = analysis.get("csv_path")
        if isinstance(csv_path, str) and csv_path not in analyses_by_csv:
            analyses_by_csv[csv_path] = (row, analysis)

    recordings = []
    for row in decoded_rows:
        csv_path = row["csv_path"]
        analysis_row, analysis = analyses_by_csv.get(csv_path, (None, None))
        item = {
            "decoded_log_id": row["id"],
            "csv_path": csv_path,
            "recording_index": _recording_index(csv_path),
            "decoded_at": row["decoded_at"],
            "decoder_command": row["decoder_command"],
            "analysis_id": analysis_row["id"] if analysis_row else None,
            "analyzed_at": analysis_row["analyzed_at"] if analysis_row else None,
            "analysis": recording_summary(analysis) if analysis else None,
        }
        recordings.append(item)

    if sort in {"start-time", "start_time"}:
        recordings.sort(key=lambda item: ((item.get("analysis") or {}).get("start_time_seconds") is None, (item.get("analysis") or {}).get("start_time_seconds") or 0.0, item["decoded_log_id"]))
    elif sort == "activity":
        recordings.sort(key=lambda item: ((item.get("analysis") or {}).get("detected_active_rows") or 0), reverse=True)
    total_recording_count = len(recordings)
    if limit is not None:
        recordings = recordings[:limit]
    return {"log_id": log_id, "recordings": recordings, "recording_count": len(recordings), "total_recording_count": total_recording_count}
