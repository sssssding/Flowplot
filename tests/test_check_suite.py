"""Evaluation arithmetic and batch failure tests; synthetic reports are not simulations."""
import copy
import json
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot import check_suite as suite


class CheckSuiteTest(unittest.TestCase):
    def setUp(self):
        (ROOT / "outputs").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "outputs")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.manifest = json.loads(suite.DEVELOPMENT_MANIFEST.read_text(encoding="utf-8-sig"))
        self.outcomes = {case["case_id"]: {"status": "checked", "predicted_codes": case["expected_codes"][:]}
                         for case in self.manifest["cases"]}
        self.output = self.directory / "batch"
        self.reports = self.directory / "reports"
        self.reports.mkdir()
        for case in self.manifest["cases"]:
            self.write_report(self.reports / case["case_id"], case)

    def write_report(self, directory, case, status="checked"):
        directory.mkdir(parents=True)
        report = {"schema_version": "diagnosis-0.1", "status": status,
                  "findings": [{"code": code, "severity": "Warning", "explanation": "synthetic test finding",
                                "feature_tags": [], "boundary_ids": [], "evidence": {}}
                               for code in case["expected_codes"]]}
        suite._write_json(directory / "diagnosis.json", report)
        metadata = {"schema_version": "check-run-0.1", "status": "completed", "diagnosis_status": status,
                    "source": {"filename": case["case_id"] + ".mph", "sha256": case["sha256"]},
                    "settings": {"reynolds_warning": 2000},
                    "rule_engine_sha256": suite.sha256(suite.RULE_SOURCE),
                    "inventory_source_sha256": suite.sha256(suite.INVENTORY_SOURCE),
                    "diagnosis_sha256": suite.sha256(directory / "diagnosis.json")}
        suite._write_json(directory / "run.json", metadata)

    def offline(self):
        return suite.run_suite(suite.DEVELOPMENT_MANIFEST, output_dir=self.output, reports_root=self.reports)

    def test_six_regression_matches_are_not_independent_acceptance(self):
        result = suite.evaluate_dataset(self.manifest, self.outcomes)
        self.assertEqual(result["exact_match_cases"], 6)
        self.assertEqual(result["metrics_on_checked_cases_only"]["recall"], 1)
        self.assertFalse(result["acceptance_eligible"])
        self.assertIn("overlaps_known_development_models", result["acceptance_blockers"])
        self.assertIsNone(result["meets_recall_above_90_percent"])

    def test_tp_fp_fn_count_once_per_model_code(self):
        self.outcomes["missing_inlet"]["predicted_codes"] = ["MISSING_OUTLET", "MISSING_OUTLET"]
        result = suite.evaluate_dataset(self.manifest, self.outcomes)
        metrics = result["metrics_on_checked_cases_only"]
        self.assertEqual((metrics["true_positive"], metrics["false_positive"], metrics["false_negative"]), (5, 1, 1))
        self.assertAlmostEqual(metrics["precision"], 5 / 6)
        self.assertAlmostEqual(metrics["recall"], 5 / 6)
        row = next(row for row in result["cases"] if row["case_id"] == "missing_inlet")
        self.assertEqual(row["missed_codes"], ["MISSING_INLET"])
        self.assertEqual(row["unexpected_codes"], ["MISSING_OUTLET"])

    def test_partial_and_unsupported_are_not_clean_negatives(self):
        for status in ("partial", "unsupported", "failed", "unscored", "missing"):
            outcomes = copy.deepcopy(self.outcomes)
            outcomes["missing_inlet"] = {"status": status}
            result = suite.evaluate_dataset(self.manifest, outcomes)
            self.assertEqual(result["checked_cases"], 5)
            self.assertEqual(result["unassessed_expected_code_count"], 1)
            self.assertAlmostEqual(result["recall_lower_bound_all_expected_codes"], 5 / 6)
            self.assertEqual(result["metrics_on_checked_cases_only"]["recall"], 1)
            self.assertIn("incomplete_checked_coverage", result["acceptance_blockers"])
            row = next(row for row in result["cases"] if row["case_id"] == "missing_inlet")
            self.assertIsNone(row["predicted_codes"])

    def test_empty_denominators_are_null_not_perfect_scores(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["cases"] = manifest["cases"][:1]
        result = suite.evaluate_dataset(manifest, {"baseline": self.outcomes["baseline"]})
        self.assertIsNone(result["metrics_on_checked_cases_only"]["precision"])
        self.assertIsNone(result["metrics_on_checked_cases_only"]["recall"])
        self.assertIsNone(result["recall_lower_bound_all_expected_codes"])

    def test_all_missing_reports_have_zero_coverage_and_zero_lower_bound(self):
        result = suite.evaluate_dataset(self.manifest, {})
        self.assertEqual(result["checked_coverage"], 0)
        self.assertEqual(result["recall_lower_bound_all_expected_codes"], 0)
        self.assertIsNone(result["metrics_on_checked_cases_only"]["recall"])

    def independent_manifest(self):
        manifest = copy.deepcopy(self.manifest)
        manifest.update(independent_acceptance_set=True, label_status="expert_reviewed",
            acceptance_declaration={"dataset_id": "synthetic scoring test, not real independent data",
                "independence_reviewed_by": "synthetic test reviewer",
                "independence_reviewed_date": "2000-01-01",
                "models_not_derived_from_development": True, "labels_fixed_before_diagnosis": True,
                "creators_and_reviewers_not_rule_developers": True})
        for index in range(4):
            manifest["cases"].append({"case_id": f"synthetic-extra-{index}", "model_path": f"extra-{index}.mph",
                                      "expected_codes": []})
        for index, case in enumerate(manifest["cases"], 1):
            case.update(sha256=f"{index:064x}", reviewed_by="synthetic test reviewer", reviewed_date="2026-10-11",
                        used_for_rule_development=False, created_by="synthetic test author",
                        origin_reference="synthetic declaration, not physical data",
                        independence_group=f"synthetic-group-{index % 2}")
        return manifest

    def declared_outcomes(self, manifest):
        return {case["case_id"]: {"status": "checked", "predicted_codes": case["expected_codes"][:]}
                for case in manifest["cases"]}

    def test_independent_declarations_require_review_and_rule_coverage(self):
        manifest = self.independent_manifest()
        result = suite.evaluate_dataset(manifest, self.declared_outcomes(manifest))
        self.assertTrue(result["acceptance_eligible"])
        self.assertTrue(result["meets_recall_above_90_percent"])
        manifest["cases"][1].pop("reviewed_date")
        self.assertFalse(suite.evaluate_dataset(manifest, self.declared_outcomes(manifest))["acceptance_eligible"])
        manifest = self.independent_manifest()
        manifest["cases"][0]["used_for_rule_development"] = True
        self.assertIn("case_development_usage_not_excluded", suite.acceptance_reasons(manifest))
        manifest["cases"] = manifest["cases"][:2]
        self.assertIn("first_five_rules_not_all_represented", suite.acceptance_reasons(manifest))

    def test_existing_development_hashes_cannot_be_relabelled_independent(self):
        manifest = self.independent_manifest()
        manifest["cases"][0]["sha256"] = self.manifest["cases"][0]["sha256"]
        self.assertIn("overlaps_known_development_models", suite.acceptance_reasons(manifest))

    def assert_strictly_blocked(self, manifest, outcomes=None):
        result = suite.evaluate_dataset(manifest, self.declared_outcomes(manifest) if outcomes is None else outcomes)
        self.assertEqual(result["checked_cases"], len(manifest["cases"]))
        self.assertFalse(result["acceptance_eligible"])
        self.assertEqual(result["evaluation_kind"], "development_or_unreviewed")
        self.assertIsNone(result["meets_recall_above_90_percent"])
        self.assertIn("formal_freeze_requirements_not_met", result["acceptance_blockers"])
        self.assertIn("不能宣称独立验收", suite.render_report(result))
        return result

    def test_six_fully_declared_cases_still_do_not_meet_formal_minimum(self):
        manifest = self.independent_manifest()
        manifest["cases"] = manifest["cases"][:6]
        self.assertEqual(suite.acceptance_reasons(manifest), [])  # Reproduce the old gate's gap.
        result = self.assert_strictly_blocked(manifest)
        self.assertEqual(result["metrics_on_checked_cases_only"]["recall"], 1)

    def test_missing_independence_declaration_cannot_be_promoted_by_generic_evaluation(self):
        manifest = self.independent_manifest()
        manifest.pop("acceptance_declaration")
        self.assertEqual(suite.acceptance_reasons(manifest), [])
        self.assert_strictly_blocked(manifest)

    def test_all_known_variants_are_excluded_by_the_formal_gate(self):
        variations = json.loads((ROOT / "data/fixtures/regression_family.json").read_text(encoding="utf-8"))
        for case in variations["cases"]:
            manifest = self.independent_manifest()
            manifest["cases"][0]["sha256"] = case["source_sha256"]
            self.assertEqual(suite.acceptance_reasons(manifest), [])
            self.assert_strictly_blocked(manifest)

    def test_future_and_noncanonical_review_dates_are_not_independent_results(self):
        for value in ("2099-01-01", "20000101"):
            manifest = self.independent_manifest()
            manifest["cases"][0]["reviewed_date"] = value
            self.assertEqual(suite.acceptance_reasons(manifest), [])
            self.assert_strictly_blocked(manifest)

    def test_missing_model_source_fields_are_not_independent_results(self):
        for field in ("created_by", "origin_reference", "independence_group"):
            manifest = self.independent_manifest()
            manifest["cases"][0].pop(field)
            self.assert_strictly_blocked(manifest)

    def test_false_or_truthy_independence_confirmations_cannot_pass(self):
        for value in (False, 1, "true", None):
            manifest = self.independent_manifest()
            manifest["acceptance_declaration"]["labels_fixed_before_diagnosis"] = value
            self.assert_strictly_blocked(manifest)

    def test_one_normalized_source_group_is_insufficient(self):
        manifest = self.independent_manifest()
        for index, case in enumerate(manifest["cases"]):
            case["independence_group"] = " GROUP " if index % 2 else "group"
        self.assert_strictly_blocked(manifest)

    def test_case_insensitive_identity_or_path_collision_is_not_independent(self):
        for field in ("case_id", "model_path"):
            manifest = self.independent_manifest()
            manifest["cases"][1][field] = manifest["cases"][0][field].upper()
            self.assert_strictly_blocked(manifest)

    def test_robustness_label_cannot_be_used_as_formal_supported_case(self):
        manifest = self.independent_manifest()
        manifest["cases"][0]["expected_codes"] = ["EVALUATION_UNAVAILABLE"]
        outcomes = self.declared_outcomes(manifest)
        outcomes["baseline"]["predicted_codes"] = []
        self.assert_strictly_blocked(manifest, outcomes)

    def test_unavailable_registry_fails_closed_without_discarding_development_metrics(self):
        from flowpilot import acceptance_dataset as dataset
        manifest = self.independent_manifest()
        with patch.object(dataset, "fingerprints", side_effect=OSError("synthetic unavailable registry")):
            result = self.assert_strictly_blocked(manifest)
        self.assertEqual(result["metrics_on_checked_cases_only"]["recall"], 1)

    def test_generic_evaluator_cannot_bypass_a_new_formal_gate_requirement(self):
        from flowpilot import acceptance_dataset as dataset
        manifest = self.independent_manifest()
        with patch.object(dataset, "validate_acceptance", side_effect=ValueError("synthetic additional requirement")) as gate:
            self.assert_strictly_blocked(manifest)
        gate.assert_called_once()

    def test_unsafe_ids_duplicate_hashes_and_unknown_codes_rejected(self):
        mutations = [lambda m: m["cases"][0].update(case_id="../escape"),
                     lambda m: m["cases"][0].update(case_id=123),
                     lambda m: m["cases"][0].update(case_id="CON"),
                     lambda m: m["cases"][1].update(case_id="baseline"),
                     lambda m: m["cases"][1].update(sha256=m["cases"][0]["sha256"]),
                     lambda m: m["cases"][0].update(expected_codes=["MADE_UP_CODE"]),
                     lambda m: m["cases"][0].update(model_path="../outside.mph"),
                     lambda m: m["cases"][0].update(model_path="C:relative.mph"),
                     lambda m: m.update(reynolds_warning=True)]
        for mutate in mutations:
            manifest = copy.deepcopy(self.manifest)
            mutate(manifest)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                suite.validate_manifest(manifest)

    def test_source_config_and_rule_version_mismatches_are_unscored(self):
        case = self.manifest["cases"][0]
        directory = self.reports / case["case_id"]
        run_path = directory / "run.json"
        original = json.loads(run_path.read_text(encoding="utf-8"))
        mutations = [lambda m: m.update(status="failed"), lambda m: m["source"].update(sha256="0" * 64),
                     lambda m: m["settings"].update(reynolds_warning=1),
                     lambda m: m.update(rule_engine_sha256="0" * 64),
                     lambda m: m.update(inventory_source_sha256="0" * 64),
                     lambda m: m.pop("diagnosis_sha256")]
        for mutate in mutations:
            metadata = copy.deepcopy(original)
            mutate(metadata)
            run_path.write_text(json.dumps(metadata), encoding="utf-8")
            self.assertEqual(suite.read_outcome(directory, case, 2000)["status"], "unscored")

    def test_tampered_diagnosis_is_unscored(self):
        case = self.manifest["cases"][0]
        directory = self.reports / case["case_id"]
        (directory / "diagnosis.json").write_text('{}', encoding="utf-8")
        self.assertEqual(suite.read_outcome(directory, case, 2000)["status"], "unscored")

    def test_offline_evaluation_writes_audit_and_report_without_comsol(self):
        with patch.object(suite, "check_model") as check:
            result = self.offline()
        check.assert_not_called()
        self.assertEqual(result["checked_cases"], 6)
        self.assertEqual(result["mode"], "evaluate")
        self.assertIn("diagnosis_sha256", result["cases"][0])
        metadata = json.loads((self.output / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "completed")
        self.assertIsNone(metadata["settings"]["loads"])
        self.assertIn("不能宣称独立验收", (self.output / "report.md").read_text(encoding="utf-8"))

    def test_missing_report_produces_incomplete_not_successful_suite(self):
        (self.reports / "missing_inlet/run.json").unlink()
        result = self.offline()
        self.assertEqual(result["checked_cases"], 5)
        metadata = json.loads((self.output / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "incomplete")

    def test_existing_output_is_preserved(self):
        self.output.mkdir()
        (self.output / "report.md").write_bytes(b"previous")
        with self.assertRaises(FileExistsError):
            self.offline()
        self.assertEqual((self.output / "report.md").read_bytes(), b"previous")

    def mock_manifest(self):
        manifest = copy.deepcopy(self.manifest)
        for case in manifest["cases"]:
            model = self.directory / case["model_path"]
            model.parent.mkdir(parents=True, exist_ok=True)
            model.write_bytes(case["case_id"].encode("ascii"))
            case["sha256"] = suite.sha256(model)
        path = self.directory / "manifest.json"
        suite._write_json(path, manifest)
        return manifest, path

    def test_failed_check_does_not_hide_other_models(self):
        manifest, path = self.mock_manifest()
        def simulate(model, *, output_dir, **kwargs):
            case = next(case for case in manifest["cases"] if case["case_id"] == output_dir.name)
            if case["case_id"] == "missing_inlet":
                raise suite.CheckError("synthetic COMSOL timeout")
            self.write_report(output_dir, case)
        with patch.object(suite, "check_model", side_effect=simulate) as check:
            result = suite.run_suite(path, comsol_root=self.directory, model_root=self.directory, output_dir=self.output)
        self.assertEqual(check.call_count, 6)
        self.assertEqual(result["checked_cases"], 5)
        self.assertEqual(result["cases"][1]["status"], "failed")

    def test_hash_mismatch_stops_before_any_check(self):
        manifest, path = self.mock_manifest()
        (self.directory / manifest["cases"][0]["model_path"]).write_bytes(b"edited")
        with patch.object(suite, "check_model") as check, self.assertRaises(suite.CheckError):
            suite.run_suite(path, comsol_root=self.directory, model_root=self.directory, output_dir=self.output)
        check.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_user_interrupt_cancels_without_success_summary(self):
        _, path = self.mock_manifest()
        with patch.object(suite, "check_model", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            suite.run_suite(path, comsol_root=self.directory, model_root=self.directory, output_dir=self.output)
        metadata = json.loads((self.output / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "cancelled")
        self.assertFalse((self.output / "summary.json").exists())

    def test_cli_exit_codes_distinguish_match_incomplete_and_mismatch(self):
        base = [sys.executable, "-X", "utf8", str(ROOT / "src/flowpilot/check_suite.py"),
                "--reports-root", str(self.reports), "--manifest", str(suite.DEVELOPMENT_MANIFEST)]
        def invoke(name):
            return subprocess.run(base + ["--output-dir", str(self.directory / name)], capture_output=True)
        self.assertEqual(invoke("all-match").returncode, 0)
        run_path = self.reports / "baseline/run.json"
        before = run_path.read_bytes()
        run_path.unlink()
        self.assertEqual(invoke("incomplete").returncode, 2)
        run_path.write_bytes(before)
        report_path = self.reports / "baseline/diagnosis.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["findings"] = [{"code": "MISSING_INLET", "severity": "Critical", "explanation": "synthetic test finding",
                               "feature_tags": [], "boundary_ids": [], "evidence": {}}]
        report_path.write_text(json.dumps(report), encoding="utf-8")
        metadata = json.loads(run_path.read_text(encoding="utf-8"))
        metadata["diagnosis_sha256"] = suite.sha256(report_path)
        run_path.write_text(json.dumps(metadata), encoding="utf-8")
        self.assertEqual(invoke("mismatch").returncode, 3)

    def test_versioned_real_batch_summary_recomputes_without_independence_claim(self):
        stored = json.loads((ROOT / "data/fixtures/batch_regression.json").read_text(encoding="utf-8"))
        outcomes = {row["case_id"]: {key: row[key] for key in
                    ("status", "predicted_codes", "diagnosis_sha256", "run_metadata_sha256")}
                    for row in stored["cases"]}
        computed = suite.evaluate_dataset(self.manifest, outcomes)
        for key, value in computed.items():
            self.assertEqual(value, stored[key])
        self.assertEqual(stored["manifest_sha256"], suite.sha256(suite.DEVELOPMENT_MANIFEST))
        self.assertEqual(stored["rule_engine_sha256"], suite.sha256(suite.RULE_SOURCE))
        self.assertEqual(stored["inventory_source_sha256"], suite.sha256(suite.INVENTORY_SOURCE))
        self.assertEqual(stored["exact_match_cases"], 6)
        self.assertIsNone(stored["meets_recall_above_90_percent"])


if __name__ == "__main__":
    unittest.main()
