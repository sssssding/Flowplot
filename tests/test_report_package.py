"""Portable reports are integrity-checked copies, not signed physics acceptance."""
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
from flowpilot import report_package as package
from flowpilot import package_integrity as integrity
from flowpilot.check_model import CheckError, sha256
from flowpilot.compare_reports import compare_reports
from flowpilot.desktop import DesktopApp
from flowpilot.desktop_session import load_completed_check
from flowpilot.diagnostics import diagnose_inventory


class ReportPackageTest(unittest.TestCase):
    def setUp(self):
        (ROOT / "outputs").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "outputs")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "original"
        self.source.mkdir()
        self.output = self.root / "分享 with spaces"
        inventory = json.loads((ROOT / "data/fixtures/cases/missing_inlet.json").read_text(encoding="utf-8-sig"))
        self.report = diagnose_inventory(inventory)
        self.metadata = {"schema_version": "check-run-0.1", "status": "completed",
                         "source": {"filename": "中文模型.mph", "sha256": "1" * 64, "path": "PRIVATE_PATH"},
                         "diagnosis_status": self.report["status"], "comsol_version": "6.3.0.290",
                         "rule_engine_sha256": "2" * 64, "inventory_source_sha256": "3" * 64,
                         "verified_loads": 2, "settings": {"reynolds_warning": 2000, "private": "PRIVATE_PATH"},
                         "comsol_root": "PRIVATE_PATH", "command": ["PRIVATE_PATH"],
                         "environment": {"secret": "PRIVATE_PATH"}}
        self.save()
        for name in ("input.mph", "inventory.json", "launcher.log", "request.json", "report.md"):
            (self.source / name).write_text("PRIVATE_PATH untrusted original", encoding="utf-8")

    def save(self):
        (self.source / "diagnosis.json").write_text(json.dumps(self.report, ensure_ascii=False), encoding="utf-8")
        self.metadata["diagnosis_status"] = self.report["status"]
        self.metadata["diagnosis_sha256"] = sha256(self.source / "diagnosis.json")
        (self.source / "run.json").write_text(json.dumps(self.metadata), encoding="utf-8")

    def test_roundtrip_unicode_report_offline_and_preserves_evidence(self):
        directory = package.export_package(self.source, self.output)
        loaded = load_completed_check(directory)
        self.assertEqual(loaded["report"], self.report)
        self.assertEqual(loaded["metadata"]["source"]["filename"], "中文模型.mph")
        self.assertEqual(loaded["view"]["items"][0]["code"], "MISSING_INLET")
        self.assertIn("声明边界", (directory / "overview.txt").read_text(encoding="utf-8"))
        self.assertIn("不证明物理正确", (directory / "report.md").read_text(encoding="utf-8"))

    def test_fixed_allowlist_excludes_models_logs_paths_and_untrusted_markdown(self):
        package.export_package(self.source, self.output)
        self.assertEqual({path.name for path in self.output.iterdir()}, integrity.PACKAGE_FILES | {"package.json"})
        for path in self.output.iterdir():
            self.assertNotIn("PRIVATE_PATH", path.read_text(encoding="utf-8"))
        metadata = load_completed_check(self.output)["metadata"]
        self.assertEqual(set(metadata["source"]), {"filename", "sha256"})
        self.assertEqual(metadata["settings"], {"reynolds_warning": 2000})

    def test_source_bytes_are_unchanged(self):
        before = {path.name: sha256(path) for path in self.source.iterdir()}
        package.export_package(self.source, self.output)
        self.assertEqual(before, {path.name: sha256(path) for path in self.source.iterdir()})

    def test_exported_provenance_remains_comparable_to_original(self):
        package.export_package(self.source, self.output)
        summary = compare_reports(self.source, self.output)
        self.assertEqual(summary["status"], "compared")
        self.assertEqual(summary["counts"]["unchanged"], 1)

    def test_partial_report_stays_partial(self):
        self.report["status"] = "partial"
        self.save()
        package.export_package(self.source, self.output)
        self.assertEqual(load_completed_check(self.output)["report"]["status"], "partial")
        self.assertEqual(compare_reports(self.source, self.output)["status"], "not_comparable")

    def test_unsupported_stays_unsupported_without_invented_overview(self):
        self.report = {"schema_version": "diagnosis-0.1", "status": "unsupported", "reason": "3D", "findings": []}
        self.save()
        package.export_package(self.source, self.output)
        self.assertEqual(load_completed_check(self.output)["report"]["status"], "unsupported")
        self.assertIn("不可用", (self.output / "overview.txt").read_text(encoding="utf-8"))

    def test_old_minimal_report_does_not_invent_provenance(self):
        self.metadata = {key: self.metadata[key] for key in ("schema_version", "status", "source")}
        self.save()
        package.export_package(self.source, self.output)
        loaded = load_completed_check(self.output)
        self.assertNotIn("verified_loads", loaded["metadata"])
        self.assertNotIn("settings", loaded["metadata"])
        self.assertEqual(compare_reports(self.source, self.output)["status"], "not_comparable")

    def test_existing_output_is_not_overwritten(self):
        self.output.mkdir()
        marker = self.output / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            package.export_package(self.source, self.output)
        self.assertEqual(marker.read_text(), "keep")

    def test_export_cannot_write_inside_source_report(self):
        with self.assertRaises(CheckError):
            package.export_package(self.source, self.source / "child")
        self.assertFalse((self.source / "child").exists())

    def test_failed_cancelled_or_tampered_input_produces_no_output(self):
        for status in ("failed", "cancelled", "running"):
            self.metadata["status"] = status
            self.save()
            with self.assertRaises(CheckError):
                package.export_package(self.source, self.output)
            self.assertFalse(self.output.exists())
        self.metadata["status"] = "completed"
        self.save()
        (self.source / "diagnosis.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(CheckError):
            package.export_package(self.source, self.output)

    def test_filename_with_paths_or_control_characters_is_rejected(self):
        for name in ("C:\\private\\model.mph", "../model.mph", "line\nmodel.mph", ""):
            self.metadata["source"]["filename"] = name
            self.save()
            with self.assertRaises(CheckError):
                package.export_package(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_markdown_evidence_cannot_break_its_code_fence(self):
        self.report["findings"][0]["explanation"] = "````\n![private](https://example.invalid/tracker)\n```"
        self.metadata["source"]["filename"] = "<img>.mph"
        self.save()
        package.export_package(self.source, self.output)
        text = (self.output / "report.md").read_text(encoding="utf-8")
        self.assertIn("`````text", text)
        self.assertEqual(text.count("`````"), 2)
        self.assertNotIn("<img>", text)
        self.assertIn("&lt;img&gt;", text)

    def test_free_text_is_preserved_not_claimed_to_be_fully_redacted(self):
        self.report["findings"][0]["evidence"]["note"] = "PRIVATE_PATH"
        self.save()
        package.export_package(self.source, self.output)
        self.assertIn("PRIVATE_PATH", (self.output / "diagnosis.json").read_text(encoding="utf-8"))
        self.assertIn("自由文本", package.PRIVACY_NOTICE)

    def test_changed_human_readable_report_is_rejected_on_import(self):
        package.export_package(self.source, self.output)
        (self.output / "report.md").write_text("altered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "report.md"):
            load_completed_check(self.output)

    def test_missing_file_is_rejected(self):
        package.export_package(self.source, self.output)
        # Simulate interrupted transfer without deleting any source/user artifacts.
        (self.output / "overview.txt").rename(self.root / "held-overview.txt")
        with self.assertRaises(ValueError):
            load_completed_check(self.output)

    def test_extra_model_or_log_is_rejected(self):
        package.export_package(self.source, self.output)
        (self.output / "input.mph").write_bytes(b"synthetic")
        with self.assertRaises(ValueError):
            load_completed_check(self.output)

    def test_manifest_cannot_request_parent_paths(self):
        package.export_package(self.source, self.output)
        path = self.output / "package.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["files"]["../private"] = {"bytes": 0, "sha256": "0" * 64}
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_completed_check(self.output)

    def test_invalid_fingerprint_structure_is_rejected(self):
        package.export_package(self.source, self.output)
        path = self.output / "package.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        for value in (None, {"bytes": True, "sha256": "0" * 64}, {"bytes": 1, "sha256": "bad"}):
            manifest = copy.deepcopy(original)
            manifest["files"]["run.json"] = value
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_completed_check(self.output)

    def test_link_and_oversized_package_files_are_rejected(self):
        with patch.object(Path, "is_symlink", return_value=True), self.assertRaises(ValueError):
            integrity.read_package_file(self.source / "run.json")
        with patch.object(integrity, "MAX_FILE_BYTES", 2), self.assertRaises(ValueError):
            integrity.read_package_file(self.source / "run.json")

    def test_write_failure_does_not_publish_completed_run(self):
        original = Path.open
        def fail_overview(path, *args, **kwargs):
            if path == self.output / "overview.txt":
                raise OSError("synthetic disk failure")
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", fail_overview), self.assertRaises(OSError):
            package.export_package(self.source, self.output)
        self.assertFalse((self.output / "run.json").exists())
        with self.assertRaises(ValueError):
            load_completed_check(self.output)

    def test_export_can_be_copied_again_without_source_paths(self):
        package.export_package(self.source, self.output)
        second = self.root / "second"
        package.export_package(self.output, second)
        self.assertEqual(load_completed_check(second)["report"], self.report)

    def test_cli_works_without_comsol(self):
        process = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "src/flowpilot/report_package.py"),
                                  str(self.source), "--output-dir", str(self.output)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue((self.output / "package.json").exists())

    def ui(self):
        app = DesktopApp.__new__(DesktopApp)
        app.session = Mock(busy=False)
        app.current_view, app.artifact_directory = {}, self.source
        app.messages, app.dialogs, app.root = Mock(), Mock(), Mock()
        app.messages.askyesno.return_value = True
        app.dialogs.askdirectory.return_value = str(self.root)
        return app

    def test_ui_export_revalidates_and_keeps_current_report(self):
        app = self.ui()
        app.export_report()
        app.messages.showinfo.assert_called_once()
        app.messages.showerror.assert_not_called()
        self.assertEqual(app.artifact_directory, self.source)
        self.assertEqual(len(list(self.root.glob("report-package-*"))), 1)

    def test_ui_privacy_decline_or_busy_creates_nothing(self):
        app = self.ui()
        app.messages.askyesno.return_value = False
        app.export_report()
        app.dialogs.askdirectory.assert_not_called()
        app.session.busy = True
        app.messages.askyesno.reset_mock()
        app.export_report()
        app.messages.askyesno.assert_not_called()
        self.assertFalse(list(self.root.glob("report-package-*")))

    def test_ui_export_failure_preserves_current_valid_view(self):
        app = self.ui()
        with patch("flowpilot.desktop.export_package", side_effect=OSError("synthetic failure")):
            app.export_report()
        app.messages.showerror.assert_called_once()
        app.messages.showinfo.assert_not_called()
        self.assertEqual(app.artifact_directory, self.source)
        self.assertIsNotNone(app.current_view)


if __name__ == "__main__":
    unittest.main()
