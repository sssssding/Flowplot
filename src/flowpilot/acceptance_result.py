"""Recompute frozen-run scores from verified reports; never authenticate human review."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot.acceptance_dataset import DISCLAIMER, _new_output, _root, verify_dataset
from flowpilot.check_model import CheckError, _markdown_text, _write_json
from flowpilot.check_suite import evaluate_dataset, read_outcome
from flowpilot.report_io import MAX_DIAGNOSIS_BYTES, MAX_METADATA_BYTES, decode_json, read_regular_file

EXTRA_FIELDS = {"manifest_sha256", "mode", "rule_engine_sha256", "inventory_source_sha256", "reynolds_warning"}


def same_json(left, right):
    """Do not treat True as 1, or silently coerce types in recorded scores."""
    options = {"sort_keys": True, "ensure_ascii": True, "allow_nan": False, "separators": (",", ":")}
    return json.dumps(left, **options) == json.dumps(right, **options)


def _snapshot(path, limit):
    payload = read_regular_file(path, max_bytes=limit)
    return decode_json(payload), hashlib.sha256(payload).hexdigest()


def suite_snapshot(directory):
    root = _root(directory)
    run, run_digest = _snapshot(root / "run.json", MAX_METADATA_BYTES)
    summary, summary_digest = _snapshot(root / "summary.json", MAX_DIAGNOSIS_BYTES)
    if (not isinstance(run, dict) or run.get("schema_version") != "check-suite-run-0.1"
            or not isinstance(summary, dict) or summary.get("schema_version") != "check-suite-report-0.1"):
        raise ValueError("批量产物的结构或版本无效")
    return {"run": run, "summary": summary, "run_sha256": run_digest, "summary_sha256": summary_digest}


def check_suite_record(snapshot, loaded, mode):
    summary, run = snapshot["summary"], snapshot["run"]
    count = len(loaded["manifest"]["cases"])
    checked = summary.get("checked_cases")
    if type(checked) is not int or not 0 <= checked <= count:
        raise ValueError("完整检查案例数无效")
    status = "completed" if checked == count else "incomplete"
    source = loaded["metadata"]["source_fingerprints"]
    settings = loaded["manifest"]["reynolds_warning"]
    expected = {"status": status, "attempted_cases": count, "checked_cases": checked, "mode": mode,
                "manifest_sha256": loaded["metadata"]["manifest_sha256"],
                "rule_engine_sha256": source["src/flowpilot/diagnostics.py"],
                "inventory_source_sha256": source["src/comsol/ModelInventory.java"]}
    if (any(not same_json(run.get(key), value) for key, value in expected.items())
            or not isinstance(run.get("settings"), dict)
            or not same_json(run["settings"].get("reynolds_warning"), settings)):
        raise ValueError("批量完成记录、来源或设置与冻结输入不符")
    provenance = {key: expected[key] for key in EXTRA_FIELDS - {"reynolds_warning"}}
    provenance["reynolds_warning"] = settings
    if any(not same_json(summary.get(key), value) for key, value in provenance.items()):
        raise ValueError("批量汇总来源或设置与冻结输入不符")
    return status


def _scoring(value):
    result = copy.deepcopy(value)
    for row in result.get("cases", []):
        if isinstance(row, dict):
            # Failure text can contain machine-local paths; it is not a scoring input.
            row.pop("reason", None)
    return result


def load_acceptance_result(directory, *, dataset_dir, reports_root=None):
    root = _root(directory)
    run, run_digest = _snapshot(root / "run.json", MAX_METADATA_BYTES)
    result, result_digest = _snapshot(root / "result.json", MAX_DIAGNOSIS_BYTES)
    if (not isinstance(run, dict) or run.get("schema_version") != "acceptance-run-0.2"
            or run.get("status") not in ("completed", "incomplete") or run.get("mode") not in ("check", "evaluate")
            or run.get("result_sha256") != result_digest or not isinstance(result, dict)
            or result.get("schema_version") != "acceptance-result-0.2"
            or result.get("software_authenticates_reviewers") is not False):
        raise ValueError("正式运行未完成、结果无绑定或版本无效；拒绝读取为验收成绩")
    try:
        start, finish = (datetime.fromisoformat(run[key]) for key in ("started_at", "finished_at"))
        if start.tzinfo is None or finish.tzinfo is None or finish < start:
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise ValueError("正式运行缺少有效的开始/结束时间") from None
    loaded = verify_dataset(dataset_dir)
    for payload in (run, result):
        if (payload.get("freeze_sha256") != loaded["freeze_sha256"]
                or payload.get("dataset_id") != loaded["metadata"]["dataset_id"]):
            raise ValueError("正式结果不属于本冻结集")
    snapshot = suite_snapshot(root / "checks")
    if (run.get("suite_run_sha256") != snapshot["run_sha256"]
            or run.get("suite_summary_sha256") != snapshot["summary_sha256"]
            or not same_json(result.get("evaluation"), snapshot["summary"])):
        raise ValueError("批量产物、正式结果或记录指纹已变化")
    expected_status = check_suite_record(snapshot, loaded, run["mode"])
    if run["status"] != expected_status:
        raise ValueError("正式完成状态与批量覆盖不符")
    if run["mode"] == "evaluate" and reports_root is None:
        raise ValueError("离线复核结果必须显式指定原单模型报告根目录；不猜测本机路径")
    if run["mode"] == "check" and reports_root is not None:
        raise ValueError("真实检查结果只复核自身 checks 子目录，不能替换报告根目录")
    reports = _root(reports_root) if reports_root is not None else _root(root / "checks")
    stored = snapshot["summary"]
    rows = stored.get("cases")
    cases = loaded["manifest"]["cases"]
    if (not isinstance(rows, list) or len(rows) != len(cases)
            or any(not isinstance(row, dict) or row.get("case_id") != case["case_id"] for row, case in zip(rows, cases))):
        raise ValueError("案例清单缺失、重排或不属于冻结集")
    outcomes, limitations = {}, []
    for case, row in zip(cases, rows):
        child = reports / case["case_id"]
        if child.is_symlink() or child.is_junction():
            raise ValueError("单模型报告目录不允许链接或目录联接")
        outcome = read_outcome(child, case, loaded["manifest"]["reynolds_warning"])
        if row.get("status") == "failed" and run["mode"] == "check" and outcome["status"] == "unscored":
            # A failed compiler/start may leave no single-model run. It cannot be scored
            # as clean, nor can we claim to have authenticated the original failure cause.
            path = child / "run.json"
            if path.exists():
                failed, _ = _snapshot(path, MAX_METADATA_BYTES)
                if not isinstance(failed, dict) or failed.get("status") != "failed":
                    raise ValueError("失败案例的终态记录不符")
            outcome = {"status": "failed", "reason": row.get("reason", "原记录失败；没有完整诊断")}
        if outcome["status"] in ("unscored", "missing", "failed"):
            limitations.append(case["case_id"])
        outcomes[case["case_id"]] = outcome
    computed = evaluate_dataset(loaded["manifest"], outcomes)
    if set(stored) != set(computed) | EXTRA_FIELDS:
        raise ValueError("正式汇总字段缺失或未知，不能静默补造")
    recorded_scores = {key: stored[key] for key in computed}
    if not same_json(_scoring(recorded_scores), _scoring(computed)):
        raise ValueError("逐模型证据、漏报/误报、覆盖或 Recall 与重算不一致")
    final = verify_dataset(dataset_dir)
    if final["freeze_sha256"] != loaded["freeze_sha256"]:
        raise ValueError("冻结集在结果复核期间变化")
    return {"schema_version": "acceptance-review-0.1",
            "status": "verified_complete" if expected_status == "completed" else "verified_incomplete",
            "dataset_id": run["dataset_id"], "mode": run["mode"], "freeze_sha256": loaded["freeze_sha256"],
            "original_run_sha256": run_digest, "original_result_sha256": result_digest,
            "suite_run_sha256": snapshot["run_sha256"], "suite_summary_sha256": snapshot["summary_sha256"],
            "summary": _scoring(computed), "unverifiable_failure_case_ids": limitations,
            "software_authenticates_reviewers": False, "disclaimer": DISCLAIMER}


def render_review(review):
    def text(value):
        return _markdown_text(html.escape(str(value), quote=True))
    def percent(value):
        return "不适用" if value is None else f"{value:.2%}"
    summary = review["summary"]
    target = summary["meets_recall_above_90_percent"]
    headline = ("完整检查记录已重算核验" if review["status"] == "verified_complete"
                else "检查未完成；不能作为独立验收通过")
    lines = ["# FlowPlot 验收结果复核", "", headline, "",
             "数据集：" + text(review["dataset_id"]),
             f"冻结标记指纹：`{review['freeze_sha256']}`", "",
             f"完整覆盖：{summary['checked_cases']}/{summary['total_cases']}；"
             f"逐模型 code 集合匹配：{summary['exact_match_cases']}/{summary['total_cases']}。",
             f"Precision：{percent(summary['metrics_on_checked_cases_only']['precision'])}；"
             f"Recall：{percent(summary['metrics_on_checked_cases_only']['recall'])}；"
             f"F1：{percent(summary['metrics_on_checked_cases_only']['f1'])}。",
             f"所有预期标签的 Recall 保守下界：{percent(summary['recall_lower_bound_all_expected_codes'])}。",
             ("声明条件下的 Recall > 90% 目标满足。" if target is True
              else "Recall > 90% 目标未满足。" if target is False else "没有完整有效的独立 Recall 目标结论。"), "",
             "| 案例 | 状态 | 漏报 | 误报 |", "|---|---|---|---|"]
    for row in summary["cases"]:
        missed = "未计分" if row["missed_codes"] is None else ", ".join(row["missed_codes"]) or "—"
        unexpected = "未计分" if row["unexpected_codes"] is None else ", ".join(row["unexpected_codes"]) or "—"
        lines.append(f"| {text(row['case_id'])} | {text(row['status'])} | {text(missed)} | {text(unexpected)} |")
    if review["unverifiable_failure_case_ids"]:
        lines += ["", "以下案例没有完整可计分的诊断指纹；只确认本次仍不可计分，"
                  "不认证原失败原因或失败文件从未变化：" + text(", ".join(review["unverifiable_failure_case_ids"])) + "。"]
    lines += ["", DISCLAIMER,
              "结果复核不是物理、严重等级、边界定位或新用户试用验收；哈希不是作者签名。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="离线核验正式验收结果并重算；不运行 COMSOL，不认证人工审核。")
    parser.add_argument("run", type=Path)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--reports-root", type=Path, help="仅用于原离线运行：必须指定原单模型报告目录")
    parser.add_argument("--output-dir", type=Path, help="可选的新目录，另存 review.json 和中文 report.md")
    args = parser.parse_args()
    try:
        review = load_acceptance_result(args.run, dataset_dir=args.dataset, reports_root=args.reports_root)
        if args.output_dir is not None:
            output = _new_output(args.output_dir, _root(args.run))
            if output.is_relative_to(_root(args.dataset)) or (
                    args.reports_root is not None and output.is_relative_to(_root(args.reports_root))):
                raise ValueError("导出不能位于冻结集或原报告目录内")
            output.mkdir(parents=True, exist_ok=False)
            _write_json(output / "review.json", review)
            with (output / "report.md").open("x", encoding="utf-8") as stream:
                stream.write(render_review(review))
        print(render_review(review))
        return 0 if review["status"] == "verified_complete" else 2
    except (OSError, ValueError, CheckError, KeyError, TypeError, RuntimeError) as error:
        parser.exit(1, f"正式结果复核失败：{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
