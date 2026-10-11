"""Export a verified, portable report folder without models, logs or local-path fields."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot.check_model import CheckError, _markdown_text, sha256
from flowpilot.desktop_session import DISCLAIMER, load_completed_check
from flowpilot.model_overview import build_overview
from flowpilot.package_integrity import MAX_FILE_BYTES, verify_package
from flowpilot.diagnostics import is_finite_number

PRIVACY_NOTICE = ("不会复制 .mph 模型、运行日志或本机路径元数据字段。"
                  "模型名称、参数、表达式、标签和诊断自由文本仍可能包含敏感信息（包括路径）；"
                  "请先审阅，再自行分享。文件哈希不是签名，不证明报告作者或物理正确性。")


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _portable_metadata(metadata, report, diagnosis):
    filename = metadata["source"]["filename"]
    if not filename or any(char in filename for char in '/\\:') or any(ord(char) < 32 for char in filename):
        raise CheckError("源模型名称不是可分享的纯文件名。")
    portable = {"schema_version": "check-run-0.1", "status": "completed",
                "source": {"filename": filename, "sha256": metadata["source"]["sha256"]},
                "diagnosis_status": report["status"], "diagnosis_sha256": hashlib.sha256(diagnosis).hexdigest()}
    # Only known scalar provenance fields; never copy source.path, commands, environment or arbitrary settings.
    for key in ("rule_engine_sha256", "inventory_source_sha256", "inventory_sha256"):
        value = metadata.get(key)
        if isinstance(value, str) and re.fullmatch(r"[a-fA-F0-9]{64}", value):
            portable[key] = value
    for key in ("comsol_version", "started_at", "finished_at"):
        value = metadata.get(key)
        if isinstance(value, str) and 0 < len(value) <= 100 and not any(ord(char) < 32 for char in value):
            portable[key] = value
    loads = metadata.get("verified_loads")
    if type(loads) is int and 1 <= loads <= 10:
        portable["verified_loads"] = loads
    settings = metadata.get("settings")
    threshold = settings.get("reynolds_warning") if isinstance(settings, dict) else None
    if is_finite_number(threshold) and threshold > 0:
        portable["settings"] = {"reynolds_warning": threshold}
    return portable


def _render_report(loaded, metadata):
    view = loaded["view"]
    def safe(value):
        return _markdown_text(html.escape(str(value)))
    lines = ["# FlowPilot 协作检查报告", "", DISCLAIMER, "", PRIVACY_NOTICE, "",
             "模型：" + safe(metadata["source"]["filename"]),
             "模型 SHA-256：`" + metadata["source"]["sha256"] + "`",
             "COMSOL：" + safe(metadata.get("comsol_version", "原记录未提供")),
             "", "## " + view["headline"], "", safe(view["detail"]), ""]
    for item in view["items"]:
        # Keep arbitrary evidence inside a long-enough fence, not active Markdown links/images.
        detail = item["detail"]
        fence = "`" * max(3, max((len(match.group()) for match in re.finditer(r"`+", detail)), default=2) + 1)
        lines += ["## " + item["code"] + " · " + item["level"], "",
                  "节点：" + safe(item["nodes"]), "边界：" + safe(item["boundaries"]),
                  "", fence + "text", detail, fence, ""]
    lines += ["## 模型概览", "", "参见同目录 overview.txt；这是报告快照，不是实时模型树。", ""]
    return "\n".join(lines)


def export_package(report_dir, output_dir):
    """Validate again; write only a new folder, with run.json published last."""
    loaded = load_completed_check(report_dir)
    directory = Path(output_dir).resolve()
    if directory == loaded["directory"] or loaded["directory"] in directory.parents:
        raise CheckError("导出目录不能放在原报告目录内。")
    diagnosis = _json_bytes(loaded["report"])
    metadata = _portable_metadata(loaded["metadata"], loaded["report"], diagnosis)
    payloads = {"diagnosis.json": diagnosis, "run.json": _json_bytes(metadata),
                "report.md": _render_report(loaded, metadata).encode("utf-8"),
                "overview.txt": build_overview(loaded["report"])["text"].encode("utf-8"),
                "README.md": ("# FlowPilot 协作报告包\n\n"
                    "先阅读 report.md 和 overview.txt。安装项目依赖后，可在桌面点击“读取已有报告”并选择本文件夹；"
                    "不需要源模型或 COMSOL 即可离线阅读。可手动压缩整个文件夹发送，接收方解压后选择该文件夹。\n\n"
                    + PRIVACY_NOTICE + "\n\n不要只发送单个文件或修改包内文件。读取时核对全部五份文件的大小与 SHA-256；"
                    "这只检测意外损坏，不是数字签名，也不复算模型或证明报告真实。"
                    "如导出中途失败，目录可能不完整；不要分享，重新导出到新目录。\n").encode("utf-8")}
    if any(len(payload) > MAX_FILE_BYTES for payload in payloads.values()):
        raise CheckError("报告过大，不能导出为当前版本的协作报告包（单文件上限 10 MiB）。")
    manifest = {"schema_version": "report-package-0.1", "created_at": datetime.now(timezone.utc).isoformat(),
                "original_run_sha256": loaded["run_sha256"],
                "original_diagnosis_sha256": loaded["metadata"]["diagnosis_sha256"],
                "privacy_notice": PRIVACY_NOTICE,
                "files": {name: {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
                          for name, payload in payloads.items()}}
    directory.mkdir(parents=True, exist_ok=False)
    with (directory / "package.json").open("xb") as stream:
        stream.write(_json_bytes(manifest))
    # Completed run is the last file: interrupted export cannot look like a completed legacy report.
    for name in [name for name in payloads if name != "run.json"] + ["run.json"]:
        with (directory / name).open("xb") as stream:
            stream.write(payloads[name])
    verify_package(directory)
    return directory


def main():
    parser = argparse.ArgumentParser(description="Export a verified offline report folder for collaboration")
    parser.add_argument("report_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        directory = export_package(args.report_dir, args.output_dir)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, CheckError, RecursionError) as error:
        parser.exit(1, f"Report export failed: {error}\n")
    print(f"Exported: {directory}\n{PRIVACY_NOTICE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
