"""Offline comparison tests. Synthetic checks are not independent acceptance models."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot import compare_reports as comparison
from flowpilot.desktop import DesktopApp
from flowpilot.diagnostics import check, normalize


class ComparisonTest(unittest.TestCase):
    def setUp(self):
        (ROOT / "outputs").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "outputs")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.report = check(normalize(json.loads((ROOT / "data/fixtures/cases/high_reynolds.json").read_text(encoding="utf-8-sig"))))
        self.before, self.after = self.directory / "前次报告", self.directory / "本次报告"

    def write_check(self, directory, *, report=None, metadata=None):
        directory.mkdir()
        value = copy.deepcopy(self.report if report is None else report)
        comparison._write_json(directory / "diagnosis.json", value)
        run = {"schema_version": "check-run-0.1", "status": "completed", "diagnosis_status": value["status"],
               "source": {"filename": "模型 with spaces.mph", "sha256": "1" * 64},
               "diagnosis_sha256": comparison.sha256(directory / "diagnosis.json"),
               "rule_engine_sha256": "a" * 64, "inventory_source_sha256": "b" * 64,
               "comsol_version": "COMSOL 6.3 test-only", "settings": {"reynolds_warning": 2000}}
        run.update(metadata or {})
        comparison._write_json(directory / "run.json", run)

    def compare(self, *, before_report=None, after_report=None, before_metadata=None, after_metadata=None):
        self.write_check(self.before, report=before_report, metadata=before_metadata)
        self.write_check(self.after, report=after_report, metadata=after_metadata)
        return comparison.compare_reports(self.before, self.after)

    def test_identical_reports_are_not_a_repair_or_physics_pass(self):
        result = self.compare()
        self.assertEqual(result["status"], "compared")
        self.assertEqual(result["counts"], {"added": 0, "removed": 0, "changed": 0, "unchanged": 1})
        self.assertTrue(result["same_model_sha256"])
        self.assertIn("不等于修复成功", result["disclaimer"])
        self.assertNotIn("repair_passed", result)
        self.assertTrue(comparison.render_comparison(result).startswith("# FlowPlot 检查报告对比"))

    def test_new_finding_is_added(self):
        empty = {**self.report, "findings": []}
        result = self.compare(before_report=empty)
        self.assertEqual(result["counts"]["added"], 1)
        self.assertEqual(result["rows"][0]["code"], "REYNOLDS_RISK")

    def test_absent_finding_is_not_reported_as_fixed(self):
        result = self.compare(after_report={**self.report, "findings": []})
        self.assertEqual(result["counts"]["removed"], 1)
        text = comparison.render_comparison(result)
        self.assertIn("本次未再报告", text)
        self.assertNotIn("已修复", text)

    def test_evidence_or_severity_change_is_detected(self):
        after = copy.deepcopy(self.report)
        after["findings"][0]["evidence"]["reynolds_height_based"] *= 2
        after["findings"][0]["severity"] = "Critical"
        result = self.compare(after_report=after)
        self.assertEqual(result["counts"]["changed"], 1)
        self.assertNotEqual(result["rows"][0]["before"], result["rows"][0]["after"])

    def test_same_rule_on_different_boundaries_is_not_collapsed(self):
        before = copy.deepcopy(self.report)
        additional = copy.deepcopy(before["findings"][0])
        additional["feature_tags"], additional["boundary_ids"] = ["inl2"], [4]
        before["findings"].append(additional)
        result = self.compare(before_report=before)
        self.assertEqual(result["counts"]["removed"], 1)
        self.assertEqual(result["counts"]["unchanged"], 1)

    def test_empty_reports_do_not_assert_models_unchanged(self):
        empty = {**self.report, "findings": []}
        result = self.compare(before_report=empty, after_report=empty,
                              after_metadata={"source": {"filename": "other.mph", "sha256": "2" * 64}})
        self.assertEqual(sum(result["counts"].values()), 0)
        self.assertFalse(result["same_model_sha256"])

    def test_unknown_source_fields_not_exported(self):
        result = self.compare(after_metadata={"source": {"filename": "after.mph", "sha256": "1" * 64,
                                                         "absolute_path": "private-local-path"}})
        self.assertNotIn("absolute_path", result["after"]["source"])

    def test_repeated_items_are_preserved_and_multiplicity_changes_count(self):
        after = copy.deepcopy(self.report)
        after["findings"] *= 2
        result = self.compare(after_report=after)
        self.assertEqual(result["counts"]["changed"], 1)
        self.assertEqual(len(result["rows"][0]["after"]), 2)

    def test_findings_and_tag_order_do_not_create_false_change(self):
        before = copy.deepcopy(self.report)
        before["findings"][0]["feature_tags"] = ["inl1", "inl2"]
        before["findings"][0]["boundary_ids"] = [1, 4]
        before["findings"].append({**before["findings"][0], "evidence": {"different": True}})
        after = copy.deepcopy(before)
        after["findings"].reverse()
        for item in after["findings"]:
            item["feature_tags"].reverse()
            item["boundary_ids"].reverse()
        result = self.compare(before_report=before, after_report=after)
        self.assertEqual(result["counts"]["unchanged"], 1)

    def test_changed_node_identity_is_not_assumed_to_be_same_entity(self):
        after = copy.deepcopy(self.report)
        after["findings"][0]["feature_tags"] = ["renamed_inlet"]
        result = self.compare(after_report=after)
        self.assertEqual(result["counts"]["added"], 1)
        self.assertEqual(result["counts"]["removed"], 1)
        self.assertIn("不验证几何实体对应关系", result["disclaimer"])

    def test_different_model_hashes_allow_comparison_with_warning(self):
        result = self.compare(after_metadata={"source": {"filename": "修改后.mph", "sha256": "2" * 64}})
        self.assertEqual(result["status"], "compared")
        self.assertFalse(result["same_model_sha256"])
        self.assertIn("请人工确认", comparison.render_comparison(result))

    def test_incomplete_reports_have_no_added_or_removed_conclusions(self):
        for status in ("partial", "unsupported"):
            with self.subTest(status=status):
                before = self.directory / status
                report = {"schema_version": "diagnosis-0.1", "status": status, "findings": [], "reason": "outside profile"}
                self.write_check(before, report=report)
                after = self.directory / (status + "-complete")
                self.write_check(after)
                result = comparison.compare_reports(before, after)
                self.assertEqual(result["status"], "not_comparable")
                self.assertIsNone(result["counts"])
                self.assertEqual(result["rows"], [])

    def test_missing_or_mismatched_provenance_blocks_comparison(self):
        cases = ({"rule_engine_sha256": None}, {"rule_engine_sha256": "c" * 64},
                 {"inventory_source_sha256": "wrong"}, {"inventory_source_sha256": "c" * 64},
                 {"comsol_version": None}, {"comsol_version": "another version"},
                 {"settings": {"reynolds_warning": 1000}}, {"settings": None},
                 {"settings": {"reynolds_warning": True}})
        self.write_check(self.before)
        for index, metadata in enumerate(cases):
            with self.subTest(metadata=metadata):
                after = self.directory / str(index)
                self.write_check(after, metadata=metadata)
                result = comparison.compare_reports(self.before, after)
                self.assertEqual(result["status"], "not_comparable")
                self.assertTrue(result["blocking_reasons"])
                self.assertIsNone(result["counts"])

    def test_profile_mismatch_blocks_comparison(self):
        result = self.compare(after_report={**self.report, "profile": "another-profile"})
        self.assertEqual(result["status"], "not_comparable")
        self.assertIn("两份报告的检查模板不同。", result["blocking_reasons"])

    def test_tampered_or_cancelled_reports_rejected(self):
        self.compare()
        (self.after / "diagnosis.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(comparison.CheckError):
            comparison.compare_reports(self.before, self.after)
        cancelled = self.directory / "cancelled"
        self.write_check(cancelled, metadata={"status": "cancelled"})
        with self.assertRaises(comparison.CheckError):
            comparison.compare_reports(self.before, cancelled)

    def test_export_is_new_only_and_inputs_unchanged(self):
        result = self.compare()
        hashes = {path: comparison.sha256(path) for path in self.directory.rglob("*.json")}
        output = self.directory / "comparison"
        comparison.write_comparison(result, output)
        original = (output / "comparison.json").read_bytes()
        with self.assertRaises(FileExistsError):
            comparison.write_comparison(result, output)
        self.assertEqual((output / "comparison.json").read_bytes(), original)
        self.assertTrue(all(comparison.sha256(path) == digest for path, digest in hashes.items()))
        self.assertNotIn(str(self.directory), (output / "report.md").read_text(encoding="utf-8"))
        self.assertEqual(result["before"]["run_sha256"], comparison.sha256(self.before / "run.json"))

    def test_filename_is_escaped_in_markdown(self):
        result = self.compare(after_metadata={"source": {"filename": "[link](bad)\n# header.mph", "sha256": "1" * 64}})
        text = comparison.render_comparison(result)
        self.assertNotIn("[link](bad)", text)
        self.assertNotIn("\n# header", text)

    def test_cli_completed_incompatible_and_invalid_exit_codes(self):
        self.compare()
        script = ROOT / "src/flowpilot/compare_reports.py"
        def run(before, after, output):
            return subprocess.run([sys.executable, "-X", "utf8", str(script), str(before), str(after),
                                   "--output-dir", str(output)], capture_output=True, encoding="utf-8")
        self.assertEqual(run(self.before, self.after, self.directory / "cli-ok").returncode, 0)
        other = self.directory / "other"
        self.write_check(other, metadata={"settings": {"reynolds_warning": 1}})
        self.assertEqual(run(self.before, other, self.directory / "cli-blocked").returncode, 2)
        invalid = run(self.before, self.directory / "missing", self.directory / "cli-invalid")
        self.assertEqual(invalid.returncode, 1)
        self.assertNotIn("Traceback", invalid.stderr)

    def test_gui_comparison_error_keeps_current_report(self):
        app = DesktopApp.__new__(DesktopApp)
        app.session, app.current_view, app.artifact_directory = Mock(busy=False), {"valid": True}, self.after
        app.dialogs, app.messages, app.root, app.show_comparison = Mock(), Mock(), Mock(), Mock()
        app.dialogs.askdirectory.return_value = str(self.before)
        with patch("flowpilot.desktop.compare_reports", side_effect=comparison.CheckError("tampered")):
            app.compare_report()
        app.messages.showerror.assert_called_once()
        app.show_comparison.assert_not_called()
        self.assertEqual(app.current_view, {"valid": True})

    def test_gui_cancel_dialog_or_busy_session_does_not_compare(self):
        app = DesktopApp.__new__(DesktopApp)
        app.session, app.current_view, app.artifact_directory = Mock(busy=True), {"valid": True}, self.after
        app.dialogs, app.root = Mock(), Mock()
        app.compare_report()
        app.dialogs.askdirectory.assert_not_called()
        app.session.busy = False
        app.dialogs.askdirectory.return_value = ""
        with patch("flowpilot.desktop.compare_reports") as compare:
            app.compare_report()
        compare.assert_not_called()

    def test_gui_export_write_failure_is_reported_without_opening_files(self):
        app = DesktopApp.__new__(DesktopApp)
        app.dialogs, app.messages = Mock(), Mock()
        app.dialogs.askdirectory.return_value = str(self.directory)
        with patch("flowpilot.desktop.write_comparison", side_effect=PermissionError("synthetic write denial")):
            app.export_comparison({}, Mock())
        app.messages.showerror.assert_called_once()
        app.messages.showinfo.assert_not_called()


if __name__ == "__main__":
    unittest.main()
