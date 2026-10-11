"""Normalize API evidence; do not evaluate COMSOL expressions in Python."""
from __future__ import annotations

import argparse
from fractions import Fraction
import itertools
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[2]
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


def normalize(inventory):
    """Accept only the verified single-rectangle, constant-property profile."""
    _require(inventory.get("schema_version") == "inventory-0.2", "需要 inventory-0.2 API 证据")
    _require(not inventory["multiphysics_tags"], "暂不支持耦合物理场")
    _require(len(inventory["components"]) == 1, "暂仅支持一个组件")
    component = inventory["components"][0]
    _require(not component["multiphysics_tags"], "暂不支持组件内耦合")
    _require(len(component["geometries"]) == 1, "暂仅支持一个几何")
    geometry = component["geometries"][0]
    _require(geometry["dimension"] == 2 and geometry["domain_count"] == 1 and geometry["boundary_count"] == 4,
             "暂仅支持二维单域四边界矩形通道")
    _require(geometry["feature_types"].count("Rectangle") == 1
             and set(geometry["feature_types"]) <= {"Rectangle", "Finalize"}, "暂不支持非矩形或组合几何")
    # New API inventories include this evidence; old versioned fixtures remain readable.
    if "rectangle_rotation_expression" in geometry:
        rotation = geometry["rectangle_rotation_expression"]
        _require(isinstance(rotation, str) and "".join(rotation.split()) in {"0", "0[deg]", "0[rad]"},
                 "当前矩形配置仅验证显式零旋转，不能用旋转后的包围盒计算通道高度")
    _require(geometry["length_unit"] == "m", "当前矩形配置仅验证米制几何")
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
        _require(mode == {"inlet": "Velocity", "outlet": "PressureNoViscousStress", "wall": "NoSlip"}[role],
                 "不支持的边界模式: " + str(mode))
        if role == "inlet":
            _require(feature["parameters"].get("ComponentWise") == "NormalInflowVelocity", "暂仅支持法向入口速度，不能用 U0in 代替分量速度")
        # COMSOL returns all four input entities even for the fallback wall.
        # Treat an unnamed all-boundaries wall as fallback, not an explicit conflict.
        fallback = (role == "wall" and not feature["named_selection"]
                    and set(feature["declared_entity_ids"] or []) == {1, 2, 3, 4})
        boundaries.append({
            "feature_tag": feature["tag"], "label": feature["label"], "type": role,
            "boundary_ids": sorted(feature["selected_entity_ids"]),
            "declared_boundary_ids": feature["declared_entity_ids"], "selection_scope": "fallback" if fallback else "explicit", "mode": mode,
            "parameters": feature["evaluated_parameters"],
        })
    result = {
        "schema_version": "diagnostic-0.1", "profile": "rectangular-channel-v1",
        "source": {"comsol_version": inventory["comsol_version"], "component_tag": component["tag"],
                   "physics_tag": physics["tag"], "study_tag": studies[0]["study_tag"]},
        "geometry": {"length_m": length, "height_m": height},
        "material": {"density": material["density"], "dynamic_viscosity": material["dynamic_viscosity"]},
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


def check(model, *, reynolds_warning=2000.0):
    """Template constraints, not a proof of physical validity or solver success."""
    validate(model)
    if not is_finite_number(reynolds_warning) or reynolds_warning <= 0:
        raise ValueError("Reynolds warning threshold must be finite and positive")
    findings = []

    def add(code, severity, explanation, tags=(), ids=(), evidence=None):
        findings.append({"code": code, "severity": severity, "explanation": explanation,
                         "feature_tags": sorted(tags), "boundary_ids": sorted(ids), "evidence": evidence or {}})

    boundaries = model["boundaries"]
    for role in ("inlet", "outlet"):
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
    for left, right in itertools.combinations(boundaries, 2):
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

    rho = scalar(model["material"]["density"], "密度")
    mu = scalar(model["material"]["dynamic_viscosity"], "动力黏度")
    material_valid = (rho is not None and mu is not None and rho > 0 and mu > 0)
    if (rho is not None and rho <= 0) or (mu is not None and mu <= 0):
        add("INVALID_MATERIAL_PARAMETER", "Critical", "当前牛顿流体模板要求正密度与正动力黏度。",
            evidence={"density_kg_m3": rho, "dynamic_viscosity_pa_s": mu})
    for boundary in boundaries:
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
        if material_valid:
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


def diagnose_inventory(inventory, **options):
    try:
        model = normalize(inventory)
    except UnsupportedModel as error:
        return {"schema_version": "diagnosis-0.1", "status": "unsupported", "reason": str(error), "findings": []}
    return {"model": model, **check(model, **options)}


def main():
    parser = argparse.ArgumentParser(description="Check COMSOL inventory JSON without solving or changing an MPH file")
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reynolds-warning", type=float, default=2000)
    args = parser.parse_args()
    # Fail before overwriting any user report.
    if args.output.exists():
        parser.error("output already exists; choose a new report path")
    try:
        result = diagnose_inventory(json.loads(args.inventory.read_text(encoding="utf-8-sig")),
                                    reynolds_warning=args.reynolds_warning)
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        parser.error("invalid inventory or options: " + str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(f"{result['status']}: {len(result['findings'])} findings; {args.output}")


if __name__ == "__main__":
    main()
