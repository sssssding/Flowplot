"""Bounded, read-only discovery of local check records; opening verifies diagnosis."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re

from flowpilot.check_model import CheckError
from flowpilot.desktop_session import load_completed_check

STATUS_LABELS = {"completed": "完成记录（打开时核验）", "failed": "失败", "cancelled": "已取消",
                 "unconfirmed": "运行中或中断，状态待确认", "invalid": "记录不完整或无效"}


def _root(output_root):
    if not str(output_root).strip():
        raise ValueError("请先选择检查结果目录。")
    root = Path(output_root).resolve(strict=True)
    if not root.is_dir():
        raise CheckError("请选择检查结果目录。")
    return root


def _linked(path):
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _safe_path(root, relative):
    parts = PurePosixPath(relative)
    windows = PureWindowsPath(relative)
    if (parts.is_absolute() or windows.drive or windows.root or not parts.parts
            or ".." in parts.parts or "\\" in relative):
        raise CheckError("历史记录路径无效。")
    path = root
    for part in parts.parts:
        path = path / part
        if _linked(path):
            raise CheckError("历史记录不跟随符号链接或目录联接。")
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise CheckError("历史记录超出所选目录。")
    return resolved


def _read_json(root, relative):
    path = _safe_path(root, relative)
    with path.open("rb") as stream:
        payload = stream.read(65537)
    if len(payload) > 65536:
        raise CheckError("运行记录过大，未自动读取。")
    value = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise CheckError("运行记录不是 JSON 对象。")
    return value


def _entry(root, relative):
    _safe_path(root, relative)
    item = {"id": relative, "status": "invalid", "model": "—", "started_at": "—",
            "source_sha256": "", "detail": "", "verified": False}
    is_session = relative.endswith("/check")
    wrapper = None
    if is_session:
        session_id = PurePosixPath(relative).parent.as_posix()
        wrapper_path = _safe_path(root, session_id + "/ui-run.json")
        if wrapper_path.exists():
            wrapper = _read_json(root, session_id + "/ui-run.json")
            if wrapper.get("schema_version") != "desktop-run-0.1":
                raise CheckError("桌面运行记录版本无效。")
        request_path = _safe_path(root, session_id + "/request.json")
        if request_path.exists():
            request = _read_json(root, session_id + "/request.json")
            if isinstance(request.get("model"), str):
                item["model"] = PureWindowsPath(request["model"]).name[:512]
            item["started_at"] = str(request.get("started_at", "—"))[:80]
    metadata_path = _safe_path(root, relative + "/run.json")
    if not metadata_path.exists():
        if wrapper is not None and wrapper.get("status") in ("failed", "cancelled"):
            item.update(status=wrapper["status"], detail=str(wrapper.get("error", ""))[:2000])
        else:
            item.update(status="unconfirmed", detail="没有最终模型检查记录；不会展示为已完成检查。")
        return item
    metadata = _read_json(root, relative + "/run.json")
    if metadata.get("schema_version") != "check-run-0.1":
        raise CheckError("不是单模型检查记录。")
    source = metadata.get("source")
    if isinstance(source, dict):
        if isinstance(source.get("filename"), str):
            item["model"] = source["filename"][:512]
        if isinstance(source.get("sha256"), str):
            item["source_sha256"] = source["sha256"][:128]
    item["started_at"] = str(metadata.get("started_at", item["started_at"]))[:80]
    status = metadata.get("status")
    item["detail"] = f"模型：{item['model']}\nSHA-256：{item['source_sha256']}\n记录阶段：{str(metadata.get('stage', '—'))[:100]}"
    if status in ("failed", "cancelled"):
        item.update(status=status, detail=item["detail"] + "\n" + str(metadata.get("error", ""))[:2000])
    elif status == "completed":
        if wrapper is not None and wrapper.get("status") in ("failed", "cancelled"):
            item.update(status=wrapper["status"], detail=item["detail"] + "\n窗口记录：" + str(wrapper.get("error", ""))[:2000])
        elif is_session and (wrapper is None or wrapper.get("status") != "completed"):
            item.update(status="unconfirmed", detail=item["detail"] + "\n窗口尚无成功收尾记录，状态待确认。")
        elif not re.fullmatch(r"[a-fA-F0-9]{64}", item["source_sha256"]):
            item["detail"] += "\n来源哈希无效。"
        else:
            for name in ("diagnosis.json", "run.json"):
                if not _safe_path(root, relative + "/" + name).is_file():
                    raise CheckError("报告文件缺失。")
            item.update(status="completed", detail=item["detail"] + "\n仅发现完成记录；打开时重新核验诊断状态与内容哈希。")
    elif status == "running":
        item["status"] = "unconfirmed"
        item["detail"] += "\n无法仅凭磁盘记录判断进程是否仍存活。"
    else:
        item["detail"] += "\n未知运行状态。"
    return item


def scan_history(output_root, *, limit=200):
    """Only one directory level, plus each child's optional check/; no model reads."""
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("历史扫描上限必须为 1–500 的整数。")
    root = _root(output_root)
    entries, truncated, skipped_links = [], False, 0
    for index, child in enumerate(root.iterdir()):
        if index >= limit:
            truncated = True
            break
        if _linked(child):
            skipped_links += 1
            continue
        if not child.is_dir():
            continue
        relative = child.name
        try:
            check = child / "check"
            if _linked(check):
                skipped_links += 1
                continue
            if check.is_dir() or (child / "request.json").is_file() or (child / "ui-run.json").is_file():
                relative += "/check"
            elif not (child / "run.json").is_file():
                continue
            else:
                # A batch root or comparison output is not itself a model check.
                metadata = _read_json(root, relative + "/run.json")
                if metadata.get("schema_version") != "check-run-0.1":
                    continue
            entries.append(_entry(root, relative))
        except (OSError, ValueError, TypeError, RecursionError, CheckError) as error:
            entries.append({"id": relative, "status": "invalid", "model": "—", "started_at": "—",
                            "source_sha256": "", "verified": False, "detail": str(error)[:2000]})
    entries.sort(key=lambda item: (item["started_at"], item["id"]), reverse=True)
    return {"root": str(root), "entries": entries, "truncated": truncated, "skipped_links": skipped_links}


def load_history_report(output_root, relative):
    root = _root(output_root)
    item = _entry(root, relative)
    if item["status"] != "completed":
        raise CheckError("该历史记录不是可打开的完成报告；请查看运行详情或重新检查。")
    # Reject changed or redirected files at selection time, not just at list refresh.
    for name in ("run.json", "diagnosis.json"):
        _safe_path(root, relative + "/" + name)
    return load_completed_check(_safe_path(root, relative))


def history_directory(output_root, relative):
    """For logs of launch failures, return the existing parent session directory."""
    root = _root(output_root)
    path = _safe_path(root, relative)
    if not path.is_dir() and relative.endswith("/check"):
        path = _safe_path(root, PurePosixPath(relative).parent.as_posix())
    if not path.is_dir():
        raise CheckError("历史目录已不存在。")
    return path
