"""Three rounds of formal unsolved CLI demonstrations; no visible GUI or user acceptance."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from flowpilot.check_model import _write_json, sha256
from flowpilot.desktop_session import load_completed_check
from flowpilot.compare_reports import compare_reports
from flowpilot.report_package import export_package
from flowpilot.engine_fingerprint import ENGINE_SOURCES, engine_fingerprint
from verify_m3_consumers import CONSUMER_SOURCES, verify_thermal_consumption

SOURCES = tuple(sorted(set(ENGINE_SOURCES) | set(CONSUMER_SOURCES) | {
    "src/comsol/ModelInventory.java", "scripts/verify_m3_demo.py"}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-root", type=Path, required=True)
    parser.add_argument("--comsol-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--write-fixture", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    summary_path = args.api_root / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("schema_version") != "m3-api-evidence-1" or summary.get("solved") is not False:
        raise ValueError("Recorded unsolved M3 API evidence is required")
    if (summary.get("source_models_unchanged") is not True or summary.get("reads_per_model") != 3
            or summary.get("solution_sequences_per_model") != 0 or summary.get("license_baseline_available") is not True
            or summary.get("implementation_sha256") != summary.get("implementation_sha256_after")):
        raise ValueError("Complete stable repeated API evidence is required")
    extractor = "src/comsol/ModelInventory.java"
    if summary["implementation_sha256"].get(extractor) != sha256(ROOT / extractor):
        raise ValueError("API summary belongs to a different extractor")
    summary_digest = sha256(summary_path)
    models = [args.api_root / (name + ".mph") for name in ("normal", "reversed_inlet", "conjugate_normal")]
    for model in models:
        if sha256(model) != summary["output_model_sha256"].get(model.stem):
            raise ValueError("Model binding differs from API evidence: " + model.stem)
    before = {name: sha256(ROOT / name) for name in SOURCES}
    model_hashes = {path.name: sha256(path) for path in models}
    engine = engine_fingerprint()
    rows = []
    for index, model in enumerate(models * 3, 1):
        round_number = (index - 1) // 3 + 1
        directory = args.output / (str(index) + "_" + model.stem)
        command = [sys.executable, str(ROOT / "src/flowpilot/check_model.py"), str(model),
                   "--comsol-root", str(args.comsol_root), "--output-dir", str(directory),
                   "--loads", "1", "--timeout", str(args.timeout)]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=args.timeout + 120)
        (args.output / (str(index) + "_cli.log")).write_text(completed.stdout + completed.stderr, encoding="utf-8")
        if completed.returncode != 0:
            raise RuntimeError("Formal CLI demonstration failed: " + model.stem)
        loaded = load_completed_check(directory)
        report, metadata = loaded["report"], loaded["metadata"]
        assert report["schema_version"] == "diagnosis-0.4" and report["profile"] == "static-3d-v1"
        assert report["status"] == "checked", report.get("reason", report["coverage"])
        assert metadata["rule_engine_sha256"] == engine
        assert metadata["inventory_source_sha256"] == before["src/comsol/ModelInventory.java"]
        assert metadata["source"]["sha256"] == model_hashes[model.name]
        codes = {finding["code"] for finding in report["findings"]}
        expected = {"INLET_DIRECTION"} if model.stem == "reversed_inlet" else set()
        assert codes == expected, (model.stem, codes, expected)
        location = verify_thermal_consumption(loaded)
        package = export_package(directory, args.output / (str(index) + "_package"))
        assert load_completed_check(package)["report"] == report
        comparison = compare_reports(directory, package)
        assert comparison["status"] == "compared"
        assert model_hashes == {path.name: sha256(path) for path in models}
        assert before == {name: sha256(ROOT / name) for name in SOURCES}
        rows.append({"round": round_number, "check": index, "case_id": model.stem, "contract": report["schema_version"],
                     "status": report["status"], "finding_codes": sorted(codes),
                     "finding_sources": [f["source"] for f in report["findings"]],
                     "finding_entity_ids": [f["boundary_ids"] for f in report["findings"]],
                     "source_sha256": metadata["source"]["sha256"],
                     "run_sha256": loaded["run_sha256"], "diagnosis_sha256": loaded["diagnosis_sha256"],
                     "rule_engine_sha256": engine, "verified_loads": metadata["verified_loads"],
                     "report_package_roundtrip_verified": True, "comparison_status": comparison["status"], **location})
    assert summary_digest == sha256(summary_path)
    result = {"schema_version": "m3-demo-evidence-1", "status": "passed",
              "verified_at": datetime.now(timezone.utc).isoformat(), "solved": False,
              "visible_gui_acceptance": False, "user_acceptance": False,
              "scope": "Three automated rounds, each checking normal/reversed/conjugate models (nine formal CLI checks) under one fixed implementation; no visible GUI acceptance.",
              "api_summary_sha256": summary_digest, "api_summary_sha256_after": sha256(summary_path), "source_models_unchanged": True,
              "source_model_sha256": model_hashes, "source_model_sha256_after": {p.name: sha256(p) for p in models},
              "implementation_sha256": before, "implementation_sha256_after": {name: sha256(ROOT / name) for name in SOURCES},
              "rule_engine_sha256": engine, "cases": rows}
    _write_json(args.output / "summary.json", result)
    if args.write_fixture:
        _write_json(ROOT / "data/fixtures/m3_demo_evidence.json", result)
    print(json.dumps({"status": "passed", "rounds": 3, "checks": len(rows), "output": str(args.output)}))


if __name__ == "__main__":
    main()
