"""Compare M0 with commit 1241c27 on six new reads and fourteen historical reads.

Only consumes existing real inventories; does not start COMSOL or solve a model.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.check_model import _write_json, sha256
from flowpilot.check_suite import DEVELOPMENT_MANIFEST
from flowpilot.desktop_session import load_completed_check
from flowpilot.diagnostics import diagnose_inventory
from flowpilot.engine_fingerprint import ENGINE_SOURCES, engine_fingerprint
from flowpilot.regression_family import SPECS, case_evidence

BASELINE_COMMIT = "1241c27"
LEGACY_SOURCES = ("src/flowpilot/diagnostics.py", "schema/diagnostic-model.schema.json", "src/comsol/ModelInventory.java")
SOURCES = tuple(sorted(set((*ENGINE_SOURCES, *LEGACY_SOURCES, "src/flowpilot/regression_family.py",
                            "scripts/verify_m0_regression.py", "data/fixtures/cases/manifest.json"))))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def legacy_projection(report):
    projected = {key: report[key] for key in ("status", "model", "profile", "numeric_policy", "findings") if key in report}
    projected["schema_version"] = "diagnosis-0.1"
    projected["findings"] = [{key: value for key, value in item.items() if key not in ("module", "source")}
                             for item in report["findings"]]
    return projected


def verify(args):
    sources = {name: sha256(ROOT / name) for name in SOURCES}
    baseline_sources = {}
    for name in LEGACY_SOURCES:
        original = subprocess.run(["git", "-C", str(ROOT), "show", BASELINE_COMMIT + ":" + name],
                                  check=True, capture_output=True).stdout
        expected = hashlib.sha256(original).hexdigest()
        if sha256(args.baseline_root / name) != expected:
            raise ValueError("Baseline source differs from pinned commit: " + name)
        baseline_sources[name] = expected
    manifest = json.loads(DEVELOPMENT_MANIFEST.read_text(encoding="utf-8-sig"))
    inputs = [(case["case_id"], args.reports_root / case["case_id"], "fresh_real_cli_inventory", case["expected_codes"], None)
              for case in manifest["cases"]]
    inputs += [(spec[0], args.family_root / "checks" / spec[0], "historical_real_inventory_replay", spec[1], spec)
               for spec in SPECS]
    inventories, loaded_reports = [], []
    for name, directory, origin, expected, spec in inputs:
        loaded = load_completed_check(directory)
        metadata = loaded["metadata"]
        if sha256(directory / "inventory.json") != metadata["inventory_sha256"]:
            raise ValueError("Inventory file differs from original run: " + name)
        if sha256(directory / "input.mph") != metadata["source"]["sha256"]:
            raise ValueError("Model snapshot differs from original run: " + name)
        if origin == "fresh_real_cli_inventory" and (loaded["report"]["schema_version"] != "diagnosis-0.2"
                or metadata["rule_engine_sha256"] != engine_fingerprint()
                or metadata["inventory_source_sha256"] != sha256(ROOT / "src/comsol/ModelInventory.java")):
            raise ValueError("Six fresh CLI reports must bind the current implementation")
        inventories.append(json.loads((directory / "inventory.json").read_text(encoding="utf-8-sig")))
        loaded_reports.append(loaded)
    code = ("import sys,json;sys.path.insert(0,sys.argv[1]+'/src');"
            "from flowpilot.diagnostics import diagnose_inventory;"
            "print(json.dumps([diagnose_inventory(i) for i in json.load(sys.stdin)],allow_nan=False))")
    baseline = subprocess.run([sys.executable, "-I", "-c", code, str(args.baseline_root.resolve())],
                              input=json.dumps(inventories), capture_output=True, text=True, encoding="utf-8", check=True)
    old_reports = json.loads(baseline.stdout)
    rows = []
    for (name, directory, origin, expected, spec), inventory, loaded, old in zip(inputs, inventories, loaded_reports, old_reports):
        current = diagnose_inventory(inventory)
        if digest(legacy_projection(current)) != digest(old):
            raise ValueError("Legacy payload changed: " + name)
        if current["status"] != "checked" or sorted({f["code"] for f in current["findings"]}) != sorted(expected):
            raise ValueError("Independent expected rule labels differ: " + name)
        if origin == "fresh_real_cli_inventory" and digest(current) != digest(loaded["report"]):
            raise ValueError("Fresh CLI diagnosis differs from current inventory replay: " + name)
        evidence = case_evidence({**loaded, "report": current, "diagnosis_sha256": digest(current)}, spec) if spec else None
        if evidence and not evidence["passed"]:
            raise ValueError("Independent SI/geometry/selection evidence differs: " + name)
        rows.append({"case_id": name, "origin": origin, "legacy_payload_equal": True, "expected_codes": sorted(expected),
                     "actual_codes": sorted({f["code"] for f in current["findings"]}), "status": current["status"],
                     "inventory_canonical_sha256": digest(inventory), "inventory_file_sha256": loaded["metadata"]["inventory_sha256"],
                     "source_model_sha256": loaded["metadata"]["source"]["sha256"],
                     "input_diagnosis_sha256": loaded["diagnosis_sha256"], "input_run_sha256": loaded["run_sha256"],
                     "input_rule_engine_sha256": loaded["metadata"]["rule_engine_sha256"],
                     "legacy_payload_sha256": digest(old), "current_diagnosis_canonical_sha256": digest(current),
                     "independent_spec_evidence": evidence})
    if sources != {name: sha256(ROOT / name) for name in SOURCES}:
        raise ValueError("Implementation changed during comparison")
    return {"schema_version": "m0-regression-evidence-1", "status": "passed", "verified_at": datetime.now(timezone.utc).isoformat(),
            "baseline_commit": BASELINE_COMMIT, "baseline_source_sha256": baseline_sources,
            "implementation_sha256": sources, "rule_engine_sha256": engine_fingerprint(), "case_count": len(rows),
            "fresh_cli_inventory_count": 6, "historical_inventory_replay_count": 14,
            "new_comsol_execution": False, "solved": False, "independent_acceptance_set": False, "expert_review": False,
            "scope": "Six newly read real CLI inventories and fourteen previously read controlled inventories; replay does not reread COMSOL.",
            "cases": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("reports-root", "family-root", "baseline-root", "output"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--write-fixture", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = verify(args)
    _write_json(args.output / "summary.json", result)
    if args.write_fixture:
        (ROOT / "data/fixtures/m0_regression.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "cases": result["case_count"], "status": result["status"]}))


if __name__ == "__main__":
    main()
