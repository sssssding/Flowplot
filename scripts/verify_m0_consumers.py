"""Offline M0 consumer smoke using genuine CLI reports and recorded API inventories.

Constructs hidden Tk widgets; does not load COMSOL, solve, or record user acceptance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.acceptance_dataset import SOURCES, REGISTRIES
from flowpilot.check_model import _write_json, render_report, sha256
from flowpilot.check_suite import DEVELOPMENT_MANIFEST, read_outcome
from flowpilot.compare_reports import compare_reports
from flowpilot.desktop import DesktopApp
from flowpilot.desktop_session import load_completed_check
from flowpilot.diagnostics import diagnose_inventory
from flowpilot.engine_fingerprint import engine_fingerprint
from flowpilot.recommend import DEFAULT_PORTABLE_MODEL, recommend_report
from flowpilot.recommend_ui import RecommendationApp
from flowpilot.report_history import load_history_report, scan_history
from flowpilot.report_package import export_package

CONSUMER_SOURCES = tuple(sorted(set((*SOURCES, *REGISTRIES)) | {
    "src/flowpilot/desktop.py", "src/flowpilot/recommend.py", "src/flowpilot/recommend_ui.py",
    "src/flowpilot/portable_recommend.py", "src/flowpilot/model_overview.py",
    "src/flowpilot/compare_reports.py", "src/flowpilot/report_package.py",
    "src/flowpilot/report_history.py", "src/flowpilot/history_window.py",
    "scripts/verify_m0_consumers.py", "data/fixtures/cases/manifest.json",
    DEFAULT_PORTABLE_MODEL.relative_to(ROOT).as_posix(),
}))


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                    separators=(",", ":")).encode()).hexdigest()


def replay_api(api_root, output):
    """Recorded real API evidence replay, explicitly distinct from a fresh CLI run."""
    summary = json.loads((api_root / "summary.json").read_text(encoding="utf-8"))
    if summary.get("solved") is not False or summary.get("schema_version") != "m0-api-evidence-1":
        raise ValueError("Expected genuine unsolved M0 API evidence summary")
    if summary["implementation_sha256"]["src/comsol/ModelInventory.java"] != sha256(ROOT / "src/comsol/ModelInventory.java"):
        raise ValueError("API evidence used a different inventory extractor")
    reports = []
    for name in ("unknown_physics", "unknown_coupling", "disabled_coupling", "missing_viscosity"):
        inventory_path = api_root / (name + ".inventory.json")
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        if canonical_digest(inventory) != summary["inventory_sha256"][name]:
            raise ValueError("Recorded API inventory binding mismatch: " + name)
        directory = output / name
        directory.mkdir()
        report = diagnose_inventory(inventory)
        _write_json(directory / "inventory.json", inventory)
        _write_json(directory / "diagnosis.json", report)
        metadata = {"schema_version": "check-run-0.1", "status": "completed",
                    "evidence_origin": "offline_replay_of_recorded_real_api_inventory",
                    "source": {"filename": name + ".mph", "sha256": sha256(api_root / (name + ".mph"))},
                    "diagnosis_status": report["status"], "diagnosis_sha256": sha256(directory / "diagnosis.json"),
                    "inventory_sha256": sha256(directory / "inventory.json"),
                    "api_inventory_sha256": sha256(inventory_path),
                    "api_summary_sha256": sha256(api_root / "summary.json"),
                    "rule_engine_sha256": engine_fingerprint(),
                    "inventory_source_sha256": sha256(ROOT / "src/comsol/ModelInventory.java"),
                    "comsol_version": inventory["comsol_version"], "verified_loads": summary["reads_per_model"],
                    "settings": {"reynolds_warning": 2000}}
        _write_json(directory / "run.json", metadata)
        (directory / "report.md").write_text(render_report(report, metadata), encoding="utf-8")
        reports.append(("api_" + name, directory, metadata["evidence_origin"]))
    return reports, sha256(api_root / "summary.json")


def exercise(name, directory, origin, output, desktop, ai, roots):
    loaded = load_completed_check(directory)
    report, metadata = loaded["report"], loaded["metadata"]
    modern = report["schema_version"] == "diagnosis-0.2"
    historical = origin == "historical_real_cli_report"
    if modern and metadata["rule_engine_sha256"] != engine_fingerprint():
        raise ValueError("Modern report used a different engine: " + name)
    desktop.show_result(loaded)
    ai.open_report(directory)
    for root in roots:
        root.update_idletasks()
        assert root.state() == "withdrawn"
    assert desktop.current_view == loaded["view"] == ai.current_view
    assert desktop.tree.get_children() == tuple(str(i) for i in range(len(report["findings"])))
    assert desktop.overview_text.get("1.0", "end").strip() == desktop.current_overview["text"].strip()
    if report["status"] != "checked":
        assert desktop.current_view["tone"] == "incomplete"
    if name in ("api_unknown_physics", "api_unknown_coupling"):
        assert report["status"] in ("partial", "unsupported") and not report["findings"]
        assert any(entry["status"] in ("unknown", "skipped") for entry in report["coverage"])
    if modern:
        assert "检查覆盖" in desktop.current_overview["text"]
        assert "检查覆盖" in loaded["view"]["detail"]
        for finding, item in zip(report["findings"], loaded["view"]["items"]):
            assert finding["source"]["component_tag"] in item["detail"]
            assert finding["source"]["physics_tag"] in item["detail"]
    else:
        assert loaded["view"]["coverage"] is None and "coverage" not in report
    entries = scan_history(directory.parent)
    assert any(item["id"] == directory.name for item in entries["entries"])
    assert load_history_report(directory.parent, directory.name)["report"] == report
    package = export_package(directory, output / (name + "_package"))
    assert load_completed_check(package)["report"] == report
    comparison = compare_reports(directory, package)
    expected = "compared" if report["status"] == "checked" else "not_comparable"
    assert comparison["status"] == expected
    recommendation = recommend_report(directory)
    assert ai.ai_result == recommendation
    if name == "baseline":
        assert recommendation["status"] == "recommended"
    elif not historical:
        assert recommendation["status"] == "unavailable"
    return {"case_id": name, "origin": origin, "contract": report["schema_version"],
            "status": report["status"], "finding_codes": [f["code"] for f in report["findings"]],
            "finding_sources": [f.get("source") for f in report["findings"]],
            "coverage": report.get("coverage"), "tone": loaded["view"]["tone"],
            "run_sha256": loaded["run_sha256"], "diagnosis_sha256": loaded["diagnosis_sha256"],
            "rule_engine_sha256": metadata.get("rule_engine_sha256"),
            "inventory_source_sha256": metadata.get("inventory_source_sha256"),
            "source_sha256": metadata["source"]["sha256"], "inventory_sha256": metadata.get("inventory_sha256"),
            "api_inventory_sha256": metadata.get("api_inventory_sha256"),
            "api_summary_sha256": metadata.get("api_summary_sha256"),
            "comparison_status": comparison["status"], "recommendation_status": recommendation["status"],
            "hidden_widgets_verified": True, "history_verified": True, "package_roundtrip_verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-root", type=Path, required=True)
    parser.add_argument("--api-root", type=Path, required=True)
    parser.add_argument("--legacy-reports-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--write-fixture", action="store_true")
    args = parser.parse_args()
    before = {name: sha256(ROOT / name) for name in CONSUMER_SOURCES}
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads(DEVELOPMENT_MANIFEST.read_text(encoding="utf-8-sig"))
    reports = []
    for case in manifest["cases"]:
        directory = args.reports_root / case["case_id"]
        assert read_outcome(directory, case, 2000)["status"] == "checked"
        loaded = load_completed_check(directory)
        assert loaded["report"]["schema_version"] == "diagnosis-0.2"
        assert loaded["metadata"].get("stage") == "complete"
        assert "evidence_origin" not in loaded["metadata"]
        assert sha256(directory / "inventory.json") == loaded["metadata"]["inventory_sha256"]
        reports.append((case["case_id"], directory, "fresh_real_cli_report"))
    api_reports, api_summary_digest = replay_api(args.api_root, args.output)
    reports += api_reports
    if args.legacy_reports_root:
        for case in manifest["cases"]:
            directory = args.legacy_reports_root / case["case_id"]
            assert load_completed_check(directory)["report"]["schema_version"] == "diagnosis-0.1"
            reports.append(("legacy_" + case["case_id"], directory, "historical_real_cli_report"))
    import tkinter as tk
    roots = [tk.Tk(), tk.Tk()]
    for root in roots:
        root.withdraw()
    rows = []
    try:
        desktop, ai = DesktopApp(roots[0]), RecommendationApp(roots[1])
        for name, directory, origin in reports:
            rows.append(exercise(name, directory, origin, args.output, desktop, ai, roots))
    finally:
        for root in roots:
            root.destroy()
    assert before == {name: sha256(ROOT / name) for name in CONSUMER_SOURCES}
    result = {"schema_version": "m0-consumer-smoke-1", "verified_at": datetime.now(timezone.utc).isoformat(),
              "status": "passed", "solved": False, "visible_gui_acceptance": False,
              "user_acceptance": False, "hidden_tk_only": True,
              "scope": "Offline consumption of real CLI reports and recorded real API inventories; no new COMSOL execution.",
              "implementation_sha256": before, "rule_engine_sha256": engine_fingerprint(),
              "api_summary_sha256": api_summary_digest, "cases": rows}
    _write_json(args.output / "summary.json", result)
    if args.write_fixture:
        (ROOT / "data/fixtures/m0_consumer_smoke.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "cases": len(rows), "status": "passed"}))


if __name__ == "__main__":
    main()
