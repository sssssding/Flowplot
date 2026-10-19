"""Normalize API evidence; do not evaluate COMSOL expressions in Python."""
from __future__ import annotations

import argparse
from fractions import Fraction
import itertools
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "schema" / "diagnostic-model.schema.json"
ROLES = {"Inlet": "inlet", "Outlet": "outlet", "Wall": "wall", "WallBC": "wall"}
ALLOWED_FEATURES = set(ROLES) | {"FluidProperties", "init"}
REYNOLDS_THRESHOLD_GUARD_ULPS = 4


class UnsupportedModel(ValueError):
    """The currently verified profile does not cover this model."""


def is_finite_number(value):
    """JSON numeric evidence/options must fit a finite float; bool is not a number."""
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _reynolds_number(rho, speed, height, mu):
    """Combine recorded decimal numbers exactly; round only the final report value.

    Fraction reads numeric values, never COMSOL expressions. This avoids overflowing
    or underflowing a product whose final quotient is still representable.
    """
    exact = Fraction(str(rho)) * Fraction(str(abs(speed))) * Fraction(str(height)) / Fraction(str(mu))
    try:
        value = float(exact)
    except OverflowError:
        return None, "above_float_range"
    if not math.isfinite(value):
        return None, "above_float_range"
    if value == 0 and exact != 0:
        return None, "below_nonzero_float_range"
    return value, None


def _require(condition, explanation):
    if not condition:
        raise UnsupportedModel(explanation)


def _legacy_evaluation(item):
    """Keep additive reader failure details in raw evidence, not the legacy model."""
    return {field: item[field] for field in ("expression", "unit", "status", "value")}


def normalize(inventory):
    """Keep rectangle numerics separate from planar boundary-only diagnostics."""
    if any(g.get("dimension") == 3 for c in inventory.get("components", []) for g in c.get("geometries", [])):
        from .flow_3d import normalize as normalize_3d
        _require(len(inventory.get("components", [])) == 1 and len(inventory["components"][0].get("physics", [])) == 1,
                 "三维规范化需要单实例投影；请使用 diagnose_inventory。")
        return normalize_3d(inventory)
    if any(g.get("axisymmetric") is True for c in inventory.get("components", [])
           for g in c.get("geometries", [])):
        return _normalize_axisymmetric(inventory)
    _require(inventory.get("schema_version") == "inventory-0.2", "需要 inventory-0.2 API 证据")
    _require(not inventory["multiphysics_tags"], "暂不支持耦合物理场")
    _require(len(inventory["components"]) == 1, "暂仅支持一个组件")
    component = inventory["components"][0]
    _require(not component["multiphysics_tags"], "暂不支持组件内耦合")
    _require(len(component["geometries"]) == 1, "暂仅支持一个几何")
    geometry = component["geometries"][0]
    count = geometry["boundary_count"]
    _require(geometry["dimension"] == 2 and geometry["domain_count"] == 1
             and type(count) is int and count >= 3, "暂仅支持二维单域平面通道")
    _require(geometry.get("axisymmetric", False) is False, "暂不支持二维轴对称模型")
    types = geometry["feature_types"]
    rectangle = types.count("Rectangle") == 1 and set(types) <= {"Rectangle", "Finalize"}
    polygon = types.count("Polygon") == 1 and set(types) <= {"Polygon", "Finalize"}
    _require(rectangle or polygon, "暂仅支持单个矩形或多边形通道，不支持其他或组合几何")
    rotation = geometry.get("rectangle_rotation_expression", "0")
    aligned = rectangle and count == 4 and isinstance(rotation, str) and "".join(rotation.split()) in {"0", "0[deg]", "0[rad]"}
    # Extended profiles require explicit planar evidence from the new API reader.
    if not aligned:
        _require(geometry.get("axisymmetric") is False, "扩展几何需要明确的非轴对称 API 证据，请重新读取模型")
    _require(geometry["length_unit"] == "m", "当前配置仅验证米制几何")
    bbox = geometry["bounding_box"]
    _require(len(bbox) == 4 and all(is_finite_number(x) for x in bbox), "几何包围盒不可用")
    length, height = bbox[1] - bbox[0], bbox[3] - bbox[2]
    _require(is_finite_number(length) and is_finite_number(height) and length > 0 and height > 0,
             "几何尺寸必须为有限的正数")
    _require(len(component["physics"]) == 1, "暂仅支持一个物理场")
    physics = component["physics"][0]
    _require(physics["type"] == "LaminarFlow" and physics["enabled"], "需要启用的 LaminarFlow")
    _require(physics["study_active"], "定常研究未启用该物理场")
    studies = inventory["studies"]
    _require(len(studies) == 1 and studies[0]["type"] == "Stationary" and studies[0]["enabled"],
             "暂仅支持单一定常研究步骤")
    _require(len(component["materials"]) == 1, "暂仅支持一个材料")
    material = component["materials"][0]
    _require(material["enabled"] and material["domain_ids"] == [1], "材料必须覆盖唯一流体域")
    unread = [f for f in physics["features"] if f.get("enabled") is True and f.get("read_status") == "unread"]
    _require(not unread, "启用节点读取失败: " + "; ".join(
        str(f.get("tag", "?")) + ": " + str(f.get("reason", "API evidence unavailable")) for f in unread))
    fluids = [f for f in physics["features"] if f["enabled"] and f["type"] == "FluidProperties"]
    _require(len(fluids) == 1 and fluids[0]["selected_entity_ids"] == [1], "需要唯一流体属性节点覆盖流体域")
    fluid = fluids[0]["parameters"]
    _require(fluid.get("Constitutiverelation") == "Newtonian"
             and fluid.get("rho_mat") == "from_mat" and fluid.get("mu_mat") == "from_mat",
             "暂仅支持从材料读取密度/黏度的牛顿流体")
    boundaries = []
    for feature in physics["features"]:
        if not feature["enabled"]:
            continue
        _require(feature["type"] in ALLOWED_FEATURES, "不支持的启用节点: " + feature["type"])
        _require(feature["child_feature_count"] == 0, "暂不支持嵌套物理节点")
        role = ROLES.get(feature["type"])
        if role is None:
            continue
        _require(feature["selection_dimensions"] == [1], "边界节点的选择维度必须为 1")
        mode = feature["parameters"].get("BoundaryCondition")
        _require(mode in {"inlet": {"Velocity"}, "outlet": {"PressureNoViscousStress"}, "wall": {"NoSlip", "Slip"}}[role],
                 "不支持的边界模式: " + str(mode))
        if role == "inlet":
            _require(feature["parameters"].get("ComponentWise") == "NormalInflowVelocity", "暂仅支持法向入口速度，不能用 U0in 代替分量速度")
        # COMSOL returns all input entities even for the fallback wall.
        # Treat an unnamed all-boundaries wall as fallback, not an explicit conflict.
        fallback = (role == "wall" and not feature["named_selection"]
                    and set(feature["declared_entity_ids"] or []) == set(range(1, count + 1)))
        boundaries.append({
            "feature_tag": feature["tag"], "label": feature["label"], "type": role,
            "boundary_ids": sorted(feature["selected_entity_ids"]),
            "declared_boundary_ids": feature["declared_entity_ids"], "selection_scope": "fallback" if fallback else "explicit", "mode": mode,
            "parameters": {key: _legacy_evaluation(value) for key, value in feature["evaluated_parameters"].items()},
        })
    rectangular_profile = aligned and all(b["mode"] == "NoSlip" for b in boundaries if b["type"] == "wall")
    if not rectangular_profile:
        _require(geometry.get("axisymmetric") is False, "扩展边界需要明确的非轴对称 API 证据，请重新读取模型")
    result = {
        "schema_version": "diagnostic-0.1", "profile": "rectangular-channel-v1" if rectangular_profile else "planar-boundaries-v1",
        "source": {"comsol_version": inventory["comsol_version"], "component_tag": component["tag"],
                   "physics_tag": physics["tag"], "study_tag": studies[0]["study_tag"]},
        "geometry": ({"length_m": length, "height_m": height} if rectangular_profile else
                     {"bounding_box_m": bbox, "boundary_count": count}),
        "material": {key: _legacy_evaluation(material[key]) for key in ("density", "dynamic_viscosity")},
        "boundaries": sorted(boundaries, key=lambda item: item["feature_tag"]),
    }
    validate(result)
    return result


