"""UI-independent asynchronous sessions; no Tk or COMSOL dependency at import time."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from flowpilot.check_model import ACTIONS, CheckError, LFS_HEADER, ROOT, _write_json, sha256
from flowpilot.package_integrity import read_verified_package
from flowpilot.diagnostics import is_finite_number
from flowpilot.report_io import MAX_DIAGNOSIS_BYTES, MAX_METADATA_BYTES, ReportReadError, decode_json, read_regular_file

CLI = ROOT / "src/flowpilot/check_model.py"
TITLES = {"MISSING_INLET": "缺少有效入口", "MISSING_OUTLET": "缺少有效出口",
          "BC_SELECTION_OVERLAP": "边界选择存在重叠", "INLET_DIRECTION": "入口方向需要核对",
          "REYNOLDS_RISK": "Re 工况风险", "INVALID_MATERIAL_PARAMETER": "材料参数无效",
          "EVALUATION_UNAVAILABLE": "求值或数值检查未完成"}
LEVELS = {"Critical": "优先处理", "Warning": "风险 / 待核对", "Suggestion": "建议"}
DISCLAIMER = "仅检查当前支持范围内的边界配置；未运行求解器，不证明物理正确或专业验收通过。"
PROGRESS_STAGES = ("snapshot", "compile", "inventory", "diagnose", "completed", "failed", "cancelled")
STAGE_LABELS = {"starting": "正在启动检查", "snapshot": "正在创建只读检查副本",
                "compile": "正在准备 COMSOL 读取程序", "inventory": "正在用 COMSOL 读取并核对模型",
                "diagnose": "正在执行配置规则并生成报告", "completed": "正在核验完成记录",
                "failed": "正在读取失败记录", "cancelled": "正在确认检查已停止"}


def read_progress(path):
    """Read a small, advisory journal; ignore partial/malformed writes and old stages."""
    try:
        with Path(path).open("rb") as stream:
            payload = stream.read(16385)
        if len(payload) > 16384:
            return None
    except OSError:
        return None
    stage, rank = None, -1
    for line in payload.splitlines(keepends=True):
        if not line.endswith(b"\n"):
            continue
        try:
            event = json.loads(line)
            value = event.get("stage") if isinstance(event, dict) else None
            if (isinstance(event, dict) and event.get("schema_version") == "check-progress-0.1"
                    and value in PROGRESS_STAGES and PROGRESS_STAGES.index(value) >= rank):
                stage, rank = value, PROGRESS_STAGES.index(value)
        except (ValueError, UnicodeError, RecursionError):
            continue
    return stage


def diagnosis_view(report):
    """Fail closed on malformed reports; provide text, not an unconditional pass badge."""
    if not isinstance(report, dict) or report.get("schema_version") != "diagnosis-0.1":
        raise CheckError("不是当前版本的诊断报告。")
    status, findings = report.get("status"), report.get("findings")
    if status not in ("checked", "partial", "unsupported") or not isinstance(findings, list):
        raise CheckError("报告缺少检查状态或问题清单。")
    items = []
    for finding in findings:
        if (not isinstance(finding, dict) or not isinstance(finding.get("code"), str) or finding["code"] not in TITLES
                or not isinstance(finding.get("severity"), str) or finding["severity"] not in LEVELS
                or not isinstance(finding.get("explanation"), str)
                or not isinstance(finding.get("feature_tags"), list)
                or any(not isinstance(tag, str) for tag in finding["feature_tags"])
                or not isinstance(finding.get("boundary_ids"), list)
                or any(type(value) is not int or value < 1 for value in finding["boundary_ids"])
                or not isinstance(finding.get("evidence"), dict)):
            raise CheckError("问题条目的结构无效，不能显示为已完成检查。")
        code = finding["code"]
        detail = (finding["explanation"] + "\n\n建议：" + ACTIONS[code] + "\n\n证据：\n"
                  + json.dumps(finding["evidence"], ensure_ascii=False, indent=2, allow_nan=False))
        items.append({"code": code, "title": TITLES[code], "level": LEVELS[finding["severity"]],
                      "nodes": ", ".join(finding["feature_tags"]) or "—",
                      "boundaries": ", ".join(map(str, finding["boundary_ids"])) or "—", "detail": detail})
    if status == "checked" and any(item["code"] == "EVALUATION_UNAVAILABLE" for item in items):
        raise CheckError("报告状态矛盾：有未完成的数值检查，却声明 checked。")
    if status == "unsupported":
        if not isinstance(report.get("reason"), str) or findings:
            raise CheckError("超出范围报告缺少原因或含有不一致结论。")
        headline, tone, detail = "超出当前支持范围", "incomplete", report["reason"]
    elif status == "partial":
        headline, tone, detail = "部分检查未完成，需要人工复核", "incomplete", "未完成项不能当作正常配置。"
    elif not findings:
        headline, tone, detail = "当前规则未发现问题", "neutral", "这不代表求解收敛或物理正确。"
    elif any(finding["severity"] == "Critical" for finding in findings):
        headline, tone, detail = "发现需要优先处理的问题", "critical", "请逐项查看证据与建议，再到 COMSOL 中核对。"
    else:
        headline, tone, detail = "发现风险或待核对项", "warning", "风险提示不等同于模型必然错误。"
    return {"headline": headline, "tone": tone, "detail": detail, "items": items, "disclaimer": DISCLAIMER}


def load_completed_check(directory):
    """Never display a stale, incomplete, or content-mismatched diagnosis as current."""
    directory = Path(directory).resolve(strict=True)
    if (directory / "package.json").exists() or (directory / "package.json").is_symlink():
        _, payloads = read_verified_package(directory)
        run_bytes, diagnosis_bytes = payloads["run.json"], payloads["diagnosis.json"]
    else:
        run_bytes = read_regular_file(directory / "run.json", max_bytes=MAX_METADATA_BYTES)
        diagnosis_bytes = read_regular_file(directory / "diagnosis.json", max_bytes=MAX_DIAGNOSIS_BYTES)
    if len(run_bytes) > MAX_METADATA_BYTES or len(diagnosis_bytes) > MAX_DIAGNOSIS_BYTES:
        raise CheckError("报告元数据或诊断文件超过读取上限。")
    try:
        metadata, report = decode_json(run_bytes), decode_json(diagnosis_bytes)
    except ReportReadError as error:
        raise CheckError(str(error)) from error
    diagnosis_digest = hashlib.sha256(diagnosis_bytes).hexdigest()
    if (not isinstance(metadata, dict) or metadata.get("schema_version") != "check-run-0.1"
            or metadata.get("status") != "completed" or not isinstance(report, dict)
            or metadata.get("diagnosis_status") != report.get("status")
            or metadata.get("diagnosis_sha256") != diagnosis_digest
            or not isinstance(metadata.get("source"), dict)
            or not isinstance(metadata["source"].get("filename"), str)
            or not re.fullmatch(r"[a-fA-F0-9]{64}", str(metadata["source"].get("sha256", "")))):
        raise CheckError("检查未完成或报告来源不符，请重新检查；不能展示为成功结论。")
    view = diagnosis_view(report)
    return {"report": report, "metadata": metadata, "view": view, "directory": directory,
            "run_sha256": hashlib.sha256(run_bytes).hexdigest(), "diagnosis_sha256": diagnosis_digest}


class DesktopSession:
    """A single owned Python child; GUI polls it without blocking its event loop."""

    def __init__(self):
        self.state = "idle"
        self.process = None
        self.directory = None
        self.result = None
        self.error = ""
        self._log = None
        self.progress_stage = "starting"
        self._started = None

    @property
    def progress_text(self):
        elapsed = max(0, int(time.monotonic() - self._started)) if self._started is not None else 0
        label = "正在取消，等待本次进程退出" if self.state == "cancelling" else STAGE_LABELS[self.progress_stage]
        return f"{label} · 已用时 {elapsed} 秒（不是完成百分比）"

    @property
    def busy(self):
        return self.state in ("running", "cancelling")

    def start(self, model, comsol_root, output_root, *, loads=2, timeout=300.0, reynolds_warning=2000.0):
        if self.busy:
            raise CheckError("当前检查尚未结束，请等待或取消。")
        if type(loads) is not int or not 1 <= loads <= 10:
            raise ValueError("重复加载次数必须为 1–10 的整数。")
        for label, value in (("超时秒数", timeout), ("Re 阈值", reynolds_warning)):
            if not is_finite_number(value) or value <= 0:
                raise ValueError(f"{label}必须为有限的正数。")
        model, comsol = Path(model).resolve(strict=True), Path(comsol_root).resolve(strict=True)
        if not model.is_file() or model.suffix.lower() != ".mph":
            raise ValueError("请选择已经存在的 .mph 模型文件。")
        with model.open("rb") as stream:
            if stream.read(len(LFS_HEADER)) == LFS_HEADER:
                raise CheckError("这是 Git LFS 指针，还未下载完整模型；请先执行 git lfs pull。")
        for name in ("comsolcompile.exe", "comsolbatch.exe"):
            if not (comsol / "bin/win64" / name).is_file():
                raise ValueError("COMSOL 目录不正确：请选择包含 bin/win64 的 Multiphysics 文件夹。")
        root = Path(output_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.directory = root / (datetime.now(timezone.utc).strftime("session-%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:12])
        self.directory.mkdir(exist_ok=False)
        self.result, self.error, self.process = None, "", None
        self.state, self.progress_stage, self._started = "idle", "starting", time.monotonic()
        self._request = {"schema_version": "desktop-request-0.1", "model": str(model), "comsol_root": str(comsol),
                         "started_at": datetime.now(timezone.utc).isoformat(),
                         "settings": {"loads": loads, "timeout": timeout, "reynolds_warning": reynolds_warning}}
        command = [sys.executable, "-X", "utf8", str(CLI), str(model), "--comsol-root", str(comsol),
                   "--output-dir", str(self.directory / "check"), "--loads", str(loads), "--timeout", str(timeout),
                   "--reynolds-warning", str(reynolds_warning), "--cancel-file", str(self.directory / "cancel.request")]
        try:
            _write_json(self.directory / "request.json", self._request)
            self._log = (self.directory / "launcher.log").open("xb")
            self.process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                            stdout=self._log, stderr=subprocess.STDOUT,
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            self.state = "running"
        except OSError as error:
            self.error = str(error)
            self._finish("failed")
            raise
        return self.directory

    def cancel(self):
        if not self.busy or self.state == "cancelling":
            return False
        # A completed result wins over a late cancellation request.
        if self.process.poll() is not None:
            self.poll()
            return False
        try:
            with (self.directory / "cancel.request").open("x", encoding="ascii") as stream:
                stream.write("cancel\n")
        except FileExistsError:
            pass
        self.state = "cancelling"
        return True

    def poll(self):
        if not self.busy:
            return self.state
        stage = read_progress(self.directory / "check/progress.jsonl")
        if stage is not None:
            self.progress_stage = stage
        if self.process.poll() is None:
            return self.state
        code = self.process.returncode
        try:
            check_metadata = self.directory / "check/run.json"
            if check_metadata.exists():
                status = decode_json(read_regular_file(check_metadata, max_bytes=MAX_METADATA_BYTES)).get("status")
            else:
                status = None
            if status == "cancelled":
                self._finish("cancelled")
            elif code == 0 and status == "completed":
                self.result = load_completed_check(self.directory / "check")
                if self.result["metadata"]["source"]["filename"] != Path(self._request["model"]).name:
                    raise CheckError("模型来源不一致。")
                self._finish("completed")
            else:
                raise CheckError(f"检查未完成（退出码 {code}）。请查看本次 launcher.log 和 check 中的日志。")
        except (OSError, ValueError, KeyError, TypeError, AttributeError, CheckError) as error:
            self.result = None
            self.error = str(error)
            self._finish("failed")
        return self.state

    def _finish(self, state):
        self.state = state
        if self._log is not None:
            try:
                self._log.close()
            except OSError as error:
                self.state, self.result = "failed", None
                self.error = (self.error + "\n" if self.error else "") + f"无法关闭本次启动日志：{error}"
            finally:
                self._log = None
        try:
            _write_json(self.directory / "ui-run.json", {"schema_version": "desktop-run-0.1", "status": self.state,
                        "finished_at": datetime.now(timezone.utc).isoformat(), "error": self.error,
                        "check_directory": "check", "started_at": self._request["started_at"]})
        except OSError as error:
            # Never recurse into another finish attempt or leave the GUI polling forever.
            self.state, self.result = "failed", None
            self.error = (self.error + "\n" if self.error else "") + f"无法保存本次窗口运行记录：{error}"
