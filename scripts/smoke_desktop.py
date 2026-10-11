"""Hidden-window integration checks; not visual QA, user testing, or expert review."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.check_model import CheckError, _write_json, sha256
from flowpilot.desktop import DesktopApp
from flowpilot.desktop_session import load_completed_check
from flowpilot.compare_reports import compare_reports, write_comparison
from flowpilot.report_package import export_package
from flowpilot.package_integrity import verify_package
from flowpilot.diagnostics import check
from flowpilot.check_suite import read_outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comsol-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reports-root", type=Path, help="optional existing batch directory for report-view checks")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    app = DesktopApp(root, comsol_root=args.comsol_root, output_root=output / "sessions")
    result = {"schema_version": "desktop-smoke-0.1", "window_hidden": True, "visual_review": False,
              "new_user_timing_validated": False, "expert_review": False, "report_views": [], "real_checks": []}
    result["source_sha256"] = {name: sha256(ROOT / name) for name in
                               ("src/flowpilot/desktop.py", "src/flowpilot/desktop_session.py",
                                "src/flowpilot/check_model.py", "src/flowpilot/compare_reports.py",
                                "src/flowpilot/report_history.py", "src/flowpilot/history_window.py",
                                "src/flowpilot/model_overview.py", "src/flowpilot/diagnostics.py",
                                "src/flowpilot/report_package.py", "src/flowpilot/package_integrity.py",
                                "src/flowpilot/report_io.py", "src/flowpilot/check_suite.py", "scripts/smoke_desktop.py")}
    manifest = json.loads((ROOT / "data/fixtures/cases/manifest.json").read_text(encoding="utf-8-sig"))
    before = {case["case_id"]: sha256(ROOT / case["model_path"]) for case in manifest["cases"]}
    assert all(before[case["case_id"]].lower() == case["sha256"].lower() for case in manifest["cases"])
    result["source_model_sha256"] = before
    errors, beats = [], [0]
    root.report_callback_exception = lambda kind, value, traceback: errors.append(str(value))

    def heartbeat():
        beats[0] += 1
        root.after(50, heartbeat)
    root.after(50, heartbeat)

    def wait_for_session(*, cancel=False):
        deadline = time.monotonic() + 180
        requested = False
        live_stages = set()
        while app.session.busy or app._after_id is not None:
            root.update()
            if app.session.busy:
                live_stages.add(app.session.progress_stage)
                if app.session.progress_stage == "inventory" and not cancel:
                    assert "COMSOL 读取" in app.status.get()
            if errors:
                raise CheckError("Tk callback failed: " + "; ".join(errors))
            if cancel and not requested and (app.session.directory / "check/batch-console.log").exists():
                app.cancel_check()
                requested = True
            if time.monotonic() >= deadline:
                app.session.cancel()
                raise CheckError("Desktop smoke test exceeded 180 seconds")
            time.sleep(0.025)
        if cancel and not requested:
            raise CheckError("Cancellation was not exercised during a real batch launch")
        return sorted(live_stages)

    try:
        completed_directories = {}
        root.update_idletasks()
        assert app.start_button.instate(["!disabled"])
        assert app.cancel_button.instate(["disabled"])
        if args.reports_root:
            for case in manifest["cases"]:
                loaded = load_completed_check(args.reports_root / case["case_id"])
                assert read_outcome(args.reports_root / case["case_id"], case, 2000)["status"] == "checked"
                app.show_result(loaded)
                root.update_idletasks()
                assert len(app.tree.get_children()) == len(loaded["report"]["findings"])
                assert app.status.get() == loaded["view"]["headline"]
                if loaded["view"]["items"]:
                    assert "建议：" in app.details.get("1.0", "end")
                assert app.current_overview["available"]
                app.result_tabs.select(app.overview_tab)
                root.update_idletasks()
                assert str(app.result_tabs.select()) == str(app.overview_tab)
                assert "声明边界" in app.overview_text.get("1.0", "end")
                assert str(app.overview_text.cget("state")) == "disabled"
                result["report_views"].append({"case_id": case["case_id"], "headline": app.status.get(),
                                                "item_count": len(app.tree.get_children()),
                                                "overview_available": app.current_overview["available"]})
        # Fail instead of opening a hidden, blocking error dialog during the smoke test.
        with patch.object(app.messages, "showerror", side_effect=lambda title, message, **kw: (_ for _ in ()).throw(CheckError(message))):
            for identity in ("baseline", "missing_inlet"):
                case = next(case for case in manifest["cases"] if case["case_id"] == identity)
                app.model.set(str(ROOT / case["model_path"]))
                app.start_check()
                assert app.start_button.instate(["disabled"])
                live_stages = wait_for_session()
                assert app.session.state == "completed", app.session.error
                completed_directories[identity] = app.session.directory / "check"
                assert app.start_button.instate(["!disabled"])
                assert app.cancel_button.instate(["disabled"])
                assert app.compare_button.instate(["!disabled"])
                actual = sorted({finding["code"] for finding in app.session.result["report"]["findings"]})
                assert actual == sorted(case["expected_codes"])
                stages = [json.loads(line)["stage"] for line in
                          (app.session.directory / "check/progress.jsonl").read_text(encoding="utf-8").splitlines()]
                assert stages == ["snapshot", "compile", "inventory", "diagnose", "completed"]
                assert "inventory" in live_stages
                overview = app.current_overview
                assert overview["available"]
                assert "1000 kg/m^3" in app.overview_text.get("1.0", "end")
                if identity == "baseline":
                    assert overview["coverage"] == {"inlet": [1], "outlet": [4], "wall": [2, 3]}
                    wall = next(item for item in overview["boundaries"] if item["role"] == "壁面")
                    assert wall["declared"] == "1, 2, 3, 4" and wall["effective"] == "2, 3"
                else:
                    assert overview["coverage"]["inlet"] == []
                    missing = app.session.result["report"]["findings"][0]
                    assert missing["evidence"]["required_role"] == "inlet"
                    assert missing["evidence"]["active_boundary_nodes"]
                with (output / (identity + "-overview.txt")).open("x", encoding="utf-8") as stream:
                    stream.write(overview["text"])
                result["real_checks"].append({"case_id": identity, "status": app.session.state,
                                               "overview_coverage": overview["coverage"],
                                               "progress_stages": stages, "live_stages_observed": live_stages,
                                               "codes": actual, "headline": app.status.get(),
                                               "comsol_version": app.session.result["metadata"]["comsol_version"],
                                               "ui_run_sha256": sha256(app.session.directory / "ui-run.json")})
                print(f"Desktop real check: {identity} -> {app.session.state}", flush=True)
            comparison = compare_reports(completed_directories["baseline"], completed_directories["missing_inlet"])
            assert comparison["status"] == "compared"
            assert comparison["counts"] == {"added": 1, "removed": 0, "changed": 0, "unchanged": 0}
            # Exercise the actual button handler; keep the new dialog hidden before an event-loop update.
            shown = []
            original_show = app.show_comparison
            def show_hidden(summary):
                window = original_show(summary)
                window.withdraw()
                shown.append((window, summary))
                return window
            with patch.object(app.dialogs, "askdirectory", return_value=str(completed_directories["baseline"])), \
                    patch.object(app, "show_comparison", side_effect=show_hidden):
                app.compare_report()
            assert len(shown) == 1 and shown[0][1]["counts"] == comparison["counts"]
            root.update_idletasks()
            shown[0][0].destroy()
            export_directory = output / "comparison"
            comparison_directory = write_comparison(comparison, export_directory)
            reverse = compare_reports(completed_directories["missing_inlet"], completed_directories["baseline"])
            assert reverse["counts"]["removed"] == 1
            result["report_comparison"] = {"status": comparison["status"], "counts": comparison["counts"],
                                            "reverse_counts": reverse["counts"], "dialog_handler_verified": True,
                                            "comparison_sha256": sha256(comparison_directory / "comparison.json"),
                                            "different_controlled_fixtures_not_a_repair_test": True}
            assert app.export_button.instate(["!disabled"])
            share_root = output / "shared"
            share_root.mkdir()
            with patch.object(app.messages, "askyesno", return_value=True), \
                    patch.object(app.messages, "showinfo") as notice, \
                    patch.object(app.dialogs, "askdirectory", return_value=str(share_root)):
                app.export_report()
                notice.assert_called_once()
            shared = next(share_root.iterdir())
            package_manifest = verify_package(shared)
            expected_report = load_completed_check(completed_directories["missing_inlet"])["report"]
            assert load_completed_check(shared)["report"] == expected_report
            assert compare_reports(completed_directories["missing_inlet"], shared)["counts"]["unchanged"] == 1
            with patch.object(app.dialogs, "askdirectory", return_value=str(shared)):
                app.import_report()
            assert app.artifact_directory == shared
            assert app.current_view["items"][0]["code"] == "MISSING_INLET"
            assert app.current_overview["coverage"]["inlet"] == []
            damaged = export_package(shared, output / "damaged-transfer")
            with (damaged / "report.md").open("ab") as stream:
                stream.write(b"\naltered transfer\n")
            try:
                load_completed_check(damaged)
                raise AssertionError("Changed human-readable report accepted")
            except ValueError:
                pass
            missing_case = next(case for case in manifest["cases"] if case["case_id"] == "missing_inlet")
            assert read_outcome(shared, missing_case, 2000)["status"] == "checked"
            assert read_outcome(damaged, missing_case, 2000)["status"] == "unscored"
            malformed = output / "synthetic-malformed-report"
            malformed.mkdir()
            bad_report = {"schema_version": "diagnosis-0.1", "status": "checked", "findings": [{"code": "MISSING_INLET"}]}
            _write_json(malformed / "diagnosis.json", bad_report)
            bad_metadata = copy.deepcopy(load_completed_check(shared)["metadata"])
            bad_metadata.update(synthetic_input=True, comsol_version="synthetic malformed report; no COMSOL run",
                                source={"filename": "synthetic-invalid-report.NO-MODEL.mph", "sha256": "0" * 64},
                                diagnosis_sha256=sha256(malformed / "diagnosis.json"))
            _write_json(malformed / "run.json", bad_metadata)
            try:
                load_completed_check(malformed)
                raise AssertionError("Malformed finding accepted")
            except CheckError:
                pass
            assert read_outcome(malformed, {"sha256": "0" * 64}, 2000)["status"] == "unscored"
            result["report_reader"] = {"valid_package_scored": True, "damaged_package_unscored": True,
                                        "malformed_finding_rejected_by_reader": True,
                                        "malformed_finding_unscored": True, "malformed_input_is_synthetic": True}
            result["report_package"] = {"dialog_handler_verified": True, "reimport_verified": True,
                                         "human_readable_tamper_rejected": True,
                                         "model_or_log_copied": False, "files": sorted(package_manifest["files"]),
                                         "manifest_sha256": sha256(shared / "package.json")}
            # Synthetic numeric evidence only: never attribute these values to a real MPH.
            result["synthetic_numeric_views"] = []
            baseline_model = load_completed_check(completed_directories["baseline"])["report"]["model"]
            for identity, density, speed, reason in (("overflow", 1e300, 1e100, "above_float_range"),
                                                     ("underflow", 1e-300, 1e-100, "below_nonzero_float_range")):
                model = copy.deepcopy(baseline_model)
                model["source"]["comsol_version"] = "synthetic numeric test; no COMSOL run"
                model["geometry"]["height_m"] = 1
                model["material"]["density"].update(expression=str(density), value=density)
                model["material"]["dynamic_viscosity"].update(expression="1", value=1)
                inlet = next(item for item in model["boundaries"] if item["type"] == "inlet")
                inlet["parameters"]["normal_velocity"].update(expression=str(speed), value=speed)
                report = {"model": model, **check(model)}
                synthetic = output / ("synthetic-numeric-" + identity)
                synthetic.mkdir()
                _write_json(synthetic / "diagnosis.json", report)
                _write_json(synthetic / "run.json", {"schema_version": "check-run-0.1", "status": "completed",
                            "synthetic_input": True, "comsol_version": "synthetic numerics; no COMSOL model",
                            "source": {"filename": "synthetic-numeric-" + identity + ".mph", "sha256": "0" * 64},
                            "diagnosis_status": "partial", "diagnosis_sha256": sha256(synthetic / "diagnosis.json")})
                app.show_result(load_completed_check(synthetic))
                assert app.current_view["tone"] == "incomplete"
                assert "部分检查未完成" in app.status.get()
                assert app.current_overview["available"]
                assert reason in app.details.get("1.0", "end")
                assert "数值量级" in app.details.get("1.0", "end")
                exported = export_package(synthetic, output / ("synthetic-package-" + identity))
                assert load_completed_check(exported)["report"] == report
                result["synthetic_numeric_views"].append({"synthetic_input": True, "real_comsol_validation": False,
                                                          "reason": reason, "diagnosis_status": "partial",
                                                          "desktop_tone": app.current_view["tone"],
                                                          "package_reimport_verified": True})
            app.model.set(str(ROOT / manifest["cases"][0]["model_path"]))
            app.start_check()
            assert app.compare_button.instate(["disabled"])
            assert app.history_button.instate(["disabled"])
            assert app.export_button.instate(["disabled"])
            wait_for_session(cancel=True)
            assert app.session.state == "cancelled", app.session.error
            assert app.session.result is None
            assert app.current_view is None
            assert app.current_overview is None
            assert "本次尚无" in app.overview_text.get("1.0", "end")
            assert app.report_button.instate(["disabled"])
            assert app.compare_button.instate(["disabled"])
            assert app.export_button.instate(["disabled"])
            assert not (app.session.directory / "check/diagnosis.json").exists()
            result["real_cancellation"] = {"status": app.session.state,
                                             "requested_after_batch_console_created": True,
                                             "check_run_sha256": sha256(app.session.directory / "check/run.json")}
            assert app.history_button.instate(["!disabled"])
            browser = app.show_history()
            browser.window.withdraw()
            deadline = time.monotonic() + 10
            while browser.scanning:
                root.update()
                assert not errors, errors
                if time.monotonic() > deadline:
                    raise CheckError("History scan exceeded 10 seconds")
                time.sleep(0.025)
            assert len(browser.records) == 3
            counts = {state: sum(entry["status"] == state for entry in browser.records.values())
                      for state in ("completed", "cancelled", "failed", "invalid", "unconfirmed")}
            assert counts == {"completed": 2, "cancelled": 1, "failed": 0, "invalid": 0, "unconfirmed": 0}
            missing_key = next(key for key, entry in browser.records.items() if entry["model"] == "missing_inlet.mph")
            browser.tree.selection_set(missing_key)
            browser.select_entry()
            assert browser.open_button.instate(["!disabled"])
            browser.open_selected()
            assert app.current_view["items"][0]["code"] == "MISSING_INLET"
            cancelled_key = next(key for key, entry in browser.records.items() if entry["status"] == "cancelled")
            browser.tree.selection_set(cancelled_key)
            browser.select_entry()
            assert browser.open_button.instate(["disabled"])
            browser.close()
            root.update_idletasks()
            result["history_browser"] = {"record_counts": counts, "verified_report_opened": "missing_inlet",
                                          "cancelled_report_open_disabled": True, "scan_ran_in_worker": True}
        result["event_loop_heartbeat_count"] = beats[0]
        assert beats[0] > 0
        result["source_hashes_unchanged"] = all(sha256(ROOT / case["model_path"]) == before[case["case_id"]]
                                                for case in manifest["cases"])
        assert result["source_hashes_unchanged"]
        result["passed"] = True
        _write_json(output / "verification.json", result)
        print("Desktop smoke passed; hidden-window functional checks only", flush=True)
    finally:
        # On an unexpected test failure, request cancellation and wait before dropping the UI.
        if app.session.busy:
            app.session.cancel()
            deadline = time.monotonic() + 30
            while app.session.busy and time.monotonic() < deadline:
                app.session.poll()
                time.sleep(0.1)
        if app._after_id is not None:
            root.after_cancel(app._after_id)
        root.destroy()


if __name__ == "__main__":
    main()
