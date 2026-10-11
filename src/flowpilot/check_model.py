"""Read a user-selected MPH snapshot with COMSOL, then run deterministic rules."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

from jsonschema import ValidationError

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot.diagnostics import diagnose_inventory, is_finite_number

ROOT = Path(__file__).resolve().parents[2]
JAVA_SOURCE = ROOT / "src" / "comsol" / "ModelInventory.java"
JSON_PREFIX = "FLOWPILOT_INVENTORY_JSON "
VERIFIED_PREFIX = "FLOWPILOT_INVENTORY_VERIFIED "
LFS_HEADER = b"version https://git-lfs.github.com/spec/v1"
ACTIONS = {
    "MISSING_INLET": "核对入口节点是否启用、选择是否为空，以及是否被其他节点覆盖。",
    "MISSING_OUTLET": "核对出口节点是否启用及有效边界选择。",
    "BC_SELECTION_OVERLAP": "在 COMSOL 中核对声明选择、有效选择和节点覆盖顺序，确认建模意图。",
    "INLET_DIRECTION": "核对法向流入速度的符号、单位及实际入口方向。",
    "REYNOLDS_RISK": "核对速度、材料参数和特征长度，并由专业人员确认当前层流工况适用性。",
    "INVALID_MATERIAL_PARAMETER": "核对材料的密度、动力黏度及其单位，当前模板要求二者为正。",
    "EVALUATION_UNAVAILABLE": "在 COMSOL 中核对表达式、单位、变量依赖及数值量级；未求值或超出表示范围的项需要人工复核。",
}


class CheckError(RuntimeError):
    """An incomplete run must not be presented as a successful diagnosis."""


class CheckCancelled(CheckError):
    """The caller explicitly requested cancellation of this run only."""


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _record_progress(run_dir, metadata, stage):
    """Advisory progress only; a completed run.json remains the result authority."""
    event = {"schema_version": "check-progress-0.1", "stage": stage,
             "at": datetime.now(timezone.utc).isoformat()}
    try:
        with (run_dir / "progress.jsonl").open("x" if stage == "snapshot" else "a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=True) + "\n")
    except OSError as error:
        # Telemetry failure must not interrupt a process or invalidate a diagnosis.
        metadata["progress_error"] = str(error)


def _driver_source(loads):
    source = JAVA_SOURCE.read_text(encoding="utf-8-sig")
    # COMSOL's batch class loader cannot resolve our sibling helper classes.
    # Select a different entry in the same inventory implementation, as in build_cases.ps1.
    replacements = {
        "public static void main(String[] args)": "public static void inspectBaseline(String[] args)",
        "public class ModelInventory {": (
            "public class FileInventory {\n"
            "  public static void main(String[] args) throws Exception {\n"
            f'    inspectFile("input.mph", {loads});\n'
            "  }\n"
        ),
    }
    for old, new in replacements.items():
        if source.count(old) != 1:
            raise CheckError("Inventory driver entry has changed; update the CLI adapter")
        source = source.replace(old, new)
    return source


def _stop_process(process):
    if os.name == "nt":
        # Target only the process tree started for this run, including Java children.
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait()


def _run(command, *, cwd, log, timeout, cancel_file=None):
    if cancel_file is not None and Path(cancel_file).exists():
        raise CheckCancelled("Check cancelled by user")
    with Path(log).open("xb") as stream:
        process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL,
                                   stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=(os.name != "nt"))
        try:
            if cancel_file is None:
                code = process.wait(timeout=timeout)
            else:
                deadline = time.monotonic() + timeout
                while True:
                    if Path(cancel_file).exists():
                        if process.poll() is None:
                            _stop_process(process)
                        raise CheckCancelled("Check cancelled by user")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, timeout)
                    try:
                        code = process.wait(timeout=min(0.2, remaining))
                        break
                    except subprocess.TimeoutExpired:
                        continue
        except subprocess.TimeoutExpired as error:
            _stop_process(process)
            raise CheckError(f"COMSOL exceeded {timeout:g} seconds; see {log}") from error
        except KeyboardInterrupt:
            _stop_process(process)
            raise
    if code != 0:
        raise CheckError(f"COMSOL returned exit code {code}; see {log}")


def _read_inventory(log, loads):
    payloads, verified = [], []
    # Markers contain ASCII JSON (including escaped Unicode), regardless of COMSOL locale.
    with Path(log).open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            line = line.rstrip("\r\n")
            if line.startswith(JSON_PREFIX):
                payloads.append(line[len(JSON_PREFIX):])
            if line.startswith(VERIFIED_PREFIX):
                verified.append(line[len(VERIFIED_PREFIX):])
    if len(payloads) != 1 or verified != [str(loads)]:
        raise CheckError(f"Missing or ambiguous COMSOL verification markers; see {log}")
    try:
        inventory = json.loads(payloads[0])
        if not isinstance(inventory, dict) or inventory.get("schema_version") != "inventory-0.2":
            raise ValueError("Expected inventory-0.2 object")
        return inventory
    except (ValueError, TypeError) as error:
        raise CheckError(f"Invalid COMSOL inventory JSON; see {log}") from error


def _markdown_text(value):
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", str(value)).replace("\n", " ").replace("\r", " ")


def render_report(report, metadata):
    statuses = {"checked": "已执行当前规则", "partial": "部分检查未完成，需人工复核",
                "unsupported": "超出当前支持范围"}
    lines = ["# FlowPilot 检查报告", "", f"模型：{_markdown_text(metadata['source']['filename'])}",
             f"SHA-256：`{metadata['source']['sha256']}`", "",
             f"状态：{statuses[report['status']]}",
             f"COMSOL：{_markdown_text(metadata['comsol_version'])}",
             (f"重复加载：{metadata['verified_loads']} 次，解析结果一致"
              if metadata['verified_loads'] > 1 else "加载：1 次（未检查重复一致性）"), ""]
    if report["status"] == "unsupported":
        lines += ["原因：" + _markdown_text(report["reason"]), ""]
    elif not report["findings"]:
        lines += ["当前规则未发现问题。", ""]
    for finding in report["findings"]:
        lines += [f"## {finding['code']} · {finding['severity']}", "",
                  _markdown_text(finding["explanation"]), "",
                  "相关节点：" + _markdown_text(", ".join(finding["feature_tags"]) or "—"),
                  "边界编号：" + _markdown_text(", ".join(map(str, finding["boundary_ids"])) or "—"), "",
                  "证据：", "", "```json", json.dumps(finding["evidence"], ensure_ascii=False, indent=2),
                  "```", "", "建议：" + ACTIONS.get(finding["code"], "请结合 COMSOL 设置人工核对。"), ""]
    lines += ["检查范围：当前仅验证二维、单域、米制、轴对齐矩形通道的稳态牛顿层流配置；"
              "入口限法向速度、出口限压力、壁面限 No Slip。", "",
              f"Re 筛查阈值：{metadata['settings']['reynolds_warning']:g}，以通道高度 H 计算。",
              "本报告是配置检查，不证明求解收敛或物理正确性；未执行求解。", ""]
    policy = report.get("numeric_policy")
    if isinstance(policy, dict) and policy.get("reynolds_threshold_guard_ulps") == 4:
        lines += ["Re 阈值比较保留 4 ULP（阈值处的浮点末位间距）保护，避免末位噪声报警；"
                  "不修改原始数值，不代表测量误差或物理安全裕量。", ""]
    return "\n".join(lines)


def check_model(model_path, *, comsol_root, output_dir, loads=1, timeout=300.0,
                reynolds_warning=2000.0, cancel_file=None):
    """Create a new run directory; read only a snapshot, never save the source model."""
    if isinstance(loads, bool) or not isinstance(loads, int) or not 1 <= loads <= 10:
        raise ValueError("loads must be an integer from 1 to 10")
    for name, value in (("timeout", timeout), ("reynolds_warning", reynolds_warning)):
        if not is_finite_number(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    model_path = Path(model_path).resolve(strict=True)
    if not model_path.is_file() or model_path.suffix.lower() != ".mph":
        raise ValueError("input must be an existing .mph file")
    with model_path.open("rb") as stream:
        if stream.read(len(LFS_HEADER)) == LFS_HEADER:
            raise CheckError("Input is a Git LFS pointer, not a model; run git lfs pull first")
    comsol_root = Path(comsol_root).resolve(strict=True)
    compiler = comsol_root / "bin" / "win64" / "comsolcompile.exe"
    batch = comsol_root / "bin" / "win64" / "comsolbatch.exe"
    for executable in (compiler, batch):
        if not executable.is_file():
            raise FileNotFoundError(f"COMSOL executable not found: {executable}")
    driver = _driver_source(loads)
    source_hash = sha256(model_path)
    output_path = Path(output_dir)
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(f"Output directory already exists: {output_path}")
    run_dir = output_path.resolve()
    # Existing output directories (including symlinks) are never reused.
    run_dir.mkdir(parents=True, exist_ok=False)
    metadata = {"schema_version": "check-run-0.1", "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "source": {"filename": model_path.name, "sha256": source_hash},
                "python_version": sys.version.split()[0],
                "rule_engine_sha256": sha256(ROOT / "src/flowpilot/diagnostics.py"),
                "inventory_source_sha256": sha256(JAVA_SOURCE),
                "settings": {"loads": loads, "timeout_seconds_per_process": timeout,
                             "reynolds_warning": reynolds_warning}, "stage": "snapshot"}
    run_options = {"timeout": timeout}
    if cancel_file is not None:
        cancel_file = Path(cancel_file).resolve()
        run_options["cancel_file"] = cancel_file
    try:
        _record_progress(run_dir, metadata, "snapshot")
        snapshot = run_dir / "input.mph"
        shutil.copyfile(model_path, snapshot)
        if sha256(snapshot) != source_hash:
            raise CheckError("Source model changed while taking the snapshot; retry with a stable file")
        source = run_dir / "FileInventory.java"
        source.write_text(driver, encoding="utf-8")
        metadata["stage"] = "compile"
        _record_progress(run_dir, metadata, "compile")
        _run([str(compiler), str(source)], cwd=run_dir, log=run_dir / "compile.log", **run_options)
        compiled = run_dir / "FileInventory.class"
        if not compiled.is_file() or compiled.stat().st_size == 0:
            raise CheckError("COMSOL returned without a compiled driver; see compile.log")
        metadata["stage"] = "inventory"
        _record_progress(run_dir, metadata, "inventory")
        console = run_dir / "batch-console.log"
        _run([str(batch), "-inputfile", str(compiled), "-nosave", "-batchlog",
              str(run_dir / "batch.log"), "-batchlogout", "-np", "2"],
             cwd=run_dir, log=console, **run_options)
        inventory = _read_inventory(console, loads)
        metadata.update(comsol_version=inventory["comsol_version"], verified_loads=loads)
        if cancel_file is not None and cancel_file.exists():
            raise CheckCancelled("Check cancelled by user")
        if sha256(snapshot) != source_hash or sha256(model_path) != source_hash:
            raise CheckError("Model hash changed during inspection; no diagnosis was published")
        metadata["stage"] = "diagnose"
        _record_progress(run_dir, metadata, "diagnose")
        report = diagnose_inventory(inventory, reynolds_warning=reynolds_warning)
        _write_json(run_dir / "inventory.json", inventory)
        _write_json(run_dir / "diagnosis.json", report)
        metadata.update(inventory_sha256=sha256(run_dir / "inventory.json"),
                        diagnosis_sha256=sha256(run_dir / "diagnosis.json"))
        with (run_dir / "report.md").open("x", encoding="utf-8") as stream:
            stream.write(render_report(report, metadata))
        metadata.update(status="completed", diagnosis_status=report["status"], stage="complete")
        return report
    except CheckCancelled as error:
        metadata.update(status="cancelled", error=str(error))
        raise
    except Exception as error:
        metadata.update(status="failed", error=str(error))
        raise
    except KeyboardInterrupt:
        metadata.update(status="cancelled", error="Interrupted by user")
        raise
    finally:
        metadata["finished_at"] = datetime.now(timezone.utc).isoformat()
        _record_progress(run_dir, metadata, metadata["status"])
        _write_json(run_dir / "run.json", metadata)


def main():
    parser = argparse.ArgumentParser(description="Read an MPH snapshot with COMSOL and produce a diagnosis (Windows)")
    parser.add_argument("model", type=Path)
    parser.add_argument("--comsol-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="new directory; existing directories are refused")
    parser.add_argument("--loads", type=int, default=1, help="repeat loads, 1 to 10 (default: 1)")
    parser.add_argument("--timeout", type=float, default=300, help="seconds per compile/batch process")
    parser.add_argument("--reynolds-warning", type=float, default=2000)
    parser.add_argument("--cancel-file", type=Path, help="optional caller-owned cancellation request file")
    args = parser.parse_args()
    try:
        report = check_model(args.model, comsol_root=args.comsol_root, output_dir=args.output_dir,
                             loads=args.loads, timeout=args.timeout, reynolds_warning=args.reynolds_warning,
                             cancel_file=args.cancel_file)
    except (OSError, ValueError, CheckError, KeyError, TypeError, ValidationError) as error:
        parser.exit(1, f"Check failed: {error}\n")
    print(f"{report['status']}: {len(report['findings'])} findings; {args.output_dir / 'report.md'}")


if __name__ == "__main__":
    main()
