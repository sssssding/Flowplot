"""Synthetic comparisons and failure injection; not actual second-machine evidence."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
import test_ai_review_safety as reports
from test_recommend import synthetic_dataset
from flowpilot import validate_recommendation as local
from flowpilot.check_model import CheckError


class LocalComparisonTest(unittest.TestCase):
    def setUp(self):
        self.fixture = reports.SnapshotSafetyTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.directory = self.fixture.directory
        self.data = synthetic_dataset()
        for row in self.data["observations"]:
            row["evidence"]["comsol_version"] = "COMSOL Multiphysics 6.3"
        self.path = self.directory / "synthetic-calibration.json"
        self.save()
        self.choice = {"status": "recommended", "selected": {"id": "balanced-2", "stol": 1e-5, "threads": 2}}

    def save(self):
        self.path.write_text(json.dumps(self.data), encoding="utf-8")

    def evaluate(self, choice=None):
        with patch.object(local, "recommend_report", return_value=choice or self.choice):
            return local.evaluate(self.directory, self.path)

    def test_actual_summary_recomputes_medians_and_does_not_claim_independent_acceptance(self):
        result = self.evaluate()
        self.assertEqual(result["status"], "measured")
        comparison = result["comparison"]
        self.assertEqual(comparison["default"]["samples"], 3)
        self.assertEqual(comparison["selected_over_default"], .5)
        self.assertTrue(comparison["observed_gain_above_noise"])
        self.assertFalse(result["independent_validation"])
        self.assertFalse(result["software_goal_complete"])
        self.assertFalse(result["solver_run_in_evaluation"])

    def test_original_configuration_is_not_counted_as_a_speedup(self):
        choice = copy.deepcopy(self.choice)
        choice["selected"] = {"id": "strict-2", "stol": 1e-6, "threads": 2}
        result = self.evaluate(choice)
        self.assertFalse(result["comparison"]["observed_gain_above_noise"])
        self.assertEqual(result["comparison"]["selected_over_default"], 1)

    def test_overlap_does_not_become_a_guaranteed_gain(self):
        row = next(r for r in self.data["observations"] if r["candidate"]["id"] == "balanced-2")
        row["evidence"]["solve_seconds"] = 5.
        self.save()
        self.assertFalse(self.evaluate()["comparison"]["observed_gain_above_noise"])

    def test_warning_in_selected_or_reference_blocks_speed_conclusion(self):
        for identity in ("balanced-2", "strict-2"):
            with self.subTest(identity=identity):
                original = copy.deepcopy(self.data)
                row = next(r for r in self.data["observations"] if r["candidate"]["id"] == identity)
                row["evidence"]["solver_warning"] = "synthetic warning"
                self.save()
                self.assertEqual(self.evaluate()["status"], "quality_failed")
                self.data = original

    def test_other_machine_data_cannot_be_declared_local_measurement(self):
        self.data["environment_id"] = "0"*64
        self.save()
        with self.assertRaisesRegex(CheckError, "同一电脑"):
            self.evaluate()

    def test_other_model_source_is_rejected(self):
        metadata = json.loads((self.directory / "run.json").read_text(encoding="utf-8"))
        metadata["source"]["sha256"] = "a"*64
        (self.directory / "run.json").write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaisesRegex(CheckError, "同一模型"):
            self.evaluate()

    def test_unavailable_recommendation_remains_unavailable(self):
        result = self.evaluate({"status": "unavailable", "reason": "synthetic unsupported", "selected": None})
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["comparison"])

    def test_report_change_during_evaluation_is_rejected(self):
        def change(*args, **kwargs):
            self.fixture.publish(filename="changed.mph")
            return self.choice
        with patch.object(local, "recommend_report", side_effect=change):
            with self.assertRaises(CheckError):
                local.evaluate(self.directory, self.path)

    def test_calibration_change_during_evaluation_is_rejected(self):
        def change(*args, **kwargs):
            self.path.write_bytes(b"changed")
            return self.choice
        with patch.object(local, "recommend_report", side_effect=change):
            with self.assertRaises(CheckError):
                local.evaluate(self.directory, self.path)

    def test_output_inside_input_report_is_rejected_without_writing(self):
        output = self.directory / "new-result.json"
        with patch.object(sys, "argv", ["local", "--report", str(self.directory), "--calibration", str(self.path),
                                      "--output", str(output)]):
            with self.assertRaises(SystemExit) as result:
                local.main()
        self.assertEqual(result.exception.code, 1)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
