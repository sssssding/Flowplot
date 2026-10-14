"""Freeze reviewed inputs before diagnosis; never invent reviewers or independent data."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import importlib.metadata
from pathlib import Path, PurePosixPath
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot.check_model import ROOT, CheckError, LFS_HEADER, _write_json, sha256
from flowpilot.check_suite import acceptance_reasons, run_suite, validate_manifest
from flowpilot.diagnostics import is_finite_number
from flowpilot.report_io import MAX_DIAGNOSIS_BYTES, MAX_METADATA_BYTES, decode_json, read_regular_file

SOURCES = (
    "src/flowpilot/diagnostics.py", "src/comsol/ModelInventory.java",
    "schema/diagnostic-model.schema.json", "src/flowpilot/check_model.py",
    "src/flowpilot/check_suite.py", "src/flowpilot/desktop_session.py",
    "src/flowpilot/report_io.py", "src/flowpilot/package_integrity.py",
    "src/flowpilot/acceptance_dataset.py",
    "src/flowpilot/acceptance_result.py",
)
REGISTRIES = ("data/fixtures/cases/manifest.json", "data/fixtures/regression_family.json",
              "data/fixtures/ai_development_registry.json")
DECLARATIONS = ("models_not_derived_from_development", "labels_fixed_before_diagnosis",
                "creators_and_reviewers_not_rule_developers")
DISCLAIMER = ("冻结仅固定已提供的文件和声明，不认证审核身份、标签正确性或真实独立性；"
              "Recall 统计不等于全部物理与界面验收通过。")


def _today():
    return datetime.now(timezone(timedelta(hours=8))).date()


def _text(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 1000 or "\x00" in value:
        raise ValueError("缺少或无效的声明字段：" + field)


def _review_date(value, field, today):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value or parsed > today:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("审核日期须为已发生的 YYYY-MM-DD 日期：" + field) from None


def fingerprints():
    # Capture the same bytes used to parse the known development registries.
    payloads = {name: read_regular_file(ROOT / name, max_bytes=1024 * 1024)
                for name in (*SOURCES, *REGISTRIES)}
    hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in payloads.items()}
    original = decode_json(payloads[REGISTRIES[0]])
    variations = decode_json(payloads[REGISTRIES[1]])
    known = {case["sha256"].lower() for case in original["cases"]}
    known.update(case["source_sha256"].lower() for case in variations["cases"])
    ai_models = decode_json(payloads[REGISTRIES[2]])
    if (not isinstance(ai_models, dict) or ai_models.get("schema_version") != "ai-development-registry-0.1"
            or ai_models.get("development_only") is not True or ai_models.get("independent_acceptance_set") is not False
            or not isinstance(ai_models.get("cases"), list) or not ai_models["cases"]):
        raise ValueError("AI 开发模型登记无效，不能冻结正式验收集")
    for case in ai_models["cases"]:
        digest = case.get("source_sha256") if isinstance(case, dict) else None
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("AI 开发模型指纹无效")
        known.add(digest)
    if len(known) < 20:
        raise ValueError("已知开发集登记不完整，不能冻结正式验收集")
    return hashes, known


def validate_acceptance(manifest, known_hashes, *, today=None):
    validate_manifest(manifest)
    today = today or _today()
    reasons = acceptance_reasons(manifest)
    if reasons:
        raise ValueError("尚不能冻结正式验收清单：" + ", ".join(reasons))
    if len(manifest["cases"]) < 10:
        raise ValueError("正式验收集至少需要 10 个未见且已审核模型")
    declaration = manifest.get("acceptance_declaration")
    if not isinstance(declaration, dict):
        raise ValueError("缺少 acceptance_declaration；不自动补写独立性声明")
    for field in ("dataset_id", "independence_reviewed_by"):
        _text(declaration.get(field), field)
    _review_date(declaration.get("independence_reviewed_date"), "independence_reviewed_date", today)
    for field in DECLARATIONS:
        if declaration.get(field) is not True:
            raise ValueError("需要团队真实确认，而非程序自动填写：" + field)
    identities, paths, groups = set(), set(), set()
    for case in manifest["cases"]:
        identity = case["case_id"].casefold()
        relative = _relative(case["model_path"])
        normalized = str(relative).casefold()
        if identity in identities or normalized in paths:
            raise ValueError("案例 ID 或模型路径大小写重名")
        identities.add(identity)
        paths.add(normalized)
        if case["sha256"].lower() in known_hashes:
            raise ValueError("模型属于已知开发集，不能重新标记为独立集：" + case["case_id"])
        for field in ("created_by", "origin_reference", "independence_group", "reviewed_by"):
            _text(case.get(field), field)
        _review_date(case.get("reviewed_date"), "reviewed_date", today)
        groups.add(case["independence_group"].strip().casefold())
        if "EVALUATION_UNAVAILABLE" in case["expected_codes"]:
            raise ValueError("未完成求值的鲁棒性样本不能混入正式支持范围验收集")
    if len(groups) < 2:
        raise ValueError("至少登记两个独立来源组；组名不同本身也不能证明独立性")
    return manifest


def _relative(value):
    if not isinstance(value, str) or "\x00" in value or ":" in value:
        raise ValueError("无效模型路径")
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or path.suffix.lower() != ".mph":
        raise ValueError("模型必须是根目录内的相对 .mph 路径")
    return path


def _root(directory):
    directory = Path(directory)
    if directory.is_symlink() or directory.is_junction() or not directory.is_dir():
        raise ValueError("数据集根目录必须是实际目录，不能是链接")
    return directory.resolve(strict=True)


def _model(root, relative):
    path = root
    for part in _relative(relative).parts:
        path = path / part
        if path.is_symlink() or path.is_junction():
            raise ValueError("模型路径不允许链接或目录联接")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("模型不在根目录内或不是普通文件")
    with resolved.open("rb") as stream:
        prefix = stream.read(len(LFS_HEADER))
    if not prefix or prefix.startswith(LFS_HEADER):
        raise ValueError("模型为空或仍是 Git LFS 指针")
    return resolved


def _new_output(output_dir, protected):
    output = Path(output_dir)
    if output.exists() or output.is_symlink() or output.is_junction():
        raise FileExistsError("输出目录已存在，拒绝覆盖：" + output.name)
    resolved = output.resolve()
    if resolved.is_relative_to(protected):
        raise ValueError("输出目录不能位于输入根目录或冻结集内部")
    return resolved


def freeze_dataset(manifest_path, *, model_root, output_dir):
    raw_manifest = read_regular_file(manifest_path, max_bytes=MAX_METADATA_BYTES)
    hashes, known = fingerprints()
    manifest = validate_acceptance(decode_json(raw_manifest), known)
    root = _root(model_root)
    output = _new_output(output_dir, root)
    models = {}
    for case in manifest["cases"]:
        path = _model(root, case["model_path"])
        if sha256(path) != case["sha256"].lower():
            raise ValueError("模型哈希与已审核清单不同：" + case["case_id"])
        models[case["case_id"]] = path
    # Every declaration and source model is validated before any output is created.
    output.mkdir(parents=True, exist_ok=False)
    (output / "models").mkdir()
    frozen = {"schema_version": "case-manifest-0.1", "label_status": "expert_reviewed",
              "independent_acceptance_set": True, "reynolds_warning": manifest.get("reynolds_warning", 2000.),
              "acceptance_declaration": manifest["acceptance_declaration"], "cases": []}
    fields = ("case_id", "expected_codes", "reviewed_by", "reviewed_date", "used_for_rule_development",
              "created_by", "origin_reference", "independence_group")
    for case in manifest["cases"]:
        relative = "models/" + case["case_id"] + ".mph"
        with models[case["case_id"]].open("rb") as source, (output / relative).open("xb") as target:
            digest = hashlib.sha256()
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
                target.write(block)
        if digest.hexdigest() != case["sha256"].lower() or sha256(output / relative) != case["sha256"].lower():
            raise ValueError("复制期间模型发生变化；未发布有效冻结集")
        frozen["cases"].append({**{key: case[key] for key in fields},
                                "model_path": relative, "sha256": digest.hexdigest()})
    _write_json(output / "manifest.json", frozen)
    for case in manifest["cases"]:
        if sha256(models[case["case_id"]]) != case["sha256"].lower():
            raise ValueError("原模型在冻结期间变化；未发布有效冻结集")
    if fingerprints()[0] != hashes:
        raise ValueError("程序或开发登记在冻结期间变化；未发布有效冻结集")
    if read_regular_file(manifest_path, max_bytes=MAX_METADATA_BYTES) != raw_manifest:
        raise ValueError("审核清单在冻结期间变化；未发布有效冻结集")
    metadata = {"schema_version": "acceptance-freeze-0.1", "status": "frozen",
                "frozen_at": datetime.now(timezone.utc).isoformat(),
                "dataset_id": frozen["acceptance_declaration"]["dataset_id"], "case_count": len(frozen["cases"]),
                "source_manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
                "manifest_sha256": sha256(output / "manifest.json"), "source_fingerprints": hashes,
                "python_version": sys.version.split()[0], "jsonschema_version": importlib.metadata.version("jsonschema"),
                "software_authenticates_reviewers": False, "disclaimer": DISCLAIMER}
    # Completion marker LAST. A failed partial copy has no valid freeze.json and is never reused.
    _write_json(output / "freeze.json", metadata)
    return metadata


def verify_dataset(directory):
    root = _root(directory)
    raw = read_regular_file(root / "freeze.json", max_bytes=MAX_METADATA_BYTES)
    metadata = decode_json(raw)
    hashes, known = fingerprints()
    manifest_raw = read_regular_file(root / "manifest.json", max_bytes=MAX_METADATA_BYTES)
    if (not isinstance(metadata, dict) or metadata.get("schema_version") != "acceptance-freeze-0.1"
            or metadata.get("status") != "frozen" or metadata.get("software_authenticates_reviewers") is not False
            or metadata.get("source_fingerprints") != hashes
            or metadata.get("manifest_sha256") != hashlib.sha256(manifest_raw).hexdigest()):
        raise ValueError("冻结状态、清单或程序版本不一致；不得沿用旧冻结结果")
    if not isinstance(metadata.get("source_manifest_sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", metadata["source_manifest_sha256"]):
        raise ValueError("缺少原审核清单来源指纹")
    try:
        frozen_at = datetime.fromisoformat(metadata["frozen_at"])
        if frozen_at.tzinfo is None:
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise ValueError("缺少有效冻结时间") from None
    manifest = validate_acceptance(decode_json(manifest_raw), known)
    if (metadata.get("case_count") != len(manifest["cases"])
            or metadata.get("dataset_id") != manifest["acceptance_declaration"]["dataset_id"]):
        raise ValueError("冻结集标识或案例数量不一致")
    expected_files = {case["case_id"] + ".mph" for case in manifest["cases"]}
    if {path.name for path in root.iterdir()} != {"models", "manifest.json", "freeze.json"}:
        raise ValueError("冻结目录含额外或缺失内容")
    model_dir = _root(root / "models")
    if {path.name for path in model_dir.iterdir()} != expected_files:
        raise ValueError("冻结模型目录含额外或缺失模型")
    for case in manifest["cases"]:
        if case["model_path"] != "models/" + case["case_id"] + ".mph":
            raise ValueError("冻结模型路径不规范")
        if sha256(_model(root, case["model_path"])) != case["sha256"].lower():
            raise ValueError("冻结模型已变化：" + case["case_id"])
    return {"metadata": metadata, "manifest": manifest, "directory": root,
            "freeze_sha256": hashlib.sha256(raw).hexdigest()}


def run_frozen(directory, *, output_dir, comsol_root=None, reports_root=None, loads=2, timeout=300.):
    if type(loads) is not int or not 1 <= loads <= 10 or not is_finite_number(timeout) or timeout <= 0:
        raise ValueError("加载次数须为 1 到 10，超时须为有限正数")
    loaded = verify_dataset(directory)
    if (comsol_root is None) == (reports_root is None):
        raise ValueError("请选择真实 COMSOL 检查或已有报告离线复核之一")
    output = _new_output(output_dir, loaded["directory"])
    if reports_root is not None:
        reports_root = _root(reports_root)
        if output.is_relative_to(reports_root):
            raise ValueError("正式运行输出不能位于输入报告根目录内部")
    output.mkdir(parents=True, exist_ok=False)
    metadata = {"schema_version": "acceptance-run-0.2", "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "dataset_id": loaded["metadata"]["dataset_id"], "freeze_sha256": loaded["freeze_sha256"],
                "mode": "check" if reports_root is None else "evaluate"}
    try:
        summary = run_suite(loaded["directory"] / "manifest.json", output_dir=output / "checks",
                            model_root=loaded["directory"], comsol_root=comsol_root, reports_root=reports_root,
                            loads=loads, timeout=timeout)
        final = verify_dataset(loaded["directory"])
        if final["freeze_sha256"] != loaded["freeze_sha256"]:
            raise ValueError("冻结集在评估期间发生变化，正式结果不发布")
        from flowpilot.acceptance_result import _snapshot, check_suite_record, same_json, suite_snapshot
        snapshot = suite_snapshot(output / "checks")
        if not same_json(summary, snapshot["summary"]):
            raise ValueError("批量返回值与保存汇总不一致，正式结果不发布")
        status = check_suite_record(snapshot, final, metadata["mode"])
        metadata.update(suite_run_sha256=snapshot["run_sha256"], suite_summary_sha256=snapshot["summary_sha256"])
        result = {"schema_version": "acceptance-result-0.2", "dataset_id": metadata["dataset_id"],
                  "freeze_sha256": loaded["freeze_sha256"], "evaluation": summary,
                  "software_authenticates_reviewers": False, "disclaimer": DISCLAIMER}
        _write_json(output / "result.json", result)
        published, result_digest = _snapshot(output / "result.json", MAX_DIAGNOSIS_BYTES)
        if not same_json(published, result):
            raise ValueError("正式结果在发布时变化；不记录为完成")
        metadata.update(status=status, result_sha256=result_digest)
        return result
    except KeyboardInterrupt:
        metadata.update(status="cancelled", error="用户中断")
        raise
    except Exception as error:
        metadata.update(status="failed", error=str(error))
        raise
    finally:
        metadata["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(output / "run.json", metadata)


def main():
    parser = argparse.ArgumentParser(description="先冻结真实已审核验收集，再核验/评估；不补造标签或审核人。")
    commands = parser.add_subparsers(dest="action", required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--manifest", type=Path, required=True)
    freeze.add_argument("--model-root", type=Path, required=True)
    freeze.add_argument("--output-dir", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("dataset", type=Path)
    run = commands.add_parser("run")
    run.add_argument("dataset", type=Path)
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--comsol-root", type=Path)
    source.add_argument("--reports-root", type=Path)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--loads", type=int, default=2)
    run.add_argument("--timeout", type=float, default=300.)
    args = parser.parse_args()
    try:
        if args.action == "freeze":
            result = freeze_dataset(args.manifest, model_root=args.model_root, output_dir=args.output_dir)
            print(f"已冻结 {result['case_count']} 个案例；尚未执行诊断。")
        elif args.action == "verify":
            loaded = verify_dataset(args.dataset)
            print(f"冻结文件和程序指纹一致：{loaded['metadata']['case_count']} 个案例。")
        else:
            result = run_frozen(args.dataset, output_dir=args.output_dir, comsol_root=args.comsol_root,
                                reports_root=args.reports_root, loads=args.loads, timeout=args.timeout)
            summary = result["evaluation"]
            print(f"完整检查 {summary['checked_cases']}/{summary['total_cases']}；{DISCLAIMER}")
            if summary["checked_cases"] != summary["total_cases"]:
                return 2
            if summary["meets_recall_above_90_percent"] is not True:
                return 3
        print(DISCLAIMER)
        return 0
    except (OSError, ValueError, CheckError, KeyError, TypeError, RuntimeError) as error:
        parser.exit(1, f"验收准备/核验失败：{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
