"""Strict report consumption tests; all edited records are synthetic local copies."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot import check_suite as suite
from flowpilot import compare_reports as comparison
from flowpilot import desktop_session as desktop
from flowpilot import package_integrity as integrity
from flowpilot import report_io
from flowpilot import report_package as package
from flowpilot.diagnostics import diagnose_inventory
from flowpilot.report_history import load_history_report


class ReportReaderTest(unittest.TestCase):
    def setUp(self):
        (ROOT / "outputs").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "outputs")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        self.report = diagnose_inventory(json.loads((ROOT / "data/fixtures/cases/high_reynolds.json").read_text(encoding="utf-8-sig")))
        manifest = json.loads(suite.DEVELOPMENT_MANIFEST.read_text(encoding="utf-8-sig"))
        self.case = next(item for item in manifest["cases"] if item["case_id"] == "high_reynolds")
        self.metadata = {"schema_version": "check-run-0.1", "status": "completed",
                         "source": {"filename": "synthetic-report.mph", "sha256": self.case["sha256"]},
                         "settings": {"reynolds_warning": 2000}, "comsol_version": "synthetic test-only",
                         "rule_engine_sha256": suite.sha256(suite.RULE_SOURCE),
                         "inventory_source_sha256": suite.sha256(suite.INVENTORY_SOURCE)}
        self.save()

    def save(self, payload=None):
        payload = payload or json.dumps(self.report, ensure_ascii=False).encode("utf-8")
        (self.source / "diagnosis.json").write_bytes(payload)
        self.metadata.update(diagnosis_status=self.report["status"], diagnosis_sha256=hashlib.sha256(payload).hexdigest())
        (self.source / "run.json").write_text(json.dumps(self.metadata), encoding="utf-8")

    def assert_rejected_everywhere(self):
        for reader in (lambda: desktop.load_completed_check(self.source),
                       lambda: comparison.compare_reports(self.source, self.source),
                       lambda: package.export_package(self.source, self.root / "exported"),
                       lambda: load_history_report(self.root, "source")):
            with self.assertRaises((ValueError, desktop.CheckError)):
                reader()
        self.assertEqual(suite.read_outcome(self.source, self.case, 2000)["status"], "unscored")
        self.assertFalse((self.root / "exported").exists())

    def test_complete_findings_remain_readable_and_scorable(self):
        loaded = desktop.load_completed_check(self.source)
        self.assertEqual(loaded["report"], self.report)
        self.assertEqual(suite.read_outcome(self.source, self.case, 2000)["status"], "checked")

    def test_code_only_finding_is_rejected_by_all_consumers(self):
        self.report["findings"] = [{"code": "REYNOLDS_RISK"}]
        self.save()
        self.assert_rejected_everywhere()

    def test_missing_required_finding_fields_are_not_scorable(self):
        original = copy.deepcopy(self.report["findings"][0])
        for key in ("severity", "explanation", "feature_tags", "boundary_ids", "evidence"):
            self.report["findings"] = [{field: value for field, value in original.items() if field != key}]
            self.save()
            self.assert_rejected_everywhere()

    def test_nonobject_evidence_is_rejected(self):
        for value in (None, [], "evidence", 1):
            self.report["findings"][0]["evidence"] = value
            self.save()
            self.assert_rejected_everywhere()

    def test_bad_code_or_severity_types_have_controlled_errors(self):
        for key in ("code", "severity"):
            original = self.report["findings"][0][key]
            for value in ([], {}, 1, None):
                self.report["findings"][0][key] = value
                self.save()
                self.assert_rejected_everywhere()
            self.report["findings"][0][key] = original

    def test_checked_with_unavailable_evaluation_is_rejected(self):
        self.report["findings"][0]["code"] = "EVALUATION_UNAVAILABLE"
        self.save()
        self.assert_rejected_everywhere()

    def test_partial_unavailable_remains_partial_not_unscored_or_clean(self):
        self.report["findings"][0]["code"] = "EVALUATION_UNAVAILABLE"
        self.report["status"] = "partial"
        self.save()
        loaded = desktop.load_completed_check(self.source)
        self.assertEqual(loaded["view"]["tone"], "incomplete")
        self.assertEqual(loaded["view"]["items"][0]["title"], "求值或数值检查未完成")
        self.assertEqual(suite.read_outcome(self.source, self.case, 2000)["status"], "partial")

    def test_direct_evaluator_rejects_checked_unavailable_outcomes(self):
        manifest = json.loads(suite.DEVELOPMENT_MANIFEST.read_text(encoding="utf-8-sig"))
        with self.assertRaises(ValueError):
            suite.evaluate_dataset(manifest, {"baseline": {"status": "checked", "predicted_codes": ["EVALUATION_UNAVAILABLE"]}})

    def test_batch_does_not_treat_boolean_threshold_as_one(self):
        self.metadata["settings"]["reynolds_warning"] = True
        self.save()
        self.assertEqual(suite.read_outcome(self.source, self.case, 1)["status"], "unscored")

    def test_duplicate_diagnosis_fields_are_rejected_even_with_matching_hash(self):
        payload = json.dumps(self.report).replace('"status": "checked"', '"status": "partial", "status": "checked"')
        self.save(payload.encode())
        self.assert_rejected_everywhere()

    def test_duplicate_run_fields_are_rejected(self):
        text = json.dumps(self.metadata).replace('"status": "completed"', '"status": "failed", "status": "completed"')
        (self.source / "run.json").write_text(text, encoding="utf-8")
        self.assert_rejected_everywhere()

    def test_nonfinite_evidence_is_rejected_for_all_json_forms(self):
        for value in ("NaN", "Infinity", "-Infinity", "1e400"):
            payload = json.dumps(self.report).replace('"reynolds_height_based": 5000.0', '"reynolds_height_based": ' + value)
            self.assertIn(value, payload)
            self.save(payload.encode())
            self.assert_rejected_everywhere()

    def test_deeply_nested_evidence_is_rejected_without_recursion_crash(self):
        for depth in (80, 2000):
            payload = json.dumps(self.report).replace('"reynolds_height_based": 5000.0',
                                                       '"reynolds_height_based": ' + '[' * depth + '0' + ']' * depth)
            self.save(payload.encode())
            self.assert_rejected_everywhere()

    def test_utf8_bom_is_supported_and_its_actual_bytes_are_hashed(self):
        self.save(b"\xef\xbb\xbf" + json.dumps(self.report).encode())
        loaded = desktop.load_completed_check(self.source)
        self.assertEqual(loaded["diagnosis_sha256"], suite.sha256(self.source / "diagnosis.json"))
        self.assertEqual(loaded["run_sha256"], suite.sha256(self.source / "run.json"))

    def test_oversized_diagnosis_is_rejected_before_decode(self):
        with patch.object(desktop, "MAX_DIAGNOSIS_BYTES", 10), patch.object(desktop, "decode_json") as decode:
            with self.assertRaises(ValueError):
                desktop.load_completed_check(self.source)
        decode.assert_not_called()

    def test_oversized_metadata_is_rejected_before_decode(self):
        with patch.object(desktop, "MAX_METADATA_BYTES", 10), patch.object(desktop, "decode_json") as decode:
            with self.assertRaises(ValueError):
                desktop.load_completed_check(self.source)
        decode.assert_not_called()

    def test_regular_report_files_reject_links(self):
        with patch.object(Path, "is_symlink", return_value=True), self.assertRaises(ValueError):
            report_io.read_regular_file(self.source / "run.json", max_bytes=65536)
        with patch.object(Path, "is_junction", return_value=True), self.assertRaises(ValueError):
            report_io.read_regular_file(self.source / "run.json", max_bytes=65536)

    def test_read_is_bounded_even_when_file_grows(self):
        with (self.source / "large.bin").open("wb") as stream:
            stream.write(b"x" * 100)
        with self.assertRaises(ValueError):
            report_io.read_regular_file(self.source / "large.bin", max_bytes=99)

    def test_same_read_bytes_drive_parse_and_hash_despite_later_disk_change(self):
        original = desktop.read_regular_file
        before = (self.source / "diagnosis.json").read_bytes()
        def read_and_change(path, **kwargs):
            payload = original(path, **kwargs)
            if Path(path).name == "diagnosis.json":
                Path(path).write_bytes(b"{}")
            return payload
        with patch.object(desktop, "read_regular_file", side_effect=read_and_change):
            loaded = desktop.load_completed_check(self.source)
        self.assertEqual(loaded["report"], self.report)
        self.assertEqual(loaded["diagnosis_sha256"], hashlib.sha256(before).hexdigest())
        with self.assertRaises(desktop.CheckError):
            desktop.load_completed_check(self.source)

    def test_package_verification_bytes_are_reused_not_reopened(self):
        exported = package.export_package(self.source, self.root / "package")
        original = integrity.read_package_file
        reads = []
        def read_and_change(path):
            payload = original(path)
            reads.append(Path(path).name)
            if Path(path).name == "diagnosis.json":
                Path(path).write_bytes(b"{}")
            return payload
        with patch.object(integrity, "read_package_file", side_effect=read_and_change), \
                patch.object(desktop, "read_regular_file", side_effect=AssertionError("unexpected reread")):
            loaded = desktop.load_completed_check(exported)
        self.assertEqual(loaded["report"], self.report)
        self.assertEqual(sorted(reads), sorted(integrity.PACKAGE_FILES))
        with self.assertRaises(ValueError):
            desktop.load_completed_check(exported)

    def test_batch_cannot_bypass_damaged_package_human_readable_file(self):
        exported = package.export_package(self.source, self.root / "package")
        self.assertEqual(suite.read_outcome(exported, self.case, 2000)["status"], "checked")
        (exported / "report.md").write_text("altered transfer", encoding="utf-8")
        self.assertEqual(suite.read_outcome(exported, self.case, 2000)["status"], "unscored")

    def test_provenance_uses_verified_snapshot_after_metadata_changes(self):
        loaded = desktop.load_completed_check(self.source)
        before_hash = loaded["run_sha256"]
        (self.source / "run.json").write_text("{}", encoding="utf-8")
        self.assertEqual(comparison._provenance(loaded)["run_sha256"], before_hash)

    def test_export_uses_verified_run_fingerprint_not_a_later_disk_read(self):
        loaded = desktop.load_completed_check(self.source)
        before_hash = loaded["run_sha256"]
        (self.source / "run.json").write_text("{}", encoding="utf-8")
        with patch.object(package, "load_completed_check", return_value=loaded):
            exported = package.export_package(self.source, self.root / "exported")
        self.assertEqual(integrity.verify_package(exported)["original_run_sha256"], before_hash)

    def test_legacy_report_without_optional_model_or_profile_is_readable(self):
        self.report.pop("model")
        self.report.pop("profile")
        self.save()
        self.assertEqual(desktop.load_completed_check(self.source)["report"], self.report)
        self.assertEqual(suite.read_outcome(self.source, self.case, 2000)["status"], "checked")

    def test_unsupported_report_with_findings_is_not_scored(self):
        self.report.update(status="unsupported", reason="synthetic outside scope")
        self.save()
        self.assert_rejected_everywhere()

    def test_session_finishes_failed_on_deep_final_metadata_instead_of_crashing(self):
        self.source.rename(self.root / "check")
        (self.root / "check/run.json").write_bytes(b"[" * 2000 + b"0" + b"]" * 2000)
        session = desktop.DesktopSession()
        session.directory, session.state = self.root, "running"
        session.process = Mock(returncode=0)
        session.process.poll.return_value = 0
        session._request = {"started_at": "synthetic", "model": "synthetic-report.mph"}
        self.assertEqual(session.poll(), "failed")
        self.assertFalse(session.busy)
        self.assertIsNone(session.result)
        self.assertEqual(session.poll(), "failed")
        self.assertEqual(json.loads((self.root / "ui-run.json").read_text(encoding="utf-8"))["status"], "failed")


if __name__ == "__main__":
    unittest.main()