def validate(model):
    def finite(value):
        if type(value) in (int, float) and not is_finite_number(value):
            raise ValueError("numeric evidence must fit a finite float")
        if isinstance(value, dict):
            for child in value.values():
                finite(child)
        elif isinstance(value, list):
            for child in value:
                finite(child)
    finite(model)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(model)
    tags = [item["feature_tag"] for item in model["boundaries"]]
    if len(tags) != len(set(tags)):
        raise ValueError("duplicate boundary feature tags")
    count = 4 if model["profile"] == "rectangular-channel-v1" else model["geometry"]["boundary_count"]
    for item in model["boundaries"]:
        for ids in (item["boundary_ids"], item["declared_boundary_ids"] or []):
            if any(entity > count for entity in ids):
                raise ValidationError("boundary ID exceeds geometry boundary count")
    if model["profile"] == "planar-boundaries-v1":
        bbox = model["geometry"]["bounding_box_m"]
        if any(not is_finite_number(bbox[i+1] - bbox[i]) or bbox[i+1] <= bbox[i] for i in (0, 2)):
            raise ValueError("invalid planar bounding box")
    if model["profile"] == "axisymmetric-pipe-v1":
        axis_ids = model["geometry"]["axis_boundary_ids"]
        if axis_ids is not None and any(entity > count for entity in axis_ids):
            raise ValidationError("axis boundary ID exceeds geometry boundary count")
        for item in model["boundaries"]:
            for key, unit in (("normal_velocity", "m/s"), ("pressure", "Pa")):
                if key in item["parameters"] and item["parameters"][key]["unit"] != unit:
                    raise ValidationError("invalid axisymmetric boundary parameter unit")
    if model["profile"] == "pipe-3d-v1":
        geometry = model["geometry"]
        bbox = geometry["bounding_box_m"]
        if any(bbox[i+1] <= bbox[i] or not is_finite_number(bbox[i+1] - bbox[i]) for i in (0, 2, 4)):
            raise ValidationError("invalid 3D bounding box")
        ends, walls, diameter = geometry["end_face_ids"], geometry["wall_face_ids"], geometry["pipe_diameter_m"]
        if (any(v is None for v in (ends, walls, diameter)) and not all(v is None for v in (ends, walls, diameter))
                or ends is not None and (len(ends) != 2 or not walls or set(ends) & set(walls))):
            raise ValidationError("inconsistent 3D pipe face/diameter evidence")
        for key in ("end_face_ids", "wall_face_ids"):
            if geometry[key] is not None and any(entity > count for entity in geometry[key]):
                raise ValidationError("3D face ID exceeds geometry boundary count")
        for item in model["boundaries"]:
            for key, unit in (("normal_velocity", "m/s"), ("pressure", "Pa")):
                if key in item["parameters"] and item["parameters"][key]["unit"] != unit:
                    raise ValidationError("invalid 3D boundary parameter unit")


