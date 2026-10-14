"""Hidden Tk functional smoke against real existing reports; not visible/user acceptance."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.check_model import _write_json, sha256
from flowpilot.desktop_session import load_completed_check
from flowpilot.recommend import read_json
from flowpilot.recommend_ui import RecommendationApp


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
        app.show_result(baseline)
        root.update()
        tests["baseline_recommendation_displayed"] = app.ai_result["status"] == "recommended"
        tests["learned_model_bound"] = app.ai_result["learned_model_sha256"] == sha256(args.learned_model)
        tests["ai_tab_present"] = "AI 参数推荐" in [app.result_tabs.tab(tab, "text") for tab in app.result_tabs.tabs()]
        tests["no_automatic_apply"] = "不自动修改" in app.ai_text.get("1.0", "end")
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
        result = {"schema_version": "ai-functional-smoke-0.1", "mode": "hidden-tk-existing-real-reports",
                  "all_passed": all(tests.values()), "checks": tests, "solver_run_in_smoke": False,
                  "visible_user_acceptance": False, "independent_performance_validation": False,
                  "source_sha256": {p: sha256(ROOT / p) for p in ("src/flowpilot/recommend.py",
                      "src/flowpilot/recommend_ui.py", "src/flowpilot/calibrate_solver.py",
                      "src/flowpilot/desktop.py", "src/flowpilot/ai_launcher.py", "FlowPlotAI.cmd",
                      "scripts/smoke_ai_recommendation.py")},
                  "learned_model_sha256": sha256(args.learned_model),
                  "calibration_observations": len(read_json(args.learned_model)["dataset"]["observations"])}
        _write_json(args.output, result)
        if not result["all_passed"]:
            raise AssertionError(tests)
        print(f"{len(tests)} hidden Tk checks passed; no solver run, no visible-user acceptance.")
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
