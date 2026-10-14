"""Feature-based portable candidate ranking, with explicit transfer uncertainty."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot.check_model import CheckError, ROOT
from flowpilot.diagnostics import validate, is_finite_number, _reynolds_number
from flowpilot.recommend import CANDIDATES, read_json, _digest
from flowpilot.solve_baseline import METRICS
from jsonschema import ValidationError

METHOD = "feature-relative-knn-v1"
NOTICE = ("跨机器、按模型特征匹配的实验性候选建议。排序使用相对耗时，不能保证本机秒数或加速；"
          "必须在副本验证，不自动修改模型，不代表物理/独立性能验收通过。")


def comsol_series(text):
    if not isinstance(text, str):
        raise ValueError("Missing COMSOL version")
    match = re.search(r"(?:Multiphysics\s+|COMSOL\s+)(\d+)\.(\d+)", text)
    if not match:
        raise ValueError("Unrecognized COMSOL version")
    return ".".join(match.groups())


def model_features(model):
    try:
        validate(model)
    except (ValidationError, ValueError, TypeError, KeyError) as error:
        raise ValueError("Unsupported or invalid diagnostic model") from error
    inlets = [b for b in model["boundaries"] if b["type"] == "inlet" and b["boundary_ids"]]
    outlets = [b for b in model["boundaries"] if b["type"] == "outlet" and b["boundary_ids"]]
    if len(inlets) != 1 or len(outlets) != 1:
        raise ValueError("Portable profile requires exactly one effective inlet and outlet")
    velocity = inlets[0]["parameters"]["normal_velocity"]
    rho, mu = model["material"]["density"], model["material"]["dynamic_viscosity"]
    for item in (velocity, rho, mu):
        if item["status"] != "resolved" or not is_finite_number(item["value"]) or item["value"] <= 0:
            raise ValueError("Portable features require positive resolved SI quantities")
    length, height = model["geometry"]["length_m"], model["geometry"]["height_m"]
    re_value, error = _reynolds_number(rho["value"], velocity["value"], height, mu["value"])
    if error or not re_value or re_value > 2000:
        raise ValueError("Re outside the conservative portable laminar profile")
    vector = [math.log10(length), math.log10(height), math.log10(re_value), math.log10(length)-math.log10(height)]
    if not all(math.isfinite(x) for x in vector):
        raise ValueError("Feature overflow")
    return {"vector": vector, "length_m": length, "height_m": height, "reynolds": re_value,
            "velocity_m_s": velocity["value"], "density_kg_m3": rho["value"],
            "viscosity_pa_s": mu["value"], "comsol_series": comsol_series(model["source"]["comsol_version"])}


def solution_checks(evidence, reference, features):
    if (not isinstance(evidence, dict) or evidence.get("schema_version") != "baseline-solve-0.1"
            or evidence.get("solver_run") is not True or evidence.get("solution_cleared_before_solve") is not True
            or evidence.get("solution_present_after_solve") is not True or evidence.get("solver_tag") != "sol1"
            or not is_finite_number(evidence.get("solve_seconds")) or not 1e-6 <= evidence["solve_seconds"] <= 3600):
        raise ValueError("Missing cold-solve proof")
    for field in ("solver_error", "solver_warning", "comsol_version"):
        if not isinstance(evidence.get(field), str):
            raise ValueError("Missing solver text field")
    if comsol_series(evidence["comsol_version"]) != features["comsol_series"]:
        raise ValueError("Solve/report COMSOL series mismatch")
    metrics = evidence.get("metrics")
    if (not isinstance(metrics, dict) or not isinstance(reference, dict)
            or any(not is_finite_number(metrics.get(k)) or not is_finite_number(reference.get(k)) for k in METRICS)):
        raise ValueError("Incomplete finite metrics/reference")
    inlet, outlet = metrics["mass_in_kg_m_s"], metrics["mass_out_kg_m_s"]
    mass_error = abs(inlet-outlet) / max(abs(inlet), abs(outlet)) if max(abs(inlet), abs(outlet)) else None
    nominal = features["density_kg_m3"] * features["velocity_m_s"] * features["height_m"]
    drift = {k: abs(metrics[k]-reference[k]) / max(abs(reference[k]), 1e-12) for k in METRICS}
    gates = {"positive_flow": inlet > 0 and outlet > 0,
             "mass_balance": mass_error is not None and mass_error < 1e-3,
             "inlet_consistent_with_si_features": math.isfinite(nominal) and nominal > 0
             and abs(inlet-nominal)/nominal < .1,
             "speed_range": 0 < metrics["max_speed_m_s"] <= 3 * features["velocity_m_s"],
             "wall_speed": 0 <= metrics["wall_interior_speed_m_s"] <= 1e-8,
             "no_reverse_velocity": metrics["min_u_m_s"] >= -1e-7,
             "positive_pressure_drop": metrics["pressure_drop_pa"] > 0,
             "reference_drift": all(x <= 1e-5 for x in drift.values()),
             "no_error_or_warning": not evidence["solver_error"].strip() and not evidence["solver_warning"].strip()}
    return {"checks": gates, "passed": all(gates.values()), "mass_relative_error": mass_error,
            "relative_drift": drift}


def validate_data(data):
    if (not isinstance(data, dict) or data.get("schema_version") != "solver-transfer-data-0.1"
            or data.get("status") != "completed" or data.get("development_only") is not True
            or data.get("independent_validation") is not False):
        raise ValueError("Invalid portable training data or acceptance claim")
    cases = data.get("cases")
    if not isinstance(cases, list) or not 3 <= len(cases) <= 100:
        raise ValueError("Portable training requires at least three measured model configurations")
    hashes, vectors, versions = set(), set(), set()
    for case in cases:
        if not isinstance(case, dict) or not _digest(case.get("source_sha256")) or case["source_sha256"] in hashes:
            raise ValueError("Duplicate or invalid model source")
        hashes.add(case["source_sha256"])
        f = model_features(case.get("diagnostic_model", {}))
        if f != case.get("features") or not _digest(case.get("environment_id")):
            raise ValueError("Features do not match validated SI model evidence")
        vectors.add(tuple(f["vector"]))
        versions.add(f["comsol_series"])
        rows = case.get("observations")
        if not isinstance(rows, list) or len(rows) != 12:
            raise ValueError("Each model requires all four candidates, three repeats each")
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("candidate"), dict):
                raise ValueError("Invalid observation")
            c = row["candidate"]
            if (type(c.get("threads")) is not int or type(c.get("stol")) not in (int, float)
                    or c not in CANDIDATES or type(row.get("repeat")) is not int or row["repeat"] not in (1, 2, 3)):
                raise ValueError("Unknown candidate/repeat")
            key = (c["id"], row["repeat"])
            if key in seen:
                raise ValueError("Duplicate repeat")
            seen.add(key)
            quality = solution_checks(row.get("evidence"), case.get("reference_metrics"), f)
            if row.get("quality") != quality:
                raise ValueError("Stored quality differs from measured evidence")
            if (not is_finite_number(row.get("process_seconds"))
                    or row["process_seconds"] <= row["evidence"]["solve_seconds"]
                    or any(not _digest(row.get(k)) for k in ("solved_sha256", "console_sha256", "batch_sha256"))):
                raise ValueError("Missing measured timing/artifact provenance")
        reference_row = next(r for r in rows if r["candidate"]["id"] == "strict-2" and r["repeat"] == 1)
        if reference_row["evidence"]["metrics"] != case["reference_metrics"]:
            raise ValueError("Quality reference must be the recorded first strict-2 cold solve")
        if not all(r["quality"]["passed"] for r in rows if r["candidate"]["id"] == "strict-2"):
            raise ValueError("Reference configuration failed; cannot train this case")
    if len(vectors) < 3 or len(versions) != 1:
        raise ValueError("Need three distinct feature points in one COMSOL series")
    return cases


def fit(data):
    validate_data(data)
    return {"schema_version": "solver-ranker-0.2", "method": METHOD, "k": 3, "data": data,
            "independent_validation": False, "expert_review": "pending"}


def rank(model, diagnostic_model, source_sha256, *, logical_cpus=None):
    if (not isinstance(model, dict) or model.get("schema_version") != "solver-ranker-0.2"
            or model.get("method") != METHOD or type(model.get("k")) is not int or model["k"] != 3
            or model.get("independent_validation") is not False or model.get("expert_review") != "pending"
            or not _digest(source_sha256)):
        raise ValueError("Invalid portable learned model")
    cases = validate_data(model.get("data"))
    result = {"schema_version": "solver-recommendation-0.2", "status": "unavailable", "notice": NOTICE,
              "method": METHOD, "source_sha256": source_sha256, "ranking": [], "selected": None,
              "requires_local_validation": True, "independent_validation": False,
              "absolute_runtime_prediction": None, "machine_hash_required": False}
    # Generalization must not override an already measured reference failure.
    registry = read_json(ROOT / "data/fixtures/ai_development_registry.json")
    if (registry.get("schema_version") != "ai-development-registry-0.1"
            or registry.get("development_only") is not True or not isinstance(registry.get("cases"), list)):
        raise ValueError("Invalid known-failure registry")
    for item in registry["cases"]:
        if not isinstance(item, dict) or not _digest(item.get("source_sha256")):
            raise ValueError("Invalid known-failure entry")
        if item.get("recommendation_blocked") is True and item["source_sha256"] == source_sha256:
            result["reason"] = "该文件的严格参考求解已有工程检查失败记录，请先修复并重新验证，不能用相似特征覆盖失败证据。"
            return result
    try:
        target = model_features(diagnostic_model)
    except (ValueError, TypeError, KeyError) as error:
        result["reason"] = "模型特征不在支持范围：" + str(error)
        return result
    if target["comsol_series"] != cases[0]["features"]["comsol_series"]:
        result["reason"] = "COMSOL 主/次版本与训练数据不同，请补充该版本的校准数据。"
        return result
    x = target["vector"]
    for index, value in enumerate(x):
        observed = [c["features"]["vector"][index] for c in cases]
        if value < min(observed)-1e-12 or value > max(observed)+1e-12:
            result["reason"] = "模型尺寸、Re 或长宽比超出训练覆盖范围，请增加此工况的实测数据。"
            return result
    neighbours = sorted(((math.dist(x, c["features"]["vector"]), c) for c in cases), key=lambda pair: pair[0])
    if neighbours[0][0] > .75:
        result["reason"] = "虽然在单项范围内，但与已测模型距离过大，拒绝外推。"
        return result
    neighbours = [pair for pair in neighbours[:3] if pair[0] <= .75]
    if neighbours[0][0] <= 1e-12:
        neighbours = [pair for pair in neighbours if pair[0] <= 1e-12]
    cpus = os.cpu_count() if logical_cpus is None else logical_cpus
    if type(cpus) is not int or cpus < 1:
        result["reason"] = "无法确认可用逻辑 CPU 数，不推荐线程配置。"
        return result
    for candidate in CANDIDATES:
        if candidate["threads"] > cpus:
            continue
        ratios, ranges, weights = [], [], []
        for distance, case in neighbours:
            defaults = [r["evidence"]["solve_seconds"] for r in case["observations"] if r["candidate"]["id"] == "strict-2"]
            observed = [r for r in case["observations"] if r["candidate"] == candidate]
            if not all(r["quality"]["passed"] for r in observed):
                break
            times = [r["evidence"]["solve_seconds"] for r in observed]
            anchor = math.exp(statistics.fmean(math.log(t) for t in defaults))
            ratios.append(statistics.fmean(math.log(t/anchor) for t in times))
            ranges.append([min(times)/max(defaults), max(times)/min(defaults)])
            weights.append(1 / max(distance, .05))
        else:
            relative = math.exp(sum(w*r for w, r in zip(weights, ratios))/sum(weights))
            result["ranking"].append({"candidate": candidate, "predicted_relative_runtime": relative,
                                      "observed_relative_range": [min(r[0] for r in ranges), max(r[1] for r in ranges)],
                                      "supporting_models": len(neighbours), "samples": 3*len(neighbours)})
    result["ranking"].sort(key=lambda item: (item["predicted_relative_runtime"], item["candidate"]["id"]))
    if not result["ranking"]:
        result["reason"] = "资源允许的候选没有通过邻近模型质量检查。"
        return result
    anchor = next((r for r in result["ranking"] if r["candidate"]["id"] == "strict-2"), None)
    best = result["ranking"][0]
    if anchor:
        distinct = best["predicted_relative_runtime"] < .95 and best["observed_relative_range"][1] < 1
        selected = best if distinct else anchor
    else:
        selected = best
    result.update(status="recommended", selected=selected["candidate"],
                  reason="按相近模型的相对耗时给出试验候选；跨模型/机器的收益和精度必须在本机副本验证。",
                  target_features=target, supported_by=[c["source_sha256"] for _, c in neighbours],
                  feature_distance=neighbours[0][0], available_logical_cpus=cpus,
                  confidence="experimental-transfer", comsol_series=target["comsol_series"])
    return result


def render(result):
    lines = ["FlowPlot · AI 参数推荐（跨环境候选）", "", NOTICE, "", result["reason"]]
    if result["selected"]:
        c = result["selected"]
        lines += ["", f"建议试验：相对容差 {c['stol']:g}，{c['threads']} 线程。",
                  "以下为相对严格双线程配置的耗时比，不是当前电脑的秒数或保证收益："]
    for row in result["ranking"]:
        c = row["candidate"]
        lines.append(f"{c['id']}: 容差 {c['stol']:g} / {c['threads']} 线程 · "
                     f"相对耗时 {row['predicted_relative_runtime']:.3f} · 支持模型 {row['supporting_models']}")
    return "\n".join(lines)+"\n"


def main():
    parser = argparse.ArgumentParser(description="Train portable FlowPlot candidate ranking from real measurements")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        learned = fit(read_json(args.dataset))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(learned, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    except (OSError, ValueError, TypeError, KeyError, CheckError) as error:
        parser.exit(1, f"Portable training failed: {error}\n")


if __name__ == "__main__":
    main()
