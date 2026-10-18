"""Batch read-only model checks and honest, provenance-checked rule evaluation."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import sys

from jsonschema import ValidationError

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot.check_model import CheckError, ROOT, check_model, sha256, _write_json
from flowpilot.engine_fingerprint import engine_fingerprint, fingerprint_from_sources
from flowpilot.diagnostics import is_finite_number
from flowpilot.desktop_session import load_completed_check
from flowpilot.report_io import MAX_METADATA_BYTES, MAX_DIAGNOSIS_BYTES, decode_json, read_regular_file

DEVELOPMENT_MANIFEST = ROOT / "data/fixtures/cases/manifest.json"
RULE_SOURCE = ROOT / "src/flowpilot/diagnostics.py"
INVENTORY_SOURCE = ROOT / "src/comsol/ModelInventory.java"
CORE_CODES = {"MISSING_INLET", "MISSING_OUTLET", "BC_SELECTION_OVERLAP", "INLET_DIRECTION", "REYNOLDS_RISK"}
CODES = CORE_CODES | {"INVALID_MATERIAL_PARAMETER", "EVALUATION_UNAVAILABLE"}


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "case-manifest-0.1":
        raise ValueError("Expected case-manifest-0.1")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 50:
        raise ValueError("Expected 1 to 50 cases")
    ids, hashes = set(), set()
    for case in cases:
        if (not isinstance(case, dict) or not isinstance(case.get("case_id"), str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", case["case_id"])
                or case["case_id"].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                                              *(f"LPT{i}" for i in range(1, 10))}):
            raise ValueError("case_id must be a safe, unique directory name")
        identity, digest = case["case_id"], case.get("sha256", "")
        if identity in ids or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise ValueError("Duplicate case ID or invalid SHA-256")
        if digest.lower() in hashes:
            raise ValueError("Duplicate model hashes would inflate evaluation")
        ids.add(identity)
        hashes.add(digest.lower())
        model_path = case.get("model_path")
        if (not isinstance(model_path, str) or not model_path or Path(model_path).is_absolute()
                or PureWindowsPath(model_path).drive or ".." in PureWindowsPath(model_path).parts):
            raise ValueError("model_path must be relative to the explicit model root, without parent traversal")
        expected = case.get("expected_codes")
        if (not isinstance(expected, list) or any(not isinstance(code, str) or code not in CODES for code in expected)
                or len(expected) != len(set(expected))):
            raise ValueError("expected_codes must contain unique supported rule codes")
    threshold = manifest.get("reynolds_warning", 2000.0)
    if not is_finite_number(threshold) or threshold <= 0:
        raise ValueError("reynolds_warning must be finite and positive")
    return manifest


def acceptance_reasons(manifest):
    reasons = []
    if manifest.get("independent_acceptance_set") is not True:
        reasons.append("independent_set_not_declared")
    if manifest.get("label_status") != "expert_reviewed":
        reasons.append("expert_labels_not_reviewed")
    known = json.loads(DEVELOPMENT_MANIFEST.read_text(encoding="utf-8-sig"))
    development_hashes = {case["sha256"].lower() for case in known["cases"]}
    if any(case["sha256"].lower() in development_hashes for case in manifest["cases"]):
        reasons.append("overlaps_known_development_models")
    covered = set()
    for case in manifest["cases"]:
        covered.update(case["expected_codes"])
        try:
            reviewed_date = case.get("reviewed_date")
            if not isinstance(reviewed_date, str):
                raise ValueError()
            date.fromisoformat(reviewed_date)
        except ValueError:
            reasons.append("missing_case_review_date")
        if not isinstance(case.get("reviewed_by"), str) or not case["reviewed_by"].strip():
            reasons.append("missing_case_reviewer")
        if case.get("used_for_rule_development") is not False:
            reasons.append("case_development_usage_not_excluded")
    if not CORE_CODES <= covered:
        reasons.append("first_five_rules_not_all_represented")
    if not any(not case["expected_codes"] for case in manifest["cases"]):
        reasons.append("no_negative_control")
    return sorted(set(reasons))


def _scores(tp, fp, fn):
    return {"true_positive": tp, "false_positive": fp, "false_negative": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}


def evaluate_dataset(manifest, outcomes):
    """Count each rule once per model; never silently score incomplete reports as clean."""
    validate_manifest(manifest)
    per_rule = {code: [0, 0, 0] for code in sorted(CODES)}
    rows, checked, exact, expected_total, unassessed = [], 0, 0, 0, 0
    for case in manifest["cases"]:
        expected = set(case["expected_codes"])
        expected_total += len(expected)
        outcome = outcomes.get(case["case_id"], {"status": "missing"})
        status = outcome.get("status")
        if status not in ("checked", "partial", "unsupported", "failed", "unscored", "missing"):
            raise ValueError("Unknown case status")
        row = {"case_id": case["case_id"], "status": status, "expected_codes": sorted(expected)}
        for key in ("diagnosis_sha256", "run_metadata_sha256"):
            if key in outcome:
                row[key] = outcome[key]
        if status == "checked":
            codes = outcome.get("predicted_codes")
            if not isinstance(codes, list) or any(not isinstance(code, str) or code not in CODES for code in codes):
                raise ValueError("Invalid predicted rule codes")
            if "EVALUATION_UNAVAILABLE" in codes:
                raise ValueError("An unavailable evaluation cannot be a fully checked outcome")
            predicted = set(codes)
            checked += 1
            exact += predicted == expected
            row.update(predicted_codes=sorted(predicted), missed_codes=sorted(expected - predicted),
                       unexpected_codes=sorted(predicted - expected))
            for code in CODES:
                per_rule[code][0] += int(code in expected and code in predicted)
                per_rule[code][1] += int(code not in expected and code in predicted)
                per_rule[code][2] += int(code in expected and code not in predicted)
        else:
            unassessed += len(expected)
            row.update(predicted_codes=None, missed_codes=None, unexpected_codes=None,
                       reason=outcome.get("reason", "No fully checked, provenance-matched report"))
        rows.append(row)
    micro = _scores(*(sum(count[i] for count in per_rule.values()) for i in range(3)))
    reasons = acceptance_reasons(manifest)
    if not reasons:
        # The legacy manifest gate predates strict freezing. Do not let the
        # generic evaluator promote a dataset the formal freeze gate rejects.
        # Import at call time: acceptance_dataset itself uses this evaluator.
        try:
            from flowpilot.acceptance_dataset import fingerprints, validate_acceptance
            _, known = fingerprints()
            validate_acceptance(manifest, known)
        except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError, RecursionError):
            reasons.append("formal_freeze_requirements_not_met")
    if checked != len(rows):
        reasons.append("incomplete_checked_coverage")
    eligible = not reasons
    recall = micro["recall"]
    return {"schema_version": "check-suite-report-0.1", "evaluation_unit": "model_rule_code",
            "evaluation_kind": "independent_acceptance" if eligible else "development_or_unreviewed",
            "total_cases": len(rows), "checked_cases": checked, "checked_coverage": checked / len(rows),
            "exact_match_cases": exact, "exact_match_fraction_all_cases": exact / len(rows),
            "metrics_on_checked_cases_only": micro,
            "per_rule_on_checked_cases_only": {code: _scores(*count) for code, count in per_rule.items()},
            "unassessed_expected_code_count": unassessed,
            "recall_lower_bound_all_expected_codes": micro["true_positive"] / expected_total if expected_total else None,
            "acceptance_eligible": eligible, "acceptance_blockers": sorted(reasons),
            "meets_recall_above_90_percent": recall > 0.9 if eligible and recall is not None else None,
            "cases": rows}


def read_outcome(directory, case, threshold):
    """Only pair a report with a successful run of the matching source/configuration."""
    try:
        loaded = load_completed_check(directory)
        metadata, report = loaded["metadata"], loaded["report"]
        settings = metadata.get("settings")
        recorded_threshold = settings.get("reynolds_warning") if isinstance(settings, dict) else None
        if (metadata.get("schema_version") != "check-run-0.1" or metadata.get("status") != "completed"
                or metadata.get("source", {}).get("sha256", "").lower() != case["sha256"].lower()
                or not is_finite_number(recorded_threshold) or recorded_threshold <= 0 or recorded_threshold != threshold
                or metadata.get("rule_engine_sha256") != (engine_fingerprint() if report.get("schema_version") == "diagnosis-0.2" else sha256(RULE_SOURCE))
                or metadata.get("inventory_source_sha256") != sha256(INVENTORY_SOURCE)
                or metadata.get("diagnosis_sha256") != loaded["diagnosis_sha256"]):
            raise ValueError("Source hash, rule source, inventory source, settings or completion state mismatch")
        status = report.get("status")
        if (report.get("schema_version") not in ("diagnosis-0.1", "diagnosis-0.2") or status not in ("checked", "partial", "unsupported")
                or metadata.get("diagnosis_status") != status or not isinstance(report.get("findings"), list)):
            raise ValueError("Malformed diagnosis or status mismatch")
        codes = [finding["code"] for finding in report["findings"]]
        if any(not isinstance(code, str) or code not in CODES for code in codes):
            raise ValueError("Unknown rule code")
        return {"status": status, "predicted_codes": codes,
                "diagnosis_sha256": loaded["diagnosis_sha256"],
                "run_metadata_sha256": loaded["run_sha256"],
                "reason": report.get("reason", "Partial reports are not clean model checks")}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, CheckError) as error:
        return {"status": "unscored", "reason": str(error)}


def render_report(summary):
    def number(value):
        return "不适用" if value is None else f"{value:.2%}"
    metrics = summary["metrics_on_checked_cases_only"]
    lines = ["# 批量模型检查与规则评估", "",
             f"完整检查覆盖：{summary['checked_cases']}/{summary['total_cases']}。",
             f"逐模型规则集合完全匹配：{summary['exact_match_cases']}/{summary['total_cases']}。", "",
             "以下统计仅针对完整 checked 报告；partial、unsupported、缺失或来源不符的报告不当作正常模型。",
             f"Precision：{number(metrics['precision'])}；Recall：{number(metrics['recall'])}；F1：{number(metrics['f1'])}。",
             f"计入所有预期标签的 Recall 保守下界：{number(summary['recall_lower_bound_all_expected_codes'])}。", "",
             ("可用于声明的独立验收统计（仍需团队核实数据独立性）。" if summary["acceptance_eligible"]
              else "当前仅为开发回归或未审核数据，不能宣称独立验收 Recall 达标。"), "",
             "| 模型 | 状态 | 漏报 code | 误报 code |", "|---|---|---|---|"]
    for row in summary["cases"]:
        missed = ", ".join(row["missed_codes"]) or "—" if row["missed_codes"] is not None else "未评估"
        unexpected = ", ".join(row["unexpected_codes"]) or "—" if row["unexpected_codes"] is not None else "未评估"
        lines.append(f"| {row['case_id']} | {row['status']} | {missed} | {unexpected} |")
    lines += ["", "独立验收阻断项：" + (", ".join(summary["acceptance_blockers"]) or "无"), "",
              "每个模型的同一规则 code 只计一次，不评价具体边界定位或严重等级是否正确。",
              "该工具不求解模型，不证明物理正确性；审核人字段不代替真实专业审核。", ""]
    return "\n".join(lines)


def run_suite(manifest_path, *, output_dir, comsol_root=None, model_root=ROOT,
              reports_root=None, loads=1, timeout=300.0):
    if type(loads) is not int or not 1 <= loads <= 10 or not is_finite_number(timeout) or timeout <= 0:
        raise ValueError("loads must be 1 to 10 and timeout finite and positive")
    manifest_path = Path(manifest_path).absolute()
    manifest_bytes = read_regular_file(manifest_path, max_bytes=MAX_METADATA_BYTES)
    manifest = validate_manifest(decode_json(manifest_bytes))
    if (comsol_root is None) == (reports_root is None):
        raise ValueError("Choose exactly one: COMSOL checks or existing reports")
    threshold = manifest.get("reynolds_warning", 2000.0)
    models = {}
    if reports_root is None:
        root = Path(model_root).resolve(strict=True)
        for case in manifest["cases"]:
            model = (root / case["model_path"]).resolve(strict=True)
            if not model.is_relative_to(root) or model.suffix.lower() != ".mph" or sha256(model).lower() != case["sha256"].lower():
                raise CheckError(f"Model outside root, wrong extension or hash mismatch: {case['case_id']}")
            models[case["case_id"]] = model
    else:
        reports_root = Path(reports_root)
        if reports_root.is_symlink() or reports_root.is_junction() or not reports_root.is_dir():
            raise ValueError("Existing reports root must be a real directory, not a link or junction")
        reports_root = reports_root.resolve(strict=True)
    from flowpilot.acceptance_dataset import fingerprints
    source_fingerprints, _ = fingerprints()
    output = Path(output_dir)
    if output.exists() or output.is_symlink() or output.is_junction():
        raise FileExistsError(f"Output directory already exists: {output}")
    directory = output.resolve()
    if reports_root is not None and directory.is_relative_to(reports_root):
        raise ValueError("Batch output must be outside the input reports root")
    directory.mkdir(parents=True, exist_ok=False)
    metadata = {"schema_version": "check-suite-run-0.1", "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "mode": "check" if reports_root is None else "evaluate", "attempted_cases": 0,
                "rule_engine_sha256": fingerprint_from_sources(source_fingerprints),
                "inventory_source_sha256": source_fingerprints["src/comsol/ModelInventory.java"],
                "source_fingerprints": source_fingerprints, "input_stability_verified": False,
                "settings": {"loads": loads if reports_root is None else None,
                             "timeout_seconds_per_process": timeout if reports_root is None else None,
                             "reynolds_warning": threshold}}
    outcomes = {}

    def verify_reports_root():
        if reports_root is not None and (reports_root.is_symlink() or reports_root.is_junction()
                                         or not reports_root.is_dir()):
            raise CheckError("Input reports root changed or became a link during this run")

    def verify_inputs():
        verify_reports_root()
        if read_regular_file(manifest_path, max_bytes=MAX_METADATA_BYTES) != manifest_bytes:
            raise CheckError("Batch manifest changed during this run; no successful result published")
        if fingerprints()[0] != source_fingerprints:
            raise CheckError("Batch program or development registry changed during this run")
        for case in manifest["cases"]:
            identity = case["case_id"]
            if identity in models:
                path = models[identity]
                if (path.is_symlink() or path.is_junction() or not path.resolve(strict=True).is_relative_to(root)
                        or sha256(path).lower() != case["sha256"].lower()):
                    raise CheckError("Batch source model changed during this run: " + identity)
            if outcomes[identity]["status"] == "failed":
                # An execution failure has no scored report to authenticate. Keep
                # it failed/incomplete; do not invent a diagnosis or failure proof.
                continue
            reread = read_outcome((reports_root or directory) / identity, case, threshold)
            fields = ("status", "predicted_codes", "diagnosis_sha256", "run_metadata_sha256")
            if any(reread.get(key) != outcomes[identity].get(key) for key in fields):
                raise CheckError("Batch report changed during this run: " + identity)

    try:
        for case in manifest["cases"]:
            verify_reports_root()
            identity = case["case_id"]
            metadata["current_case"] = identity
            child = (reports_root or directory) / identity
            if reports_root is None:
                try:
                    check_model(models[identity], comsol_root=comsol_root, output_dir=child,
                                loads=loads, timeout=timeout, reynolds_warning=threshold)
                except (OSError, ValueError, CheckError, KeyError, TypeError, ValidationError) as error:
                    outcomes[identity] = {"status": "failed", "reason": str(error)}
            if identity not in outcomes:
                outcomes[identity] = read_outcome(child, case, threshold)
            metadata["attempted_cases"] += 1
            print(f"{identity}: {outcomes[identity]['status']}", flush=True)
        summary = evaluate_dataset(manifest, outcomes)
        summary.update(manifest_sha256=metadata["manifest_sha256"], mode=metadata["mode"],
                       rule_engine_sha256=metadata["rule_engine_sha256"],
                       inventory_source_sha256=metadata["inventory_source_sha256"], reynolds_warning=threshold)
        verify_inputs()
        _write_json(directory / "summary.json", summary)
        summary_bytes = read_regular_file(directory / "summary.json", max_bytes=MAX_DIAGNOSIS_BYTES)
        canonical = {"sort_keys": True, "allow_nan": False, "ensure_ascii": True}
        if json.dumps(decode_json(summary_bytes), **canonical) != json.dumps(summary, **canonical):
            raise CheckError("Saved batch summary differs from computed scores")
        report_bytes = render_report(summary).encode("utf-8")
        with (directory / "report.md").open("xb") as stream:
            stream.write(report_bytes)
        verify_inputs()
        if (read_regular_file(directory / "summary.json", max_bytes=MAX_DIAGNOSIS_BYTES) != summary_bytes
                or read_regular_file(directory / "report.md", max_bytes=MAX_DIAGNOSIS_BYTES) != report_bytes):
            raise CheckError("Batch outputs changed before completion")
        metadata.update(status="completed" if summary["checked_cases"] == summary["total_cases"] else "incomplete",
                        checked_cases=summary["checked_cases"], input_stability_verified=True,
                        summary_sha256=hashlib.sha256(summary_bytes).hexdigest())
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
    parser = argparse.ArgumentParser(description="Batch read-only checks or evaluate matching saved reports (Windows)")
    parser.add_argument("--manifest", type=Path, default=DEVELOPMENT_MANIFEST)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--comsol-root", type=Path)
    source.add_argument("--reports-root", type=Path)
    parser.add_argument("--model-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--loads", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    try:
        summary = run_suite(args.manifest, output_dir=args.output_dir, comsol_root=args.comsol_root,
                            model_root=args.model_root, reports_root=args.reports_root, loads=args.loads, timeout=args.timeout)
    except (OSError, ValueError, CheckError, KeyError, TypeError) as error:
        parser.exit(1, f"Suite failed: {error}\n")
    print(f"Checked {summary['checked_cases']}/{summary['total_cases']}; {args.output_dir / 'report.md'}")
    if summary["checked_cases"] != summary["total_cases"]:
        parser.exit(2, "Incomplete suite; inspect per-case statuses\n")
    if summary["exact_match_cases"] != summary["total_cases"]:
        parser.exit(3, "Rule-label mismatches found; inspect report\n")


if __name__ == "__main__":
    main()
