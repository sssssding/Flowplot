"""Synthetic frozen runs test integrity/score reproduction, not independent COMSOL acceptance."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_acceptance_dataset as fixtures

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot import acceptance_dataset as dataset, acceptance_result as reader, check_suite as suite
from flowpilot.check_model import CheckError


class AcceptanceResultTest(unittest.TestCase):
    save_manifest = fixtures.AcceptanceDatasetTest.save_manifest

    def setUp(self):
        fixtures.AcceptanceDatasetTest.setUp(self)
        dataset.freeze_dataset(self.manifest_path, model_root=self.models, output_dir=self.output)
        self.reports = self.root / "synthetic-reports"
        for case in self.manifest["cases"]:
            child = self.reports / case["case_id"]
            child.mkdir(parents=True)
            report = {"schema_version": "diagnosis-0.1", "status": "checked", "findings": [
                {"code": code, "severity": "Warning", "explanation": "synthetic, not a COMSOL finding",
                 "feature_tags": [], "boundary_ids": [], "evidence": {}} for code in case["expected_codes"]]}
            dataset._write_json(child / "diagnosis.json", report)
            metadata = {"schema_version": "check-run-0.1", "status": "completed", "diagnosis_status": "checked",
                "source": {"filename": case["case_id"] + ".mph", "sha256": case["sha256"]},
                "settings": {"reynolds_warning": 2000.}, "comsol_version": "synthetic; no COMSOL execution",
                "rule_engine_sha256": dataset.sha256(ROOT / "src/flowpilot/diagnostics.py"),
                "inventory_source_sha256": dataset.sha256(ROOT / "src/comsol/ModelInventory.java"),
                "diagnosis_sha256": dataset.sha256(child / "diagnosis.json")}
            dataset._write_json(child / "run.json", metadata)
        self.run = self.root / "formal-run"

    def run_pipeline(self, mode="check", *, failed=False):
        def simulate_model(model, **options):
            if failed and model.stem == "case-000":
                raise CheckError("synthetic compiler startup failure; no terminal single-model file")
            shutil.copytree(self.reports / model.stem, options["output_dir"])
        with patch.object(suite, "check_model", side_effect=simulate_model), patch("builtins.print"):
            return dataset.run_frozen(self.output, output_dir=self.run,
                **({"comsol_root": self.root} if mode == "check" else {"reports_root": self.reports}))

    def load(self, reports_root=None):
        return reader.load_acceptance_result(self.run, dataset_dir=self.output, reports_root=reports_root)

    def mutate(self, path, transform):
        value = json.loads(path.read_text(encoding="utf-8"))
        transform(value)
        path.write_text(json.dumps(value), encoding="utf-8")

    def rebind_aggregates(self):
        # Simulate tampering with both hashes and content. Independent recomputation must
        # still reject wrong metrics; public hashes alone are not an author signature.
        summary = json.loads((self.run / "checks/summary.json").read_text(encoding="utf-8"))
        self.mutate(self.run / "checks/run.json", lambda r: r.update(
            summary_sha256=dataset.sha256(self.run / "checks/summary.json")))
        self.mutate(self.run / "result.json", lambda r: r.update(evaluation=summary))
        self.mutate(self.run / "run.json", lambda r: r.update(
            result_sha256=dataset.sha256(self.run / "result.json"),
            suite_summary_sha256=dataset.sha256(self.run / "checks/summary.json"),
            suite_run_sha256=dataset.sha256(self.run / "checks/run.json")))

    def test_actual_orchestration_recomputed_with_synthetic_model_reader_only(self):
        result = self.run_pipeline()
        review = self.load()
        self.assertEqual(review["status"], "verified_complete")
        self.assertTrue(review["summary"]["meets_recall_above_90_percent"])
        self.assertTrue(reader.render_review(review).startswith("# FlowPlot 验收结果复核"))
        self.assertFalse(review["software_authenticates_reviewers"])
        self.assertEqual(review["original_result_sha256"], dataset.sha256(self.run / "result.json"))
        self.assertEqual(review["original_run_sha256"], dataset.sha256(self.run / "run.json"))
        self.assertEqual(review["summary"]["metrics_on_checked_cases_only"], result["evaluation"]["metrics_on_checked_cases_only"])

    def test_offline_requires_explicit_original_reports_and_reads_them(self):
        self.run_pipeline("evaluate")
        with self.assertRaisesRegex(ValueError, "显式指定"):
            self.load()
        review = self.load(self.reports)
        self.assertEqual(review["status"], "verified_complete")
        with self.assertRaises(ValueError):
            self.load(self.root)

    def test_online_root_cannot_be_replaced(self):
        self.run_pipeline()
        with self.assertRaisesRegex(ValueError, "不能替换"):
            self.load(self.reports)

    def test_result_and_suite_file_changes_rejected_even_for_whitespace(self):
        self.run_pipeline()
        for relative in ("result.json", "checks/summary.json", "checks/run.json"):
            path = self.run / relative
            before = path.read_bytes()
            path.write_bytes(before + b" ")
            with self.subTest(path=relative), self.assertRaises(ValueError):
                self.load()
            path.write_bytes(before)

    def test_failed_cancelled_running_or_legacy_records_rejected(self):
        self.run_pipeline()
        path = self.run / "run.json"
        before = path.read_bytes()
        for change in (lambda r: r.update(status="failed"), lambda r: r.update(status="cancelled"),
                       lambda r: r.update(status="running"), lambda r: r.update(schema_version="acceptance-run-0.1"),
                       lambda r: r.pop("result_sha256"), lambda r: r.pop("finished_at")):
            self.mutate(path, change)
            with self.assertRaises(ValueError):
                self.load()
            path.write_bytes(before)

    def test_completion_record_storage_failure_leaves_no_usable_result(self):
        original = dataset._write_json
        def fail(path, value):
            if path == self.run / "run.json":
                raise OSError("synthetic completion record storage failure")
            return original(path, value)
        with patch.object(dataset, "_write_json", side_effect=fail), self.assertRaises(OSError):
            self.run_pipeline()
        self.assertTrue((self.run / "result.json").exists())
        self.assertFalse((self.run / "run.json").exists())
        with self.assertRaises((ValueError, OSError)):
            self.load()

    def test_result_from_other_dataset_or_freeze_rejected(self):
        self.run_pipeline()
        path = self.run / "result.json"
        before = path.read_bytes()
        for change in (lambda r: r.update(dataset_id="another-set"),
                       lambda r: r.update(freeze_sha256="0" * 64),
                       lambda r: r.update(software_authenticates_reviewers=True)):
            self.mutate(path, change)
            self.mutate(self.run / "run.json", lambda r: r.update(result_sha256=dataset.sha256(path)))
            with self.assertRaises(ValueError):
                self.load()
            path.write_bytes(before)

    def test_rebound_wrong_counts_recall_boolean_or_rule_metrics_rejected(self):
        self.run_pipeline()
        paths = [self.run / name for name in ("run.json", "result.json", "checks/summary.json", "checks/run.json")]
        before = [path.read_bytes() for path in paths]
        changes = (lambda s: s.update(exact_match_cases=9),
                   lambda s: s["metrics_on_checked_cases_only"].update(recall=.99),
                   lambda s: s["metrics_on_checked_cases_only"].update(recall=True),
                   lambda s: s["per_rule_on_checked_cases_only"]["MISSING_INLET"].update(false_positive=1),
                   lambda s: s.update(meets_recall_above_90_percent=False))
        for change in changes:
            self.mutate(self.run / "checks/summary.json", change)
            self.rebind_aggregates()
            with self.assertRaisesRegex(ValueError, "重算不一致"):
                self.load()
            for path, payload in zip(paths, before):
                path.write_bytes(payload)

    def test_rebound_missing_duplicate_reordered_or_extra_rows_rejected(self):
        self.run_pipeline()
        paths = [self.run / name for name in ("run.json", "result.json", "checks/summary.json", "checks/run.json")]
        before = [path.read_bytes() for path in paths]
        for change in (lambda s: s["cases"].pop(), lambda s: s["cases"].reverse(),
                       lambda s: s["cases"][0].update(case_id=s["cases"][1]["case_id"]),
                       lambda s: s.update(unknown_score=100)):
            self.mutate(self.run / "checks/summary.json", change)
            self.rebind_aggregates()
            with self.assertRaises(ValueError):
                self.load()
            for path, payload in zip(paths, before):
                path.write_bytes(payload)

    def test_changed_missing_or_rehashed_single_model_report_rejected(self):
        self.run_pipeline()
        child = self.run / "checks/case-000"
        diagnosis = child / "diagnosis.json"
        before = diagnosis.read_bytes()
        diagnosis.unlink()
        with self.assertRaises(ValueError):
            self.load()
        diagnosis.write_bytes(before + b" ")
        with self.assertRaises(ValueError):
            self.load()
        self.mutate(child / "run.json", lambda r: r.update(diagnosis_sha256=dataset.sha256(diagnosis)))
        with self.assertRaises(ValueError):
            self.load()

    def test_partial_and_unsupported_are_recomputed_without_pass(self):
        child = self.reports / "case-000"
        self.mutate(child / "diagnosis.json", lambda r: r.update(status="partial", findings=[{
            "code": "EVALUATION_UNAVAILABLE", "severity": "Warning", "explanation": "synthetic unresolved input",
            "feature_tags": [], "boundary_ids": [], "evidence": {}}]))
        self.mutate(child / "run.json", lambda r: r.update(diagnosis_status="partial", diagnosis_sha256=dataset.sha256(child / "diagnosis.json")))
        self.run_pipeline()
        review = self.load()
        self.assertEqual(review["status"], "verified_incomplete")
        self.assertEqual(review["summary"]["checked_cases"], 9)
        self.assertIsNone(review["summary"]["meets_recall_above_90_percent"])
        self.assertIn("不能作为独立验收通过", reader.render_review(review))
        self.run = self.root / "unsupported-run"
        self.mutate(child / "diagnosis.json", lambda r: r.update(status="unsupported", reason="synthetic unsupported", findings=[]))
        self.mutate(child / "run.json", lambda r: r.update(diagnosis_status="unsupported", diagnosis_sha256=dataset.sha256(child / "diagnosis.json")))
        self.run_pipeline()
        self.assertEqual(self.load()["summary"]["cases"][0]["status"], "unsupported")

    def test_failure_without_single_model_artifact_remains_unassessed(self):
        self.run_pipeline(failed=True)
        review = self.load()
        self.assertEqual(review["status"], "verified_incomplete")
        self.assertEqual(review["unverifiable_failure_case_ids"], ["case-000"])
        self.assertIsNone(review["summary"]["meets_recall_above_90_percent"])
        self.assertIn("不认证原失败原因", reader.render_review(review))
        child = self.run / "checks/case-000"
        shutil.copytree(self.reports / "case-000", child)
        with self.assertRaises(ValueError):
            self.load()  # Do not apply newly repaired reports to old aggregate scores.

    def test_unscored_reports_stay_incomplete_not_clean_negatives(self):
        (self.reports / "case-000/diagnosis.json").unlink()
        self.run_pipeline("evaluate")
        review = self.load(self.reports)
        self.assertEqual(review["summary"]["cases"][0]["status"], "unscored")
        self.assertEqual(review["summary"]["unassessed_expected_code_count"], 1)

    def test_changed_freeze_model_or_source_rejects_result(self):
        self.run_pipeline()
        path = self.output / "models/case-000.mph"
        before = path.read_bytes()
        path.write_bytes(before + b"changed")
        with self.assertRaises(ValueError):
            self.load()
        path.write_bytes(before)
        original = dataset.fingerprints
        def changed():
            hashes, known = original()
            hashes[dataset.SOURCES[0]] = "0" * 64
            return hashes, known
        with patch.object(dataset, "fingerprints", side_effect=changed), self.assertRaises(ValueError):
            self.load()

    def test_freeze_changes_during_result_read_are_rejected(self):
        self.run_pipeline()
        original = reader.read_outcome
        def changed(*args):
            value = original(*args)
            if args[1]["case_id"] == "case-000":
                path = self.output / "freeze.json"
                path.write_bytes(path.read_bytes() + b" ")
            return value
        with patch.object(reader, "read_outcome", side_effect=changed), self.assertRaisesRegex(ValueError, "复核期间变化"):
            self.load()

    def test_provenance_hashes_use_same_read_bytes_not_second_disk_reads(self):
        self.run_pipeline()
        original = reader.read_regular_file
        initial = {name: dataset.sha256(self.run / name) for name in ("run.json", "result.json")}
        reads = {name: 0 for name in initial}
        def change_after_read(path, **options):
            value = original(path, **options)
            if path.parent == self.run and path.name in reads:
                reads[path.name] += 1
                path.write_bytes(value + b" ")
            return value
        with patch.object(reader, "read_regular_file", side_effect=change_after_read):
            review = self.load()
        self.assertEqual(reads, {"run.json": 1, "result.json": 1})
        self.assertEqual(review["original_run_sha256"], initial["run.json"])
        self.assertEqual(review["original_result_sha256"], initial["result.json"])

    def test_oversized_duplicate_and_nonfinite_result_json_rejected(self):
        self.run_pipeline()
        path = self.run / "result.json"
        before = path.read_bytes()
        for payload in (b" " * (reader.MAX_DIAGNOSIS_BYTES + 1), b'{"x":1,"x":2}', b'{"score":NaN}'):
            path.write_bytes(payload)
            with self.assertRaises(ValueError):
                self.load()
        path.write_bytes(before)

    def test_linked_report_directories_refused_by_guard(self):
        self.run_pipeline()
        child = self.run / "checks/case-000"
        with patch.object(Path, "is_junction", autospec=True, side_effect=lambda p: p == child), self.assertRaises(ValueError):
            self.load()

    def test_markdown_escapes_free_text_without_claiming_physics_pass(self):
        self.run_pipeline()
        review = self.load()
        review["dataset_id"] = '<script>alert(1)</script> | **unsafe**'
        rendered = reader.render_review(review)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("不认证审核身份", rendered)
        self.assertIn("不是物理", rendered)

    def test_optional_batch_stability_bindings_cannot_be_falsified_by_outer_rehash(self):
        self.run_pipeline()
        batch = self.run / "checks/run.json"
        top = self.run / "run.json"
        batch_raw, top_raw = batch.read_bytes(), top.read_bytes()
        for change in (lambda r: r.update(summary_sha256="0" * 64),
                       lambda r: r.update(input_stability_verified=1),
                       lambda r: r.update(input_stability_verified=False),
                       lambda r: r.update(source_fingerprints={"synthetic wrong source": "0" * 64})):
            self.mutate(batch, change)
            self.mutate(top, lambda r: r.update(suite_run_sha256=dataset.sha256(batch)))
            with self.assertRaises(ValueError):
                self.load()
            batch.write_bytes(batch_raw)
            top.write_bytes(top_raw)

    def test_missing_optional_batch_fields_are_not_fabricated_as_verified(self):
        self.run_pipeline()
        batch = self.run / "checks/run.json"
        self.mutate(batch, lambda r: [r.pop(key, None) for key in
                    ("summary_sha256", "input_stability_verified", "source_fingerprints")])
        self.mutate(self.run / "run.json", lambda r: r.update(suite_run_sha256=dataset.sha256(batch)))
        self.assertEqual(self.load()["status"], "verified_complete")
        self.assertNotIn("input_stability_verified", json.loads(batch.read_text(encoding="utf-8")))

    def test_cli_review_export_existing_output_and_incomplete_exit(self):
        self.run_pipeline()
        export = self.root / "export"
        command = [sys.executable, "-X", "utf8", str(ROOT / "src/flowpilot/acceptance_result.py"),
                   str(self.run), "--dataset", str(self.output), "--output-dir", str(export)]
        result = subprocess.run(command, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        self.assertEqual({p.name for p in export.iterdir()}, {"review.json", "report.md"})
        result = subprocess.run(command, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.run = self.root / "failed-run"
        self.run_pipeline(failed=True)
        command = [sys.executable, "-X", "utf8", str(ROOT / "src/flowpilot/acceptance_result.py"),
                   str(self.run), "--dataset", str(self.output)]
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)


if __name__ == "__main__":
    unittest.main()
