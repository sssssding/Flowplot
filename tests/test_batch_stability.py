"""Synthetic concurrent-change/fault tests; not COMSOL or independent acceptance."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_check_suite as fixtures
from flowpilot import acceptance_dataset as dataset, check_suite as suite


class BatchStabilityTest(unittest.TestCase):
    write_report = fixtures.CheckSuiteTest.write_report
    mock_manifest = fixtures.CheckSuiteTest.mock_manifest

    def setUp(self):
        fixtures.CheckSuiteTest.setUp(self)
        quiet = patch("builtins.print")
        quiet.start()
        self.addCleanup(quiet.stop)
        self.manifest_path = self.directory / "local-manifest.json"
        suite._write_json(self.manifest_path, self.manifest)

    def offline(self):
        return suite.run_suite(self.manifest_path, output_dir=self.output, reports_root=self.reports)

    def assert_failed(self, summary_exists=False):
        run = json.loads((self.output / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(run["status"], "failed")
        self.assertFalse(run["input_stability_verified"])
        self.assertEqual((self.output / "summary.json").exists(), summary_exists)
        return run

    def after_evaluation(self, action):
        original = suite.evaluate_dataset
        def evaluate(*args, **kwargs):
            result = original(*args, **kwargs)
            action()
            return result
        return patch.object(suite, "evaluate_dataset", side_effect=evaluate)

    def test_completed_run_binds_actual_parsed_manifest_and_summary_bytes(self):
        before = self.manifest_path.read_bytes()
        self.offline()
        run = json.loads((self.output / "run.json").read_text(encoding="utf-8"))
        self.assertTrue(run["input_stability_verified"])
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["manifest_sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(run["summary_sha256"], suite.sha256(self.output / "summary.json"))
        self.assertEqual(run["source_fingerprints"], dataset.fingerprints()[0])
        self.assertNotIn(b"\r", (self.output / "report.md").read_bytes())

    def test_manifest_hash_is_not_reopened_separately_from_parsing(self):
        original = suite.sha256
        def digest(path):
            if Path(path) == self.manifest_path:
                raise AssertionError("manifest must be hashed from its parsed bytes")
            return original(path)
        with patch.object(suite, "sha256", side_effect=digest):
            self.assertEqual(self.offline()["checked_cases"], 6)

    def test_duplicate_nonfinite_deep_or_oversized_manifest_rejected_before_output(self):
        for payload in (b'{"cases":[],"cases":[]}', b'{"bad":NaN}', b" " * 65537,
                        b"[" * 70 + b"0" + b"]" * 70):
            self.manifest_path.write_bytes(payload)
            with self.assertRaises(ValueError):
                self.offline()
            self.assertFalse(self.output.exists())

    def test_manifest_link_or_junction_is_not_resolved_away_before_validation(self):
        for predicate in ("is_symlink", "is_junction"):
            with patch.object(Path, predicate, autospec=True, side_effect=lambda path: path == self.manifest_path), \
                    self.assertRaises(ValueError):
                self.offline()
            self.assertFalse(self.output.exists())

    def test_manifest_changes_immediately_after_parse_use_old_digest_but_fail_run(self):
        raw = self.manifest_path.read_bytes()
        original = suite.validate_manifest
        changed = False
        def validate(value):
            nonlocal changed
            result = original(value)
            if not changed:
                self.manifest_path.write_bytes(raw + b"\n")
                changed = True
            return result
        with patch.object(suite, "validate_manifest", side_effect=validate), self.assertRaises(suite.CheckError):
            self.offline()
        run = self.assert_failed()
        self.assertEqual(run["manifest_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(run["attempted_cases"], 6)

    def test_manifest_changes_after_scoring_are_rejected_before_summary(self):
        with self.after_evaluation(lambda: self.manifest_path.write_bytes(b"changed synthetic manifest")), \
                self.assertRaises(suite.CheckError):
            self.offline()
        self.assert_failed()

    def test_program_or_registry_change_before_publish_fails_closed(self):
        first, known = dataset.fingerprints()
        changed = dict(first, **{"synthetic-change": "0" * 64})
        with patch.object(dataset, "fingerprints", side_effect=[(first, known), (changed, known)]), \
                self.assertRaises(suite.CheckError):
            self.offline()
        self.assert_failed()

    def test_registry_failure_before_output_does_not_create_success_record(self):
        with patch.object(dataset, "fingerprints", side_effect=OSError("synthetic missing registry")), \
                self.assertRaises(OSError):
            self.offline()
        self.assertFalse(self.output.exists())

    def test_scored_report_change_or_deletion_before_publish_rejected(self):
        report = self.reports / "baseline/diagnosis.json"
        raw = report.read_bytes()
        for index, action in enumerate((lambda: report.write_bytes(b"{}"), report.unlink)):
            self.output = self.directory / f"changed-report-{index}"
            with self.after_evaluation(action), self.assertRaises(suite.CheckError):
                self.offline()
            self.assert_failed()
            report.write_bytes(raw)

    def test_changed_run_metadata_is_detected_even_when_diagnosis_is_unchanged(self):
        run_path = self.reports / "baseline/run.json"
        with self.after_evaluation(lambda: run_path.write_bytes(run_path.read_bytes() + b"\n")), \
                self.assertRaises(suite.CheckError):
            self.offline()
        self.assert_failed()

    def test_partial_report_change_does_not_silently_keep_incomplete_summary(self):
        child = self.reports / "baseline"
        report = json.loads((child / "diagnosis.json").read_text(encoding="utf-8"))
        report["status"] = "partial"
        (child / "diagnosis.json").write_text(json.dumps(report), encoding="utf-8")
        run = json.loads((child / "run.json").read_text(encoding="utf-8"))
        run.update(diagnosis_status="partial", diagnosis_sha256=suite.sha256(child / "diagnosis.json"))
        (child / "run.json").write_text(json.dumps(run), encoding="utf-8")
        with self.after_evaluation(lambda: (child / "run.json").write_bytes(b"{}")), self.assertRaises(suite.CheckError):
            self.offline()
        self.assert_failed()

    def test_missing_report_becoming_complete_requires_new_evaluation(self):
        path = self.reports / "baseline/run.json"
        raw = path.read_bytes()
        path.unlink()
        with self.after_evaluation(lambda: path.write_bytes(raw)), self.assertRaises(suite.CheckError):
            self.offline()
        self.assert_failed()

    def simulate_model(self, model, *, output_dir, **kwargs):
        case = next(case for case in self.active_manifest["cases"] if case["case_id"] == output_dir.name)
        self.write_report(output_dir, case)

    def test_model_source_changes_after_own_check_still_fail_whole_batch(self):
        self.active_manifest, path = self.mock_manifest()
        model = self.directory / self.active_manifest["cases"][0]["model_path"]
        with patch.object(suite, "check_model", side_effect=self.simulate_model), \
                self.after_evaluation(lambda: model.write_bytes(b"synthetic concurrent model change")), \
                self.assertRaises(suite.CheckError):
            suite.run_suite(path, comsol_root=self.directory, model_root=self.directory, output_dir=self.output)
        self.assert_failed()

    def test_model_source_replaced_by_link_after_checks_is_rejected(self):
        self.active_manifest, path = self.mock_manifest()
        model = self.directory / self.active_manifest["cases"][0]["model_path"]
        original = suite.evaluate_dataset
        activated = False
        def evaluate(*args, **kwargs):
            nonlocal activated
            result = original(*args, **kwargs)
            activated = True
            return result
        with patch.object(suite, "check_model", side_effect=self.simulate_model), \
                patch.object(suite, "evaluate_dataset", side_effect=evaluate), \
                patch.object(Path, "is_symlink", autospec=True, side_effect=lambda p: activated and p == model), \
                self.assertRaises(suite.CheckError):
            suite.run_suite(path, comsol_root=self.directory, model_root=self.directory, output_dir=self.output)
        self.assert_failed()

    def test_saved_summary_not_matching_computed_scores_is_rejected(self):
        original = suite._write_json
        def tamper(path, value):
            original(path, value)
            if path.name == "summary.json":
                changed = copy.deepcopy(value)
                changed["checked_cases"] = float(changed["checked_cases"])
                path.write_text(json.dumps(changed), encoding="utf-8")
        with patch.object(suite, "_write_json", side_effect=tamper), self.assertRaises(suite.CheckError):
            self.offline()
        self.assert_failed(summary_exists=True)

    def test_inputs_changed_after_summary_write_leave_failed_not_completed_record(self):
        original = suite._write_json
        def change(path, value):
            original(path, value)
            if path.name == "summary.json":
                self.manifest_path.write_bytes(self.manifest_path.read_bytes() + b"\n")
        with patch.object(suite, "_write_json", side_effect=change), self.assertRaises(suite.CheckError):
            self.offline()
        self.assert_failed(summary_exists=True)

    def test_summary_changed_during_report_rendering_is_rejected(self):
        original = suite.render_report
        def render(value):
            result = original(value)
            path = self.output / "summary.json"
            path.write_bytes(path.read_bytes() + b"\n")
            return result
        with patch.object(suite, "render_report", side_effect=render), self.assertRaises(suite.CheckError):
            self.offline()
        self.assert_failed(summary_exists=True)

    def test_human_report_changed_during_final_input_guard_is_rejected(self):
        original = dataset.fingerprints
        calls = 0
        def fingerprint():
            nonlocal calls
            result = original()
            calls += 1
            if calls == 3:
                (self.output / "report.md").write_bytes(b"synthetic falsely clean human summary")
            return result
        with patch.object(dataset, "fingerprints", side_effect=fingerprint), self.assertRaises(suite.CheckError):
            self.offline()
        self.assert_failed(summary_exists=True)

    def test_report_write_failure_preserves_failed_terminal_record(self):
        original = Path.open
        def deny(path, *args, **kwargs):
            if path == self.output / "report.md" and args == ("xb",):
                raise OSError("synthetic storage failure")
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", deny), self.assertRaises(OSError):
            self.offline()
        self.assert_failed(summary_exists=True)

    def test_stable_execution_failure_remains_unscored_and_incomplete(self):
        self.active_manifest, path = self.mock_manifest()
        def simulate(model, **options):
            if options["output_dir"].name == "baseline":
                raise suite.CheckError("synthetic compiler failure without report")
            return self.simulate_model(model, **options)
        with patch.object(suite, "check_model", side_effect=simulate):
            result = suite.run_suite(path, comsol_root=self.directory, model_root=self.directory, output_dir=self.output)
        self.assertEqual(result["cases"][0]["status"], "failed")
        self.assertEqual(result["checked_cases"], 5)
        run = json.loads((self.output / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(run["status"], "incomplete")
        self.assertTrue(run["input_stability_verified"])


if __name__ == "__main__":
    unittest.main()