def check(model, *, reynolds_warning=2000.0, rule_groups=None):
    """Template constraints, not a proof of physical validity or solver success."""
    if model.get("schema_version") in {"diagnostic-0.2", "diagnostic-0.3"}:
        raise UnsupportedModel("轴对称诊断需要带规则覆盖和来源的报告；请使用 diagnose_inventory，而非旧 check API。")
    validate(model)
    if not is_finite_number(reynolds_warning) or reynolds_warning <= 0:
        raise ValueError("Reynolds warning threshold must be finite and positive")
    groups = {"boundaries", "material", "numerics"} if rule_groups is None else set(rule_groups)
    findings = []

    def add(code, severity, explanation, tags=(), ids=(), evidence=None):
        findings.append({"code": code, "severity": severity, "explanation": explanation,
                         "feature_tags": sorted(tags), "boundary_ids": sorted(ids), "evidence": evidence or {}})

    boundaries = model["boundaries"]
    if "numerics" in groups and model["profile"] == "planar-boundaries-v1":
        add("EVALUATION_UNAVAILABLE", "Warning", "已检查平面通道的边界配置；当前几何或壁面设置没有已验证的 Re 筛查配置，"
            "未将包围盒尺寸当作通道高度，Re 风险筛查未执行。",
            evidence={"quantity": "reynolds", "reason": "no_verified_reynolds_profile",
                      "profile": model["profile"], "bounding_box_m": model["geometry"]["bounding_box_m"]})
    for role in (("inlet", "outlet") if "boundaries" in groups else ()):
        role_nodes = [item for item in boundaries if item["type"] == role]
        if not any(item["boundary_ids"] for item in role_nodes):
            add("MISSING_" + role.upper(), "Critical", "当前通道模板缺少有效" + ("入口" if role == "inlet" else "出口")
                + "；这不是对所有 COMSOL 模型的普遍判错。",
                tags=[item["feature_tag"] for item in role_nodes],
                evidence={"required_role": role, "observation_scope": "enabled_normalized_boundary_nodes",
                          "active_role_node_count": len(role_nodes), "effective_boundary_ids": [],
                          "absence_kind": "no_enabled_role_node" if not role_nodes else "all_effective_selections_empty",
                          "active_boundary_nodes": [
                              {"feature_tag": item["feature_tag"], "role": item["type"],
                               "declared_boundary_ids": item["declared_boundary_ids"],
                               "effective_boundary_ids": item["boundary_ids"], "selection_scope": item["selection_scope"]}
                              for item in sorted(boundaries, key=lambda item: item["feature_tag"])]})
    # Never interpret an all-boundaries fallback wall as conflicting with overrides.
    for left, right in (itertools.combinations(boundaries, 2) if "boundaries" in groups else ()):
        if left["type"] == right["type"] or "fallback" in (left["selection_scope"], right["selection_scope"]):
            continue
        overlap = set(left["declared_boundary_ids"] or []) & set(right["declared_boundary_ids"] or [])
        if overlap:
            add("BC_SELECTION_OVERLAP", "Warning", "不同边界角色声明了同一边界；COMSOL 可按节点优先级覆盖，需人工核对意图。",
                (left["feature_tag"], right["feature_tag"]), overlap,
                {"effective_left": left["boundary_ids"], "effective_right": right["boundary_ids"]})

    def scalar(item, label, tags=()):
        if item["status"] != "resolved":
            add("EVALUATION_UNAVAILABLE", "Warning", label + "无法按指定单位求值，相关数值检查未执行。", tags,
                evidence={"expression": item["expression"], "unit": item["unit"]})
            return None
        return item["value"]

    rho = scalar(model["material"]["density"], "密度") if "material" in groups else None
    mu = scalar(model["material"]["dynamic_viscosity"], "动力黏度") if "material" in groups else None
    material_valid = (rho is not None and mu is not None and rho > 0 and mu > 0)
    if (rho is not None and rho <= 0) or (mu is not None and mu <= 0):
        add("INVALID_MATERIAL_PARAMETER", "Critical", "当前牛顿流体模板要求正密度与正动力黏度。",
            evidence={"density_kg_m3": rho, "dynamic_viscosity_pa_s": mu})
    for boundary in (boundaries if "numerics" in groups else ()):
        if not boundary["boundary_ids"]:
            continue
        tag, role = boundary["feature_tag"], boundary["type"]
        if role == "outlet":
            scalar(boundary["parameters"]["pressure"], "出口压力", (tag,))
        if role != "inlet":
            continue
        speed = scalar(boundary["parameters"]["normal_velocity"], "入口法向速度", (tag,))
        if speed is None:
            continue
        if speed <= 0:
            add("INLET_DIRECTION", "Warning", "入口法向速度未指向域内或为零；该符号约定只用于法向速度模式。",
                (tag,), boundary["boundary_ids"], {"normal_velocity_m_s": speed})
        if material_valid and model["profile"] == "rectangular-channel-v1":
            height = model["geometry"]["height_m"]
            reynolds, unavailable = _reynolds_number(rho, speed, height, mu)
            if unavailable:
                add("EVALUATION_UNAVAILABLE", "Warning", "名义 Reynolds 数超出当前报告的非零有限数值表示范围；"
                    "Re 风险筛查未完成，不能按零或正常工况处理。", (tag,), boundary["boundary_ids"],
                    {"quantity": "reynolds_height_based", "reason": unavailable,
                     "formula": "rho * abs(Uin) * H / mu", "density_kg_m3": rho,
                     "normal_velocity_m_s": speed, "height_m": height, "dynamic_viscosity_pa_s": mu,
                     "threshold": reynolds_warning})
                continue
            # Geometry/API values can differ by their last binary digits (e.g. H=0.05
            # arrives as 0.05000000000000001). Protect the threshold comparison only,
            # never round the evidence or treat this as a physical uncertainty bound.
            margin = REYNOLDS_THRESHOLD_GUARD_ULPS * math.ulp(float(reynolds_warning))
            if reynolds > reynolds_warning and reynolds - reynolds_warning > margin:
                add("REYNOLDS_RISK", "Warning", "以通道高度计算的名义 Reynolds 数超过可配置筛查阈值及末位浮点比较保护；不是普适转捩判据或湍流结论。",
                    (tag,), boundary["boundary_ids"], {"reynolds_height_based": reynolds, "threshold": reynolds_warning,
                                                       "numerical_comparison_margin": margin})
    return {"schema_version": "diagnosis-0.1", "profile": model["profile"],
            "status": "partial" if any(x["code"] == "EVALUATION_UNAVAILABLE" for x in findings) else "checked",
            "numeric_policy": {"reynolds_threshold_guard_ulps": REYNOLDS_THRESHOLD_GUARD_ULPS},
            "findings": sorted(findings, key=lambda x: (x["code"], x["feature_tags"]))}



