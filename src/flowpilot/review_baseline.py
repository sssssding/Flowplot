"""Prepare review evidence from the committed baseline's saved COMSOL solution."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import struct
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot.check_model import CheckError, ROOT, _run, _write_json, sha256

JAVA_SOURCE = ROOT / "src/comsol/BaselineReview.java"
MANIFEST = ROOT / "data/fixtures/cases/manifest.json"
REFERENCE = ROOT / "data/fixtures/baseline_verification.json"
METRICS = ("mass_in_kg_m_s", "mass_out_kg_m_s", "max_speed_m_s",
           "wall_interior_speed_m_s", "min_u_m_s", "pressure_drop_pa")
SECTIONS = (0.1, 0.25, 0.5, 0.9)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def analyze_samples(payload, reference):
    """Validate field evidence and compute engineering checks, never expert approval."""
    if payload.get("schema_version") != "baseline-review-0.1" or payload.get("solver_run") is not False:
        raise CheckError("Expected saved-solution baseline review evidence")
    if not isinstance(payload.get("comsol_version"), str):
        raise CheckError("Missing COMSOL version")
    if not _number(payload.get("height_m")) or not math.isclose(payload["height_m"], 0.05):
        raise CheckError("Unexpected baseline height")
    if not _number(payload.get("inlet_velocity_m_s")) or not math.isclose(payload["inlet_velocity_m_s"], 0.01):
        raise CheckError("Unexpected baseline inlet velocity")
    metrics = payload.get("metrics", {})
    if not isinstance(metrics, dict) or any(not _number(metrics.get(key)) for key in METRICS):
        raise CheckError("Missing or non-finite baseline metrics")
    sections = payload.get("sections", [])
    if not isinstance(sections, list) or len(sections) != len(SECTIONS):
        raise CheckError("Expected four velocity cross-sections")
    summaries = []
    for section, expected_x in zip(sections, SECTIONS):
        if not isinstance(section, dict) or not _number(section.get("x_m")) or section["x_m"] != expected_x:
            raise CheckError("Unexpected cross-section location")
        for key in ("y_m", "u_m_s", "v_m_s", "speed_m_s", "pressure_pa"):
            values = section.get(key)
            if not isinstance(values, list) or len(values) != 101 or not all(map(_number, values)):
                raise CheckError("Expected 101 finite samples per expression")
        if any(not math.isclose(y, payload["height_m"] * i / 100, abs_tol=1e-12)
               for i, y in enumerate(section["y_m"])):
            raise CheckError("Unexpected vertical sample coordinates")
        u, speed = section["u_m_s"], section["speed_m_s"]
        peak = max(map(abs, u))
        symmetry = max(abs(left - right) for left, right in zip(u, reversed(u))) / max(peak, 1e-12)
        summaries.append({"x_m": expected_x, "center_u_m_s": u[50],
                          "wall_sample_speed_m_s": max(abs(speed[0]), abs(speed[-1])),
                          "symmetry_relative_error": symmetry,
                          "center_above_wall": u[50] > max(abs(u[0]), abs(u[-1])),
                          "nonnegative_speed": min(speed) >= -1e-12})
    metrics = dict(metrics)
    mass_scale = max(abs(metrics["mass_in_kg_m_s"]), abs(metrics["mass_out_kg_m_s"]))
    metrics["mass_relative_error"] = (abs(metrics["mass_in_kg_m_s"] - metrics["mass_out_kg_m_s"]) / mass_scale
                                      if mass_scale > 0 else None)
    reference_match = {key: math.isclose(metrics[key], reference[key], rel_tol=1e-8, abs_tol=1e-12)
                       for key in METRICS}
    checks = {
        "reference_metrics_match": all(reference_match.values()),
        "positive_mass_flow": metrics["mass_in_kg_m_s"] > 0 and metrics["mass_out_kg_m_s"] > 0,
        "mass_balance_below_1e_3": metrics["mass_relative_error"] is not None and metrics["mass_relative_error"] < 1e-3,
        "wall_interior_speed_below_1e_8": 0 <= metrics["wall_interior_speed_m_s"] <= 1e-8,
        "no_reverse_u_above_tolerance": metrics["min_u_m_s"] >= -1e-7,
        "max_speed_in_baseline_range": 0 < metrics["max_speed_m_s"] <= 3 * payload["inlet_velocity_m_s"],
        "positive_pressure_drop": metrics["pressure_drop_pa"] > 0,
        "section_walls_below_1e_8": all(s["wall_sample_speed_m_s"] <= 1e-8 for s in summaries),
        "section_centers_above_walls": all(s["center_above_wall"] for s in summaries),
        "nonnegative_sampled_speed": all(s["nonnegative_speed"] for s in summaries),
        "profile_symmetry_below_1_percent": all(s["symmetry_relative_error"] <= 0.01 for s in summaries),
    }
    return {"schema_version": "baseline-review-report-0.1", "review_status": "expert_review_pending",
            "solver_run": False, "comsol_version": payload["comsol_version"], "metrics": metrics,
            "reference_match": reference_match, "engineering_checks": checks,
            "engineering_checks_passed": all(checks.values()), "sections": summaries}


def _read_payload(log):
    prefix = "FLOWPILOT_REVIEW_JSON "
    with Path(log).open(encoding="utf-8", errors="replace") as stream:
        lines = [line.rstrip("\r\n") for line in stream]
    payloads = [line[len(prefix):] for line in lines if line.startswith(prefix)]
    if len(payloads) != 1 or lines.count("FLOWPILOT_REVIEW_VERIFIED") != 1:
        raise CheckError(f"Missing or ambiguous review completion markers; see {log}")
    try:
        payload = json.loads(payloads[0])
    except ValueError as error:
        raise CheckError(f"Invalid review JSON; see {log}") from error
    if not isinstance(payload, dict):
        raise CheckError("Review payload must be an object")
    return payload


def _verify_png(path, size):
    with Path(path).open("rb") as stream:
        header = stream.read(24)
    if (len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR"
            or struct.unpack(">II", header[16:24]) != size):
        raise CheckError(f"Missing or unexpected PNG image: {path}")


def render_review(review):
    metrics = review["metrics"]
    mass_error = metrics["mass_relative_error"]
    lines = ["# 基准模型速度场复核材料", "", "状态：工程材料已生成，专业审核待完成。",
             "数据来自已提交基准模型的保存解，本次未运行求解器。",
             f"源模型 SHA-256：`{review['source']['sha256']}`", "",
             "## 速度云图", "", "![COMSOL 保存解速度云图，单位 m/s](velocity.png)", "",
             "原始长宽比为 20:1；图中显示速度大小，坐标及色标来自 COMSOL。", "",
             "## 截面轴向速度", "", "![COMSOL 四个截面的轴向速度曲线](profiles.png)", "",
             "横轴为 y/H，纵轴为 u（m/s），截面位置为 x=0.1、0.25、0.5、0.9 m。", "",
             "## 数值核对", "", "| 指标 | 保存解实测 |", "|---|---:|",
             f"| 最大速度 | {metrics['max_speed_m_s']:.10g} m/s |",
             f"| 入口质量流量 | {metrics['mass_in_kg_m_s']:.10g} kg/(m·s) |",
             f"| 出口质量流量 | {metrics['mass_out_kg_m_s']:.10g} kg/(m·s) |",
             f"| 相对质量误差 | {format(mass_error, '.10g') if mass_error is not None else '无法计算'} |",
             f"| 壁面内部最大速度 | {metrics['wall_interior_speed_m_s']:.10g} m/s |",
             f"| 最小轴向速度 | {metrics['min_u_m_s']:.10g} m/s |",
             f"| 压降 | {metrics['pressure_drop_pa']:.10g} Pa |", "",
             "工程检查全部通过：" + ("是" if review["engineering_checks_passed"] else "否，需查看 review.json"), "",
             "四个截面各采样 101 点，原始 u、v、速度大小和压力见 field_samples.json。"
             "截面对称性 1% 为工程筛查阈值，不是网格无关性或物理准确性验收。", "",
             "## 专业复核待办", "",
             "- [ ] 复核入口发展区、速度云图、壁面条件与截面形状。",
             "- [ ] 核对离散入口流量偏差和当前守恒阈值是否满足比赛要求。",
             "- [ ] 填写审核人、日期、结论和剩余问题。", "",
             "可在 COMSOL 中打开本目录 baseline_with_review_plots.mph 查看新增图组。"
             "该文件是本地复核副本，原始基准与五个异常模型保持原样。", ""]
    return "\n".join(lines)


def review_baseline(*, comsol_root, output_dir, model_path=None, timeout=300.0):
    if not _number(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    baseline = next(item for item in manifest["cases"] if item["case_id"] == "baseline")
    model_path = Path(model_path or ROOT / baseline["model_path"]).resolve(strict=True)
    source_hash = sha256(model_path)
    if source_hash.lower() != baseline["sha256"].lower():
        raise CheckError("This exporter requires the committed baseline hash; keep local edits as a separate model")
    comsol_root = Path(comsol_root).resolve(strict=True)
    compiler = comsol_root / "bin/win64/comsolcompile.exe"
    batch = comsol_root / "bin/win64/comsolbatch.exe"
    for executable in (compiler, batch):
        if not executable.is_file():
            raise FileNotFoundError(f"COMSOL executable not found: {executable}")
    output_path = Path(output_dir)
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(f"Output directory already exists: {output_path}")
    run_dir = output_path.resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    metadata = {"schema_version": "baseline-review-run-0.1", "status": "running", "stage": "snapshot",
                "source": {"filename": model_path.name, "sha256": source_hash},
                "started_at": datetime.now(timezone.utc).isoformat(), "solver_run": False,
                "exporter_sha256": sha256(JAVA_SOURCE), "timeout_seconds_per_process": timeout}
    try:
        snapshot = run_dir / "input.mph"
        shutil.copyfile(model_path, snapshot)
        if sha256(snapshot) != source_hash:
            raise CheckError("Baseline changed during snapshot")
        source = run_dir / "BaselineReview.java"
        shutil.copyfile(JAVA_SOURCE, source)
        metadata["stage"] = "compile"
        _run([str(compiler), str(source)], cwd=run_dir, log=run_dir / "compile.log", timeout=timeout)
        compiled = run_dir / "BaselineReview.class"
        if not compiled.is_file() or compiled.stat().st_size == 0:
            raise CheckError("No compiled review driver; see compile.log")
        metadata["stage"] = "export"
        console = run_dir / "batch-console.log"
        _run([str(batch), "-inputfile", str(compiled), "-nosave", "-graphics", "-3drend", "sw",
              "-batchlog", str(run_dir / "batch.log"), "-batchlogout", "-np", "2"],
             cwd=run_dir, log=console, timeout=timeout)
        payload = _read_payload(console)
        reference = json.loads(REFERENCE.read_text(encoding="utf-8-sig"))["runs"][0]
        review = analyze_samples(payload, reference)
        for name, size in (("velocity.png", (1600, 400)), ("profiles.png", (1200, 800))):
            _verify_png(run_dir / name, size)
        review_model = run_dir / "baseline_with_review_plots.mph"
        if not review_model.is_file() or review_model.stat().st_size <= 128:
            raise CheckError("Review model was not exported")
        if sha256(snapshot) != source_hash or sha256(model_path) != source_hash:
            raise CheckError("Source or snapshot hash changed; review cannot be published")
        review["source"] = metadata["source"]
        review["review_model_sha256"] = sha256(review_model)
        _write_json(run_dir / "field_samples.json", {**payload, "source": metadata["source"]})
        _write_json(run_dir / "review.json", review)
        with (run_dir / "report.md").open("x", encoding="utf-8") as stream:
            stream.write(render_review(review))
        metadata.update(status="completed", stage="complete", comsol_version=payload["comsol_version"],
                        engineering_checks_passed=review["engineering_checks_passed"])
        return review
    except Exception as error:
        metadata.update(status="failed", error=str(error))
        raise
    except KeyboardInterrupt:
        metadata.update(status="cancelled", error="Interrupted by user")
        raise
    finally:
        metadata["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(run_dir / "run.json", metadata)


def main():
    parser = argparse.ArgumentParser(description="Export committed baseline plots from its saved solution (Windows)")
    parser.add_argument("--comsol-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", type=Path, help="optional alternate path to the identical committed baseline")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    try:
        review = review_baseline(comsol_root=args.comsol_root, output_dir=args.output_dir,
                                 model_path=args.model, timeout=args.timeout)
    except (OSError, ValueError, KeyError, TypeError, CheckError) as error:
        parser.exit(1, f"Review failed: {error}\n")
    print(f"Review exported; engineering checks: {review['engineering_checks_passed']}; expert review pending; "
          f"{args.output_dir / 'report.md'}")


if __name__ == "__main__":
    main()
