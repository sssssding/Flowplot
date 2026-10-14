"""Read-only handoff checks; never download, restore, solve, or initialize a UI."""
from __future__ import annotations

import argparse
import hashlib
import importlib
from importlib import metadata
import json
from pathlib import Path, PurePosixPath
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data/fixtures/cases/manifest.json"
LFS_HEADER = b"version https://git-lfs.github.com/spec/v1"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def read_cases(manifest):
    path = Path(manifest)
    with path.open("rb") as stream:
        payload = stream.read(65537)
    if len(payload) > 65536:
        raise ValueError("manifest exceeds 64 KiB")
    value = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    if not isinstance(value, dict) or value.get("schema_version") != "case-manifest-0.1":
        raise ValueError("expected case-manifest-0.1")
    cases = value.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 50:
        raise ValueError("expected 1 to 50 cases")
    identities, paths, hashes = set(), set(), set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("case must be an object")
        identity, relative, digest = (case.get(key) for key in ("case_id", "model_path", "sha256"))
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", identity):
            raise ValueError("invalid case ID")
        if not isinstance(relative, str) or not relative or "\x00" in relative:
            raise ValueError("invalid model path")
        normalized = PurePosixPath(relative.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts or ":" in relative or normalized.suffix.lower() != ".mph":
            raise ValueError("model path must be a relative .mph path without traversal")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise ValueError("invalid SHA-256")
        if identity in identities or str(normalized).casefold() in paths or digest.lower() in hashes:
            raise ValueError("duplicate case, path, or model hash")
        identities.add(identity)
        paths.add(str(normalized).casefold())
        hashes.add(digest.lower())
    return cases


def check_models(cases, model_root):
    root = Path(model_root).resolve(strict=True)
    results = []
    for case in cases:
        item = {"case_id": case["case_id"], "model_path": case["model_path"],
                "expected_sha256": case["sha256"].lower()}
        try:
            relative = PurePosixPath(case["model_path"].replace("\\", "/"))
            path = root.joinpath(*relative.parts).resolve(strict=True)
            if not path.is_relative_to(root):
                item.update(status="outside_root", message="模型链接指向指定目录之外；未读取。")
            elif not path.is_file():
                item.update(status="not_file", message="模型路径不是普通文件。")
            else:
                with path.open("rb") as stream:
                    prefix = stream.read(len(LFS_HEADER))
                    if prefix == LFS_HEADER:
                        item.update(status="lfs_pointer", message="只有 Git LFS 指针；先运行 git lfs pull。")
                    else:
                        digest = hashlib.sha256(prefix)
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(block)
                        actual = digest.hexdigest()
                        item["actual_sha256"] = actual
                        if actual == item["expected_sha256"]:
                            item.update(status="ok", message="与已提交清单一致。")
                        else:
                            item.update(status="hash_mismatch", message="文件与清单不同；保留本地修改，不要改清单哈希绕过保护。")
        except FileNotFoundError:
            item.update(status="missing", message="模型文件不存在；检查克隆和 LFS 下载。")
        except (OSError, RuntimeError):
            item.update(status="read_error", message="无法读取模型；检查文件占用或访问权限。")
        results.append(item)
    return results


def check_environment(comsol_root=None):
    checks = [{"name": "python", "status": "ok" if (3, 12) <= sys.version_info[:2] <= (3, 13) else "warning",
               "version": sys.version.split()[0], "message": "项目已验证 Python 3.12/3.13；其他版本需另外验证。"}]
    for module, distribution in (("jsonschema", "jsonschema"), ("tkinter", None)):
        try:
            imported = importlib.import_module(module)
            version = metadata.version(distribution) if distribution else str(imported.TkVersion)
            checks.append({"name": module, "status": "ok", "version": version,
                           "message": "可导入；不代表可见窗口已经验证。" if module == "tkinter" else "依赖可导入。"})
        except (ImportError, OSError, metadata.PackageNotFoundError):
            checks.append({"name": module, "status": "error", "message": "依赖不可用；检查当前 Python 环境和 requirements-dev.txt。"})
    if comsol_root is None:
        checks.append({"name": "comsol", "status": "warning", "message": "未指定 COMSOL 目录；可做离线测试，不能据此确认实模环境。"})
    else:
        try:
            root = Path(comsol_root).resolve(strict=True)
            present = all((root / "bin/win64" / name).is_file() for name in ("comsolcompile.exe", "comsolbatch.exe"))
        except (OSError, RuntimeError):
            present = False
        checks.append({"name": "comsol", "status": "ok" if present else "error",
                       "message": "编译/批处理文件存在；许可证、版本和模块仍需真实运行确认。" if present else "未找到 COMSOL 编译/批处理文件。"})
    return checks


def preflight(*, manifest=MANIFEST, model_root=ROOT, comsol_root=None):
    environment = check_environment(comsol_root)
    result = {"schema_version": "handoff-preflight-0.1", "environment": environment,
              "models": [], "readonly": True, "license_validated": False,
              "visual_review": False, "expert_review": False}
    try:
        result["models"] = check_models(read_cases(manifest), model_root)
    except (OSError, ValueError, TypeError, RuntimeError, RecursionError):
        result["manifest_error"] = "清单或模型根目录不可用；检查格式、路径和访问权限。"
    blocked = ("manifest_error" in result or any(item["status"] != "ok" for item in result["models"])
               or any(item["status"] == "error" for item in environment))
    result["status"] = "blocked" if blocked else "ready_with_warnings" if any(item["status"] == "warning" for item in environment) else "ready"
    return result


def main():
    parser = argparse.ArgumentParser(description="只读检查接手文件和本机依赖，不改模型、不运行 COMSOL。")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--model-root", type=Path, default=ROOT)
    parser.add_argument("--comsol-root", type=Path)
    parser.add_argument("--json", action="store_true", help="向标准输出打印结构化结果，不写文件")
    args = parser.parse_args()
    result = preflight(manifest=args.manifest, model_root=args.model_root, comsol_root=args.comsol_root)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        print("接手预检：" + result["status"])
        if "manifest_error" in result:
            print(result["manifest_error"])
        for item in result["environment"]:
            print(f"{item['name']}: {item['status']} — {item['message']}")
        for item in result["models"]:
            print(f"{item['case_id']}: {item['status']} — {item['message']}")
        print("本预检不下载/恢复文件、不求解、不确认许可证或专业验收。")
    return 1 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