MODULE_ID = "flow"
RULES = (
    ("MISSING_INLET", "boundaries", ("verified_planar_flow_profile", "uncoupled_flow_semantics", "effective_boundary_selections")),
    ("MISSING_OUTLET", "boundaries", ("verified_planar_flow_profile", "uncoupled_flow_semantics", "effective_boundary_selections")),
    ("BC_SELECTION_OVERLAP", "boundaries", ("verified_planar_flow_profile", "uncoupled_flow_semantics", "declared_boundary_selections")),
    ("INVALID_MATERIAL_PARAMETER", "material", ("verified_newtonian_material_binding", "evaluated_material_constants")),
    ("INLET_DIRECTION", "numerics", ("verified_planar_flow_profile", "uncoupled_flow_semantics", "evaluated_boundary_parameters")),
    ("REYNOLDS_RISK", "numerics", ("verified_rectangle_scale", "uncoupled_flow_semantics", "evaluated_material_constants", "evaluated_boundary_parameters")),
    ("BOUNDARY_PARAMETER_EVALUATION", "numerics", ("uncoupled_flow_semantics", "evaluated_boundary_parameters")),
    ("EVALUATION_UNAVAILABLE", "evaluation", ("recorded_scalar_evaluation_status",)),
)

AXIS_RULES = tuple((code, group, tuple(
    "verified_axisymmetric_flow_profile" if d == "verified_planar_flow_profile" else
    "verified_pipe_diameter" if d == "verified_rectangle_scale" else d for d in dependencies))
    for code, group, dependencies in RULES) + (
    ("AXIS_SELECTION_INCONSISTENT", "boundaries", ("axisymmetric_coordinates", "geometric_axis_boundaries", "effective_boundary_selections")),
    ("EMPTY_BOUNDARY_SELECTION", "boundaries", ("enabled_boundary_nodes", "effective_boundary_selections")),
)


def rules_for_profile(profile):
    if profile == "pipe-3d-v1":
        from .flow_3d import RULES as three_d_rules
        return three_d_rules
    return AXIS_RULES if profile == "axisymmetric-pipe-v1" else RULES


def _axis_geometry(geometry):
    """Infer a straight pipe only from a rectangle and recorded edge samples.

    No entity ID, selection label, or bounding box alone establishes a role.
    Missing topology leaves boundary/material checks available without a scale.
    """
    evidence = geometry.get("axisymmetric_evidence", {})
    if (evidence.get("read_status") != "read" or evidence.get("coordinate_names") != ["Rg", "PHIg", "Zg"]
            or evidence.get("spatial_coordinate_names") != ["r", "phi", "z"]):
        return None, None
    count = geometry["boundary_count"]
    edges = evidence.get("boundaries", [])
    if len(edges) != count or {e.get("boundary_id") for e in edges} != set(range(1, count + 1)):
        return None, None
    samples = {}
    for edge in edges:
        points = edge.get("sample_coordinates")
        if (not isinstance(points, list) or len(points) < 3
                or any(not isinstance(row, list) or len(row) != 2 for row in points)
                or not all(is_finite_number(x) for row in points for x in row)
                or edge.get("domain_ids") != [1]):
            return None, None
        samples[edge["boundary_id"]] = [list(row) for row in zip(*points)]
    axis = sorted(i for i, xy in samples.items() if all(x == 0 for x in xy[0]))
    types = geometry.get("feature_types", [])
    rotation = geometry.get("rectangle_rotation_expression")
    if (count != 4 or types.count("Rectangle") != 1 or set(types) - {"Rectangle", "Finalize"}
            or not isinstance(rotation, str) or "".join(rotation.split()) not in {"0", "0[deg]", "0[rad]"}
            or len(axis) != 1):
        return axis, None
    all_r = [x for xy in samples.values() for x in xy[0]]
    all_z = [x for xy in samples.values() for x in xy[1]]
    radius, bottom, top = max(all_r), min(all_z), max(all_z)
    if min(all_r) != 0 or radius <= 0 or top <= bottom:
        return axis, None
    roles = []
    for xy in samples.values():
        r, z = xy
        if len(set(r)) == 1 and r[0] in (0, radius) and min(z) == bottom and max(z) == top:
            roles.append("axis" if r[0] == 0 else "wall")
        elif len(set(z)) == 1 and z[0] in (bottom, top) and min(r) == 0 and max(r) == radius:
            roles.append("bottom" if z[0] == bottom else "top")
    diameter = radius * 2
    return axis, diameter if sorted(roles) == ["axis", "bottom", "top", "wall"] and is_finite_number(diameter) else None


