"""Local transfer tests use synthetic MPH/diagnoses; not actual independent acceptance."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_acceptance_result as fixtures

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot import acceptance_bundle as bundle, report_package


class AcceptanceBundleTest(unittest.TestCase):
    save_manifest = fixtures.AcceptanceResultTest.save_manifest
    run_pipeline = fixtures.AcceptanceResultTest.run_pipeline
    mutate = fixtures.AcceptanceResultTest.mutate

    def setUp(self):
        fixtures.AcceptanceResultTest.setUp(self)
        self.packet = self.root / "bundle"

    def export(self, mode="check", *, failed=False):
        if not self.run.exists():
            self.run_pipeline(mode, failed=failed)
        return bundle.export_bundle(self.run, dataset_dir=self.output, output_dir=self.packet,
            reports_root=self.reports if mode == "evaluate" else None, include_models=True)

    def rebind(self, key):
        value = bundle._digest(self.packet / key, bundle._limit(key))
        self.mutate(self.packet / "bundle.json", lambda m: m["files"].update({key: value}))

    def test_confirmation_is_explicit_and_before_any_read_or_copy(self):
        for value in (False, None, 1, "true"):
            with patch.object(bundle, "load_acceptance_result") as read, self.assertRaises(ValueError):
                bundle.export_bundle(self.run, dataset_dir=self.output, output_dir=self.packet, include_models=value)
            read.assert_not_called()
        self.assertFalse(self.packet.exists())

    def test_online_bundle_contains_models_but_no_check_snapshots_logs_or_requests(self):
        self.run_pipeline()
        child = self.run / "checks/case-000"
        for name in ("input.mph", "request.json", "launcher.log", "inventory.json", "license.txt"):
            (child / name).write_text("synthetic private data that must not be copied", encoding="utf-8")
        value = self.export()
        self.assertEqual(value["review"]["status"], "verified_complete")
        files = value["metadata"]["files"]
        self.assertEqual(sum(key.endswith(".mph") for key in files), 10)
        self.assertTrue(all(key.startswith("dataset/models/") for key in files if key.endswith(".mph")))
        self.assertFalse(any(key.endswith(("input.mph", "launcher.log", "request.json", "inventory.json", "license.txt")) for key in files))
        self.assertTrue(value["metadata"]["includes_models"])
        self.assertFalse(value["review"]["software_authenticates_reviewers"])

    def test_received_bundle_is_self_contained_after_originals_are_unavailable(self):
        self.export()
        received = self.root / "received with spaces"
        shutil.copytree(self.packet, received)
        # Rename only this test's known temporary source directories, never repository models.
        self.output.rename(self.root / "original-frozen-hidden")
        self.run.rename(self.root / "original-run-hidden")
        self.reports.rename(self.root / "original-reports-hidden")
        value = bundle.verify_bundle(received)
        self.assertEqual(value["review"]["status"], "verified_complete")
        self.assertEqual(value["review"]["summary"]["checked_cases"], 10)

    def test_offline_bundle_has_its_own_report_root_and_recomputes(self):
        value = self.export("evaluate")
        self.assertEqual(value["metadata"]["mode"], "evaluate")
        self.assertTrue((self.packet / "reports/case-000/diagnosis.json").is_file())
        self.assertFalse((self.packet / "run/checks/case-000").exists())
        self.output.rename(self.root / "offline-frozen-hidden")
        self.run.rename(self.root / "offline-run-hidden")
        self.reports.rename(self.root / "offline-reports-hidden")
        self.assertEqual(bundle.verify_bundle(self.packet)["review"]["status"], "verified_complete")

    def test_failed_case_does_not_become_complete_through_transfer(self):
        value = self.export(failed=True)
        self.assertEqual(value["review"]["status"], "verified_incomplete")
        self.assertEqual(value["review"]["unverifiable_failure_case_ids"], ["case-000"])
        self.assertIsNone(value["review"]["summary"]["meets_recall_above_90_percent"])
        self.assertFalse((self.packet / "run/checks/case-000").exists())

    def test_partial_diagnosis_and_missing_offline_diagnosis_remain_incomplete(self):
        child = self.reports / "case-000"
        self.mutate(child / "diagnosis.json", lambda r: r.update(status="partial", findings=[{
            "code": "EVALUATION_UNAVAILABLE", "severity": "Warning", "explanation": "synthetic unavailable",
            "feature_tags": [], "boundary_ids": [], "evidence": {}}]))
        self.mutate(child / "run.json", lambda r: r.update(diagnosis_status="partial",
            diagnosis_sha256=hashlib.sha256((child / "diagnosis.json").read_bytes()).hexdigest()))
        self.assertEqual(self.export()["review"]["status"], "verified_incomplete")
        self.run = self.root / "missing-diagnosis-run"
        self.packet = self.root / "missing-diagnosis-bundle"
        (child / "diagnosis.json").unlink()
        value = self.export("evaluate")
        self.assertEqual(value["review"]["summary"]["cases"][0]["status"], "unscored")
        self.assertTrue((self.packet / "reports/case-000/run.json").exists())
        self.assertFalse((self.packet / "reports/case-000/diagnosis.json").exists())

    def test_original_report_capsule_is_preserved_not_flattened(self):
        child = self.reports / "case-000"
        capsule = report_package.export_package(child, self.root / "original-capsule")
        child.rename(self.root / "pre-capsule-report")
        shutil.copytree(capsule, child)
        value = self.export()
        copied = self.packet / "run/checks/case-000"
        self.assertEqual({p.name for p in copied.iterdir()}, bundle.CAPSULE_FILES)
        key = "run/checks/case-000/report.md"
        (self.packet / key).write_bytes((self.packet / key).read_bytes() + b"changed")
        self.rebind(key)  # Outer manifest cannot bypass the original capsule's inner integrity.
        with self.assertRaises(ValueError):
            bundle.verify_bundle(self.packet)
        self.assertEqual(value["review"]["status"], "verified_complete")

    def test_corrupt_model_or_report_rejected_by_file_integrity(self):
        self.export()
        for key in ("dataset/models/case-000.mph", "run/checks/case-000/diagnosis.json", "run/result.json", "report.md"):
            path = self.packet / key
            before = path.read_bytes()
            path.write_bytes(before + b" ")
            with self.subTest(key=key), self.assertRaises(ValueError):
                bundle.verify_bundle(self.packet)
            path.write_bytes(before)

    def test_rebound_model_and_human_summary_still_require_semantic_verification(self):
        self.export()
        key = "dataset/models/case-000.mph"
        path = self.packet / key
        before = path.read_bytes()
        manifest_before = (self.packet / "bundle.json").read_bytes()
        path.write_bytes(before + b"changed")
        self.rebind(key)
        with self.assertRaises(ValueError):
            bundle.verify_bundle(self.packet)
        path.write_bytes(before)
        (self.packet / "bundle.json").write_bytes(manifest_before)
        (self.packet / "report.md").write_text("synthetic forged pass claim", encoding="utf-8")
        self.rebind("report.md")
        with self.assertRaisesRegex(ValueError, "证据重算不符"):
            bundle.verify_bundle(self.packet)

    def test_extra_files_empty_directories_and_missing_files_rejected(self):
        self.export()
        extra = self.packet / "private.log"
        extra.touch()
        with self.assertRaises(ValueError):
            bundle.verify_bundle(self.packet)
        extra.unlink()
        extra = self.packet / "extra-empty"
        extra.mkdir()
        with self.assertRaises(ValueError):
            bundle.verify_bundle(self.packet)
        extra.rmdir()
        (self.packet / "README.md").unlink()
        with self.assertRaises(ValueError):
            bundle.verify_bundle(self.packet)

    def test_unsafe_or_wrong_mode_file_keys_rejected(self):
        self.export()
        path = self.packet / "bundle.json"
        before = path.read_bytes()
        for key in ("../escape", "C:/escape.mph", "/escape.mph", "dataset\\manifest.json", "dataset//manifest.json",
                    "reports/case-000/run.json"):
            self.mutate(path, lambda m: m["files"].update({key: {"bytes": 0, "sha256": "0" * 64}}))
            with self.assertRaises(ValueError):
                bundle.verify_bundle(self.packet)
            path.write_bytes(before)

    def test_invalid_state_tool_version_boolean_size_or_count_rejected(self):
        self.export()
        path = self.packet / "bundle.json"
        before = path.read_bytes()
        changes = (lambda m: m.update(status="running"), lambda m: m.update(includes_models=1),
                   lambda m: m.update(bundle_tool_sha256="0" * 64),
                   lambda m: m["files"]["README.md"].update(bytes=True),
                   lambda m: m.update(source_run_sha256="0" * 64))
        for change in changes:
            self.mutate(path, change)
            with self.assertRaises(ValueError):
                bundle.verify_bundle(self.packet)
            path.write_bytes(before)

    def test_size_limits_are_enforced_before_output_creation(self):
        self.run_pipeline()
        with patch.object(bundle, "MAX_MODEL_BYTES", 2), self.assertRaises(ValueError):
            self.export()
        self.assertFalse(self.packet.exists())
        with patch.object(bundle, "MAX_TOTAL_BYTES", 1), self.assertRaises(ValueError):
            self.export()
        self.assertFalse(self.packet.exists())
        with patch.object(bundle, "MAX_FILES", 1), self.assertRaises(ValueError):
            self.export()
        self.assertFalse(self.packet.exists())

    def test_existing_output_or_nested_source_output_not_reused(self):
        self.run_pipeline()
        self.packet.mkdir()
        with self.assertRaises(FileExistsError):
            self.export()
        self.assertEqual(list(self.packet.iterdir()), [])
        for path in (self.output / "new", self.run / "new"):
            with self.assertRaises(ValueError):
                bundle.export_bundle(self.run, dataset_dir=self.output, output_dir=path, include_models=True)
            self.assertFalse(path.exists())

    def test_partial_copy_or_completion_write_failure_has_no_valid_marker(self):
        self.run_pipeline()
        original_open = Path.open
        def fail(path, *args, **kwargs):
            if path == self.packet / "dataset/models/case-003.mph" and args == ("xb",):
                raise OSError("synthetic copy storage failure")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", fail), self.assertRaises(OSError):
            self.export()
        self.assertFalse((self.packet / "bundle.json").exists())
        self.packet = self.root / "marker-failed"
        original_write = bundle._write_json
        def fail_marker(path, value):
            if path == self.packet / "bundle.json":
                raise OSError("synthetic completion marker failure")
            return original_write(path, value)
        with patch.object(bundle, "_write_json", side_effect=fail_marker), self.assertRaises(OSError):
            self.export()
        with self.assertRaises((ValueError, OSError)):
            bundle.verify_bundle(self.packet)

    def test_source_changes_after_copy_are_not_published(self):
        self.run_pipeline()
        original_digest = bundle._digest
        def change(path, limit, *, target=None):
            value = original_digest(path, limit, target=target)
            if target is not None and path == self.output / "models/case-000.mph":
                path.write_bytes(b"synthetic concurrent modification of test input")
            return value
        with patch.object(bundle, "_digest", side_effect=change), self.assertRaises(ValueError):
            self.export()
        self.assertFalse((self.packet / "bundle.json").exists())

    def test_link_and_directory_budget_guards(self):
        self.export()
        target = self.packet / "dataset/models"
        with patch.object(Path, "is_junction", autospec=True, side_effect=lambda p: p == target), self.assertRaises(ValueError):
            bundle.verify_bundle(self.packet)
        with patch.object(bundle, "MAX_ENTRIES", 2), self.assertRaises(ValueError):
            bundle.verify_bundle(self.packet)
        with patch.object(bundle, "MAX_FILES", 2), self.assertRaises(ValueError):
            bundle.verify_bundle(self.packet)

    def test_json_bounds_and_duplicate_manifest_fields_rejected(self):
        self.export()
        path = self.packet / "bundle.json"
        for raw in (b" " * (bundle.MAX_MANIFEST_BYTES + 1), b'{"files":{},"files":{}}', b'{"bad":NaN}'):
            path.write_bytes(raw)
            with self.assertRaises(ValueError):
                bundle.verify_bundle(self.packet)

    def test_cli_confirmation_export_verify_and_incomplete_status(self):
        self.run_pipeline()
        command = [sys.executable, "-X", "utf8", str(ROOT / "src/flowpilot/acceptance_bundle.py")]
        export = command + ["export", str(self.run), "--dataset", str(self.output), "--output-dir", str(self.packet)]
        self.assertEqual(subprocess.run(export, capture_output=True).returncode, 1)
        result = subprocess.run(export + ["--include-models"], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(subprocess.run(command + ["verify", str(self.packet)], capture_output=True,
                                        cwd=self.root).returncode, 0)
        self.run = self.root / "failed-run"
        self.packet = self.root / "failed-packet"
        self.export(failed=True)
        self.assertEqual(subprocess.run(command + ["verify", str(self.packet)], capture_output=True).returncode, 2)


if __name__ == "__main__":
    unittest.main()
