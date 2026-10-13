"""Opt-in local transfer of frozen models and result evidence; no upload or extraction."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path, PurePosixPath
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot.acceptance_dataset import _new_output, _root, verify_dataset
from flowpilot.acceptance_result import load_acceptance_result, render_review, same_json
from flowpilot.check_model import CheckError, _write_json, sha256
from flowpilot.package_integrity import PACKAGE_FILES, read_verified_package
from flowpilot.report_io import MAX_DIAGNOSIS_BYTES, MAX_METADATA_BYTES, decode_json, read_regular_file

MAX_MODEL_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_FILES = 512
MAX_ENTRIES = 1024
FIXED = {"dataset/freeze.json", "dataset/manifest.json", "run/run.json", "run/result.json",
         "run/checks/run.json", "run/checks/summary.json", "review.json", "report.md", "README.md"}
CAPSULE_FILES = PACKAGE_FILES | {"package.json"}
CASE = r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}"
PRIVACY = ("本包包含冻结 MPH、审核人/来源声明及原始报告元数据，不是轻量脱敏报告包。"
           "参数、模型和失败记录可能包含敏感信息或本机路径；请确认数据授权并人工审查后自行分享。"
           "工具不上传、不联网、不认证身份或物理正确性；文件哈希不是作者签名。")


def _key(value):
    if (not isinstance(value, str) or any(c in value for c in ("\\", ":", "\x00"))
            or PurePosixPath(value).as_posix() != value or ".." in PurePosixPath(value).parts):
        raise ValueError("包内路径无效")
    if value in FIXED:
        return value
    if re.fullmatch("dataset/models/" + CASE + r"\.mph", value):
        return value
    names = "|".join(re.escape(name) for name in CAPSULE_FILES | {"diagnosis.json"})
    if re.fullmatch(r"(?:run/checks|reports)/" + CASE + "/(?:" + names + ")", value):
        return value
    raise ValueError("不允许的包内文件：" + value[:120])


def _limit(key):
    if key.endswith(".mph"):
        return MAX_MODEL_BYTES
    if key.endswith(("run.json", "freeze.json", "manifest.json", "package.json")):
        return MAX_METADATA_BYTES
    return MAX_DIAGNOSIS_BYTES


def _path(root, key):
    key = _key(key)
    path = root
    for part in PurePosixPath(key).parts:
        path = path / part
        if path.is_symlink() or path.is_junction():
            raise ValueError("核验包不允许文件链接或目录联接")
    if not path.is_file() or not path.resolve(strict=True).is_relative_to(root):
        raise ValueError("包内文件缺失或越界：" + key)
    return path


def _digest(path, limit, *, target=None):
    if path.is_symlink() or path.is_junction() or not path.is_file():
        raise ValueError("只允许普通文件")
    size, digest = 0, hashlib.sha256()
    with path.open("rb") as source:
        while True:
            block = source.read(min(1024 * 1024, max(1, limit - size + 1)))
            if not block:
                break
            size += len(block)
            if size > limit:
                raise ValueError("文件超过核验包读取/复制上限：" + path.name)
            digest.update(block)
            if target is not None:
                target.write(block)
    return {"bytes": size, "sha256": digest.hexdigest()}


def _case_plan(source, target_prefix):
    if source.is_symlink() or source.is_junction():
        raise ValueError("单模型报告目录不能是链接")
    if not source.exists():
        return {}
    if not source.is_dir():
        raise ValueError("单模型报告路径不是目录")
    if (source / "package.json").exists() or (source / "package.json").is_symlink():
        # Preserve the entire original capsule, so its extra integrity checks cannot be bypassed.
        read_verified_package(source)
        names = CAPSULE_FILES
    else:
        names = {name for name in ("run.json", "diagnosis.json")
                 if (source / name).exists() or (source / name).is_symlink()}
    return {target_prefix + "/" + name: source / name for name in names}


def _shape(files, manifest, mode):
    mandatory = FIXED | {"dataset/models/" + c["case_id"] + ".mph" for c in manifest["cases"]}
    if not mandatory <= set(files):
        raise ValueError("核验包缺少冻结输入或正式结果文件")
    allowed = set(mandatory)
    prefix = "run/checks" if mode == "check" else "reports"
    for case in manifest["cases"]:
        base = prefix + "/" + case["case_id"] + "/"
        present = {name[len(base):] for name in files if name.startswith(base)}
        if "package.json" in present:
            if present != CAPSULE_FILES:
                raise ValueError("单模型协作报告包必须完整保留，不能拆散")
        elif not present <= {"run.json", "diagnosis.json"}:
            raise ValueError("普通诊断只允许运行与诊断 JSON，不复制日志")
        allowed.update(base + name for name in present)
    if set(files) != allowed:
        raise ValueError("核验包含未登记模型/报告或错误模式的额外文件")


def _tree(root, files, mode):
    expected_dirs = set()
    for key in files:
        for parent in PurePosixPath(key).parents:
            if str(parent) != ".":
                expected_dirs.add(str(parent))
    if mode == "evaluate":
        expected_dirs.add("reports")
    found_files, found_dirs, pending, count = set(), set(), [(root, "")], 0
    while pending:
        directory, prefix = pending.pop()
        for entry in directory.iterdir():
            count += 1
            if count > MAX_ENTRIES:
                raise ValueError("核验包目录项过多")
            key = prefix + entry.name
            if entry.is_symlink() or entry.is_junction():
                raise ValueError("核验包不允许链接或目录联接")
            if entry.is_dir():
                if key not in expected_dirs:
                    raise ValueError("核验包含额外目录：" + key[:120])
                found_dirs.add(key)
                pending.append((entry, key + "/"))
            elif entry.is_file():
                found_files.add(key)
            else:
                raise ValueError("核验包含非普通文件")
    if found_files != set(files) | {"bundle.json"} or found_dirs != expected_dirs:
        raise ValueError("核验包文件/目录缺失或额外")


def _integrity(root):
    raw = read_regular_file(root / "bundle.json", max_bytes=MAX_MANIFEST_BYTES)
    value = decode_json(raw)
    if (not isinstance(value, dict) or value.get("schema_version") != "acceptance-bundle-0.1"
            or value.get("status") != "ready" or value.get("includes_models") is not True
            or value.get("mode") not in ("check", "evaluate")
            or value.get("bundle_tool_sha256") != sha256(Path(__file__))
            or not isinstance(value.get("files"), dict) or not 1 <= len(value["files"]) <= MAX_FILES):
        raise ValueError("核验包状态、工具版本或文件清单无效")
    folded, total = set(), 0
    for key, expected in value["files"].items():
        _key(key)
        if key.casefold() in folded:
            raise ValueError("包内路径大小写重名")
        folded.add(key.casefold())
        if (not isinstance(expected, dict) or set(expected) != {"bytes", "sha256"}
                or type(expected["bytes"]) is not int or not 0 <= expected["bytes"] <= _limit(key)
                or not isinstance(expected["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", expected["sha256"])):
            raise ValueError("核验包文件指纹无效")
        total += expected["bytes"]
        if total > MAX_TOTAL_BYTES:
            raise ValueError("核验包总大小超过上限")
    _tree(root, value["files"], value["mode"])
    for key, expected in value["files"].items():
        if _digest(_path(root, key), _limit(key)) != expected:
            raise ValueError("核验包文件已改变：" + key)
    return value, hashlib.sha256(raw).hexdigest()


def verify_bundle(directory):
    root = _root(directory)
    metadata, digest = _integrity(root)
    loaded = verify_dataset(root / "dataset")
    _shape(metadata["files"], loaded["manifest"], metadata["mode"])
    review = load_acceptance_result(root / "run", dataset_dir=root / "dataset",
        reports_root=root / "reports" if metadata["mode"] == "evaluate" else None)
    expected = {"source_freeze_sha256": review["freeze_sha256"],
                "source_run_sha256": review["original_run_sha256"],
                "source_result_sha256": review["original_result_sha256"], "mode": review["mode"]}
    if any(metadata.get(key) != value for key, value in expected.items()):
        raise ValueError("核验包来源绑定不符")
    stored = decode_json(read_regular_file(root / "review.json", max_bytes=MAX_DIAGNOSIS_BYTES))
    if not same_json(stored, review) or read_regular_file(root / "report.md", max_bytes=MAX_DIAGNOSIS_BYTES) != render_review(review).encode("utf-8"):
        raise ValueError("包内复核摘要与证据重算不符")
    # A second bounded integrity pass detects ordinary concurrent edits during logical review.
    if _integrity(root)[1] != digest:
        raise ValueError("核验包在复核期间变化")
    return {"metadata": metadata, "bundle_sha256": digest, "review": review}


def export_bundle(directory, *, dataset_dir, output_dir, reports_root=None, include_models=False):
    if include_models is not True:
        raise ValueError("必须显式确认 include_models=True / --include-models；" + PRIVACY)
    review = load_acceptance_result(directory, dataset_dir=dataset_dir, reports_root=reports_root)
    source, frozen = _root(directory), _root(dataset_dir)
    loaded = verify_dataset(frozen)
    reports = _root(reports_root) if review["mode"] == "evaluate" else source / "checks"
    output = _new_output(output_dir, source)
    if output.is_relative_to(frozen) or output.is_relative_to(reports):
        raise ValueError("导出目录不能位于冻结集或原报告内部")
    plan = {"dataset/" + name: frozen / name for name in ("freeze.json", "manifest.json")}
    plan.update({"run/" + name: source / name for name in ("run.json", "result.json", "checks/run.json", "checks/summary.json")})
    prefix = "reports" if review["mode"] == "evaluate" else "run/checks"
    for case in loaded["manifest"]["cases"]:
        identity = case["case_id"]
        plan["dataset/models/" + identity + ".mph"] = frozen / "models" / (identity + ".mph")
        plan.update(_case_plan(reports / identity, prefix + "/" + identity))
    if len(plan) + 3 > MAX_FILES:
        raise ValueError("核验包文件数超过上限，未创建输出")
    entries, total = {}, 0
    for key, path in plan.items():
        _key(key)
        entries[key] = _digest(path, _limit(key))
        total += entries[key]["bytes"]
        if total > MAX_TOTAL_BYTES:
            raise ValueError("核验包超过总大小上限，未创建输出")
    output.mkdir(parents=True, exist_ok=False)
    if review["mode"] == "evaluate":
        (output / "reports").mkdir()
    for key, path in plan.items():
        target = output.joinpath(*PurePosixPath(key).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            if _digest(path, _limit(key), target=stream) != entries[key]:
                raise ValueError("源文件在复制期间变化，未发布有效核验包")
    copied = load_acceptance_result(output / "run", dataset_dir=output / "dataset",
        reports_root=output / "reports" if review["mode"] == "evaluate" else None)
    final = load_acceptance_result(source, dataset_dir=frozen,
        reports_root=reports if review["mode"] == "evaluate" else None)
    if not same_json(review, copied) or not same_json(review, final):
        raise ValueError("原证据或复制结果发生变化，未发布有效核验包")
    _write_json(output / "review.json", review)
    # Canonical UTF-8 bytes make the receiving-side rendered-text check platform independent.
    for name, text in (("report.md", render_review(review)), ("README.md", "# FlowPlot 离线验收核验包\n\n" + PRIVACY +
            "\n\n使用匹配源码运行 acceptance_bundle.py verify；无需 COMSOL 许可证。"
            "核验不代表专业或全部项目验收通过。不要只分享 review.json。\n")):
        with (output / name).open("xb") as stream:
            stream.write(text.encode("utf-8"))
    for key in ("review.json", "report.md", "README.md"):
        entries[key] = _digest(output / key, _limit(key))
    total = sum(value["bytes"] for value in entries.values())
    if total > MAX_TOTAL_BYTES or len(entries) > MAX_FILES:
        raise ValueError("核验包生成内容超限，未发布完成标记")
    _shape(entries, loaded["manifest"], review["mode"])
    metadata = {"schema_version": "acceptance-bundle-0.1", "status": "ready",
                "created_at": datetime.now(timezone.utc).isoformat(), "includes_models": True, "mode": review["mode"],
                "bundle_tool_sha256": sha256(Path(__file__)), "source_freeze_sha256": review["freeze_sha256"],
                "source_run_sha256": review["original_run_sha256"], "source_result_sha256": review["original_result_sha256"],
                "files": entries, "privacy_notice": PRIVACY}
    _write_json(output / "bundle.json", metadata)
    return verify_bundle(output)


def main():
    parser = argparse.ArgumentParser(description="显式同意后复制冻结模型和验收证据；接收端离线核验，不上传。")
    commands = parser.add_subparsers(dest="action", required=True)
    export = commands.add_parser("export")
    export.add_argument("run", type=Path)
    export.add_argument("--dataset", type=Path, required=True)
    export.add_argument("--reports-root", type=Path)
    export.add_argument("--output-dir", type=Path, required=True)
    export.add_argument("--include-models", action="store_true", help="确认包包含 MPH 和审核声明；人工审查后自行分享")
    verify = commands.add_parser("verify")
    verify.add_argument("bundle", type=Path)
    args = parser.parse_args()
    try:
        value = verify_bundle(args.bundle) if args.action == "verify" else export_bundle(args.run,
            dataset_dir=args.dataset, output_dir=args.output_dir, reports_root=args.reports_root, include_models=args.include_models)
        print(render_review(value["review"]))
        print(PRIVACY)
        return 0 if value["review"]["status"] == "verified_complete" else 2
    except (OSError, ValueError, CheckError, KeyError, TypeError, RuntimeError) as error:
        parser.exit(1, f"离线核验包操作失败：{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