def _normalize_axisymmetric(inventory):
    _require(inventory.get("schema_version") == "inventory-0.2", "需要 inventory-0.2 API 证据")
    _require(not inventory["multiphysics_tags"] and len(inventory["components"]) == 1, "需要单组件流动投影")
    component = inventory["components"][0]
    _require(not component["multiphysics_tags"] and len(component["geometries"]) == 1, "需要单几何流动投影")
    geometry = component["geometries"][0]
    _require(geometry["dimension"] == 2 and geometry.get("axisymmetric") is True
             and geometry["domain_count"] == 1 and geometry["length_unit"] == "m", "轴对称规则仅验证米制二维单域")
    bbox, count = geometry["bounding_box"], geometry["boundary_count"]
    _require(type(count) is int and count > 0 and len(bbox) == 4 and all(is_finite_number(x) for x in bbox)
             and bbox[0] >= 0 and bbox[1] > bbox[0] and bbox[3] > bbox[2], "轴对称几何范围证据不可用")
    _require(len(component["physics"]) == 1, "需要单物理场投影")
    physics = component["physics"][0]
    _require(physics["type"] == "LaminarFlow" and physics["enabled"] is True and physics["study_active"] is True,
             "需要研究明确启用的 LaminarFlow")
    studies = inventory["studies"]
    _require(len(studies) == 1 and studies[0]["type"] == "Stationary" and studies[0]["enabled"] is True,
             "轴对称规则仅验证单一定常研究")
    _require(len(component["materials"]) == 1, "需要唯一有效流体材料")
    material = component["materials"][0]
    _require(material["enabled"] is True and material["domain_ids"] == [1], "材料必须覆盖唯一流体域")
    features = [f for f in physics["features"] if f.get("enabled") is not False]
    fluids = [f for f in features if f.get("type") == "FluidProperties"]
    binding = len(fluids) == 1 and fluids[0].get("enabled") is True and fluids[0].get("selected_entity_ids") == [1]
    params = fluids[0].get("parameters", {}) if binding else {}
    binding = bool(binding and params.get("Constitutiverelation") == "Newtonian"
                   and params.get("rho_mat") == "from_mat" and params.get("mu_mat") == "from_mat")
    boundaries, complete = [], True
    roles = {**ROLES, "AxialSymmetry": "axis"}
    for feature in features:
        kind = feature.get("type", "unknown")
        if kind in {"FluidProperties", "init"}:
            complete = complete and feature.get("read_status") != "unread" and feature.get("child_feature_count") == 0
            continue
        role = roles.get(kind, "unknown")
        known = (feature.get("enabled") is True and feature.get("read_status") != "unread"
                 and feature.get("selection_dimensions") == [1]
                 and isinstance(feature.get("selected_entity_ids"), list))
        parameters = feature.get("parameters", {})
        mode = "AxialSymmetry" if role == "axis" else parameters.get("BoundaryCondition")
        verified = (role != "unknown" and known and feature.get("child_feature_count") == 0
                    and mode in {"axis": {"AxialSymmetry"}, "inlet": {"Velocity"},
                                 "outlet": {"PressureNoViscousStress"}, "wall": {"NoSlip", "Slip"}}[role]
                    and (role != "inlet" or parameters.get("ComponentWise") == "NormalInflowVelocity"))
        declared = feature.get("declared_entity_ids")
        # COMSOL's managed default axis declares all edges, then filters to r=0.
        # As with the default wall, that declaration is not an explicit conflict.
        fallback = role in {"wall", "axis"} and not feature.get("named_selection") and declared is not None and set(declared) == set(range(1, count + 1))
        boundaries.append({"feature_tag": feature["tag"], "label": feature.get("label", ""), "feature_type": kind,
                           "type": role, "boundary_ids": sorted(feature["selected_entity_ids"]) if known else [],
                           "declared_boundary_ids": declared, "selection_scope": "fallback" if fallback else "explicit",
                           "selection_known": known, "mode": mode if isinstance(mode, str) else None,
                           "verified_mode": verified,
                           "parameters": {k: _legacy_evaluation(v) for k, v in feature.get("evaluated_parameters", {}).items()
                                          if k in {"normal_velocity", "pressure"}}})
        complete = complete and verified
    axis, diameter = _axis_geometry(geometry)
    open_pipe = complete and diameter is not None and any(b["type"] in {"inlet", "outlet"} for b in boundaries)
    # Diameter is geometric evidence; using it in a pipe-flow screen additionally
    # requires ports on end edges and a no-slip wall on the outer radial edge.
    end_ids, outer_ids = set(), set()
    if diameter is not None:
        for edge in geometry["axisymmetric_evidence"]["boundaries"]:
            points = edge["sample_coordinates"]
            if len({p[1] for p in points}) == 1:
                end_ids.add(edge["boundary_id"])
            if all(p[0] == diameter / 2 for p in points):
                outer_ids.add(edge["boundary_id"])
    wall_ids = set().union(*(set(b["boundary_ids"]) for b in boundaries if b["type"] == "wall" and b["mode"] == "NoSlip"))
    pipe_bc_verified = bool(open_pipe and outer_ids and wall_ids == outer_ids and all(
        (set(b["boundary_ids"]) | set(b["declared_boundary_ids"] or [])) <= end_ids
        for b in boundaries if b["type"] in {"inlet", "outlet"}))
    result = {"schema_version": "diagnostic-0.2", "profile": "axisymmetric-pipe-v1",
              "source": {"comsol_version": inventory["comsol_version"], "component_tag": component["tag"],
                         "physics_tag": physics["tag"], "study_tag": studies[0]["study_tag"]},
              "geometry": {"bounding_box_m": bbox, "boundary_count": count, "axis_boundary_ids": axis,
                           "pipe_diameter_m": diameter, "flow_configuration": "open_pipe" if open_pipe else "closed_or_unverified"},
              "material": {k: _legacy_evaluation(material[k]) for k in ("density", "dynamic_viscosity")},
              "material_binding_verified": binding, "boundary_inventory_complete": complete,
              "reynolds_profile_verified": pipe_bc_verified,
              "boundaries": sorted(boundaries, key=lambda b: b["feature_tag"])}
    validate(result)
    return result


