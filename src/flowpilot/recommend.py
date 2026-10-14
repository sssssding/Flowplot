"""Local, calibrated k-nearest-neighbour runtime regression; never edits MPH files."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot.check_model import ROOT, CheckError, _write_json, sha256
from flowpilot.desktop_session import load_completed_check
from flowpilot.report_io import decode_json, read_regular_file
from flowpilot.solve_baseline import analyze_solve, JAVA_SOURCE, REFERENCE
from flowpilot.review_baseline import MANIFEST

DEFAULT_MODEL = ROOT / "data/ai/solver_ranker.json"
DEFAULT_PORTABLE_MODEL = ROOT / "data/ai/portable_ranker.json"
CANDIDATES = (
    {"id": "strict-1", "stol": 1e-6, "threads": 1},
    {"id": "strict-2", "stol": 1e-6, "threads": 2},
    {"id": "balanced-2", "stol": 1e-5, "threads": 2},
    {"id": "loose-2", "stol": 1e-4, "threads": 2},
)
METHOD = "knn-log-runtime-v1"
NOTICE = ("本机校准的实验性推荐，仅适用于同一基准文件和运行环境。"
          "不自动修改/求解模型，不证明物理正确或在独立模型上优于默认配置。")


def environment_id():
    """Cohort fingerprint, without hostname, account, paths, or license data."""
    fields = [platform.system(), platform.release(), platform.machine(), platform.processor(), os.cpu_count()]
    return hashlib.sha256(json.dumps(fields, ensure_ascii=True).encode("ascii")).hexdigest()


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def read_json(path):
    value = decode_json(read_regular_file(path, max_bytes=1024 * 1024))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def validate_dataset(dataset):
    """Recompute quality gates, never trust a saved 'passed' flag or runtime prediction."""
    if (not isinstance(dataset, dict) or dataset.get("schema_version") != "solver-calibration-0.1"
            or dataset.get("status") != "completed" or type(dataset.get("repeats")) is not int or dataset["repeats"] != 3
            or not _digest(dataset.get("source_sha256")) or not _digest(dataset.get("environment_id"))):
        raise ValueError("Incomplete or invalid calibration")
    baseline = next(case for case in read_json(MANIFEST)["cases"] if case["case_id"] == "baseline")
    if dataset["source_sha256"] != baseline["sha256"].lower():
        raise ValueError("Only the registered baseline has matching quality-reference metrics")
    expected_sources = {"driver": sha256(JAVA_SOURCE), "reference": sha256(REFERENCE)}
    if dataset.get("sources") != expected_sources:
        raise ValueError("Calibration driver/reference changed; recalibrate instead of editing hashes")
    rows = dataset.get("observations")
    if not isinstance(rows, list) or len(rows) != len(CANDIDATES) * 3:
        raise ValueError("Expected three observations per candidate")
    reference = read_json(REFERENCE)["runs"][0]
    seen, versions = set(), set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("candidate"), dict):
            raise ValueError("Invalid observation")
        candidate = row["candidate"]
        # bool compares equal to 1: reject it before allowlist comparison.
        if (type(candidate.get("threads")) is not int or type(candidate.get("stol")) not in (int, float)
                or candidate not in CANDIDATES or type(row.get("repeat")) is not int
                or row["repeat"] not in (1, 2, 3)):
            raise ValueError("Unknown configuration/repeat")
        key = (candidate["id"], row["repeat"])
        if key in seen:
            raise ValueError("Duplicate configuration/repeat")
        seen.add(key)
        if not isinstance(row.get("evidence"), dict):
            raise ValueError("Missing solve evidence object")
        analysis = analyze_solve(row["evidence"], reference)
        if row.get("analysis") != analysis:
            raise ValueError("Observation quality checks do not match raw evidence")
        if (type(row.get("process_seconds")) not in (int, float)
                or not math.isfinite(row["process_seconds"])
                or row["process_seconds"] <= row["evidence"]["solve_seconds"]):
            raise ValueError("Invalid process timing")
        if any(not _digest(row.get(field)) for field in ("solved_sha256", "console_sha256", "batch_sha256")):
            raise ValueError("Missing artifact provenance")
        versions.add(row["evidence"]["comsol_version"])
    if len(versions) != 1:
        raise ValueError("Mixed COMSOL versions cannot train one local ranker")
    return rows


def fit(dataset):
    validate_dataset(dataset)
    # Lazy learning: retain the validated measured samples, not invented training labels.
    return {"schema_version": "solver-ranker-0.1", "method": METHOD, "k": 3,
            "dataset": dataset, "independent_validation": False, "expert_review": "pending"}


def features(candidate):
    return math.log10(candidate["stol"]), math.log2(candidate["threads"])


def rank(model, source_sha256, *, cohort=None):
    if (not isinstance(model, dict) or model.get("schema_version") != "solver-ranker-0.1"
            or model.get("method") != METHOD or type(model.get("k")) is not int or model["k"] != 3
            or model.get("independent_validation") is not False or model.get("expert_review") != "pending"):
        raise ValueError("Invalid or unsupported learned model")
    rows = validate_dataset(model.get("dataset"))
    dataset = model["dataset"]
    result = {"schema_version": "solver-recommendation-0.1", "status": "unavailable", "notice": NOTICE,
              "source_sha256": source_sha256, "ranking": [], "selected": None,
              "independent_validation": False, "method": METHOD}
    if not _digest(source_sha256):
        raise ValueError("Invalid model source digest")
    if source_sha256 != dataset["source_sha256"]:
        result["reason"] = "该模型未参与校准，不能把基准耗时预测推广到此模型。"
        return result
    if (cohort or environment_id()) != dataset["environment_id"]:
        result["reason"] = "本机运行环境与校准记录不同，请在当前电脑重新校准。"
        return result
    for candidate in CANDIDATES:
        measured = [row for row in rows if row["candidate"] == candidate]
        safe = all(row["analysis"]["engineering_checks_passed"]
                   and not row["evidence"]["solver_warning"].strip() for row in measured)
        if not safe:
            continue
        x = features(candidate)
        neighbours = sorted(rows, key=lambda row: sum((a-b)**2 for a, b in zip(x, features(row["candidate"]))))[:3]
        # Restrict deployment to exact observed candidates. No unsafe interpolation.
        if any(row["candidate"] != candidate for row in neighbours):
            raise ValueError("Insufficient exact calibration neighbours")
        seconds = [row["evidence"]["solve_seconds"] for row in neighbours]
        prediction = math.exp(statistics.fmean(math.log(t) for t in seconds))
        result["ranking"].append({"candidate": candidate, "predicted_solve_seconds": prediction,
                                  "observed_range_seconds": [min(seconds), max(seconds)], "samples": len(seconds)})
    result["ranking"].sort(key=lambda item: (item["predicted_solve_seconds"], item["candidate"]["id"]))
    default = next((item for item in result["ranking"] if item["candidate"]["id"] == "strict-2"), None)
    if not default:
        result["reason"] = "原基准配置未通过全部校准质量检查，不发布推荐。"
        return result
    best = result["ranking"][0]
    # Small or overlapping differences are not proof of a gain. Prefer current settings.
    distinct = (best["predicted_solve_seconds"] < 0.95 * default["predicted_solve_seconds"]
                and best["observed_range_seconds"][1] < default["observed_range_seconds"][0])
    chosen = best if distinct else default
    result.update(status="recommended", selected=chosen["candidate"],
                  reason=("候选在本机测量中更快，建议先在副本验证；不是独立性能结论。" if distinct
                          else "候选收益不足 5% 或测量范围重叠，保留原基准配置更稳妥。"),
                  calibration_samples=len(rows), comsol_version=rows[0]["evidence"]["comsol_version"])
    return result


def recommend_report(directory, model_path=None):
    from flowpilot.portable_recommend import NOTICE as portable_notice, rank as portable_rank
    loaded = load_completed_check(directory)
    source = loaded["metadata"]["source"]["sha256"].lower()
    if loaded["report"]["status"] != "checked" or loaded["report"]["findings"]:
        return {"status": "unavailable", "source_sha256": source, "notice": portable_notice,
                "reason": "存在诊断问题或检查不完整，请先处理；推荐不得覆盖规则证据。", "ranking": [], "selected": None}
    raw = read_regular_file(model_path or DEFAULT_PORTABLE_MODEL, max_bytes=1024 * 1024)
    learned = decode_json(raw)
    result = (portable_rank(learned, loaded["report"]["model"], source)
              if isinstance(learned, dict) and learned.get("schema_version") == "solver-ranker-0.2"
              else rank(learned, source))
    result["learned_model_sha256"] = hashlib.sha256(raw).hexdigest()
    result["diagnosis_sha256"] = loaded["diagnosis_sha256"]
    return result


def render(result):
    if result.get("method") == "feature-relative-knn-v1":
        from flowpilot.portable_recommend import render as portable_render
        return portable_render(result)
    lines = ["FlowPlot · AI 参数推荐", "", result.get("notice", NOTICE), "", result["reason"]]
    if result.get("selected"):
        c = result["selected"]
        lines += ["", f"建议：稳态相对容差 {c['stol']:g}；计算线程数 {c['threads']}。",
                  "以下预测仅为 runAll 调用耗时，不含启动/加载/保存，也不是耗时保证："]
    for item in result["ranking"]:
        c, interval = item["candidate"], item["observed_range_seconds"]
        lines.append(f"{c['id']}: 容差 {c['stol']:g} / {c['threads']} 线程 · "
                     f"预测 {item['predicted_solve_seconds']:.3f}s · 实测 {interval[0]:.3f}–{interval[1]:.3f}s")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="FlowPlot local learned parameter recommender (never solves)")
    commands = parser.add_subparsers(dest="command", required=True)
    train = commands.add_parser("train")
    train.add_argument("--dataset", type=Path, required=True)
    train.add_argument("--output", type=Path, required=True)
    infer = commands.add_parser("recommend")
    infer.add_argument("--report", type=Path, required=True)
    infer.add_argument("--learned-model", type=Path, default=DEFAULT_PORTABLE_MODEL)
    infer.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "train":
            dataset = read_json(args.dataset)
            if dataset.get("schema_version") == "solver-transfer-data-0.1":
                from flowpilot.portable_recommend import fit as portable_fit
                result = portable_fit(dataset)
            else:
                result = fit(dataset)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            _write_json(args.output, result)
            print(f"Learned local ranker saved: {args.output}")
            return
        result = recommend_report(args.report, args.learned_model)
        if args.output:
            _write_json(args.output, result)
        print(render(result))
        if result["status"] != "recommended":
            sys.exit(2)
    except (OSError, ValueError, TypeError, KeyError, CheckError) as error:
        parser.exit(1, f"Recommendation failed: {error}\n")


if __name__ == "__main__":
    main()
