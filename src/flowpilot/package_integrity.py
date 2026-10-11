"""Bounded integrity checks for a fixed, non-executable report folder; no extraction."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from flowpilot.report_io import MAX_METADATA_BYTES, decode_json, read_regular_file

PACKAGE_FILES = frozenset(("run.json", "diagnosis.json", "report.md", "overview.txt", "README.md"))
MAX_FILE_BYTES = 10 * 1024 * 1024


def read_package_file(path):
    return read_regular_file(path, max_bytes=MAX_FILE_BYTES)


def read_verified_package(directory):
    """Return the exact verified byte snapshots, not a promise about later reads."""
    directory = Path(directory)
    manifest = decode_json(read_regular_file(directory / "package.json", max_bytes=MAX_METADATA_BYTES))
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != "report-package-0.1"
            or not isinstance(manifest.get("files"), dict) or set(manifest["files"]) != PACKAGE_FILES):
        raise ValueError("报告包清单版本或文件列表无效。")
    entries = set()
    for entry in directory.iterdir():
        entries.add(entry.name)
        if len(entries) > len(PACKAGE_FILES) + 1:
            raise ValueError("报告包包含额外文件。")
    if entries != PACKAGE_FILES | {"package.json"}:
        raise ValueError("报告包包含额外或缺失文件，请选择完整的原始导出目录。")
    payloads = {}
    for name in sorted(PACKAGE_FILES):
        expected = manifest["files"][name]
        if (not isinstance(expected, dict) or type(expected.get("bytes")) is not int
                or not 0 <= expected["bytes"] <= MAX_FILE_BYTES
                or not isinstance(expected.get("sha256"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", expected["sha256"])):
            raise ValueError("报告包文件指纹无效。")
        payload = read_package_file(directory / name)
        if len(payload) != expected["bytes"] or hashlib.sha256(payload).hexdigest() != expected["sha256"]:
            raise ValueError(f"报告包文件不完整或已改变：{name}")
        payloads[name] = payload
    return manifest, payloads


def verify_package(directory):
    """Hashes detect accidental changes, NOT malicious edits or author identity."""
    return read_verified_package(directory)[0]