def _axis_rule_results(model, blockers=()):
    """Coverage and findings share the same prerequisites, including node cases."""
    rules = {code: {"rule_id": code, "status": "checked", "reason": "所需轴对称 API 证据已核验。",
                    "dependencies": list(deps), "evidence_refs": []}
             for code, _, deps in AXIS_RULES}
    boundaries, geometry = model["boundaries"], model["geometry"]
    axis = geometry["axis_boundary_ids"]
    axis_consistent = axis is not None and set(axis) == set().union(
        *(set(b["boundary_ids"]) for b in boundaries if b["type"] == "axis")) and not any(
            (set(b["boundary_ids"]) | (set(b["declared_boundary_ids"] or []) if b["selection_scope"] == "explicit" else set())) & set(axis)
            for b in boundaries if b["type"] != "axis") and not any(
                set(b["declared_boundary_ids"] or []) - set(axis) for b in boundaries
                if b["type"] == "axis" and b["selection_scope"] == "explicit")
    def skip(code, reason):
        rules[code].update(status="skipped", reason=reason)
    if not model["material_binding_verified"]:
        skip("INVALID_MATERIAL_PARAMETER", "尚未验证该材料绑定或本构模式；材料参数规则未执行。")
    elif not all(v["status"] == "resolved" for v in model["material"].values()) and not any(
            v["status"] == "resolved" and v["value"] <= 0 for v in model["material"].values()):
        skip("INVALID_MATERIAL_PARAMETER", "材料常数未求值，正值规则缺少证据。")
    for code in ("MISSING_INLET", "MISSING_OUTLET"):
        if geometry["flow_configuration"] != "open_pipe":
            skip(code, "仅对已验证且至少有一个端口节点的开口圆管检查必需入口/出口；封闭或未验证流动不适用。")
    if (geometry["axis_boundary_ids"] is None or not model["boundary_inventory_complete"]
            or any(b["selection_scope"] == "explicit" and b["declared_boundary_ids"] is None for b in boundaries)):
        skip("AXIS_SELECTION_INCONSISTENT", "轴线采样证据或边界模式不完整，不能判断轴线角色。")
    if any(not b["selection_known"] for b in boundaries):
        skip("EMPTY_BOUNDARY_SELECTION", "至少一个启用节点的有效选择不可读。")
    if not model["boundary_inventory_complete"] or any(b["declared_boundary_ids"] is None for b in boundaries):
        skip("BC_SELECTION_OVERLAP", "节点模式或声明选择不完整，冲突规则未执行。")
    for code in ("INLET_DIRECTION", "REYNOLDS_RISK", "BOUNDARY_PARAMETER_EVALUATION"):
        cases = []
        for b in boundaries:
            if not b["boundary_ids"] or (b["type"] not in {"inlet", "outlet"} if code == "BOUNDARY_PARAMETER_EVALUATION" else b["type"] != "inlet"):
                continue
            key = "normal_velocity" if b["type"] == "inlet" else "pressure"
            value = b["parameters"].get(key)
            ok = model["boundary_inventory_complete"] and b["verified_mode"] and value is not None and value["status"] == "resolved"
            reason = "该节点已验证的参数可用。" if ok else "该节点模式未验证或所需参数未求值。"
            if code == "REYNOLDS_RISK":
                if (geometry["pipe_diameter_m"] is None or not model["material_binding_verified"]
                        or not model["reynolds_profile_verified"]
                        or geometry["flow_configuration"] != "open_pipe" or not axis_consistent
                        or not all(v["status"] == "resolved" for v in model["material"].values())
                        or any(x["type"] == "wall" and x["mode"] != "NoSlip" for x in boundaries)):
                    ok, reason = False, "缺少已验证开口圆管、轴线配置、无滑移壁面或材料常数；不以包围盒代替尺度。"
                elif ok and all(v["value"] > 0 for v in model["material"].values()):
                    _, error = _reynolds_number(model["material"]["density"]["value"], value["value"],
                                                geometry["pipe_diameter_m"], model["material"]["dynamic_viscosity"]["value"])
                    if error:
                        ok, reason = False, "Re 数超出有限数值表示范围: " + error
            cases.append({"feature_tag": b["feature_tag"], "status": "checked" if ok else "skipped", "reason": reason, "evidence_refs": []})
        rules[code]["cases"] = cases
        if any(c["status"] != "checked" for c in cases) or not model["boundary_inventory_complete"]:
            skip(code, "至少一个节点或模式缺少证据；仅执行可独立成立的节点规则。")
        if code == "REYNOLDS_RISK" and (geometry["pipe_diameter_m"] is None or geometry["flow_configuration"] != "open_pipe"):
            skip(code, "仅对已验证开口圆管执行直径尺度的 Re 风险筛查。")
    if blockers:
        for code, group, _ in AXIS_RULES:
            if group not in {"material", "evaluation"}:
                skip(code, "未知或未支持耦合可能改变流动语义；依赖规则未执行。")
                rules[code]["dependencies"].append("coupling_scope_and_semantics")
                for case in rules[code].get("cases", []):
                    case.update(status="skipped", reason=rules[code]["reason"])
    return rules


