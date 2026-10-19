"""Reproduce engineering checks, not professional/independent/user acceptance.

Runs offline tests and optional read-only COMSOL checks in a new output tree.
No source model is saved, solved, restored, or relabelled as independent data.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.check_model import CheckError, _write_json, sha256
from flowpilot.check_suite import DEVELOPMENT_MANIFEST
from flowpilot.preflight import preflight
from flowpilot.recommend import read_json


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprints():
    suffixes = {".py", ".java", ".in", ".json", ".cmd", ".ps1"}
    files = set(ROOT.glob("*.cmd"))
    for name in ("src", "tests", "scripts", "schema", "data/fixtures", "data/ai"):
        files.update(p for p in (ROOT / name).rglob("*") if p.is_file() and p.suffix in suffixes)
    return {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p) for p in sorted(files)}


def verify(*, output_dir, model_root, comsol_root=None):
    models = Path(model_root).resolve(strict=True)
    output = Path(output_dir)
    if output.exists() or output.is_symlink() or output.is_junction():
        raise FileExistsError("Use a new verification output directory")
    output = output.resolve()
    if output == models or models in output.parents:
        raise CheckError("Verification output must be outside the input model tree")
    original = ROOT / "models/baseline_pipe_2d_laminar.mph"
    baseline_before = sha256(original)
    sources = fingerprints()
    committed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    record = {"schema_version": "engineering-verification-0.1", "status": "running", "started_at": now(),
              "git_head": committed, "source_sha256": sources, "user_baseline_sha256_before": baseline_before,
              "environment": {"python": sys.version, "executable": sys.executable,
                              "platform": platform.platform(), "jsonschema": importlib.metadata.version("jsonschema")},
              "stages": [], "solver_run": False, "professional_acceptance": False,
              "independent_acceptance": False, "visible_ui_acceptance": False,
              "cross_hardware_performance_verified": False, "software_goal_complete": False}
    output.mkdir(parents=True, exist_ok=False)

    def run_stage(name, arguments):
        log = output / (name + ".log")
        stage = {"name": name, "command": [sys.executable, "-X", "utf8", *map(str, arguments)],
                 "started_at": now(), "status": "running"}
        record["stages"].append(stage)
        print(f"Starting {name}", flush=True)
        start = time.monotonic()
        with log.open("xb") as stream:
            process = subprocess.run(stage["command"], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        stage.update(exit_code=process.returncode, elapsed_seconds=time.monotonic()-start,
                     finished_at=now(), log_sha256=sha256(log), status="passed" if process.returncode == 0 else "failed")
        if process.returncode:
            raise CheckError(f"{name} failed; inspect {log.name}")
        print(f"Completed {name}", flush=True)
        return log

    try:
        inputs = preflight(manifest=DEVELOPMENT_MANIFEST, model_root=models, comsol_root=comsol_root)
        _write_json(output / "preflight.json", inputs)
        if inputs["status"] == "blocked":
            raise CheckError("Preflight blocked; preserve original files and inspect preflight.json")
        log = run_stage("unit-tests", ["-m", "unittest", "discover", "-s", "tests", "-q"])
        text = log.read_text(encoding="utf-8", errors="replace")
        counts = re.findall(r"^Ran (\d+) tests in [^\n]+", text, re.MULTILINE)
        footers = re.findall(r"^OK(?: \(skipped=(\d+)\))?\s*$", text, re.MULTILINE)
        if not counts or not footers or int(counts[-1]) < 1:
            raise CheckError("Test result footer missing; do not infer success from exit code alone")
        record["offline_tests"] = {"run": int(counts[-1]), "skipped": int(footers[-1] or 0), "failures": 0, "errors": 0}
        if comsol_root is not None:
            run_stage("comsol-readonly", ["src/flowpilot/check_suite.py", "--manifest", DEVELOPMENT_MANIFEST,
                      "--model-root", models, "--comsol-root", comsol_root,
                      "--output-dir", output / "checks", "--loads", "2"])
            run_stage("offline-recheck", ["src/flowpilot/check_suite.py", "--manifest", DEVELOPMENT_MANIFEST,
                      "--reports-root", output / "checks", "--output-dir", output / "offline"])
            actual, offline = read_json(output / "checks/summary.json"), read_json(output / "offline/summary.json")
            for summary in (actual, offline):
                if (summary["checked_cases"] != 6 or summary["exact_match_cases"] != 6
                        or summary.get("acceptance_eligible") is not False):
                    raise CheckError("Expected six development matches without independent-acceptance claims")
            record["comsol_readonly"] = {"checked": 6, "matching": 6, "loads_each": 2, "offline_matching": 6,
                                         "summary_sha256": sha256(output / "checks/summary.json")}
        after = preflight(manifest=DEVELOPMENT_MANIFEST, model_root=models, comsol_root=comsol_root)
        _write_json(output / "preflight-after.json", after)
        record["user_baseline_sha256_after"] = sha256(original)
        if (after != inputs or record["user_baseline_sha256_after"] != baseline_before
                or fingerprints() != sources):
            raise CheckError("Source inputs, implementation, or user baseline changed during verification")
        record.update(status="engineering_checks_passed" if comsol_root else "offline_checks_passed",
                      inputs_preserved=True, source_stability_verified=True)
        return record
    except KeyboardInterrupt:
        record.update(status="cancelled")
        raise
    except Exception as error:
        record.update(status="failed", error=str(error))
        raise
    finally:
        record["finished_at"] = now()
        _write_json(output / "verification.json", record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--comsol-root", type=Path)
    args = parser.parse_args()
    try:
        result = verify(output_dir=args.output_dir, model_root=args.model_root, comsol_root=args.comsol_root)
    except (OSError, ValueError, TypeError, KeyError, CheckError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Verification failed: {error}\n")
    print(json.dumps({"status": result["status"], "offline_tests": result["offline_tests"],
                      "software_goal_complete": False}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
