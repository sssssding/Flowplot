"""Hidden Tk functional smoke against real existing reports; not visible/user acceptance."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.check_model import _write_json, sha256
from flowpilot.desktop_session import load_completed_check
from flowpilot.recommend import read_json
from flowpilot.recommend_ui import RecommendationApp
from flowpilot.diagnostics import check
from flowpilot import portable_recommend
from flowpilot.recommend import export_recommendation
from flowpilot.report_package import export_package


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports-root", type=Path, required=True)
    parser.add_argument("--learned-model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    app = RecommendationApp(root, learned_model=args.learned_model)
    tests = {}
    try:
        baseline = load_completed_check(args.reports_root / "baseline")
        app.open_report(args.reports_root / "baseline")
        root.update()
        tests["baseline_recommendation_displayed"] = app.ai_result["status"] == "recommended"
        tests["learned_model_bound"] = app.ai_result["learned_model_sha256"] == sha256(args.learned_model)
        tests["ai_tab_present"] = "AI 参数推荐" in [app.result_tabs.tab(tab, "text") for tab in app.result_tabs.tabs()]
        tests["offline_preview_selects_ai_tab"] = app.result_tabs.select() == str(app.ai_tab)
        tests["no_automatic_apply"] = "不自动修改" in app.ai_text.get("1.0", "end")
        opened = []
        with patch.object(app, "_open", side_effect=opened.append):
            app.report_button.invoke()
        tests["report_button_opens_current_markdown_without_import"] = opened == [baseline["directory"] / "report.md"]
        portable_run = app.ai_result.get("method") == portable_recommend.METHOD
        if portable_run:
            shown = app.ai_text.get("1.0", "end")
            tests["training_coverage_and_development_scope_visible"] = ("训练依据" in shown
                and "不是独立模型数" in shown and app.ai_result["training_coverage"]["observations"] > 0)
            tests["target_features_visible"] = "当前报告" in shown and "L/H=" in shown
            tests["mesh_uncertainty_visible"] = ("网格限制" in shown
                and app.ai_result["training_coverage"]["mesh_features_available"] is False)
            tests["validation_next_action_visible"] = "至少三次冷求解" in shown and "质量失败不接受速度收益" in shown
            with patch("flowpilot.portable_recommend.os.cpu_count", return_value=1):
                app.refresh_recommendation()
            tests["single_cpu_explanation_is_not_speed_claim"] = (app.ai_result["selected"]["threads"] == 1
                and "资源约束" in app.ai_text.get("1.0", "end"))
            app.refresh_recommendation()
        for case in ("missing_inlet", "missing_outlet", "selection_overlap", "reversed_inlet", "high_reynolds"):
            app.show_result(load_completed_check(args.reports_root / case))
            root.update()
            tests[case + "_abstained"] = app.ai_result["status"] == "unavailable" and app.ai_result["selected"] is None
        app.show_result(baseline)
        app.clear_result()
        tests["stale_recommendation_cleared"] = app.ai_result is None and "尚无有效报告" in app.ai_text.get("1.0", "end")
        app.show_result(baseline)
        app.learned_model = args.learned_model.parent / "missing-model.json"
        app.refresh_recommendation()
        tests["missing_model_not_stale"] = app.ai_result is None and "暂不能推荐" in app.ai_text.get("1.0", "end")
        app.set_busy(True)
        tests["busy_buttons_disabled"] = str(app.ai_refresh_button["state"]) == "disabled"
        app.set_busy(False)
        tests["idle_buttons_enabled"] = str(app.ai_refresh_button["state"]) == "normal"
        app.open_report(args.reports_root / "baseline")
        try:
            app.open_report(args.reports_root / "missing-report-directory")
        except (OSError, ValueError, RuntimeError):
            pass
        else:
            raise AssertionError("Missing report must be rejected")
        tests["invalid_preview_clears_old_recommendation"] = app.ai_result is None and app.current_view is None
        app.learned_model = args.learned_model
        # Only mutate our own temporary report, never the real input reports.
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            run_bytes = (args.reports_root / "baseline/run.json").read_bytes()
            diagnosis_bytes = (args.reports_root / "baseline/diagnosis.json").read_bytes()
            (directory / "run.json").write_bytes(run_bytes)
            (directory / "diagnosis.json").write_bytes(diagnosis_bytes)
            app.open_report(directory)
            metadata = copy.deepcopy(baseline["metadata"])
            metadata["finished_at"] = "synthetic metadata change for snapshot regression"
            (directory / "run.json").write_text(json.dumps(metadata), encoding="utf-8")
            app.refresh_recommendation()
            tests["metadata_change_blocks_manual_refresh"] = app.ai_result is None and "重新读取报告" in app.ai_text.get("1.0", "end")
            warning = {"model": baseline["report"]["model"], **check(baseline["report"]["model"], reynolds_warning=100)}
            (directory / "diagnosis.json").write_text(json.dumps(warning), encoding="utf-8")
            metadata["diagnosis_sha256"] = sha256(directory / "diagnosis.json")
            metadata["diagnosis_status"] = warning["status"]
            metadata["settings"] = {"reynolds_warning": 100}
            (directory / "run.json").write_text(json.dumps(metadata), encoding="utf-8")
            old_warning = load_completed_check(directory)
            app.refresh_recommendation()
            tests["diagnosis_change_blocks_manual_refresh"] = app.ai_result is None and "重新读取报告" in app.ai_text.get("1.0", "end")
            (directory / "run.json").write_bytes(run_bytes)
            (directory / "diagnosis.json").write_bytes(diagnosis_bytes)
            app.show_result(old_warning)
            tests["old_warning_cannot_show_new_recommendation"] = (app.ai_result is None
                and any(item["code"] == "REYNOLDS_RISK" for item in app.current_view["items"]))
            app.open_report(directory)
            tests["explicit_reread_restores_matching_recommendation"] = (app.ai_result["status"] == "recommended"
                and app.ai_result["run_sha256"] == baseline["run_sha256"]
                and app.ai_result["diagnosis_sha256"] == baseline["diagnosis_sha256"])
            original_rank = portable_recommend.rank
            def change_metadata(*args, **kwargs):
                changed = copy.deepcopy(baseline["metadata"])
                changed["finished_at"] = "synthetic change during recommendation"
                (directory / "run.json").write_text(json.dumps(changed), encoding="utf-8")
                return original_rank(*args, **kwargs)
            with patch.object(portable_recommend, "rank", side_effect=change_metadata):
                app.refresh_recommendation()
            tests["metadata_change_during_ranking_clears_ai"] = (app.ai_result is None
                and "重新读取报告" in app.ai_text.get("1.0", "end"))
            (directory / "run.json").write_bytes(run_bytes)
            app.open_report(directory)
            def change_diagnosis(*args, **kwargs):
                (directory / "diagnosis.json").write_text(json.dumps(warning), encoding="utf-8")
                changed = copy.deepcopy(baseline["metadata"])
                changed.update(diagnosis_sha256=sha256(directory / "diagnosis.json"),
                               diagnosis_status=warning["status"], settings={"reynolds_warning": 100})
                (directory / "run.json").write_text(json.dumps(changed), encoding="utf-8")
                return original_rank(*args, **kwargs)
            with patch.object(portable_recommend, "rank", side_effect=change_diagnosis):
                app.refresh_recommendation()
            tests["diagnosis_change_during_ranking_clears_ai"] = (app.ai_result is None
                and "重新读取报告" in app.ai_text.get("1.0", "end"))
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            if portable_run:
                synthetic = directory / "synthetic-outside-coverage"
                synthetic.mkdir()
                changed_model = copy.deepcopy(baseline["report"]["model"])
                changed_model["geometry"]["length_m"] = 5.
                changed_report = {"model": changed_model, **check(changed_model)}
                _write_json(synthetic / "diagnosis.json", changed_report)
                changed_metadata = copy.deepcopy(baseline["metadata"])
                changed_metadata.update(diagnosis_sha256=sha256(synthetic / "diagnosis.json"),
                                        diagnosis_status=changed_report["status"])
                _write_json(synthetic / "run.json", changed_metadata)
                app.open_report(synthetic)
                tests["outside_coverage_explains_dimension_and_range"] = (app.ai_result["status"] == "unavailable"
                    and "长度 L=5" in app.ai_text.get("1.0", "end") and "0.5–2" in app.ai_text.get("1.0", "end"))
            package = export_package(args.reports_root / "baseline", directory / "package")
            try:
                export_recommendation(package, package / "candidate.json", args.learned_model)
            except (OSError, ValueError, RuntimeError):
                pass
            else:
                raise AssertionError("Recommendation output inside package must be rejected")
            tests["recommendation_export_keeps_package_readable"] = (not (package / "candidate.json").exists()
                and load_completed_check(package)["report"] == baseline["report"])
            output = directory / "candidate.json"
            exported = export_recommendation(package, output, args.learned_model)
            tests["separate_recommendation_export_binds_package_snapshot"] = (read_json(output) == exported
                and exported["run_sha256"] == load_completed_check(package)["run_sha256"])
        result = {"schema_version": "ai-functional-smoke-0.1", "mode": "hidden-tk-existing-real-reports",
                  "all_passed": all(tests.values()), "checks": tests, "solver_run_in_smoke": False,
                  "visible_user_acceptance": False, "independent_performance_validation": False,
                  "snapshot_regression_inputs_synthetic": True,
                  "explanation_regression_inputs_synthetic": portable_run,
                  "report_button_default_viewer_mocked": True,
                  "source_sha256": {p: sha256(ROOT / p) for p in ("src/flowpilot/recommend.py",
                      "src/flowpilot/portable_recommend.py", "src/flowpilot/benchmark_portable.py", "src/comsol/PortableFamily.java",
                      "src/flowpilot/acceptance_dataset.py", "data/fixtures/ai_development_registry.json",
                      "src/flowpilot/recommend_ui.py", "src/flowpilot/calibrate_solver.py",
                      "src/flowpilot/desktop.py", "src/flowpilot/ai_launcher.py", "FlowPlotAI.cmd",
                      "scripts/smoke_ai_recommendation.py")},
                  "learned_model_sha256": sha256(args.learned_model),
                  "calibration_observations": (sum(len(c["observations"]) for c in read_json(args.learned_model)["data"]["cases"])
                      if read_json(args.learned_model).get("schema_version") == "solver-ranker-0.2"
                      else len(read_json(args.learned_model)["dataset"]["observations"]))}
        _write_json(args.output, result)
        if not result["all_passed"]:
            raise AssertionError(tests)
        print(f"{len(tests)} hidden Tk checks passed; no solver run, no visible-user acceptance.")
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
