"""Render verified coverage without inventing it for historical reports."""
import json


def coverage_text(report):
    if report.get("schema_version") not in ("diagnosis-0.2", "diagnosis-0.3", "diagnosis-0.4"):
        return ""
    lines = ["检查覆盖（按物理场 / 耦合）"]
    for item in report["coverage"]:
        source = json.dumps(item["source"], ensure_ascii=False, sort_keys=True)
        lines.append(f"{item['kind']} · {item['module']} · {source} · {item['status']}：{item['reason']}")
        for rule in item["rules"]:
            lines.append(f"  {rule['rule_id']} · {rule['status']}：{rule['reason']}")
    return "\n".join(lines)
