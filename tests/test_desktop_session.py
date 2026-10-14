"""Headless UI/session checks. Mock processes are not real COMSOL integration."""
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
from flowpilot import check_model as checker
from flowpilot import desktop_session as desktop
from flowpilot.desktop import DesktopApp
from flowpilot.diagnostics import diagnose_inventory


class DesktopSessionTest(unittest.TestCase):
    def setUp(self):
        (ROOT / "outputs").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "outputs")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.model = self.directory / "模型 with spaces.mph"
        self.model.write_bytes(b"offline synthetic model")
        self.comsol = self.directory / "COMSOL with spaces"
        binaries = self.comsol / "bin/win64"
        binaries.mkdir(parents=True)
        for name in ("comsolcompile.exe", "comsolbatch.exe"):
            (binaries / name).touch()
        self.report = diagnose_inventory(json.loads((ROOT / "data/fixtures/cases/baseline.json").read_text(encoding="utf-8-sig")))
        self.session = desktop.DesktopSession()
        self.process = Mock()
        self.process.poll.return_value = None
        self.process.returncode = None
        self.addCleanup(self.cleanup_session)

    def cleanup_session(self):
        if self.session._log is not None:
            self.session._log.close()

    def start(self):
        with patch.object(desktop.subprocess, "Popen", return_value=self.process) as popen:
            directory = self.session.start(self.model, self.comsol, self.directory / "sessions")
        return directory, popen.call_args

    def write_completed(self, directory, report=None, status="completed"):
        directory.mkdir(parents=True, exist_ok=True)
        report = report or self.report
        desktop._write_json(directory / "diagnosis.json", report)
        desktop._write_json(directory / "run.json", {"schema_version": "check-run-0.1", "status": status,
                            "diagnosis_status": report["status"], "diagnosis_sha256": desktop.sha256(directory / "diagnosis.json"),
                            "source": {"filename": self.model.name, "sha256": desktop.sha256(self.model)}})
        (directory / "report.md").write_text("synthetic report", encoding="utf-8")

    def complete(self, code=0):
        self.process.poll.return_value = code
        self.process.returncode = code

    def test_clean_report_is_neutral_not_a_physics_pass(self):
        view = desktop.diagnosis_view(self.report)
        self.assertEqual(view["headline"], "当前规则未发现问题")
        self.assertEqual(view["tone"], "neutral")
        self.assertIn("不证明物理正确", view["disclaimer"])

    def test_real_fixture_diagnoses_have_chinese_actions_and_evidence(self):
        for name in ("missing_inlet", "missing_outlet", "selection_overlap", "reversed_inlet", "high_reynolds"):
            inventory = json.loads((ROOT / f"data/fixtures/cases/{name}.json").read_text(encoding="utf-8-sig"))
            view = desktop.diagnosis_view(diagnose_inventory(inventory))
            self.assertTrue(view["items"])
            for item in view["items"]:
                self.assertIn("建议：", item["detail"])
                self.assertIn("证据：", item["detail"])
                self.assertIn(item["code"], desktop.TITLES)

    def test_partial_and_unsupported_are_incomplete(self):
        partial = copy.deepcopy(self.report)
        partial["status"] = "partial"
        unsupported = {"schema_version": "diagnosis-0.1", "status": "unsupported", "reason": "3D is outside profile", "findings": []}
        for report in (partial, unsupported):
            self.assertEqual(desktop.diagnosis_view(report)["tone"], "incomplete")

    def test_bad_report_shape_is_not_a_clean_result(self):
        for report in ({}, {"schema_version": "diagnosis-0.1", "status": "checked", "findings": "bad"},
                       {"schema_version": "diagnosis-0.1", "status": "unsupported", "findings": []}):
            with self.assertRaises(desktop.CheckError):
                desktop.diagnosis_view(report)

    def test_completed_report_requires_matching_content_hash(self):
        directory = self.directory / "check"
        self.write_completed(directory)
        self.assertEqual(desktop.load_completed_check(directory)["view"]["tone"], "neutral")
        (directory / "diagnosis.json").write_text('{}', encoding="utf-8")
        with self.assertRaises(desktop.CheckError):
            desktop.load_completed_check(directory)

    def test_failed_or_cancelled_run_cannot_display_its_stale_report(self):
        for status in ("failed", "cancelled", "running"):
            directory = self.directory / status
            self.write_completed(directory, status=status)
            with self.assertRaises(desktop.CheckError):
                desktop.load_completed_check(directory)

    def test_launch_preserves_unicode_paths_and_never_uses_a_shell(self):
        directory, call = self.start()
        command = call.args[0]
        self.assertIn(str(self.model), command)
        self.assertIn(str(self.comsol), command)
        self.assertNotIn("shell", call.kwargs)
        self.assertIn("--cancel-file", command)
        self.assertFalse((directory / "check").exists())
        self.assertTrue(self.session.busy)
        self.assertEqual(self.session.poll(), "running")
        self.assertEqual(self.model.read_bytes(), b"offline synthetic model")

    def test_only_validated_completed_result_is_displayed(self):
        directory, _ = self.start()
        self.write_completed(directory / "check")
        self.complete()
        self.assertEqual(self.session.poll(), "completed")
        self.assertEqual(self.session.result["report"], self.report)
        self.assertFalse(self.session.busy)
        self.assertEqual(json.loads((directory / "ui-run.json").read_text(encoding="utf-8"))["status"], "completed")

    def test_exit_zero_without_backend_metadata_is_failure(self):
        self.start()
        self.complete()
        self.assertEqual(self.session.poll(), "failed")
        self.assertIsNone(self.session.result)

    def write_progress(self, directory, stages):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "progress.jsonl"
        path.write_text("".join(json.dumps({"schema_version": "check-progress-0.1", "stage": stage}) + "\n"
                                for stage in stages), encoding="utf-8")
        return path

    def test_running_progress_is_chinese_and_does_not_publish_results(self):
        directory, _ = self.start()
        self.write_progress(directory / "check", ["snapshot", "compile", "inventory"])
        self.assertEqual(self.session.poll(), "running")
        self.assertEqual(self.session.progress_stage, "inventory")
        self.assertIn("COMSOL 读取", self.session.progress_text)
        self.assertIn("不是完成百分比", self.session.progress_text)
        self.assertIsNone(self.session.result)

    def test_completed_progress_is_not_authority_to_complete(self):
        directory, _ = self.start()
        self.write_progress(directory / "check", ["completed"])
        self.assertEqual(self.session.poll(), "running")
        self.assertIsNone(self.session.result)
        self.complete()
        self.assertEqual(self.session.poll(), "failed")
        self.assertIsNone(self.session.result)

    def test_progress_reader_ignores_partial_malformed_and_backward_events(self):
        path = self.write_progress(self.directory / "check", ["snapshot", "inventory", "compile", "unknown"])
        with path.open("ab") as stream:
            stream.write(b'not json\n[]\n{"schema_version":"check-progress-0.1","stage":"completed"}')
        self.assertEqual(desktop.read_progress(path), "inventory")
        with path.open("ab") as stream:
            stream.write(b"\n")
        self.assertEqual(desktop.read_progress(path), "completed")

    def test_missing_or_oversized_progress_is_advisory_only(self):
        self.assertIsNone(desktop.read_progress(self.directory / "missing"))
        path = self.directory / "oversized"
        path.write_bytes(b"x" * 16385)
        self.assertIsNone(desktop.read_progress(path))

    def test_deep_or_invalid_encoding_progress_does_not_break_polling(self):
        path = self.directory / "invalid-progress"
        path.write_bytes(b"[" * 1100 + b"0" + b"]" * 1100 + b"\n\xff\n")
        self.assertIsNone(desktop.read_progress(path))

    def test_progress_elapsed_time_uses_monotonic_clock(self):
        self.start()
        self.session._started = 100
        with patch.object(desktop.time, "monotonic", return_value=112.9):
            self.assertIn("已用时 12 秒", self.session.progress_text)

    def test_cancellation_text_wins_over_last_progress_stage(self):
        self.start()
        self.session.cancel()
        self.assertIn("正在取消", self.session.progress_text)

    def test_window_run_write_failure_finishes_once_without_stale_result(self):
        directory, _ = self.start()
        self.write_completed(directory / "check")
        self.complete()
        with patch.object(desktop, "_write_json", side_effect=PermissionError("synthetic disk denial")) as write:
            self.assertEqual(self.session.poll(), "failed")
            self.assertEqual(self.session.poll(), "failed")
        write.assert_called_once()
        self.assertFalse(self.session.busy)
        self.assertIsNone(self.session.result)
        self.assertIsNone(self.session._log)
        self.assertIn("无法保存", self.session.error)

    def test_existing_window_run_record_is_not_overwritten(self):
        directory, _ = self.start()
        self.write_completed(directory / "check")
        original = b"external record"
        (directory / "ui-run.json").write_bytes(original)
        self.complete()
        self.assertEqual(self.session.poll(), "failed")
        self.assertEqual((directory / "ui-run.json").read_bytes(), original)
        self.assertIsNone(self.session.result)

    def test_log_close_error_is_terminal_and_recorded(self):
        directory, _ = self.start()
        self.write_completed(directory / "check")
        self.complete()
        self.session._log.close()
        bad_log = Mock()
        bad_log.close.side_effect = OSError("synthetic flush failure")
        self.session._log = bad_log
        self.assertEqual(self.session.poll(), "failed")
        bad_log.close.assert_called_once()
        self.assertIsNone(self.session._log)
        self.assertIsNone(self.session.result)
        self.assertIn("关闭本次启动日志", self.session.error)
        self.assertEqual(json.loads((directory / "ui-run.json").read_text(encoding="utf-8"))["status"], "failed")

    def test_request_write_failure_never_launches_or_keeps_previous_result(self):
        self.session.state, self.session.result = "completed", {"stale": True}
        original_write = desktop._write_json
        def fail_request(path, value):
            if path.name == "request.json":
                raise PermissionError("synthetic request denial")
            original_write(path, value)
        with patch.object(desktop, "_write_json", side_effect=fail_request), \
                patch.object(desktop.subprocess, "Popen") as popen, self.assertRaises(PermissionError):
            self.session.start(self.model, self.comsol, self.directory / "sessions")
        popen.assert_not_called()
        self.assertEqual(self.session.state, "failed")
        self.assertIsNone(self.session.result)

    def test_cancel_write_failure_keeps_check_running_and_retryable(self):
        self.start()
        with patch.object(Path, "open", side_effect=PermissionError("synthetic cancel denial")), self.assertRaises(PermissionError):
            self.session.cancel()
        self.assertEqual(self.session.state, "running")
        self.assertTrue(self.session.cancel())

    def test_cancel_ui_write_failure_does_not_close_window_or_stop_polling(self):
        app = DesktopApp.__new__(DesktopApp)
        app._closing, app._after_id = True, "scheduled-poll"
        app.session, app.messages, app.root = Mock(), Mock(), Mock()
        app.session.cancel.side_effect = PermissionError("synthetic cancel denial")
        app.cancel_check()
        self.assertFalse(app._closing)
        self.assertEqual(app._after_id, "scheduled-poll")
        app.messages.showerror.assert_called_once()
        app.root.destroy.assert_not_called()

    def test_nonzero_exit_cannot_display_even_a_stale_completed_result(self):
        directory, _ = self.start()
        self.write_completed(directory / "check")
        self.complete(1)
        self.assertEqual(self.session.poll(), "failed")
        self.assertIsNone(self.session.result)

    def test_cancel_requests_only_owned_session_and_awaits_backend(self):
        directory, _ = self.start()
        self.assertTrue(self.session.cancel())
        self.assertFalse(self.session.cancel())
        self.assertEqual(self.session.poll(), "cancelling")
        self.assertTrue((directory / "cancel.request").exists())
        self.write_completed(directory / "check", status="cancelled")
        self.complete(1)
        self.assertEqual(self.session.poll(), "cancelled")
        self.assertIsNone(self.session.result)
        self.assertFalse(self.process.kill.called)

    def test_late_cancel_does_not_replace_completed_result(self):
        directory, _ = self.start()
        self.write_completed(directory / "check")
        self.complete()
        self.assertFalse(self.session.cancel())
        self.assertEqual(self.session.state, "completed")
        self.assertFalse((directory / "cancel.request").exists())

    def test_double_start_is_rejected(self):
        self.start()
        with self.assertRaises(desktop.CheckError):
            self.session.start(self.model, self.comsol, self.directory)

    def test_launch_error_is_recorded_and_log_closed(self):
        with patch.object(desktop.subprocess, "Popen", side_effect=OSError("fixture launch failure")), self.assertRaises(OSError):
            self.session.start(self.model, self.comsol, self.directory / "sessions")
        self.assertEqual(self.session.state, "failed")
        self.assertIsNone(self.session._log)
        self.assertEqual(json.loads((self.session.directory / "ui-run.json").read_text(encoding="utf-8"))["status"], "failed")

    def test_lfs_pointer_refused_before_launch(self):
        self.model.write_bytes(desktop.LFS_HEADER + b"\noid sha256:fixture\n")
        with patch.object(desktop.subprocess, "Popen") as popen, self.assertRaises(desktop.CheckError):
            self.session.start(self.model, self.comsol, self.directory / "sessions")
        popen.assert_not_called()

    def test_missing_environment_and_invalid_options_do_not_start_process(self):
        with patch.object(desktop.subprocess, "Popen") as popen:
            for options in ({"loads": True}, {"loads": 0}, {"timeout": float("inf")}, {"reynolds_warning": -1}):
                with self.assertRaises(ValueError):
                    self.session.start(self.model, self.comsol, self.directory, **options)
            with self.assertRaises(ValueError):
                self.session.start(self.model, self.directory, self.directory)
        popen.assert_not_called()

    def test_cancelled_flag_before_launch_does_not_create_process(self):
        cancel = self.directory / "cancel.request"
        cancel.touch()
        with patch.object(checker.subprocess, "Popen") as popen, self.assertRaises(checker.CheckCancelled):
            checker._run(["unused"], cwd=self.directory, log=self.directory / "log", timeout=1, cancel_file=cancel)
        popen.assert_not_called()

    def test_cooperative_cancel_stops_only_started_process(self):
        cancel = self.directory / "cancel.request"
        process = Mock()
        process.poll.return_value = None
        def wait(timeout):
            cancel.touch()
            raise subprocess.TimeoutExpired("fixture", timeout)
        process.wait.side_effect = wait
        with patch.object(checker.subprocess, "Popen", return_value=process), \
                patch.object(checker, "_stop_process") as stop, self.assertRaises(checker.CheckCancelled):
            checker._run(["unused"], cwd=self.directory, log=self.directory / "log", timeout=1, cancel_file=cancel)
        stop.assert_called_once_with(process)

    def test_backend_cancel_is_recorded_without_publishing_diagnosis(self):
        cancel = self.directory / "cancel.request"
        cancel.touch()
        output = self.directory / "cancelled-check"
        with patch.object(checker.subprocess, "Popen") as popen, self.assertRaises(checker.CheckCancelled):
            checker.check_model(self.model, comsol_root=self.comsol, output_dir=output, cancel_file=cancel)
        popen.assert_not_called()
        metadata = json.loads((output / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "cancelled")
        self.assertFalse((output / "diagnosis.json").exists())

    def test_invalid_new_request_clears_previous_display_before_error(self):
        app = DesktopApp.__new__(DesktopApp)
        app.session = Mock(busy=False, directory=None)
        app.model = Mock()
        app.model.get.return_value = ""
        app.clear_result, app.set_details = Mock(), Mock()
        app.status, app.status_label, app.messages, app.root = Mock(), Mock(), Mock(), Mock()
        app.start_check()
        app.clear_result.assert_called_once_with()
        app.session.start.assert_not_called()
        self.assertIn("未展示诊断结论", app.status.set.call_args.args[0])
        app.messages.showerror.assert_called_once()

    def test_cooperative_mode_still_enforces_process_timeout(self):
        cancel = self.directory / "not-requested"
        process = Mock()
        process.wait.side_effect = subprocess.TimeoutExpired("fixture", 0.1)
        with patch.object(checker.subprocess, "Popen", return_value=process), \
                patch.object(checker.time, "monotonic", side_effect=[0, 0, 1]), \
                patch.object(checker, "_stop_process") as stop, self.assertRaisesRegex(checker.CheckError, "exceeded"):
            checker._run(["unused"], cwd=self.directory, log=self.directory / "timeout.log", timeout=0.1, cancel_file=cancel)
        stop.assert_called_once_with(process)

    def test_versioned_desktop_smoke_separates_functional_checks_from_acceptance(self):
        stored = json.loads((ROOT / "data/fixtures/desktop_smoke_report_boundaries.json").read_text(encoding="utf-8"))
        self.assertTrue(stored["passed"])
        self.assertTrue(stored["window_hidden"])
        self.assertFalse(stored["visual_review"])
        self.assertFalse(stored["new_user_timing_validated"])
        self.assertFalse(stored["expert_review"])
        self.assertTrue(stored["source_hashes_unchanged"])
        self.assertEqual(len(stored["report_views"]), 6)
        self.assertEqual([run["case_id"] for run in stored["real_checks"]], ["baseline", "missing_inlet"])
        self.assertEqual(stored["real_checks"][1]["codes"], ["MISSING_INLET"])
        self.assertEqual(stored["real_checks"][0]["overview_coverage"], {"inlet": [1], "outlet": [4], "wall": [2, 3]})
        self.assertEqual(stored["real_checks"][1]["overview_coverage"]["inlet"], [])
        self.assertTrue(all(item["overview_available"] for item in stored["report_views"]))
        for run in stored["real_checks"]:
            self.assertEqual(run["progress_stages"], ["snapshot", "compile", "inventory", "diagnose", "completed"])
            self.assertIn("inventory", run["live_stages_observed"])
        self.assertEqual(stored["real_cancellation"]["status"], "cancelled")
        self.assertTrue(stored["real_cancellation"]["requested_after_batch_console_created"])
        self.assertGreater(stored["event_loop_heartbeat_count"], 0)
        self.assertEqual(stored["report_comparison"]["counts"]["added"], 1)
        self.assertEqual(stored["report_comparison"]["reverse_counts"]["removed"], 1)
        self.assertTrue(stored["report_comparison"]["dialog_handler_verified"])
        self.assertTrue(stored["report_comparison"]["different_controlled_fixtures_not_a_repair_test"])
        self.assertEqual(stored["history_browser"]["record_counts"]["completed"], 2)
        self.assertEqual(stored["history_browser"]["record_counts"]["cancelled"], 1)
        self.assertEqual(stored["history_browser"]["verified_report_opened"], "missing_inlet")
        self.assertTrue(stored["history_browser"]["cancelled_report_open_disabled"])
        self.assertTrue(stored["report_package"]["dialog_handler_verified"])
        self.assertTrue(stored["report_package"]["reimport_verified"])
        self.assertTrue(stored["report_package"]["human_readable_tamper_rejected"])
        self.assertFalse(stored["report_package"]["model_or_log_copied"])
        for field in ("valid_package_scored", "damaged_package_unscored", "malformed_finding_rejected_by_reader",
                      "malformed_finding_unscored", "malformed_input_is_synthetic"):
            self.assertTrue(stored["report_reader"][field])
        self.assertEqual(stored["report_package"]["files"], ["README.md", "diagnosis.json", "overview.txt", "report.md", "run.json"])
        self.assertEqual([item["reason"] for item in stored["synthetic_numeric_views"]],
                         ["above_float_range", "below_nonzero_float_range"])
        for item in stored["synthetic_numeric_views"]:
            self.assertTrue(item["synthetic_input"])
            self.assertFalse(item["real_comsol_validation"])
            self.assertEqual(item["diagnosis_status"], "partial")
            self.assertEqual(item["desktop_tone"], "incomplete")
            self.assertTrue(item["package_reimport_verified"])
        for path, digest in stored["source_sha256"].items():
            if path == "src/flowpilot/report_package.py":
                # Full COMSOL smoke predates only this exporter change; do not
                # relabel it. The current exporter has separate real-report
                # offline Tk/reimport evidence and a current-byte fingerprint.
                self.assertEqual(digest, "8399fc4f0f37baa7b092f11e712ddf27f34d3afceb0f4f8afbf6f4407423e018")
                offline = json.loads((ROOT / "data/fixtures/report_export_offline_smoke.json").read_text(encoding="utf-8"))
                self.assertEqual(desktop.sha256(ROOT / path), offline["source_sha256"][path])
            else:
                self.assertEqual(desktop.sha256(ROOT / path), digest)
        manifest = json.loads((ROOT / "data/fixtures/cases/manifest.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(stored["source_model_sha256"], {case["case_id"]: case["sha256"].lower() for case in manifest["cases"]})

    def test_previous_desktop_smoke_is_preserved_without_rebinding_sources(self):
        # The prior engineering record remains byte-for-byte historical evidence.
        self.assertEqual(desktop.sha256(ROOT / "data/fixtures/desktop_smoke.json"),
                         "d6670077d40a1185f9a224428e6089424ea66c2f8cf2391d1b418ad87661a849")
        self.assertEqual(desktop.sha256(ROOT / "data/fixtures/desktop_smoke_eligibility_gate.json"),
                         "637230a460c793a1e7d7ffd1d5569ba642a3175a063bbce90471e4319d233703")
        self.assertEqual(desktop.sha256(ROOT / "data/fixtures/desktop_smoke_batch_stability.json"),
                         "5d04b9ef644ef0ca3acac3b6db8763df0247755ad1e46eb2d47a13cfbbfd236e")
        self.assertEqual(desktop.sha256(ROOT / "data/fixtures/desktop_smoke_report_boundaries.json"),
                         "09a2869c5b1c7b31ea27519f4dde2dbec40036bc7b96fcdb480f9e69fbc1e5f8")

    def test_current_exporter_offline_smoke_does_not_claim_new_comsol_or_user_acceptance(self):
        stored = json.loads((ROOT / "data/fixtures/report_export_offline_smoke.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["schema_version"], "naming-smoke-0.1")
        for flag in ("passed", "window_hidden", "models_unchanged", "new_package_reimport_verified"):
            self.assertTrue(stored[flag])
        for flag in ("comsol_invoked", "visual_review", "new_user_timing_validated", "expert_review"):
            self.assertFalse(stored[flag])
        for path, digest in stored["source_sha256"].items():
            self.assertEqual(desktop.sha256(ROOT / path), digest)
        manifest = json.loads((ROOT / "data/fixtures/cases/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["old_report_case_ids"], [case["case_id"] for case in manifest["cases"]])
        self.assertEqual(stored["source_model_sha256"], {case["case_id"]: case["sha256"].lower() for case in manifest["cases"]})


if __name__ == "__main__":
    unittest.main()
