"""Sequential cold solves of the committed baseline, with fail-closed evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot.check_model import CheckError, ROOT, _run, _write_json, sha256
from flowpilot.review_baseline import MANIFEST, REFERENCE, METRICS, _number

JAVA_SOURCE = ROOT / "src/comsol/BaselineSolve.java"


def _read_payload(log):
    lines = Path(log).read_text(encoding="utf-8", errors="replace").splitlines()
    prefix = "FLOWPILOT_SOLVE_JSON "
    payloads = [line[len(prefix):] for line in lines if line.startswith(prefix)]
    markers = ("FLOWPILOT_SOLUTION_CLEARED", "FLOWPILOT_SOLVE_VERIFIED")
    if len(payloads) != 1 or any(lines.count(marker) != 1 for marker in markers):
        raise CheckError(f"Missing or ambiguous cold-solve markers; see {log}")
    payload_index = next(i for i, line in enumerate(lines) if line.startswith(prefix))
    if not lines.index(markers[0]) < payload_index < lines.index(markers[1]):
        raise CheckError("Cold-solve markers are out of order")
    payload = json.loads(payloads[0])
    if not isinstance(payload, dict):
        raise CheckError("Expected a solve evidence object")
    return payload


def analyze_solve(payload, reference):
    """Check a fresh solve against fixed baseline thresholds and historical metrics."""
    if (payload.get("schema_version") != "baseline-solve-0.1"
            or payload.get("solver_run") is not True
            or payload.get("solution_cleared_before_solve") is not True
            or payload.get("solution_present_after_solve") is not True
            or payload.get("solver_tag") != "sol1"):
        raise CheckError("Expected proof of a cleared and newly computed baseline solution")
    if not _number(payload.get("solve_seconds")) or payload["solve_seconds"] <= 0:
        raise CheckError("Missing finite, positive solver timing")
    for key in ("comsol_version", "solver_warning", "solver_error"):
        if not isinstance(payload.get(key), str) or (key == "comsol_version" and not payload[key]):
            raise CheckError(f"Missing solver field: {key}")
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict) or any(not _number(metrics.get(key)) for key in METRICS):
        raise CheckError("Missing or non-finite solve metrics")
    metrics = {key: metrics[key] for key in METRICS}
    inlet, outlet = metrics["mass_in_kg_m_s"], metrics["mass_out_kg_m_s"]
    scale = max(abs(inlet), abs(outlet))
    metrics["mass_relative_error"] = abs(inlet - outlet) / scale if scale else None
    # Same relative drift threshold as the original repeated-solve baseline generator.
    drift = {key: abs(metrics[key] - reference[key]) / max(abs(reference[key]), 1e-12)
             for key in METRICS}
    checks = {
        "positive_mass_flow": inlet > 0 and outlet > 0,
        "mass_balance_below_1e_3": metrics["mass_relative_error"] is not None
        and metrics["mass_relative_error"] < 1e-3,
        "max_speed_in_baseline_range": 0 < metrics["max_speed_m_s"] <= 0.03,
        "wall_interior_speed_below_1e_8": 0 <= metrics["wall_interior_speed_m_s"] <= 1e-8,
        "no_reverse_u_above_tolerance": metrics["min_u_m_s"] >= -1e-7,
        "positive_pressure_drop": metrics["pressure_drop_pa"] > 0,
        "no_solver_error": not payload["solver_error"].strip(),
        "historical_metrics_within_1e_5": all(value <= 1e-5 for value in drift.values()),
    }
    return {"metrics": metrics, "reference_relative_drift": drift,
            "engineering_checks": checks, "engineering_checks_passed": all(checks.values())}


def summarize_runs(runs, requested):
    if not runs or len(runs) != requested:
        raise CheckError("Incomplete solve suite")
    first = runs[0]["analysis"]["metrics"]
    drift = {key: max(abs(run["analysis"]["metrics"][key] - first[key])
                      / max(abs(first[key]), 1e-12) for run in runs) for key in METRICS}
    versions = {run["evidence"]["comsol_version"] for run in runs}
    return {"schema_version": "baseline-solve-suite-0.1", "requested_runs": requested,
            "completed_runs": len(runs), "comsol_versions": sorted(versions),
            "cold_solve": True, "relative_drift_from_first": drift,
            "all_checks_passed": (len(versions) == 1 and all(value <= 1e-5 for value in drift.values())
                                  and all(run["analysis"]["engineering_checks_passed"] for run in runs)),
            "expert_review_status": "expert_review_pending",
            "gui_log_comparison_status": "pending", "runs": runs}


def render_report(summary):
    lines = ["# 基准重复求解报告", "", f"连续完成：{summary['completed_runs']} 次冷启动求解。",
             f"工程检查通过：{summary['all_checks_passed']}。专业审核、GUI 日志对照仍待完成。", "",
             "每次从同一基准重新复制并启动独立 COMSOL 进程；先清除保存解，再运行原 sol1。",
             "不更改参数、网格或求解器配置，不保存原始模型。", "",
             "| 次数 | 求解调用耗时（s） | 进程耗时（s） | 相对质量误差 | 最大速度（m/s） | 压降（Pa） |",
             "|---:|---:|---:|---:|---:|---:|"]
    for run in summary["runs"]:
        m = run["analysis"]["metrics"]
        lines.append(f"| {run['index']} | {run['evidence']['solve_seconds']:.3f} | "
                     f"{run['process_seconds']:.3f} | {m['mass_relative_error']:.9g} | "
                     f"{m['max_speed_m_s']:.9g} | {m['pressure_drop_pa']:.9g} |")
    lines += ["", "各 run-NN 目录包含原始控制台、COMSOL batch 日志、采样指标及 solved.mph 副本。",
              "solve_seconds 仅计 runAll 调用；process_seconds 含软件启动、加载、求解及保存。",
              "原始日志可能包含本机或许可证信息，不直接上传。求解器警告保留在每次 evidence 中，不能当作已人工审核。",
              "五次相同模型运行不是五个独立验收模型，也不证明规则 Recall 或推荐模型效果。", ""]
    return "\n".join(lines)


def solve_baseline(*, comsol_root, output_dir, runs=5, timeout=300.0, model_path=None):
    if type(runs) is not int or not 1 <= runs <= 10:
        raise ValueError("runs must be an integer from 1 to 10")
    if not _number(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    baseline = next(item for item in manifest["cases"] if item["case_id"] == "baseline")
    model = Path(model_path or ROOT / baseline["model_path"]).resolve(strict=True)
    source_hash = sha256(model)
    if source_hash.lower() != baseline["sha256"].lower():
        raise CheckError("Only the committed baseline hash is allowed; abnormal and edited models are refused")
    reference = json.loads(REFERENCE.read_text(encoding="utf-8-sig"))["runs"][0]
    comsol = Path(comsol_root).resolve(strict=True)
    compiler, batch = (comsol / "bin/win64" / name for name in ("comsolcompile.exe", "comsolbatch.exe"))
    for executable in (compiler, batch):
        if not executable.is_file():
            raise FileNotFoundError(f"COMSOL executable not found: {executable}")
    output = Path(output_dir)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Output directory already exists: {output}")
    directory = output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    metadata = {"schema_version": "baseline-solve-run-0.1", "status": "running", "stage": "compile",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "source": {"filename": model.name, "sha256": source_hash},
                "driver_sha256": sha256(JAVA_SOURCE), "reference_sha256": sha256(REFERENCE),
                "requested_runs": runs, "completed_runs": 0, "timeout_seconds_per_process": timeout,
                "threads": 2, "python_version": sys.version.split()[0]}
    results = []
    try:
        source = directory / "BaselineSolve.java"
        shutil.copyfile(JAVA_SOURCE, source)
        _run([str(compiler), str(source)], cwd=directory, log=directory / "compile.log", timeout=timeout)
        compiled = directory / "BaselineSolve.class"
        if not compiled.is_file() or not compiled.stat().st_size:
            raise CheckError("Missing compiled solve driver; see compile.log")
        for index in range(1, runs + 1):
            metadata.update(stage="solve", current_run=index)
            child = directory / f"run-{index:02d}"
            child.mkdir()
            snapshot = child / "input.mph"
            shutil.copyfile(model, snapshot)
            if sha256(snapshot) != source_hash:
                raise CheckError("Baseline changed during snapshot")
            console = child / "batch-console.log"
            started = time.monotonic()
            _run([str(batch), "-inputfile", str(compiled), "-nosave", "-batchlog", str(child / "batch.log"),
                  "-batchlogout", "-np", "2"], cwd=child, log=console, timeout=timeout)
            elapsed = time.monotonic() - started
            payload = _read_payload(console)
            analysis = analyze_solve(payload, reference)
            solved = child / "solved.mph"
            if not solved.is_file() or solved.stat().st_size <= 128:
                raise CheckError("Solved model was not saved")
            batch_log = child / "batch.log"
            if not batch_log.is_file() or not batch_log.stat().st_size:
                raise CheckError("Missing native batch log")
            if sha256(snapshot) != source_hash or sha256(model) != source_hash:
                raise CheckError("Source or snapshot changed; refusing completed suite")
            result = {"index": index, "evidence": payload, "analysis": analysis,
                      "process_seconds": elapsed, "solved_model_sha256": sha256(solved),
                      "console_sha256": sha256(console), "batch_log_sha256": sha256(batch_log)}
            _write_json(child / "result.json", result)
            if not analysis["engineering_checks_passed"]:
                raise CheckError(f"Run {index} failed engineering validation; see {child / 'result.json'}")
            results.append(result)
            metadata["completed_runs"] = len(results)
            print(f"Run {index}/{runs}: solved in {payload['solve_seconds']:.3f}s; checks passed", flush=True)
        summary = summarize_runs(results, runs)
        summary.update(source=metadata["source"], driver_sha256=metadata["driver_sha256"],
                       reference_sha256=metadata["reference_sha256"], threads=2)
        if not summary["all_checks_passed"]:
            raise CheckError("Solve suite drift or COMSOL version mismatch")
        _write_json(directory / "summary.json", summary)
        with (directory / "report.md").open("x", encoding="utf-8") as stream:
            stream.write(render_report(summary))
        metadata.update(status="completed", stage="complete")
        return summary
    except Exception as error:
        metadata.update(status="failed", error=str(error))
        raise
    except KeyboardInterrupt:
        metadata.update(status="cancelled", error="Interrupted by user")
        raise
    finally:
        metadata["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(directory / "run.json", metadata)


def main():
    parser = argparse.ArgumentParser(description="Cold-solve the committed baseline repeatedly (Windows)")
    parser.add_argument("--comsol-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--model", type=Path, help="alternate path to the identical committed baseline")
    args = parser.parse_args()
    try:
        summary = solve_baseline(comsol_root=args.comsol_root, output_dir=args.output_dir,
                                 runs=args.runs, timeout=args.timeout, model_path=args.model)
    except (OSError, ValueError, TypeError, KeyError, CheckError) as error:
        parser.exit(1, f"Solve failed: {error}\n")
    print(f"Completed {summary['completed_runs']} cold solves; {args.output_dir / 'report.md'}")


if __name__ == "__main__":
    main()
