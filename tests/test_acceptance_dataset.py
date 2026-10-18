"""Synthetic byte files/declarations test workflow integrity, NOT actual independent acceptance."""
import copy
from datetime import date
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot import acceptance_dataset as dataset
from flowpilot.check_suite import CORE_CODES, evaluate_dataset
from flowpilot.engine_fingerprint import engine_fingerprint


class AcceptanceDatasetTest(unittest.TestCase):
    def setUp(self):
        (ROOT / "outputs").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "outputs")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.models = self.root / "input models"
        self.models.mkdir()
        self.reports_root = self.root / "reports"
        self.reports_root.mkdir()
        self.output = self.root / "frozen"
        self.manifest_path = self.root / "review.json"
        self.manifest = {"schema_version": "case-manifest-0.1", "label_status": "expert_reviewed",
            "independent_acceptance_set": True, "reynolds_warning": 2000., "cases": [],
            "acceptance_declaration": {"dataset_id": "synthetic-test-only-not-real-acceptance",
                "independence_reviewed_by": "synthetic unit-test declaration, not a real reviewer",
                "independence_reviewed_date": "2000-01-01", **dict.fromkeys(dataset.DECLARATIONS, True)}}
        for index in range(10):
            identity = f"case-{index:03}"
            model = self.models / (identity + ".mph")
            model.write_bytes(f"synthetic byte fixture {index}, not a COMSOL model".encode())
            self.manifest["cases"].append({"case_id": identity, "model_path": model.name,
                "sha256": dataset.sha256(model), "expected_codes": [sorted(CORE_CODES)[index]] if index < 5 else [],
                "reviewed_by": "synthetic test reviewer", "reviewed_date": "2000-01-01",
                "used_for_rule_development": False, "created_by": "synthetic test author",
                "origin_reference": "synthetic unit-test bytes, not independent physical data",
                "independence_group": f"synthetic-group-{index % 2}"})
        self.save_manifest()

    def save_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def freeze(self):
        return dataset.freeze_dataset(self.manifest_path, model_root=self.models, output_dir=self.output)

    def validate(self):
        return dataset.validate_acceptance(self.manifest, dataset.fingerprints()[1], today=date(2026, 10, 13))

    def frozen_json(self, name, mutate):
        path = self.output / name
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        path.write_text(json.dumps(value), encoding="utf-8")

    def suite(self, manifest_path, **options):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(options["model_root"], self.output)
        options["output_dir"].mkdir(parents=True)
        outcomes = {c["case_id"]: {"status": "checked", "predicted_codes": c["expected_codes"]}
                    for c in manifest["cases"]}
        return self.save_suite(manifest_path, options, evaluate_dataset(manifest, outcomes))

    def save_suite(self, manifest_path, options, summary):
        mode = "check" if options.get("reports_root") is None else "evaluate"
        provenance = {"manifest_sha256": dataset.sha256(manifest_path), "mode": mode,
                      "rule_engine_sha256": engine_fingerprint(),
                      "inventory_source_sha256": dataset.sha256(ROOT / "src/comsol/ModelInventory.java")}
        summary.update(**provenance, reynolds_warning=2000.)
        dataset._write_json(options["output_dir"] / "summary.json", summary)
        dataset._write_json(options["output_dir"] / "run.json", {"schema_version": "check-suite-run-0.1",
            "status": "completed" if summary["checked_cases"] == summary["total_cases"] else "incomplete",
            "checked_cases": summary["checked_cases"], "attempted_cases": summary["total_cases"],
            "settings": {"reynolds_warning": 2000.}, **provenance})
        return summary

    def test_freeze_snapshot_then_verify_without_comsol_or_mutating_input(self):
        before = self.manifest_path.read_bytes()
        source_hashes = {p.name: dataset.sha256(p) for p in self.models.iterdir()}
        metadata = self.freeze()
        loaded = dataset.verify_dataset(self.output)
        self.assertEqual(metadata, loaded["metadata"])
        self.assertEqual(metadata["case_count"], 10)
        self.assertEqual(metadata["source_manifest_sha256"], hashlib.sha256(before).hexdigest())
        self.assertFalse(metadata["software_authenticates_reviewers"])
        self.assertEqual(self.manifest_path.read_bytes(), before)
        self.assertEqual({p.name: dataset.sha256(p) for p in self.models.iterdir()}, source_hashes)
        self.assertEqual(loaded["freeze_sha256"], dataset.sha256(self.output / "freeze.json"))
        self.assertTrue(all(c["model_path"].startswith("models/") for c in loaded["manifest"]["cases"]))

    def test_missing_review_or_declaration_never_creates_output(self):
        mutations = [lambda m: m.pop("acceptance_declaration"),
                     lambda m: m.update(label_status="pending"),
                     lambda m: m["cases"][0].pop("reviewed_by"),
                     lambda m: m["cases"][0].update(used_for_rule_development=True),
                     lambda m: m["cases"][0].pop("created_by"),
                     lambda m: m["cases"][0].pop("origin_reference"),
                     lambda m: m["cases"][0].pop("independence_group")]
        before = copy.deepcopy(self.manifest)
        for mutate in mutations:
            self.manifest = copy.deepcopy(before)
            mutate(self.manifest)
            self.save_manifest()
            with self.assertRaises(ValueError):
                self.freeze()
            self.assertFalse(self.output.exists())

    def test_boolean_declarations_must_be_true_not_truthy(self):
        for field in dataset.DECLARATIONS:
            for value in (False, 1, "true", None):
                self.manifest["acceptance_declaration"][field] = value
                with self.assertRaises(ValueError):
                    self.validate()
            self.manifest["acceptance_declaration"][field] = True

    def test_minimum_size_rule_coverage_and_negative_control(self):
        for change in (lambda m: m.update(cases=m["cases"][:6]),
                       lambda m: m["cases"][0].update(expected_codes=[]),
                       lambda m: [c.update(expected_codes=c["expected_codes"] or ["MISSING_INLET"]) for c in m["cases"]]):
            original = copy.deepcopy(self.manifest)
            change(self.manifest)
            with self.assertRaises(ValueError):
                self.validate()
            self.manifest = original

    def test_review_dates_cannot_be_future_or_noncanonical(self):
        for value in ("2099-01-01", "2026-10-14", "20261001", "invalid", True, None):
            self.manifest["cases"][0]["reviewed_date"] = value
            with self.assertRaises(ValueError):
                self.validate()
        self.manifest["cases"][0]["reviewed_date"] = "2000-01-01"
        self.manifest["acceptance_declaration"]["independence_reviewed_date"] = "2099-01-01"
        with self.assertRaises(ValueError):
            self.validate()

    def test_known_original_and_variation_hashes_cannot_be_relabelled(self):
        original = json.loads((ROOT / dataset.REGISTRIES[0]).read_text(encoding="utf-8"))
        variants = json.loads((ROOT / dataset.REGISTRIES[1]).read_text(encoding="utf-8"))
        hashes = [c["sha256"] for c in original["cases"]] + [c["source_sha256"] for c in variants["cases"]]
        self.assertEqual(len(set(h.lower() for h in hashes)), 20)
        for digest in hashes:
            self.manifest["cases"][0]["sha256"] = digest
            with self.assertRaises(ValueError):
                self.validate()

    def test_ai_training_and_rejected_generated_models_are_not_independent(self):
        registry = json.loads((ROOT / dataset.REGISTRIES[2]).read_text(encoding="utf-8"))
        for case in registry["cases"]:
            self.manifest["cases"][0]["sha256"] = case["source_sha256"]
            with self.subTest(case=case["case_id"]), self.assertRaises(ValueError):
                self.validate()

    def test_single_source_group_and_unavailable_evaluation_not_formal_cases(self):
        original = copy.deepcopy(self.manifest)
        for case in self.manifest["cases"]:
            case["independence_group"] = "same-group"
        with self.assertRaises(ValueError):
            self.validate()
        self.manifest = original
        self.manifest["cases"][9]["expected_codes"] = ["EVALUATION_UNAVAILABLE"]
        with self.assertRaises(ValueError):
            self.validate()

    def test_case_insensitive_ids_and_paths_are_unique(self):
        self.manifest["cases"][1]["case_id"] = self.manifest["cases"][0]["case_id"].upper()
        with self.assertRaises(ValueError):
            self.validate()
        self.manifest["cases"][1]["case_id"] = "case-001"
        self.manifest["cases"][1]["model_path"] = self.manifest["cases"][0]["model_path"].upper()
        with self.assertRaises(ValueError):
            self.validate()

    def test_traversal_absolute_and_alternate_stream_paths_rejected(self):
        for value in ("../escape.mph", "C:\\escape.mph", "C:relative.mph", "/escape.mph", "x.mph:stream", "x\x00.mph"):
            self.manifest["cases"][0]["model_path"] = value
            with self.assertRaises((ValueError, OSError)):
                self.validate()

    def test_duplicate_json_and_oversized_manifest_rejected(self):
        for payload in (b'{"cases":[],"cases":[]}', b" " * (65536 + 1), b'{"bad":NaN}'):
            self.manifest_path.write_bytes(payload)
            with self.assertRaises(ValueError):
                self.freeze()
        self.assertFalse(self.output.exists())

    def test_lfs_pointer_empty_missing_and_hash_mismatch_block_before_copy(self):
        model = self.models / self.manifest["cases"][0]["model_path"]
        for payload in (dataset.LFS_HEADER + b"\noid sha256:abc\n", b"", b"user modified bytes"):
            model.write_bytes(payload)
            with self.assertRaises(ValueError):
                self.freeze()
            self.assertFalse(self.output.exists())
        model.unlink()
        with self.assertRaises(OSError):
            self.freeze()

    def test_links_are_rejected_even_when_target_within_root(self):
        original = self.models / self.manifest["cases"][0]["model_path"]
        target = self.models / "actual.mph"
        original.rename(target)
        try:
            original.symlink_to(target)
        except OSError:
            self.skipTest("symlink permission unavailable")
        with self.assertRaises(ValueError):
            self.freeze()
        self.assertFalse(self.output.exists())

    def test_symlink_and_junction_guards_with_simulated_filesystem_flags(self):
        model = self.models / self.manifest["cases"][0]["model_path"]
        for method in ("is_symlink", "is_junction"):
            with patch.object(Path, method, autospec=True, side_effect=lambda p: p == model):
                with self.assertRaisesRegex(ValueError, "链接或目录联接"):
                    self.freeze()
            self.assertFalse(self.output.exists())

    def test_existing_output_and_output_under_inputs_refused(self):
        self.output.mkdir()
        with self.assertRaises(FileExistsError):
            self.freeze()
        self.assertEqual(list(self.output.iterdir()), [])
        with self.assertRaises(ValueError):
            dataset.freeze_dataset(self.manifest_path, model_root=self.models, output_dir=self.models / "new")

    def test_partial_copy_has_no_completion_marker_and_inputs_preserved(self):
        real_open = Path.open
        def fail(path, *args, **kwargs):
            if path == self.output / "models/case-003.mph" and args == ("xb",):
                raise OSError("synthetic storage error")
            return real_open(path, *args, **kwargs)
        with patch.object(Path, "open", fail), self.assertRaises(OSError):
            self.freeze()
        self.assertFalse((self.output / "freeze.json").exists())
        self.assertEqual(len(list(self.models.glob("*.mph"))), 10)
        with self.assertRaises((OSError, ValueError)):
            dataset.verify_dataset(self.output)

    def test_manifest_changed_mid_freeze_cannot_publish_marker(self):
        real_write = dataset._write_json
        def write(path, value):
            real_write(path, value)
            if path.name == "manifest.json":
                self.manifest_path.write_text("{}", encoding="utf-8")
        with patch.object(dataset, "_write_json", side_effect=write), self.assertRaises(ValueError):
            self.freeze()
        self.assertFalse((self.output / "freeze.json").exists())

    def test_original_model_changed_mid_freeze_cannot_publish_marker(self):
        real_write = dataset._write_json
        def write(path, value):
            real_write(path, value)
            if path.name == "manifest.json":
                (self.models / "case-000.mph").write_bytes(b"synthetic concurrent modification")
        with patch.object(dataset, "_write_json", side_effect=write), self.assertRaises(ValueError):
            self.freeze()
        self.assertFalse((self.output / "freeze.json").exists())

    def test_source_changed_mid_freeze_cannot_publish_marker(self):
        real_fingerprints = dataset.fingerprints
        hashes, known = real_fingerprints()
        changed = dict(hashes, **{dataset.SOURCES[0]: "0" * 64})
        with patch.object(dataset, "fingerprints", side_effect=[(hashes, known), (changed, known)]), self.assertRaises(ValueError):
            self.freeze()
        self.assertFalse((self.output / "freeze.json").exists())

    def test_changed_model_label_and_source_version_rejected_by_verify(self):
        self.freeze()
        model = self.output / "models/case-000.mph"
        original = model.read_bytes()
        model.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            dataset.verify_dataset(self.output)
        model.write_bytes(original)
        manifest = self.output / "manifest.json"
        original = manifest.read_bytes()
        manifest.write_bytes(original + b" ")
        with self.assertRaises(ValueError):
            dataset.verify_dataset(self.output)
        manifest.write_bytes(original)
        hashes, known = dataset.fingerprints()
        hashes[dataset.SOURCES[0]] = "0" * 64
        with patch.object(dataset, "fingerprints", return_value=(hashes, known)), self.assertRaises(ValueError):
            dataset.verify_dataset(self.output)

    def test_extra_missing_and_linked_dataset_files_rejected(self):
        self.freeze()
        extra = self.output / "unreviewed.json"
        extra.touch()
        with self.assertRaises(ValueError):
            dataset.verify_dataset(self.output)
        extra.unlink()
        extra = self.output / "models/extra.mph"
        extra.touch()
        with self.assertRaises(ValueError):
            dataset.verify_dataset(self.output)
        extra.unlink()
        (self.output / "models/case-000.mph").unlink()
        with self.assertRaises(ValueError):
            dataset.verify_dataset(self.output)

    def test_freeze_metadata_missing_provenance_or_invalid_time_rejected(self):
        self.freeze()
        path = self.output / "freeze.json"
        before = path.read_bytes()
        for change in (lambda m: m.pop("source_manifest_sha256"), lambda m: m.pop("frozen_at"),
                       lambda m: m.update(frozen_at="2026-10-13"), lambda m: m.update(status="running"),
                       lambda m: m.update(software_authenticates_reviewers=True)):
            self.frozen_json("freeze.json", change)
            with self.assertRaises(ValueError):
                dataset.verify_dataset(self.output)
            path.write_bytes(before)

    def test_run_uses_frozen_manifest_records_identity_and_offline_mode(self):
        self.freeze()
        output = self.root / "run"
        with patch.object(dataset, "run_suite", side_effect=self.suite) as run:
            result = dataset.run_frozen(self.output, output_dir=output, reports_root=self.root / "reports")
        self.assertEqual(run.call_args.kwargs["reports_root"], self.root / "reports")
        self.assertTrue(result["evaluation"]["meets_recall_above_90_percent"])
        self.assertFalse(result["software_authenticates_reviewers"])
        self.assertEqual(result["freeze_sha256"], dataset.sha256(self.output / "freeze.json"))
        self.assertEqual(json.loads((output / "run.json").read_text(encoding="utf-8"))["status"], "completed")

    def test_saved_suite_differs_from_returned_summary_is_not_published(self):
        self.freeze()
        output = self.root / "run"
        def run(*args, **kwargs):
            summary = self.suite(*args, **kwargs)
            path = kwargs["output_dir"] / "summary.json"
            changed = json.loads(path.read_text(encoding="utf-8"))
            changed["exact_match_cases"] = 9
            path.write_text(json.dumps(changed), encoding="utf-8")
            return summary
        with patch.object(dataset, "run_suite", side_effect=run), self.assertRaisesRegex(ValueError, "保存汇总不一致"):
            dataset.run_frozen(self.output, output_dir=output, reports_root=self.reports_root)
        self.assertFalse((output / "result.json").exists())

    def test_inconsistent_suite_terminal_record_is_not_published(self):
        self.freeze()
        output = self.root / "run"
        def run(*args, **kwargs):
            summary = self.suite(*args, **kwargs)
            path = kwargs["output_dir"] / "run.json"
            changed = json.loads(path.read_text(encoding="utf-8"))
            changed["attempted_cases"] = 9
            path.write_text(json.dumps(changed), encoding="utf-8")
            return summary
        with patch.object(dataset, "run_suite", side_effect=run), self.assertRaisesRegex(ValueError, "完成记录"):
            dataset.run_frozen(self.output, output_dir=output, reports_root=self.reports_root)
        self.assertFalse((output / "result.json").exists())

    def test_result_changed_while_publishing_is_not_recorded_completed(self):
        self.freeze()
        output = self.root / "run"
        original = dataset._write_json
        def change(path, value):
            original(path, value)
            if path == output / "result.json":
                changed = json.loads(path.read_text(encoding="utf-8"))
                changed["dataset_id"] = "synthetic concurrent corruption"
                path.write_text(json.dumps(changed), encoding="utf-8")
        with patch.object(dataset, "run_suite", side_effect=self.suite), patch.object(dataset, "_write_json", side_effect=change):
            with self.assertRaisesRegex(ValueError, "发布时变化"):
                dataset.run_frozen(self.output, output_dir=output, reports_root=self.reports_root)
        self.assertEqual(json.loads((output / "run.json").read_text(encoding="utf-8"))["status"], "failed")

    def test_run_detects_during_evaluation_mutation_and_publishes_no_result(self):
        self.freeze()
        output = self.root / "run"
        def run(*args, **kwargs):
            summary = self.suite(*args, **kwargs)
            (self.output / "models/case-000.mph").write_bytes(b"synthetic concurrent change")
            return summary
        with patch.object(dataset, "run_suite", side_effect=run), self.assertRaises(ValueError):
            dataset.run_frozen(self.output, output_dir=output, reports_root=self.reports_root)
        self.assertFalse((output / "result.json").exists())
        self.assertEqual(json.loads((output / "run.json").read_text(encoding="utf-8"))["status"], "failed")

    def test_freeze_marker_byte_change_during_run_invalidates_result(self):
        self.freeze()
        output = self.root / "run"
        def run(*args, **kwargs):
            summary = self.suite(*args, **kwargs)
            path = self.output / "freeze.json"
            path.write_bytes(path.read_bytes() + b" ")
            return summary
        with patch.object(dataset, "run_suite", side_effect=run), self.assertRaisesRegex(ValueError, "冻结集在评估期间"):
            dataset.run_frozen(self.output, output_dir=output, reports_root=self.reports_root)
        self.assertFalse((output / "result.json").exists())

    def test_run_interrupted_or_failed_is_recorded_not_success(self):
        self.freeze()
        for label, error in (("cancelled", KeyboardInterrupt()), ("failed", OSError("synthetic process failure"))):
            output = self.root / label
            with patch.object(dataset, "run_suite", side_effect=error), self.assertRaises(type(error)):
                dataset.run_frozen(self.output, output_dir=output, comsol_root=self.root)
            self.assertEqual(json.loads((output / "run.json").read_text(encoding="utf-8"))["status"], label)
            self.assertFalse((output / "result.json").exists())

    def test_run_partial_retains_all_cases_and_incomplete_status(self):
        self.freeze()
        def run(manifest_path, **kwargs):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            kwargs["output_dir"].mkdir(parents=True)
            outcomes = {c["case_id"]: {"status": "checked", "predicted_codes": c["expected_codes"]}
                        for c in manifest["cases"]}
            outcomes[manifest["cases"][0]["case_id"]] = {"status": "partial"}
            return self.save_suite(manifest_path, kwargs, evaluate_dataset(manifest, outcomes))
        output = self.root / "run"
        with patch.object(dataset, "run_suite", side_effect=run):
            result = dataset.run_frozen(self.output, output_dir=output, comsol_root=self.root)
        self.assertEqual(result["evaluation"]["total_cases"], 10)
        self.assertIsNone(result["evaluation"]["meets_recall_above_90_percent"])
        self.assertEqual(json.loads((output / "run.json").read_text(encoding="utf-8"))["status"], "incomplete")

    def test_run_invalid_settings_or_changed_freeze_never_starts_backend(self):
        self.freeze()
        output = self.root / "run"
        with patch.object(dataset, "run_suite") as run:
            for settings in ({"loads": True}, {"timeout": float("nan")}, {"timeout": 0}, {"loads": 11}):
                with self.assertRaises(ValueError):
                    dataset.run_frozen(self.output, output_dir=output, comsol_root=self.root, **settings)
            self.frozen_json("freeze.json", lambda m: m.update(status="failed"))
            with self.assertRaises(ValueError):
                dataset.run_frozen(self.output, output_dir=output, comsol_root=self.root)
        run.assert_not_called()
        self.assertFalse(output.exists())

    def test_cli_freeze_verify_and_existing_development_set_refused(self):
        command = [sys.executable, "-X", "utf8", str(ROOT / "src/flowpilot/acceptance_dataset.py")]
        result = subprocess.run(command + ["freeze", "--manifest", str(self.manifest_path),
            "--model-root", str(self.models), "--output-dir", str(self.output)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        result = subprocess.run(command + ["verify", str(self.output)], capture_output=True)
        self.assertEqual(result.returncode, 0)
        missing_reports = self.root / "empty-reports"
        missing_reports.mkdir()
        result = subprocess.run(command + ["run", str(self.output), "--reports-root", str(missing_reports),
                                "--output-dir", str(self.root / "offline-missing")], capture_output=True)
        self.assertEqual(result.returncode, 2)
        formal = json.loads((self.root / "offline-missing/result.json").read_text(encoding="utf-8"))
        self.assertEqual(formal["evaluation"]["total_cases"], 10)
        self.assertEqual(formal["evaluation"]["checked_cases"], 0)
        self.assertFalse(formal["evaluation"]["acceptance_eligible"])
        result = subprocess.run(command + ["freeze", "--manifest", str(ROOT / dataset.REGISTRIES[0]),
            "--model-root", str(ROOT), "--output-dir", str(self.root / "invalid")], capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.root / "invalid").exists())

    def test_cli_run_success_and_recall_failure_with_synthetic_reports(self):
        self.freeze()
        reports = self.root / "synthetic-reports"
        for case in self.manifest["cases"]:
            child = reports / case["case_id"]
            child.mkdir(parents=True)
            report = {"schema_version": "diagnosis-0.1", "status": "checked", "findings": [
                {"code": code, "severity": "Warning", "explanation": "synthetic test finding",
                 "feature_tags": [], "boundary_ids": [], "evidence": {}} for code in case["expected_codes"]]}
            dataset._write_json(child / "diagnosis.json", report)
            metadata = {"schema_version": "check-run-0.1", "status": "completed", "diagnosis_status": "checked",
                        "source": {"filename": case["case_id"] + ".mph", "sha256": case["sha256"]},
                        "settings": {"reynolds_warning": 2000.},
                        "rule_engine_sha256": dataset.sha256(ROOT / "src/flowpilot/diagnostics.py"),
                        "inventory_source_sha256": dataset.sha256(ROOT / "src/comsol/ModelInventory.java"),
                        "diagnosis_sha256": dataset.sha256(child / "diagnosis.json")}
            dataset._write_json(child / "run.json", metadata)
        command = [sys.executable, "-X", "utf8", str(ROOT / "src/flowpilot/acceptance_dataset.py"),
                   "run", str(self.output), "--reports-root", str(reports), "--output-dir"]
        result = subprocess.run(command + [str(self.root / "success")], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        child = reports / "case-000"
        report = json.loads((child / "diagnosis.json").read_text(encoding="utf-8"))
        report["findings"] = []
        (child / "diagnosis.json").write_text(json.dumps(report), encoding="utf-8")
        metadata = json.loads((child / "run.json").read_text(encoding="utf-8"))
        metadata["diagnosis_sha256"] = dataset.sha256(child / "diagnosis.json")
        (child / "run.json").write_text(json.dumps(metadata), encoding="utf-8")
        result = subprocess.run(command + [str(self.root / "recall-missed")], capture_output=True)
        self.assertEqual(result.returncode, 3)
        result_json = json.loads((self.root / "recall-missed/result.json").read_text(encoding="utf-8"))
        self.assertEqual(result_json["evaluation"]["metrics_on_checked_cases_only"]["recall"], .8)
        self.assertFalse(result_json["evaluation"]["meets_recall_above_90_percent"])


if __name__ == "__main__":
    unittest.main()
