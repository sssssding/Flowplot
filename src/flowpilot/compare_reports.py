"""Compare two completed checks offline; differences never prove a repair."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot.check_model import CheckError, _markdown_text, _write_json, sha256
from flowpilot.desktop_session import TITLES, load_completed_check
from flowpilot.diagnostics import is_finite_number

DISCLAIMER = ("本次仅比较两份报告，不重新加载或求解模型。“本次未再报告”不等于修复成功；"
              "节点和边界按标识匹配，不验证几何实体对应关系、模型演进关系或物理正确性。")
CHANGE_LABELS = {"added": "本次新增报告", "removed": "本次未再报告",
                 "changed": "等级、解释、证据或条目数量变化", "unchanged": "报告条目相同"}


def _provenance(loaded):
    metadata = loaded["metadata"]
    settings = metadata.get("settings")
    return {"source": {key: metadata["source"][key] for key in ("filename", "sha256")},
            "diagnosis_status": loaded["report"]["status"],
            "rule_engine_sha256": metadata.get("rule_engine_sha256"),
            "inventory_source_sha256": metadata.get("inventory_source_sha256"),
            "comsol_version": metadata.get("comsol_version"),
            "reynolds_warning": settings.get("reynolds_warning") if isinstance(settings, dict) else None,
            "profile": loaded["report"].get("profile"),
            "run_sha256": loaded["run_sha256"],
            "diagnosis_sha256": metadata["diagnosis_sha256"]}


def _groups(findings):
    groups = {}
    for item in findings:
        key = (item["code"], tuple(sorted(item["feature_tags"])), tuple(sorted(item["boundary_ids"])))
        canonical = {**item, "feature_tags": list(key[1]), "boundary_ids": list(key[2])}
        groups.setdefault(key, []).append(canonical)
    for values in groups.values():
        values.sort(key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=True, allow_nan=False))
    return groups


def compare_reports(before_dir, after_dir):
    """Re-read and verify both files, even if a GUI already displays one of them."""
    before, after = (load_completed_check(path) for path in (before_dir, after_dir))
    sides = [_provenance(loaded) for loaded in (before, after)]
    reasons = []
    if any(side["diagnosis_status"] != "checked" for side in sides):
        reasons.append("至少一份报告未完成全部规则（partial / unsupported），不能推断问题新增或消失。")
    for field, label in (("rule_engine_sha256", "规则源码"), ("inventory_source_sha256", "模型读取源码")):
        values = [side[field] for side in sides]
        if any(not isinstance(value, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", value) for value in values):
            reasons.append(f"缺少有效的{label}哈希。")
        elif values[0].lower() != values[1].lower():
            reasons.append(f"两份报告的{label}不同。")
    for field, label in (("comsol_version", "COMSOL 版本"), ("profile", "检查模板")):
        values = [side[field] for side in sides]
        if any(not isinstance(value, str) or not value for value in values):
            reasons.append(f"缺少{label}。")
        elif values[0] != values[1]:
            reasons.append(f"两份报告的{label}不同。")
    thresholds = [side["reynolds_warning"] for side in sides]
    if any(not is_finite_number(value) or value <= 0 for value in thresholds):
        reasons.append("缺少有效的 Re 筛查阈值。")
    elif thresholds[0] != thresholds[1]:
        reasons.append("两份报告的 Re 筛查阈值不同。")
    rows = []
    if not reasons:
        left, right = (_groups(loaded["report"]["findings"]) for loaded in (before, after))
        for key in sorted(left.keys() | right.keys()):
            old, new = left.get(key, []), right.get(key, [])
            identical = json.dumps(old, sort_keys=True, allow_nan=False) == json.dumps(new, sort_keys=True, allow_nan=False)
            kind = "added" if not old else "removed" if not new else "unchanged" if identical else "changed"
            rows.append({"kind": kind, "code": key[0], "title": TITLES[key[0]],
                         "feature_tags": list(key[1]), "boundary_ids": list(key[2]), "before": old, "after": new})
    counts = {kind: sum(row["kind"] == kind for row in rows) for kind in CHANGE_LABELS} if not reasons else None
    return {"schema_version": "report-comparison-0.1", "status": "not_comparable" if reasons else "compared",
            "created_at": datetime.now(timezone.utc).isoformat(), "before": sides[0], "after": sides[1],
            "same_model_sha256": sides[0]["source"]["sha256"].lower() == sides[1]["source"]["sha256"].lower(),
            "blocking_reasons": reasons, "counts": counts, "rows": rows, "disclaimer": DISCLAIMER}


def render_comparison(summary):
    lines = ["# FlowPilot 检查报告对比", "", summary["disclaimer"], ""]
    for field, label in (("before", "前次"), ("after", "本次")):
        side = summary[field]
        lines += [f"{label}：{_markdown_text(side['source']['filename'])}",
                  f"模型 SHA-256：`{side['source']['sha256']}`",
                  f"COMSOL：{_markdown_text(side['comsol_version'])}；Re 筛查阈值：{_markdown_text(side['reynolds_warning'])}", ""]
    if summary["same_model_sha256"]:
        lines += ["两份报告的模型字节哈希相同。", ""]
    else:
        lines += ["两份报告的模型字节哈希不同；请人工确认所选文件确实适合对比。", ""]
    if summary["status"] == "not_comparable":
        lines += ["## 无法直接比较", ""]
        lines += ["- " + _markdown_text(reason) for reason in summary["blocking_reasons"]]
        return "\n".join(lines) + "\n"
    lines += ["## 差异汇总", ""]
    lines += [f"- {label}：{summary['counts'][kind]} 组" for kind, label in CHANGE_LABELS.items()]
    lines += ["", "按规则、节点标识和边界编号分组；同组重复条目保留，不按问题数宣称质量提升。", ""]
    for row in summary["rows"]:
        lines += [f"## {CHANGE_LABELS[row['kind']]} · {row['code']}", "",
                  "相关节点：" + _markdown_text(", ".join(row["feature_tags"]) or "—"),
                  "边界编号：" + _markdown_text(", ".join(map(str, row["boundary_ids"])) or "—"), "",
                  "```json", json.dumps({"before": row["before"], "after": row["after"]}, ensure_ascii=False, indent=2),
                  "```", ""]
    return "\n".join(lines) + "\n"


def write_comparison(summary, output_dir):
    """New output only; never alter either input report directory."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=False)
    _write_json(directory / "comparison.json", summary)
    with (directory / "report.md").open("x", encoding="utf-8") as stream:
        stream.write(render_comparison(summary))
    return directory.resolve()


def main():
    parser = argparse.ArgumentParser(description="Compare completed model-check reports offline")
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = compare_reports(args.before, args.after)
        directory = write_comparison(summary, args.output_dir)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, CheckError, RecursionError) as error:
        parser.exit(1, f"Comparison failed: {error}\n")
    print(f"{summary['status']}: {directory / 'report.md'}")
    return 0 if summary["status"] == "compared" else 2


if __name__ == "__main__":
    sys.exit(main())
