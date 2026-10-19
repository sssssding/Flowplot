"""Read-only overview of normalized evidence; never evaluate model expressions."""
from __future__ import annotations

from jsonschema import ValidationError

from flowpilot.diagnostics import validate
from flowpilot.coverage_view import coverage_text

ROLES = {"inlet": "入口", "outlet": "出口", "wall": "壁面", "axis": "轴线"}
MODES = {"Velocity": "法向速度入口", "PressureNoViscousStress": "压力出口", "NoSlip": "无滑移壁面", "Slip": "滑移壁面", "AxialSymmetry": "轴对称条件"}
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
    modern = isinstance(report, dict) and report.get("schema_version") in ("diagnosis-0.2", "diagnosis-0.3", "diagnosis-0.4")
    if modern:
        from flowpilot.diagnostics import validate_diagnosis_report
        try:
            validate_diagnosis_report(report)
        except (ValueError, TypeError, KeyError, ValidationError):
            return unavailable("诊断报告结构或覆盖状态无效。")
        if report.get("schema_version") == "diagnosis-0.4":
            lines = ["模型概览（报告快照）", "", NOTICE, "", coverage_text(report)]
            spatial_boundaries = []
            for module in report["modules"]:
                model = module.get("model")
                if not isinstance(model, dict):
                    continue
                geometry = model.get("geometry", {})
                lines += ["", "三维几何（报告中的已核验证据）", "模板：" + model["profile"],
                          "来源：" + " / ".join(str(v) for v in module["source"].values()),
                          "流体域：" + _ids(geometry.get("fluid_domain_ids")),
                          "面数量：" + str(geometry.get("boundary_count", "未读取"))]
                bbox = geometry.get("bounding_box_m")
                if isinstance(bbox, list) and len(bbox) == 6:
                    lines += [f"包围盒 {axis}：[{bbox[2*i]:.9g}, {bbox[2*i+1]:.9g}] m" for i, axis in enumerate("xyz")]
                diameter = geometry.get("pipe_diameter_m")
                lines.append(f"已核验圆管直径：{diameter:.9g} m" if diameter is not None else "圆管直径：未核验；不从包围盒推定")
                lines += ["端面：" + _ids(geometry.get("end_face_ids")), "壁面：" + _ids(geometry.get("wall_face_ids"))]
                lines += ["", "流体材料参数", "密度 · " + _evaluated(model["material"]["density"]),
                          "动力黏度 · " + _evaluated(model["material"]["dynamic_viscosity"]), "", "启用的面边界节点"]
                for item in model["boundaries"]:
                    role = ROLES.get(item["type"], "未核验边界类型")
                    mode = MODES.get(item["mode"], item["mode"] or "无法读取")
                    if item.get("verified_mode") is False:
                        mode += "（未核验模式）"
                    effective = _ids(item["boundary_ids"] if item.get("selection_known", True) else None)
                    detail = "\n".join(label + " · " + _evaluated(item["parameters"][key])
                                       for key, label in (("normal_velocity", "入口法向速度"), ("pressure", "出口压力"))
                                       if key in item["parameters"])
                    scope = "全边界回退" if item["selection_scope"] == "fallback" else "显式选择"
                    spatial_boundaries.append({"tag": item["feature_tag"], "source": module["source"],
                                               "role": role, "label": item["label"], "mode": mode, "scope": scope,
                                               "declared": _ids(item["declared_boundary_ids"]), "effective": effective, "detail": detail})
                    lines += [f"{item['feature_tag']} · {item['label']} · {role} · {mode}",
                              "  声明面：" + _ids(item["declared_boundary_ids"]) + "；实际生效面：" + effective,
                              "  选择性质：" + scope]
                    if detail:
                        lines.append("  " + detail)
            return {"available": True, "reason": "", "boundaries": spatial_boundaries, "coverage": None,
                    "module_coverage": report["coverage"], "text": "\n".join(lines)}
        if not isinstance(report.get("model"), dict):
            return {"available": True, "reason": "", "boundaries": [], "coverage": None,
                    "module_coverage": report["coverage"],
                    "text": "模型概览（报告快照）\n\n" + NOTICE + "\n\n" + coverage_text(report)}
    if not isinstance(report, dict) or report.get("schema_version") not in ("diagnosis-0.1", "diagnosis-0.2", "diagnosis-0.3", "diagnosis-0.4"):
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
    if modern:
        lines += [coverage_text(report), ""]
    if report["status"] == "partial":
        lines += ["注意：部分检查未完成，未求值参数或无法表示的派生量不能当作正常数值。", ""]
    lines += [f"模板：{model['profile']}", f"组件：{source['component_tag']}；物理场：{source['physics_tag']}；研究：{source['study_tag']}",
              f"COMSOL：{source['comsol_version']}", ""]
    if model["profile"] == "rectangular-channel-v1":
        lines += ["几何（米制、轴对齐矩形）",
                  f"x 向尺寸 L：{geometry['length_m']:.9g} m；y 向尺寸 H：{geometry['height_m']:.9g} m"]
    elif model["profile"] == "axisymmetric-pipe-v1":
        bbox = geometry["bounding_box_m"]
        lines += ["几何（二维轴对称圆管，r/z 坐标）", f"边界数量：{geometry['boundary_count']}",
                  f"径向 r：[{bbox[0]:.9g}, {bbox[1]:.9g}] m；轴向 z：[{bbox[2]:.9g}, {bbox[3]:.9g}] m",
                  "r = 0 轴线边界：" + _ids(geometry["axis_boundary_ids"])]
        diameter = geometry["pipe_diameter_m"]
        lines.append(f"已核验圆管直径 D：{diameter:.9g} m" if diameter is not None else "圆管直径：未核验，不从包围盒推定")
        lines.append("流动配置：" + {"open_pipe": "已核验开口圆管", "closed_or_unverified": "封闭或未核验，不套用开口入口/出口要求"}[geometry["flow_configuration"]])
        lines.append("尺寸仅按已核验几何证据展示；数值规则是否执行以逐条检查覆盖为准。")
    else:
        bbox = geometry["bounding_box_m"]
        lines += ["几何（二维单域平面通道）", f"边界数量：{geometry['boundary_count']}",
                  f"包围盒 x：[{bbox[0]:.9g}, {bbox[1]:.9g}] m；y：[{bbox[2]:.9g}, {bbox[3]:.9g}] m",
                  "包围盒不是通道高度；当前模板未执行 Re 风险筛查。"]
    lines += ["", "材料参数", "密度 · " + _evaluated(model["material"]["density"]),
              "动力黏度 · " + _evaluated(model["material"]["dynamic_viscosity"]), "", "启用的边界节点"]
    boundaries = []
    for item in sorted(model["boundaries"], key=lambda item: item["feature_tag"]):
        role = ROLES.get(item["type"], "未核验边界类型")
        mode = MODES.get(item["mode"], item["mode"] or "无法读取")
        if item.get("verified_mode") is False:
            mode += "（未核验模式，依赖检查见覆盖）"
        effective = _ids(item["boundary_ids"] if item.get("selection_known", True) else None)
        detail = "\n".join(label + " · " + _evaluated(item["parameters"][key])
                           for key, label in (("normal_velocity", "入口法向速度"), ("pressure", "出口压力"))
                           if key in item["parameters"])
        scope = ("全边界回退" + role + "（按当前模板识别）") if item["selection_scope"] == "fallback" else "显式选择"
        boundaries.append({"tag": item["feature_tag"], "role": role, "label": item["label"],
                           "mode": mode, "scope": scope,
                           "declared": _ids(item["declared_boundary_ids"]), "effective": effective,
                           "detail": detail})
        lines += [f"{item['feature_tag']} · {item['label']} · {role} · {mode}",
                  f"  声明边界：{_ids(item['declared_boundary_ids'])}；实际生效边界：{effective}",
                  "  选择性质：" + scope]
        if detail:
            lines.append("  " + detail)
    roles = ROLES if model["profile"] == "axisymmetric-pipe-v1" else {key: value for key, value in ROLES.items() if key != "axis"}
    coverage = {role: None if any(item["type"] == role and item.get("selection_known") is False for item in model["boundaries"]) else
                sorted({boundary for item in model["boundaries"] if item["type"] == role for boundary in item["boundary_ids"]})
                for role in roles}
    lines += ["", "各角色实际生效边界（按 API 编号，不推断实体位置）"]
    lines += [f"{ROLES[role]}：{_ids(ids)}" for role, ids in coverage.items()]
    return {"available": True, "reason": "", "boundaries": boundaries, "coverage": coverage, "text": "\n".join(lines)}