def _check_axisymmetric(model, *, reynolds_warning=2000.0, rule_groups=None, blockers=()):
    validate(model)
    if not is_finite_number(reynolds_warning) or reynolds_warning <= 0:
        raise ValueError("Reynolds warning threshold must be finite and positive")
    groups = {"boundaries", "material", "numerics", "evaluation"} if rule_groups is None else set(rule_groups) | {"evaluation"}
    rules = _axis_rule_results(model, blockers)
    findings = []
    def allowed(code, tag=None):
        group = next(g for c, g, _ in AXIS_RULES if c == code)
        rule = rules[code]
        return group in groups and (rule["status"] == "checked" or tag is not None and any(
            c["feature_tag"] == tag and c["status"] == "checked" for c in rule.get("cases", [])))
    def add(code, severity, text, tags=(), ids=(), evidence=None):
        findings.append({"code": code, "severity": severity, "explanation": text,
                         "feature_tags": sorted(set(tags)), "boundary_ids": sorted(set(ids)), "evidence": evidence or {}})
    boundaries, geometry = model["boundaries"], model["geometry"]
    for role in ("inlet", "outlet"):
        code = "MISSING_" + role.upper()
        nodes = [b for b in boundaries if b["type"] == role]
        if allowed(code) and not any(b["boundary_ids"] for b in nodes):
            add(code, "Critical", "已验证开口圆管缺少有效" + ("入口" if role == "inlet" else "出口") + "；核对节点启用、有效选择及覆盖关系。",
                [b["feature_tag"] for b in nodes], evidence={"required_role": role, "flow_configuration": "open_pipe"})
    if allowed("EMPTY_BOUNDARY_SELECTION"):
        for b in boundaries:
            if not b["boundary_ids"] and b["selection_scope"] != "fallback":
                add("EMPTY_BOUNDARY_SELECTION", "Warning", "启用边界节点的有效选择为空；核对选择及被覆盖关系，确认是否仍需该节点。",
                    [b["feature_tag"]], evidence={"declared_boundary_ids": b["declared_boundary_ids"], "role": b["type"]})
    if allowed("AXIS_SELECTION_INCONSISTENT"):
        axis = set(geometry["axis_boundary_ids"])
        covered = set()
        for b in boundaries:
            selected = set(b["boundary_ids"])
            declared = set(b["declared_boundary_ids"] or []) if b["selection_scope"] == "explicit" else set()
            if b["type"] == "axis":
                covered |= selected & axis
                bad = (selected | declared) - axis
            else:
                bad = (selected | declared) & axis
            if bad:
                add("AXIS_SELECTION_INCONSISTENT", "Warning", "边界角色与 r=0 几何轴线不一致；将轴对称条件作用到轴线并核对其他边界的选择。",
                    [b["feature_tag"]], bad, {"geometric_axis_boundary_ids": sorted(axis), "role": b["type"],
                                             "declared_boundary_ids": b["declared_boundary_ids"], "effective_boundary_ids": b["boundary_ids"]})
        if axis - covered:
            add("AXIS_SELECTION_INCONSISTENT", "Warning", "几何轴线缺少有效轴对称节点覆盖；核对轴线条件的启用和选择。",
                ids=axis-covered, evidence={"geometric_axis_boundary_ids": sorted(axis)})
    if allowed("BC_SELECTION_OVERLAP"):
        for left, right in itertools.combinations(boundaries, 2):
            if left["type"] == right["type"] or "fallback" in {left["selection_scope"], right["selection_scope"]}:
                continue
            overlap = set(left["declared_boundary_ids"]) & set(right["declared_boundary_ids"])
            if overlap:
                add("BC_SELECTION_OVERLAP", "Warning", "不同流动边界角色声明同一边界；核对节点优先级与实际生效选择。",
                    [left["feature_tag"], right["feature_tag"]], overlap,
                    {"effective_left": left["boundary_ids"], "effective_right": right["boundary_ids"]})
    rho, mu = (model["material"][k] for k in ("density", "dynamic_viscosity"))
    if model["material_binding_verified"] and "material" in groups:
        for key, value in model["material"].items():
            if value["status"] != "resolved":
                add("EVALUATION_UNAVAILABLE", "Warning", "材料常数无法求值，依赖该值的检查未执行。", evidence={"quantity": key, "expression": value["expression"]})
    if allowed("INVALID_MATERIAL_PARAMETER") and any(v["status"] == "resolved" and v["value"] <= 0 for v in (rho, mu)):
        add("INVALID_MATERIAL_PARAMETER", "Critical", "当前牛顿流体要求正密度与正动力黏度；核对材料表达式及单位。",
            evidence={"density_kg_m3": rho["value"], "dynamic_viscosity_pa_s": mu["value"]})
    for b in boundaries:
        if not b["boundary_ids"] or b["type"] not in {"inlet", "outlet"} or "numerics" not in groups or blockers:
            continue
        tag = b["feature_tag"]
        key = "normal_velocity" if b["type"] == "inlet" else "pressure"
        value = b["parameters"].get(key)
        if b["verified_mode"] and (value is None or value["status"] != "resolved"):
            add("EVALUATION_UNAVAILABLE", "Warning", "边界参数无法按指定单位求值；相关数值检查未执行。", [tag], b["boundary_ids"], {"quantity": key})
        if b["type"] != "inlet" or not value or value["status"] != "resolved":
            continue
        speed = value["value"]
        if allowed("INLET_DIRECTION", tag) and speed <= 0:
            add("INLET_DIRECTION", "Warning", "法向入口速度为零或未指向域内；核对入口符号与法向速度模式。", [tag], b["boundary_ids"], {"normal_velocity_m_s": speed})
        if allowed("REYNOLDS_RISK", tag) and rho["value"] > 0 and mu["value"] > 0:
            reynolds, error = _reynolds_number(rho["value"], speed, geometry["pipe_diameter_m"], mu["value"])
            margin = REYNOLDS_THRESHOLD_GUARD_ULPS * math.ulp(float(reynolds_warning))
            if not error and reynolds > reynolds_warning and reynolds - reynolds_warning > margin:
                add("REYNOLDS_RISK", "Warning", "按已验证圆管直径计算的名义 Reynolds 数超过筛查阈值；建议核对层流假设，此值不证明转捩或求解失败。",
                    [tag], b["boundary_ids"], {"reynolds_diameter_based": reynolds, "pipe_diameter_m": geometry["pipe_diameter_m"],
                                             "threshold": reynolds_warning, "numerical_comparison_margin": margin})
    return {"profile": model["profile"],
            "status": "checked" if all(r["status"] == "checked" for r in rules.values()) else "partial",
            "numeric_policy": {"reynolds_threshold_guard_ulps": REYNOLDS_THRESHOLD_GUARD_ULPS},
            "findings": sorted(findings, key=lambda f: (f["code"], f["feature_tags"]))}


def _run_axisymmetric(inventory, component_index, physics_index, blockers, **options):
    import copy
    component = copy.deepcopy(inventory["components"][component_index])
    physics = component["physics"][physics_index]
    refs = [f"/components/{component_index}/physics/{physics_index}", f"/components/{component_index}/geometries",
            f"/components/{component_index}/materials", "/studies"]
    component["physics"] = [physics]
    component["materials"] = [m for m in component["materials"] if m.get("enabled") is not False and m.get("domain_ids") != []]
    component["multiphysics_tags"] = []
    projection = {**inventory, "components": [component], "multiphysics_tags": []}
    try:
        model = _normalize_axisymmetric(projection)
    except (UnsupportedModel, KeyError, ValidationError) as error:
        return {"status": "skipped", "reason": str(error), "rules": [
            {"rule_id": code, "status": "skipped", "reason": str(error), "dependencies": list(deps), "evidence_refs": refs}
            for code, _, deps in AXIS_RULES], "findings": [], "evidence_refs": refs}
    rules = _axis_rule_results(model, blockers)
    feature_refs = {f["tag"]: f"/components/{component_index}/physics/{physics_index}/features/{i}" for i, f in enumerate(physics["features"])}
    for rule in rules.values():
        rule["evidence_refs"] = list(dict.fromkeys(refs + list(blockers)))
        for case in rule.get("cases", []):
            case["evidence_refs"] = [feature_refs[case["feature_tag"]]]
    report = _check_axisymmetric(model, blockers=blockers, **options)
    complete = all(r["status"] == "checked" for r in rules.values())
    return {"status": "checked" if complete else "skipped", "reason": "已执行已核验轴对称圆管规则。" if complete else "部分轴对称规则缺少证据或不适用，详见规则覆盖。",
            "rules": list(rules.values()), "findings": report["findings"], "model": model,
            "evidence_refs": refs, "numeric_policy": report["numeric_policy"]}


