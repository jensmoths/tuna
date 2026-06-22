from __future__ import annotations

import csv
import math
import unittest

from tests.analysis_helpers import AnalysisTestCase
from tuna_blackbox.csv_summary import analyze_csv_log
from tuna_blackbox.evidence import build_tuning_evidence


class AnalysisEvidenceTests(AnalysisTestCase):
    def test_analyze_csv_log_builds_filter_evidence(self):
        path = self.root / "filter-evidence.csv"
        fieldnames = [
            "time",
            "gyroADC[0]",
            "gyroADC[1]",
            "gyroADC[2]",
            "gyroUnfilt[0]",
            "gyroUnfilt[1]",
            "gyroUnfilt[2]",
            "setpoint[0]",
            "setpoint[1]",
            "setpoint[2]",
            "motor[0]",
            "axisP[0]",
            "axisI[0]",
            "axisD[0]",
            "rcCommand[3]",
        ]
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for index in range(1000):
                noise = math.sin(2 * math.pi * 300 * index / 1000)
                writer.writerow(
                    {name: 0 for name in fieldnames}
                    | {
                        "time": index * 1000,
                        "gyroADC[0]": noise,
                        "gyroUnfilt[0]": noise,
                        "axisD[0]": noise,
                        "motor[0]": 1200,
                        "rcCommand[3]": 1200,
                    }
                )

        summary = analyze_csv_log(path)

        roll = summary["tuning_evidence"]["filter_diagnosis"]["axes"]["roll"]
        self.assertEqual(roll["classification"], "possibly_too_light")
        self.assertIn("low_high_frequency_attenuation", roll["flags"])
        self.assertIn("capture_plan", summary["tuning_evidence"])

    def test_analyze_csv_log_detects_propwash_recovery_segments(self):
        path = self.root / "propwash.csv"
        fieldnames = ["time", "gyroADC[0]", "gyroADC[1]", "gyroADC[2]", "setpoint[0]", "setpoint[1]", "setpoint[2]", "motor[0]", "axisP[0]", "axisI[0]", "axisD[0]", "rcCommand[3]"]
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for index in range(20):
                throttle = 1200 if index < 5 else 1600
                gyro = 0 if index < 5 else (index - 5) * 80
                writer.writerow({name: 0 for name in fieldnames} | {"time": index * 10_000, "gyroADC[0]": gyro, "motor[0]": throttle, "rcCommand[3]": throttle})

        summary = analyze_csv_log(path)

        propwash = summary["propwash_analysis"]
        self.assertEqual(propwash["summary"]["segment_count"], 1)
        self.assertIn("high_gyro_activity_after_throttle_recovery", propwash["segments"][0]["flags"])
        self.assertEqual(summary["segments"]["propwash"][0]["start_row"], 6)

    def test_sparse_dterm_spikes_do_not_drive_evidence_classification(self):
        evidence = build_tuning_evidence({
            "quality": {"usable": True},
            "analysis_capabilities": {"limitations": []},
            "segments": {"high_rate": [{}]},
            "filter_analysis": {"axes": {"roll": {"available": True, "bands": {"250-500Hz": {"attenuation_ratio": 0.25}}}}},
            "spectrum": {"signals": {"axisD[0]": {"bands": {"250-500Hz": {"fraction": 0.01}}}}},
            "step_response": {"axes": {"roll": {"flags": [], "summary": {"event_count": 0}}}},
            "pid_term_analysis": {"axes": {"roll": {"samples": 300_000, "dterm_noise": {"spike_count": 10}, "throttle_coupling": {"dterm_spikes_near_throttle_changes": 0}, "flags": ["dterm_spikes"]}}},
        })

        self.assertEqual(evidence["filter_diagnosis"]["axes"]["roll"]["classification"], "no_strong_filter_evidence")
        self.assertEqual(evidence["pid_response"]["axes"]["roll"]["classifications"], ["no_strong_pid_response_evidence"])

    def test_capture_plan_explains_missing_propwash_and_unknown_debug_mode(self):
        evidence = build_tuning_evidence({
            "quality": {"usable": True},
            "analysis_capabilities": {"limitations": []},
            "segments": {"high_rate": [{"axis": "roll"}]},
            "propwash_analysis": {"available": True, "segments": []},
            "rpm_analysis": {"available": True, "debug_mode_family": "unknown"},
        })

        plan = evidence["capture_plan"]
        self.assertIn("No propwash recovery segments were detected", plan["reasons"])
        self.assertIn("Debug fields are present but debug_mode is unknown", "\n".join(plan["reasons"]))
        self.assertIn("record debug_mode", "\n".join(plan["recommended_blackbox_settings"]))

    def test_conflicting_filter_evidence_is_mixed(self):
        evidence = build_tuning_evidence({
            "quality": {"usable": True},
            "analysis_capabilities": {"limitations": []},
            "segments": {"high_rate": [{"axis": "roll"}]},
            "filter_analysis": {"axes": {"roll": {"available": True, "bands": {"250-500Hz": {"attenuation_ratio": 0.01}}}}},
            "spectrum": {"signals": {"axisD[0]": {"bands": {"250-500Hz": {"fraction": 0.01}}}}},
            "step_response": {"axes": {"roll": {"flags": [], "summary": {"event_count": 0}}}},
            "pid_term_analysis": {"axes": {"roll": {"samples": 10_000, "dterm_noise": {"spike_count": 100}, "throttle_coupling": {"dterm_spikes_near_throttle_changes": 0}, "flags": ["dterm_spikes"]}}},
        })

        self.assertEqual(evidence["filter_diagnosis"]["axes"]["roll"]["classification"], "mixed_filter_evidence")


if __name__ == "__main__":
    unittest.main()
