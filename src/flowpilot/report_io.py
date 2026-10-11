"""Bounded, strict JSON snapshots for local report readers; not authentication."""
from __future__ import annotations

import json
import math
from pathlib import Path

MAX_METADATA_BYTES = 64 * 1024
MAX_DIAGNOSIS_BYTES = 10 * 1024 * 1024
MAX_JSON_DEPTH = 64


class ReportReadError(ValueError):
    """Malformed or oversized data must never become a completed conclusion."""


def read_regular_file(path, *, max_bytes):
    path = Path(path)
    if path.is_symlink() or path.is_junction() or not path.is_file():
        raise ReportReadError("报告不允许链接、目录或缺失文件：" + path.name)
    with path.open("rb") as stream:
        payload = stream.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ReportReadError(f"报告文件超过读取上限（{max_bytes} 字节）：{path.name}")
    return payload


def decode_json(payload):
    """No duplicate keys, NaN/Infinity, exponent overflow, or deeply nested JSON."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ReportReadError("报告 JSON 含重复字段：" + key[:80])
            result[key] = value
        return result

    def constant(value):
        raise ReportReadError("报告 JSON 含非有限数值。")

    def number(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ReportReadError("报告 JSON 数值溢出。")
        return parsed

    try:
        value = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=pairs,
                           parse_constant=constant, parse_float=number)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ReportReadError("报告 JSON 无效：" + str(error)[:200]) from error
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if isinstance(item, (dict, list)):
            if depth >= MAX_JSON_DEPTH:
                raise ReportReadError("报告 JSON 嵌套过深。")
            children = item.values() if isinstance(item, dict) else item
            pending.extend((child, depth + 1) for child in children if isinstance(child, (dict, list)))
    return value
