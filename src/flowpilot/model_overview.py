"""Read-only overview of normalized evidence; never evaluate model expressions."""
from __future__ import annotations

from jsonschema import ValidationError

from flowpilot.diagnostics import validate

ROLES = {"inlet": "入口", "outlet": "出口", "wall": "壁面"}
MODES = {"Velocity": "法向速度入口", "PressureNoViscousStress": "压力出口", "NoSlip": "无滑移壁面", "Slip": "滑移壁面"}
NOTICE = ("这是报告中已归一化证据的概览，不是实时 COMSOL 模型树，也不证明物理正确。"
          "仅列启用且进入当前模板的边界节点；未列出不代表已从模型删除。"
          "声明选择与实际生效选择可能因节点覆盖不同，不能仅凭声明重叠断言错误。")


def _ids(values):
    if values is None:
        return "无法读取"
    return ", ".join(map(str, values)) if values else "空选择"


def _evaluated(value):
    expression = value["expression"] or "（空表达式）"
    if value["status"] == "unresolved":
        return f"表达式：{expression}；未求值（单位：{value['unit']}），不能按 0 处理"
    return f"表达式：{expression}；求值：{value['value']:.9g} {value['unit']}"


def build_overview(report):
    """Unavailable evidence stays unavailable, including legacy or unsupported reports."""
    def unavailable(reason):
        return {"available": False, "reason": reason, "boundaries": [], "coverage": None,
                "text": "模型概览不可用：" + reason + "\n\n" + NOTICE}
    if not isinstance(report, dict) or report.get("schema_version") != "diagnosis-0.1":
        return unavailable("不是当前版本的诊断报告。")
    if report.get("status") == "unsupported":
        return unavailable("模型超出当前模板；" + str(report.get("reason", "请查看诊断原因。")))
    if report.get("status") not in ("checked", "partial"):
        return unavailable("诊断状态无效。")
    model = report.get("model")
    if not isinstance(model, dict):
        return unavailable("报告没有归一化模型证据，不能推测尺寸或边界。")
    try:
        validate(model)
        if report.get("profile") != model["profile"]:
            return unavailable("报告与归一化模型的模板不一致。")
    except (OSError, ValueError, KeyError, TypeError, RecursionError, ValidationError):
        return unavailable("归一化模型证据不符合当前结构要求。")
    geometry, source = model["geometry"], model["source"]
    lines = ["模型概览（报告快照）", "", NOTICE, ""]
    if report["status"] == "partial":
        lines += ["注意：部分检查未完成，未求值参数或无法表示的派生量不能当作正常数值。", ""]
    lines += [f"模板：{model['profile']}", f"组件：{source['component_tag']}；物理场：{source['physics_tag']}；研究：{source['study_tag']}",
              f"COMSOL：{source['comsol_version']}", ""]
    if model["profile"] == "rectangular-channel-v1":
        lines += ["几何（米制、轴对齐矩形）",
                  f"x 向尺寸 L：{geometry['length_m']:.9g} m；y 向尺寸 H：{geometry['height_m']:.9g} m"]
    else:
        bbox = geometry["bounding_box_m"]
        lines += ["几何（二维单域平面通道）", f"边界数量：{geometry['boundary_count']}",
                  f"包围盒 x：[{bbox[0]:.9g}, {bbox[1]:.9g}] m；y：[{bbox[2]:.9g}, {bbox[3]:.9g}] m",
                  "包围盒不是通道高度；当前模板未执行 Re 风险筛查。"]
    lines += ["", "材料参数", "密度 · " + _evaluated(model["material"]["density"]),
              "动力黏度 · " + _evaluated(model["material"]["dynamic_viscosity"]), "", "启用的边界节点"]
    boundaries = []
    for item in sorted(model["boundaries"], key=lambda item: item["feature_tag"]):
        detail = "\n".join(label + " · " + _evaluated(item["parameters"][key])
                           for key, label in (("normal_velocity", "入口法向速度"), ("pressure", "出口压力"))
                           if key in item["parameters"])
        scope = "全边界回退壁面（按当前模板识别）" if item["selection_scope"] == "fallback" else "显式选择"
        boundaries.append({"tag": item["feature_tag"], "role": ROLES[item["type"]], "label": item["label"],
                           "mode": MODES[item["mode"]], "scope": scope,
                           "declared": _ids(item["declared_boundary_ids"]), "effective": _ids(item["boundary_ids"]),
                           "detail": detail})
        lines += [f"{item['feature_tag']} · {item['label']} · {ROLES[item['type']]} · {MODES[item['mode']]}",
                  f"  声明边界：{_ids(item['declared_boundary_ids'])}；实际生效边界：{_ids(item['boundary_ids'])}",
                  "  选择性质：" + scope]
        if detail:
            lines.append("  " + detail)
    coverage = {role: sorted({boundary for item in model["boundaries"] if item["type"] == role for boundary in item["boundary_ids"]})
                for role in ROLES}
    lines += ["", "各角色实际生效边界（按 API 编号，不推断实体位置）"]
    lines += [f"{ROLES[role]}：{_ids(ids)}" for role, ids in coverage.items()]
    return {"available": True, "reason": "", "boundaries": boundaries, "coverage": coverage, "text": "\n".join(lines)}
