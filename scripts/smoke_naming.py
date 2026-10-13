"""Hidden Tk naming/old-report compatibility check, not visual or new-user acceptance."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.check_model import CheckError, _write_json, sha256
from flowpilot.compare_reports import compare_reports
from flowpilot.desktop import DesktopApp
from flowpilot.desktop_session import load_completed_check
from flowpilot.report_package import export_package
from flowpilot.report_io import decode_json, read_regular_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    reports = args.reports_root.resolve(strict=True)
    output = args.output_dir.resolve()
    if output.is_relative_to(reports):
        raise CheckError("Output must be outside the input reports")
    manifest = decode_json(read_regular_file(ROOT / "data/fixtures/cases/manifest.json", max_bytes=65536))
    # Existing development reports only; no model loading or solver is invoked.
    loaded = {case["case_id"]: load_completed_check(reports / case["case_id"]) for case in manifest["cases"]}
    model_hashes = {case["case_id"]: sha256(ROOT / case["model_path"]) for case in manifest["cases"]}
    if any(model_hashes[case["case_id"]] != case["sha256"].lower() for case in manifest["cases"]):
        raise CheckError("Original models do not match manifest")
    sources = ("FlowPlot.cmd", "FlowPilot.cmd", "src/flowpilot/desktop.py", "src/flowpilot/launcher.py",
               "src/flowpilot/history_window.py", "src/flowpilot/check_model.py",
               "src/flowpilot/compare_reports.py", "src/flowpilot/report_package.py", "scripts/smoke_naming.py")
    source_hashes = {name: sha256(ROOT / name) for name in sources}
    output.mkdir(parents=True, exist_ok=False)
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    browser = comparison = None
    app = None
    errors = []
    try:
        app = DesktopApp(root, output_root=output / "sessions")
        root.report_callback_exception = lambda kind, error, traceback: errors.append(str(error))
        assert root.title() == "FlowPlot · 模型边界检查"
        widgets, labels = [root], []
        while widgets:
            widget = widgets.pop()
            widgets.extend(widget.winfo_children())
            if "text" in widget.keys():
                labels.append(str(widget.cget("text")))
        assert "FlowPlot 模型边界检查" in labels
        for report in loaded.values():
            app.show_result(report)
            root.update_idletasks()
            assert app.current_view["headline"] == report["view"]["headline"]
        summary = compare_reports(reports / "baseline", reports / "missing_inlet")
        comparison = app.show_comparison(summary)
        comparison.withdraw()
        assert comparison.title() == "FlowPlot · 前次 / 本次检查对比"
        browser = app.show_history()
        browser.window.withdraw()
        assert browser.window.title() == "FlowPlot · 检查历史"
        deadline = time.monotonic() + 10
        while browser.scanning:
            root.update()
            if errors or time.monotonic() > deadline:
                raise CheckError("History did not complete: " + "; ".join(errors))
            time.sleep(0.025)
        package = export_package(reports / "missing_inlet", output / "report-package")
        assert (package / "report.md").read_text(encoding="utf-8").startswith("# FlowPlot 协作检查报告")
        assert (package / "README.md").read_text(encoding="utf-8").startswith("# FlowPlot 协作报告包")
        assert load_completed_check(package)["report"] == loaded["missing_inlet"]["report"]
        assert not errors, errors
        assert source_hashes == {name: sha256(ROOT / name) for name in sources}
        assert model_hashes == {case["case_id"]: sha256(ROOT / case["model_path"]) for case in manifest["cases"]}
        result = {"schema_version": "naming-smoke-0.1", "application_name": "FlowPlot", "passed": True,
                  "window_hidden": True, "visual_review": False, "new_user_timing_validated": False,
                  "expert_review": False, "comsol_invoked": False, "models_unchanged": True,
                  "main_title": root.title(), "history_title": browser.window.title(),
                  "comparison_title": comparison.title(), "old_report_case_ids": list(loaded),
                  "new_package_reimport_verified": True, "source_sha256": source_hashes,
                  "source_model_sha256": model_hashes}
        _write_json(output / "verification.json", result)
        print("FlowPlot naming smoke passed; hidden Tk only, no COMSOL invoked.")
    finally:
        if browser is not None and not browser.closed:
            browser.close()
        if comparison is not None:
            comparison.destroy()
        if app is not None and app._after_id is not None:
            root.after_cancel(app._after_id)
        root.destroy()


if __name__ == "__main__":
    main()
