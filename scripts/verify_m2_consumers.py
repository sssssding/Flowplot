"""Consume recorded real M2 API evidence with hidden Tk; never execute COMSOL or solve."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from verify_m0_consumers import CONSUMER_SOURCES as M0_SOURCES, canonical_digest
from flowpilot.check_model import _write_json, render_report, sha256
from flowpilot.compare_reports import compare_reports
from flowpilot.desktop import DesktopApp
from flowpilot.desktop_session import load_completed_check
from flowpilot.diagnostics import diagnose_inventory
from flowpilot.engine_fingerprint import engine_fingerprint
from flowpilot.model_overview import build_overview
from flowpilot.portable_recommend import model_features
from flowpilot.recommend_ui import RecommendationApp
from flowpilot.recommend import recommend_report
from flowpilot.report_history import load_history_report, scan_history
from flowpilot.report_package import export_package

CONSUMER_SOURCES = tuple(sorted(set(M0_SOURCES) | {"scripts/verify_m2_consumers.py", "src/flowpilot/coverage_view.py", "src/flowpilot/engine_fingerprint.py", "src/flowpilot/diagnostic_modules/heat.py", "src/flowpilot/diagnostic_modules/thermal_coupling.py"}))


def exercise(name, directory, origin, output, desktop, ai, roots):
    loaded = load_completed_check(directory)
    report, metadata = loaded["report"], loaded["metadata"]
    historical = origin == "historical_real_cli_report"
    if not historical:
        assert metadata["rule_engine_sha256"] == engine_fingerprint()
    desktop.show_result(loaded)
    ai.open_report(directory)
    for root in roots:
        root.update_idletasks()
        assert root.state() == "withdrawn"
    assert desktop.current_view == loaded["view"] == ai.current_view
    assert desktop.tree.get_children() == tuple(str(i) for i in range(len(report["findings"])))
    assert desktop.overview_text.get("1.0", "end").strip() == desktop.current_overview["text"].strip()
    for index, item in enumerate(loaded["view"]["items"]):
        desktop.tree.selection_set(str(index))
        desktop.select_finding()
        assert item["detail"] in desktop.details.get("1.0", "end")
    if report["status"] != "checked":
        assert loaded["view"]["tone"] == "incomplete"
    if report["schema_version"] in ("diagnosis-0.2", "diagnosis-0.3"):
        assert "检查覆盖" in desktop.current_overview["text"]
        for finding, item in zip(report["findings"], loaded["view"]["items"]):
            assert finding["source"]["component_tag"] in item["detail"]
            for key in ("physics_tag", "coupling_tag"):
                if finding["source"].get(key):
                    assert finding["source"][key] in item["detail"]
    assert any(item["id"] == directory.name for item in scan_history(directory.parent)["entries"])
    assert load_history_report(directory.parent, directory.name)["report"] == report
    package = export_package(directory, output / (name + "_package"))
    assert load_completed_check(package)["report"] == report
    comparison = compare_reports(directory, package)
    assert comparison["status"] == ("compared" if report["status"] == "checked" else "not_comparable")
    recommendation = recommend_report(directory)
    assert ai.ai_result == recommendation
    if not historical:
        assert recommendation["status"] == "unavailable"
    return {"case_id": name, "origin": origin, "contract": report["schema_version"],
            "status": report["status"], "finding_codes": [f["code"] for f in report["findings"]],
            "finding_sources": [f.get("source") for f in report["findings"]],
            "coverage": report.get("coverage"), "tone": loaded["view"]["tone"],
            "run_sha256": loaded["run_sha256"], "diagnosis_sha256": loaded["diagnosis_sha256"],
            "rule_engine_sha256": metadata.get("rule_engine_sha256"),
            "inventory_source_sha256": metadata.get("inventory_source_sha256"),
            "source_sha256": metadata["source"]["sha256"], "inventory_sha256": metadata.get("inventory_sha256"),
            "api_inventory_sha256": metadata.get("api_inventory_sha256"), "api_summary_sha256": metadata.get("api_summary_sha256"),
            "comparison_status": comparison["status"], "recommendation_status": recommendation["status"],
            "hidden_widgets_verified": True, "history_verified": True, "package_roundtrip_verified": True}


def replay_api(api_root, output):
    summary_path = api_root / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("schema_version") != "m2-api-evidence-1" or summary.get("solved") is not False:
        raise ValueError("Expected recorded unsolved M2 API evidence")
    if (summary.get("source_models_unchanged") is not True or summary.get("license_baseline_available") is not True
            or summary.get("reads_per_model") != 3 or summary.get("solution_sequences_per_model") != 0
            or summary["implementation_sha256"] != summary["implementation_sha256_after"]):
        raise ValueError("Real API verification prerequisites are incomplete")
    if summary["implementation_sha256"]["src/comsol/ModelInventory.java"] != sha256(ROOT / "src/comsol/ModelInventory.java"):
        raise ValueError("API evidence used a different extractor")
    reports = []
    for name, expected in sorted(summary["inventory_sha256"].items()):
        inventory_path, model_path = api_root / (name + ".inventory.json"), api_root / (name + ".mph")
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        if canonical_digest(inventory) != expected:
            raise ValueError("API inventory binding mismatch: " + name)
        if sha256(model_path) != summary["output_model_sha256"][name]:
            raise ValueError("Recorded real model binding mismatch: " + name)
        directory = output / name
        directory.mkdir()
        report = diagnose_inventory(inventory)
        _write_json(directory / "inventory.json", inventory)
        _write_json(directory / "diagnosis.json", report)
        metadata = {"schema_version": "check-run-0.1", "status": "completed",
                    "evidence_origin": "offline_replay_of_recorded_real_api_inventory",
                    "source": {"filename": model_path.name, "sha256": sha256(model_path)},
                    "diagnosis_status": report["status"], "diagnosis_sha256": sha256(directory / "diagnosis.json"),
                    "inventory_sha256": sha256(directory / "inventory.json"),
                    "api_inventory_sha256": sha256(inventory_path), "api_summary_sha256": sha256(summary_path),
                    "rule_engine_sha256": engine_fingerprint(),
                    "inventory_source_sha256": sha256(ROOT / "src/comsol/ModelInventory.java"),
                    "comsol_version": inventory["comsol_version"], "verified_loads": summary["reads_per_model"],
                    "settings": {"reynolds_warning": 2000}}
        _write_json(directory / "run.json", metadata)
        (directory / "report.md").write_text(render_report(report, metadata), encoding="utf-8")
        reports.append((name, directory, metadata["evidence_origin"]))
    if not reports:
        raise ValueError("No real M2 API inventories")
    return reports, sha256(summary_path)


def verify_thermal_consumption(loaded):
    report = loaded["report"]
    overview = build_overview(report)
    assert overview["available"] and "检查覆盖" in overview["text"]
    for finding, item in zip(report["findings"], loaded["view"]["items"]):
        assert "COMSOL 定位" in item["detail"]
        for key, tag in finding["source"].items():
            if tag:
                assert tag in item["detail"]
        for tag in finding["feature_tags"]:
            assert tag in item["nodes"]
        for entity in finding["boundary_ids"]:
            assert str(entity) in item["boundaries"]
    return {"overview_available": True, "node_entity_location_verified": True,
            "thermal_contract_verified": report["schema_version"] == "diagnosis-0.3"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-root", type=Path, required=True)
    parser.add_argument("--legacy-reports-root", type=Path, required=True)
    parser.add_argument("--m0-reports-root", type=Path, required=True)
    parser.add_argument("--m1-reports-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--write-fixture", action="store_true")
    args = parser.parse_args()
    before = {name: sha256(ROOT / name) for name in CONSUMER_SOURCES}
    args.output.mkdir(parents=True, exist_ok=False)
    reports, api_digest = replay_api(args.api_root, args.output)
    legacy = sorted(path.parent for path in args.legacy_reports_root.glob("*/run.json"))
    if not legacy:
        raise ValueError("Historical reports are required")
    for directory in legacy:
        assert load_completed_check(directory)["report"]["schema_version"] == "diagnosis-0.1"
        reports.append(("legacy_" + directory.name, directory, "historical_real_cli_report"))
    modern_history = sorted(path.parent for path in args.m0_reports_root.glob("*/run.json"))
    if not modern_history:
        raise ValueError("Historical M0 diagnosis-0.2 reports are required")
    for directory in modern_history:
        assert load_completed_check(directory)["report"]["schema_version"] == "diagnosis-0.2"
        reports.append(("m0_" + directory.name, directory, "historical_real_cli_report"))
    m1_history = sorted(path.parent for path in args.m1_reports_root.glob("*/run.json"))
    if not m1_history:
        raise ValueError("Historical M1 diagnosis-0.2 reports are required")
    for directory in m1_history:
        assert load_completed_check(directory)["report"]["schema_version"] == "diagnosis-0.2"
        reports.append(("m1_" + directory.name, directory, "historical_real_cli_report"))
    import tkinter as tk
    roots = [tk.Tk(), tk.Tk()]
    for root in roots:
        root.withdraw()
    rows = []
    try:
        desktop, ai = DesktopApp(roots[0]), RecommendationApp(roots[1])
        for name, directory, origin in reports:
            row = exercise(name, directory, origin, args.output, desktop, ai, roots)
            if origin != "historical_real_cli_report":
                row.update(verify_thermal_consumption(load_completed_check(directory)))
            rows.append(row)
    finally:
        for root in roots:
            root.destroy()
    assert any(row.get("thermal_contract_verified") for row in rows), "No real thermal report was consumed"
    assert before == {name: sha256(ROOT / name) for name in CONSUMER_SOURCES}
    result = {"schema_version": "m2-consumer-smoke-1", "verified_at": datetime.now(timezone.utc).isoformat(),
              "status": "passed", "solved": False, "visible_gui_acceptance": False,
              "user_acceptance": False, "hidden_tk_only": True,
              "scope": "Offline replay of recorded real M2 API inventories and historical reports; no fresh COMSOL execution.",
              "implementation_sha256": before, "rule_engine_sha256": engine_fingerprint(),
              "api_summary_sha256": api_digest, "cases": rows}
    _write_json(args.output / "summary.json", result)
    if args.write_fixture:
        (ROOT / "data/fixtures/m2_consumer_smoke.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "cases": len(rows), "status": "passed"}))


if __name__ == "__main__":
    main()