def run_instance(inventory, component_index, physics_index, blockers, **options):
    """Project one API instance; coupling gates boundary/numeric rules only.

    Other interfaces are omitted only after the scheduler has considered coupling
    scope. Material positivity remains an independent assertion about the recorded
    Newtonian constants, never a claim about coupled material behavior.
    """
    import copy

    component = inventory["components"][component_index]
    geometries = component.get("geometries", [])
    if any(g.get("dimension") == 3 for g in geometries):
        from .flow_3d import run_instance as run_3d_instance
        return run_3d_instance(inventory, component_index, physics_index, blockers, **options)
    if (len(geometries) == 1 and geometries[0].get("axisymmetric") is True
            and geometries[0].get("domain_count", 0) > 1):
        from .flow_scope import run_instance as run_domain_instance
        return run_domain_instance(inventory, component_index, physics_index, blockers, **options)
    physics = component["physics"][physics_index]
    if any(g.get("axisymmetric") is True for g in component.get("geometries", [])):
        return _run_axisymmetric(inventory, component_index, physics_index, blockers, **options)
    refs = [f"/components/{component_index}/physics/{physics_index}",
            f"/components/{component_index}/geometries",
            f"/components/{component_index}/materials", "/studies"]
    projection = copy.deepcopy(inventory)
    projected_component = copy.deepcopy(component)
    projected_component["physics"] = [copy.deepcopy(physics)]
    # Explicitly unused nodes cannot supply the unique active fluid material.
    # Selected/unknown material domains are retained, preserving the M0 gate.
    projected_component["materials"] = [m for m in projected_component["materials"]
                                        if m.get("enabled") is not False and m.get("domain_ids") != []]
    projected_component["multiphysics_tags"] = []
    projection["components"] = [projected_component]
    projection["multiphysics_tags"] = []
    rules = [{"rule_id": code, "status": "skipped", "reason": "",
              "dependencies": list(dependencies), "evidence_refs": list(refs)}
             for code, group, dependencies in RULES]
    try:
        model = normalize(projection)
    except (UnsupportedModel, KeyError, ValidationError) as error:
        for rule in rules:
            rule["reason"] = str(error)
        return {"status": "skipped", "reason": str(error), "rules": rules,
                "findings": [], "evidence_refs": refs}
    groups = {"material"} if blockers else {"boundaries", "material", "numerics"}
    report = check(model, rule_groups=groups, **options)
    material_resolved = all(v["status"] == "resolved" for v in model["material"].values())
    material_positive = material_resolved and all(v["value"] > 0 for v in model["material"].values())
    feature_refs = {f["tag"]: f"/components/{component_index}/physics/{physics_index}/features/{i}"
                    for i, f in enumerate(physics["features"])}
    for rule, (code, group, dependencies) in zip(rules, RULES):
        if blockers and group not in {"material", "evaluation"}:
            rule.update(reason="未知或未支持耦合可能改变流动语义；依赖规则未执行。",
                        evidence_refs=refs + list(blockers))
            rule["dependencies"].append("coupling_scope_and_semantics")
        elif code == "EVALUATION_UNAVAILABLE":
            rule.update(status="checked", reason="已检查实际使用的标量求值可用性；不可用值作为证据缺口报告。")
        elif group == "material" and not material_resolved:
            proven_invalid = any(v["status"] == "resolved" and v["value"] <= 0
                                 for v in model["material"].values())
            rule.update(status="checked" if proven_invalid else "skipped",
                        reason="已确认至少一个材料常数非正，足以判定正值要求不满足；其他常数的缺失证据仍单独报告。"
                        if proven_invalid else "材料常数求值证据不可用；正值检查未完成。")
        elif group == "numerics":
            cases = []
            for boundary in model["boundaries"]:
                if not boundary["boundary_ids"] or (code != "BOUNDARY_PARAMETER_EVALUATION" and boundary["type"] != "inlet"):
                    continue
                if not boundary["parameters"]:
                    continue
                values = boundary["parameters"].values()
                resolved = all(v["status"] == "resolved" for v in values)
                reason = "该节点所需求值证据可用；规则已执行。"
                if not resolved:
                    reason = "该节点参数求值不可用；依赖此值的检查未执行。"
                if code == "REYNOLDS_RISK":
                    if model["profile"] != "rectangular-channel-v1":
                        resolved, reason = False, "缺少已验证的矩形通道尺度；未使用包围盒代替。"
                    elif not material_resolved:
                        resolved, reason = False, "材料常数未求值；Re 检查未执行。"
                    elif not material_positive:
                        resolved, reason = True, "已核验 Re 前提：材料常数非正；材料规则已报告错误，不计算未定义商值。"
                    elif resolved:
                        speed = boundary["parameters"]["normal_velocity"]["value"]
                        _, error = _reynolds_number(model["material"]["density"]["value"], speed,
                                                    model["geometry"]["height_m"], model["material"]["dynamic_viscosity"]["value"])
                        if error:
                            resolved, reason = False, "Re 超出有限数值表示范围: " + error
                cases.append({"feature_tag": boundary["feature_tag"], "status": "checked" if resolved else "skipped",
                              "reason": reason, "evidence_refs": [feature_refs[boundary["feature_tag"]]]})
            rule["cases"] = cases
            complete = all(case["status"] == "checked" for case in cases)
            # Unverified scales/material evidence remain incomplete even without an inlet.
            if code == "REYNOLDS_RISK" and (model["profile"] != "rectangular-channel-v1" or not material_resolved):
                complete = False
            rule.update(status="checked" if complete else "skipped",
                        reason="所有有效节点的规则与前提均已检查。" if complete else "至少一个节点或共同前提缺少证据；仅保留已检查节点的独立结果。")
        else:
            rule.update(status="checked", reason="所需 API 证据与已验证配置可用；规则已执行。")
    complete = all(rule["status"] == "checked" for rule in rules)
    return {"status": "checked" if complete else "skipped",
            "reason": "已执行当前已验证二维平面流动规则。" if complete else "仅执行证据与依赖条件已满足的规则；其余见规则覆盖。",
            "rules": rules, "findings": report["findings"], "model": model,
            "evidence_refs": refs, "numeric_policy": report["numeric_policy"]}
