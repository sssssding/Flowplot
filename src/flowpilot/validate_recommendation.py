"""Compare a candidate with actual local cold solves, never independent acceptance."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import statistics
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot.check_model import CheckError, _write_json, sha256
from flowpilot.desktop_session import load_completed_check
from flowpilot.portable_recommend import comsol_series
from flowpilot.recommend import DEFAULT_PORTABLE_MODEL, environment_id, recommend_report, validate_dataset
from flowpilot.report_io import decode_json, read_regular_file


def evaluate(report_dir, calibration, *, model_path=DEFAULT_PORTABLE_MODEL):
    raw = read_regular_file(calibration, max_bytes=1024*1024)
    dataset = decode_json(raw)
    rows = validate_dataset(dataset)
    if dataset["environment_id"] != environment_id():
        raise CheckError("请在实际测量的同一电脑/运行环境生成评估，不将其他电脑秒数当作本机实测。")
    loaded = load_completed_check(report_dir)
    identity = loaded["run_sha256"], loaded["diagnosis_sha256"]
    source = loaded["metadata"]["source"]["sha256"].lower()
    if source != dataset["source_sha256"]:
        raise CheckError("检查报告与实测数据不是同一模型文件。")
    recommendation = recommend_report(report_dir, model_path, expected_fingerprints=identity)
    result = {"schema_version": "local-recommendation-validation-0.1", "status": "unavailable",
              "development_only": True, "independent_validation": False, "software_goal_complete": False,
              "solver_run_in_evaluation": False, "measurement_environment_id": dataset["environment_id"],
              "source_sha256": source, "run_sha256": identity[0], "diagnosis_sha256": identity[1],
              "calibration_sha256": hashlib.sha256(raw).hexdigest(), "evaluator_sha256": sha256(Path(__file__)),
              "recommendation": recommendation, "comparison": None,
              "notice": "仅核对当前电脑、已登记开发基准的实测；不是未见模型、专业审核或独立性能验收。"}
    if recommendation["status"] == "recommended":
        selected = recommendation["selected"]
        requested = {"strict-2", selected["id"]}
        measured = {key: [r for r in rows if r["candidate"]["id"] == key] for key in requested}
        safe = all(r["analysis"]["engineering_checks_passed"] and not r["evidence"]["solver_warning"].strip()
                   for group in measured.values() for r in group)
        series = loaded["report"]["model"]["source"]["comsol_version"]
        if any(comsol_series(r["evidence"]["comsol_version"]) != comsol_series(series) for r in rows):
            raise CheckError("检查报告与冷求解的 COMSOL 主/次版本不同。")
        if not safe:
            result.update(status="quality_failed", reason="所选或默认配置未通过全部工程质量检查，不接受速度收益。")
        else:
            def summary(group):
                values = [r["evidence"]["solve_seconds"] for r in group]
                return {"samples": len(values), "median_seconds": statistics.median(values),
                        "minimum_seconds": min(values), "maximum_seconds": max(values),
                        "stdev_seconds": statistics.stdev(values)}
            default = summary(measured["strict-2"])
            chosen = summary(measured[selected["id"]])
            ratio = chosen["median_seconds"] / default["median_seconds"]
            gain = (selected["id"] != "strict-2" and ratio < .95
                    and chosen["maximum_seconds"] < default["minimum_seconds"])
            result.update(status="measured", reason="选定配置有本机观测收益，仍需独立模型验证。" if gain
                          else "没有满足大于 5% 且测量范围不重叠的收益证据；保留严格配置，不声称加速。",
                          comparison={"default_candidate": "strict-2", "selected_candidate": selected["id"],
                                      "default": default, "selected": chosen, "selected_over_default": ratio,
                                      "observed_gain_above_noise": gain, "quality_checks_passed": True,
                                      "speed_scope": "runAll-only-not-startup-loading-saving"})
    else:
        result["reason"] = recommendation["reason"]
    latest = load_completed_check(report_dir)
    if (latest["run_sha256"], latest["diagnosis_sha256"]) != identity or read_regular_file(
            calibration, max_bytes=1024*1024) != raw:
        raise CheckError("报告或测量数据在评估期间变化，请重新读取。")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--learned-model", type=Path, default=DEFAULT_PORTABLE_MODEL)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        target = args.output
        if target.exists() or target.is_symlink() or target.is_junction():
            raise FileExistsError("Use a new result file")
        resolved = target.resolve()
        for protected in (args.report.resolve(strict=True), args.calibration.resolve(strict=True).parent):
            if resolved == protected or protected in resolved.parents:
                raise CheckError("评估输出须在输入报告和测量目录之外。")
        result = evaluate(args.report, args.calibration, model_path=args.learned_model)
        _write_json(resolved, result)
    except (OSError, ValueError, KeyError, TypeError, CheckError) as error:
        parser.exit(1, f"Local validation failed: {error}\n")
    print(result["reason"])
    return 0 if result["status"] == "measured" else 2


if __name__ == "__main__":
    raise SystemExit(main())
