"""History discovery is not report validation or proof a recorded process is alive."""
import json
from pathlib import Path
from queue import Queue
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot import report_history as history
from flowpilot.check_model import _write_json, sha256
from flowpilot.desktop import DesktopApp
from flowpilot.history_window import HistoryBrowser


class HistoryTest(unittest.TestCase):
    def setUp(self):
        (ROOT / "outputs").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "outputs")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.report = {"schema_version": "diagnosis-0.1", "status": "checked", "findings": []}

    def write_check(self, name, *, status="completed", session=False, ui_status="completed", error=""):
        parent = self.directory / name
        directory = parent / "check" if session else parent
        directory.mkdir(parents=True)
        _write_json(directory / "diagnosis.json", self.report)
        _write_json(directory / "run.json", {"schema_version": "check-run-0.1", "status": status,
                    "started_at": "2026-10-11T12:00:00+00:00", "diagnosis_status": "checked", "error": error,
                    "source": {"filename": "模型 with spaces.mph", "sha256": "a" * 64},
                    "diagnosis_sha256": sha256(directory / "diagnosis.json")})
        if session:
            _write_json(parent / "request.json", {"model": "C:/private/模型 with spaces.mph"})
            if ui_status is not None:
                _write_json(parent / "ui-run.json", {"schema_version": "desktop-run-0.1", "status": ui_status, "error": error})
        return directory

    def test_empty_directory_is_not_error(self):
        result = history.scan_history(self.directory)
        self.assertEqual(result["entries"], [])
        self.assertFalse(result["truncated"])

    def test_plain_and_session_reports_found_without_model_or_diagnosis_reads(self):
        self.write_check("single")
        self.write_check("session-one", session=True)
        original_open = Path.open
        def no_diagnosis(path, *args, **kwargs):
            if path.name == "diagnosis.json" or path.suffix == ".mph":
                raise AssertionError("Scanner must not read diagnosis or model")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", no_diagnosis):
            result = history.scan_history(self.directory)
        self.assertEqual({item["id"] for item in result["entries"]}, {"single", "session-one/check"})
        self.assertTrue(all(item["status"] == "completed" and not item["verified"] for item in result["entries"]))

    def test_failed_cancelled_and_unconfirmed_records_are_distinct(self):
        for status in ("failed", "cancelled", "running"):
            self.write_check(status, status=status)
        records = {item["id"]: item for item in history.scan_history(self.directory)["entries"]}
        self.assertEqual(records["failed"]["status"], "failed")
        self.assertEqual(records["cancelled"]["status"], "cancelled")
        self.assertEqual(records["running"]["status"], "unconfirmed")

    def test_completed_backend_but_failed_window_is_not_openable(self):
        self.write_check("window-failed", session=True, ui_status="failed", error="disk full")
        item = history.scan_history(self.directory)["entries"][0]
        self.assertEqual(item["status"], "failed")
        self.assertIn("disk full", item["detail"])
        with self.assertRaises(history.CheckError):
            history.load_history_report(self.directory, item["id"])

    def test_missing_window_final_record_is_unconfirmed(self):
        self.write_check("unfinished", session=True, ui_status=None)
        self.assertEqual(history.scan_history(self.directory)["entries"][0]["status"], "unconfirmed")

    def test_launch_failure_without_check_directory_keeps_logs_accessible(self):
        session = self.directory / "launch-failed"
        session.mkdir()
        _write_json(session / "ui-run.json", {"schema_version": "desktop-run-0.1", "status": "failed", "error": "cannot launch"})
        _write_json(session / "request.json", {"model": "C:/private/input.mph", "started_at": "2026-10-11"})
        item = history.scan_history(self.directory)["entries"][0]
        self.assertEqual(item["status"], "failed")
        self.assertEqual(item["model"], "input.mph")
        self.assertEqual(history.history_directory(self.directory, item["id"]), session)

    def test_malformed_record_does_not_hide_other_records(self):
        broken = self.write_check("broken")
        (broken / "run.json").write_text("[]", encoding="utf-8")
        self.write_check("good")
        statuses = {item["id"]: item["status"] for item in history.scan_history(self.directory)["entries"]}
        self.assertEqual(statuses, {"broken": "invalid", "good": "completed"})

    def test_oversized_record_not_read_in_full(self):
        directory = self.write_check("oversized")
        (directory / "run.json").write_bytes(b"x" * 65537)
        self.assertEqual(history.scan_history(self.directory)["entries"][0]["status"], "invalid")

    def test_scan_limit_explicit_and_inputs_validated(self):
        for name in ("a", "b", "c"):
            self.write_check(name)
        result = history.scan_history(self.directory, limit=2)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["entries"]), 2)
        for limit in (True, 0, 501):
            with self.assertRaises(ValueError):
                history.scan_history(self.directory, limit=limit)
        with self.assertRaises(ValueError):
            history.scan_history("")

    def test_nested_unrelated_outputs_are_not_recursively_searched(self):
        nested = self.directory / "unrelated/deep"
        nested.mkdir(parents=True)
        _write_json(nested / "run.json", {"schema_version": "check-run-0.1"})
        batch = self.directory / "batch"
        batch.mkdir()
        _write_json(batch / "run.json", {"schema_version": "batch-check-run-0.1"})
        self.assertEqual(history.scan_history(self.directory)["entries"], [])

    def test_links_are_skipped_without_reading_contents(self):
        child = self.write_check("linked")
        with patch.object(history, "_linked", side_effect=lambda path: path == child):
            result = history.scan_history(self.directory)
        self.assertEqual(result["skipped_links"], 1)
        self.assertEqual(result["entries"], [])

    def test_redirected_check_directory_is_skipped(self):
        directory = self.write_check("junction", session=True)
        with patch.object(history, "_linked", side_effect=lambda path: path == directory):
            result = history.scan_history(self.directory)
        self.assertEqual(result["skipped_links"], 1)
        self.assertEqual(result["entries"], [])

    def test_parent_escape_and_absolute_history_ids_rejected(self):
        for name in ("../escape", "/absolute", "C:/absolute", "a\\b"):
            with self.assertRaises(history.CheckError):
                history.load_history_report(self.directory, name)

    def test_open_revalidates_diagnosis_after_listing(self):
        directory = self.write_check("tampered")
        item = history.scan_history(self.directory)["entries"][0]
        self.assertEqual(item["status"], "completed")
        (directory / "diagnosis.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(history.CheckError):
            history.load_history_report(self.directory, item["id"])

    def test_open_checks_redirected_files_again(self):
        directory = self.write_check("redirected")
        history.scan_history(self.directory)
        with patch.object(history, "_linked", side_effect=lambda path: path == directory / "diagnosis.json"), \
                self.assertRaises(history.CheckError):
            history.load_history_report(self.directory, "redirected")

    def test_open_valid_report_does_not_change_files(self):
        directory = self.write_check("good", session=True)
        hashes = {path: sha256(path) for path in self.directory.rglob("*.json")}
        loaded = history.load_history_report(self.directory, "good/check")
        self.assertEqual(loaded["view"]["headline"], "当前规则未发现问题")
        self.assertEqual(loaded["directory"], directory)
        self.assertTrue(all(sha256(path) == digest for path, digest in hashes.items()))

    def test_invalid_source_hash_not_truncated_to_valid_value(self):
        directory = self.write_check("invalid-hash")
        metadata = json.loads((directory / "run.json").read_text(encoding="utf-8"))
        metadata["source"]["sha256"] += "x"
        (directory / "run.json").write_text(json.dumps(metadata), encoding="utf-8")
        self.assertEqual(history.scan_history(self.directory)["entries"][0]["status"], "invalid")

    def test_records_sorted_by_time_then_identifier(self):
        self.write_check("a")
        self.write_check("b")
        self.assertEqual([item["id"] for item in history.scan_history(self.directory)["entries"]], ["b", "a"])

    def test_desktop_busy_state_blocks_history_open_and_result_replacement(self):
        app = DesktopApp.__new__(DesktopApp)
        app.session, app.show_result = Mock(busy=True), Mock()
        self.assertIsNone(app.show_history())
        with self.assertRaises(history.CheckError):
            app.open_history_result({})
        app.show_result.assert_not_called()

    def test_history_open_failure_keeps_current_report(self):
        browser = HistoryBrowser.__new__(HistoryBrowser)
        browser.selected = Mock(return_value={"id": "bad", "status": "completed"})
        browser.scanning, browser.scan_root = False, str(self.directory)
        browser.on_open, browser.messages, browser.status, browser.window = Mock(), Mock(), Mock(), Mock()
        browser.open_selected()
        browser.on_open.assert_not_called()
        browser.messages.showerror.assert_called_once()

    def test_closed_browser_does_not_touch_widgets_on_late_scan_result(self):
        browser = HistoryBrowser.__new__(HistoryBrowser)
        browser.closed, browser._after_id, browser._queue = True, "pending", Queue()
        browser._queue.put(({}, None))
        browser.window = Mock()
        browser.poll_scan()
        browser.window.after.assert_not_called()
        self.assertEqual(browser._queue.qsize(), 1)

    def test_scan_failure_clears_busy_state_without_old_rows(self):
        browser = HistoryBrowser.__new__(HistoryBrowser)
        browser.closed, browser.scanning, browser._queue = False, True, Queue()
        browser._queue.put((None, "fixture scan failure"))
        browser.path_entry, browser.choose_button, browser.refresh_button = Mock(), Mock(), Mock()
        browser.status, browser.set_details = Mock(), Mock()
        browser.poll_scan()
        self.assertFalse(browser.scanning)
        browser.set_details.assert_called_once_with("fixture scan failure")


if __name__ == "__main__":
    unittest.main()
