"""Read-only preparation hints; never create labels, freeze files, or certify reviewers."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot import acceptance_dataset as dataset
from flowpilot.check_suite import CORE_CODES, validate_manifest
from flowpilot.report_io import MAX_METADATA_BYTES, decode_json, read_regular_file

DISCLAIMER = ("预检只核对当前文件和声明，不冻结、不诊断、不求解、不填写审核信息；"
              "可进入冻结准备不等于身份认证、真实独立性或正式验收通过。")


def inspect_manifest(manifest_path, *, model_root):
    result = {"schema_version": "acceptance-preflight-0.1", "status": "invalid",
              "readonly": True, "software_authenticates_reviewers": False,
              "formal_acceptance_completed": False, "freeze_created": False,
              "issues": [], "cases": [], "disclaimer": DISCLAIMER}
    issues = result["issues"]

    def issue(code, field, message, case_id=None):
        item = {"code": code, "field": field, "message": message}
        if case_id is not None:
            item["case_id"] = case_id
        issues.append(item)

    try:
        raw = read_regular_file(manifest_path, max_bytes=MAX_METADATA_BYTES)
        result["manifest_sha256"] = hashlib.sha256(raw).hexdigest()
        manifest = decode_json(raw)
        validate_manifest(manifest)
    except (OSError, ValueError, TypeError, RuntimeError, RecursionError):
        issue("manifest_invalid", "manifest", "清单不可读或基本结构无效；先核对 JSON、案例 ID、路径、哈希和规则 code。")
        return result
    try:
        hashes, known = dataset.fingerprints()
        tool_raw = read_regular_file(Path(__file__), max_bytes=1024 * 1024)
        hashes["src/flowpilot/acceptance_preflight.py"] = hashlib.sha256(tool_raw).hexdigest()
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        issue("registry_unavailable", "program_fingerprints", "程序或开发集登记不可读/不完整；不能判断独立集准备条件。")
        return result
    result["program_fingerprints"] = hashes
    today = dataset._today()

    def text(value, field, identity=None):
        try:
            dataset._text(value, field)
            return True
        except ValueError:
            issue("review_text_required", field, "需由团队提供真实、非空且长度有效的信息，不自动补写。", identity)
            return False

    def date(value, field, identity=None):
        try:
            dataset._review_date(value, field, today)
        except ValueError:
            issue("review_date_invalid", field, "须为真实已发生的 YYYY-MM-DD 日期，不接受未来或非标准日期。", identity)

    if manifest.get("independent_acceptance_set") is not True:
        issue("independent_set_not_declared", "independent_acceptance_set", "尚未真实确认独立集；开发数据不能仅改标记提升资格。")
    if manifest.get("label_status") != "expert_reviewed":
        issue("expert_review_pending", "label_status", "需先完成真实专业标签审核；不以程序预期替代。")
    if len(manifest["cases"]) < 10:
        issue("too_few_cases", "cases", "正式集至少需要 10 个未见且已审核模型。")
    declaration = manifest.get("acceptance_declaration")
    if not isinstance(declaration, dict):
        issue("declaration_missing", "acceptance_declaration", "缺少团队独立性审核声明。")
        declaration = {}
    for field in ("dataset_id", "independence_reviewed_by"):
        text(declaration.get(field), "acceptance_declaration." + field)
    date(declaration.get("independence_reviewed_date"), "acceptance_declaration.independence_reviewed_date")
    for field in dataset.DECLARATIONS:
        if declaration.get(field) is not True:
            issue("declaration_not_confirmed", "acceptance_declaration." + field,
                  "需要团队真实确认；不能用数字、字符串或工具自动填写代替布尔 true。")
    try:
        root = dataset._root(model_root)
    except (OSError, ValueError, RuntimeError):
        root = None
        issue("model_root_invalid", "model_root", "模型根目录不可用或为链接；未读取任何模型。")
    identities, paths, groups, covered = set(), set(), set(), set()
    for case in manifest["cases"]:
        identity = case["case_id"]
        if identity.casefold() in identities:
            issue("case_id_collision", "case_id", "案例 ID 存在大小写重名。", identity)
        identities.add(identity.casefold())
        covered.update(case["expected_codes"])
        for field in ("created_by", "origin_reference", "reviewed_by", "independence_group"):
            valid = text(case.get(field), field, identity)
            if valid and field == "independence_group":
                groups.add(case[field].strip().casefold())
        date(case.get("reviewed_date"), "reviewed_date", identity)
        if case.get("used_for_rule_development") is not False:
            issue("development_usage_not_excluded", "used_for_rule_development", "需真实确认未用于规则调试。", identity)
        if case["sha256"].lower() in known:
            issue("known_development_model", "sha256", "清单哈希属于已登记的开发模型，不能作为独立案例。", identity)
        if "EVALUATION_UNAVAILABLE" in case["expected_codes"]:
            issue("robustness_case_not_formal", "expected_codes", "未完成求值样本应归鲁棒性检查，不混入正式支持范围集。", identity)
        row = {"case_id": identity, "model_status": "not_checked", "file_hash_matches": None}
        result["cases"].append(row)
        try:
            relative = dataset._relative(case["model_path"])
            if str(relative).casefold() in paths:
                issue("model_path_collision", "model_path", "模型路径存在大小写重名。", identity)
            paths.add(str(relative).casefold())
        except ValueError:
            row["model_status"] = "unsafe_path"
            issue("model_path_invalid", "model_path", "只允许根目录内的相对 MPH 路径，不允许越界或备用数据流。", identity)
            continue
        if root is None:
            continue
        try:
            path = dataset._model(root, case["model_path"])
            digest = dataset.sha256(path)
            row.update(actual_sha256=digest, file_hash_matches=digest == case["sha256"].lower())
            row["model_status"] = "matches" if row["file_hash_matches"] else "hash_mismatch"
            if not row["file_hash_matches"]:
                issue("model_hash_mismatch", "sha256", "模型与审核清单不同；保留原件并重新人工确认，不自动改哈希。", identity)
        except FileNotFoundError:
            row["model_status"] = "missing"
            issue("model_missing", "model_path", "模型文件不存在；确认文件位置及 LFS 下载。", identity)
        except ValueError:
            row["model_status"] = "invalid_file"
            issue("model_file_invalid", "model_path", "模型为空、仍为 LFS 指针、是链接/目录或路径无效；未作为有效模型。", identity)
        except (OSError, RuntimeError):
            row["model_status"] = "read_error"
            issue("model_read_error", "model_path", "无法读取模型；检查权限、占用和路径。", identity)
    missing = sorted(CORE_CODES - covered)
    if missing:
        issue("rules_not_covered", "expected_codes", "尚未覆盖首批规则：" + ", ".join(missing))
    if not any(not case["expected_codes"] for case in manifest["cases"]):
        issue("negative_control_missing", "expected_codes", "至少需要一个审核后无预期问题的负对照。")
    if len(groups) < 2:
        issue("independent_groups_insufficient", "independence_group", "至少登记两个独立来源组；不同组名本身也不证明独立性。")
    # Hints cannot weaken the actual freeze gate, even if the preparation UI misses a field.
    try:
        dataset.validate_acceptance(manifest, known, today=today)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        issue("freeze_validation_failed", "manifest", "正式冻结校验未通过；上列为准备提示，最终仍以冻结入口重新检查为准。")
    try:
        final_hashes, final_known = dataset.fingerprints()
        final_hashes["src/flowpilot/acceptance_preflight.py"] = hashlib.sha256(
            read_regular_file(Path(__file__), max_bytes=1024 * 1024)).hexdigest()
        if read_regular_file(manifest_path, max_bytes=MAX_METADATA_BYTES) != raw or final_hashes != hashes or final_known != known:
            raise ValueError("changed")
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        issue("inputs_changed", "manifest/program_fingerprints", "预检期间清单、程序或开发集登记变化，须重新预检。")
    result["summary"] = {"case_count": len(manifest["cases"]), "declared_group_count": len(groups),
                         "matching_model_count": sum(row["file_hash_matches"] is True for row in result["cases"]),
                         "issue_count": len(issues)}
    result["status"] = "blocked" if issues else "ready_to_freeze"
    return result


def render_preflight(result):
    lines = ["FlowPlot 验收清单草稿预检：" + result["status"], DISCLAIMER]
    if "summary" in result:
        summary = result["summary"]
        lines.append(f"案例：{summary['case_count']}；文件哈希匹配：{summary['matching_model_count']}；"
                     f"声明来源组：{summary['declared_group_count']}；待办：{summary['issue_count']}。")
    for item in result["issues"]:
        label = (item["case_id"] + " / ") if "case_id" in item else ""
        lines.append(label + item["field"] + "：" + item["message"])
    for row in result["cases"]:
        lines.append(row["case_id"] + "：" + row["model_status"])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="只读列出正式清单准备问题；不补造数据、不创建冻结目录。")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--json", action="store_true", help="仅向标准输出打印，不写文件")
    args = parser.parse_args()
    result = inspect_manifest(args.manifest, model_root=args.model_root)
    if args.json:
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        print(render_preflight(result))
    return 0 if result["status"] == "ready_to_freeze" else 2 if result["status"] == "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
