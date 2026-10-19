"""Conservative independent flow checks inside a multi-domain heat model.

Retains real entity IDs and does not manufacture a rectangular geometry or a
pipe diameter from the whole component bounding box. Full channel/profile
checks remain skipped until a domain geometry adapter is separately verified.
"""
import itertools

from . import flow
from .heat import checked, finding, finish, ids, make_rules


def run_instance(inventory, component_index, physics_index, blockers=(), **options):
    component = inventory["components"][component_index]
    physics = component["physics"][physics_index]
    pointer = f"/components/{component_index}/physics/{physics_index}"
    refs = [pointer, f"/components/{component_index}/materials", f"/components/{component_index}/geometries", "/studies"]
    rules = make_rules(flow.AXIS_RULES, refs)
    by_code = {r["rule_id"]: r for r in rules}
    for rule in rules:
        rule["reason"] = "多域流动仅保留独立材料和已核验节点结果；未验证流体域的圆管几何。"
    findings = []
    geometries = component.get("geometries", [])
    if (len(geometries) != 1 or geometries[0].get("dimension") != 2 or geometries[0].get("axisymmetric") is not True
            or physics.get("enabled") is not True or physics.get("study_active") is not True
            or physics.get("type") != "LaminarFlow"):
        return finish(rules, findings, refs)
    features = physics.get("features", [])
    fluids = [(i, f) for i, f in enumerate(features) if f.get("type") == "FluidProperties" and f.get("enabled") is True]
    selected = (ids(fluids[0][1].get("selected_entity_ids")) if len(fluids) == 1
                and fluids[0][1].get("selection_dimensions") == [2] else None)
    if selected is None or len(selected) != 1:
        return finish(rules, findings, refs)
    params = fluids[0][1].get("parameters", {})
    binding = (params.get("Constitutiverelation") == "Newtonian" and params.get("rho_mat") == "from_mat"
               and params.get("mu_mat") == "from_mat")
    materials = [(i, m) for i, m in enumerate(component.get("materials", [])) if m.get("enabled") is not False]
    uncertain = any(ids(m.get("domain_ids")) is None or m.get("enabled") is None for _, m in materials)
    candidates = [(i, m) for i, m in materials if ids(m.get("domain_ids")) is not None and selected & ids(m["domain_ids"])]
    if binding and not uncertain and len(candidates) == 1:
        mi, material = candidates[0]
        values = {key: material.get(key, {}) for key in ("density", "dynamic_viscosity")}
        resolved = {key: value["value"] for key, value in values.items()
                    if value.get("status") == "resolved" and flow.is_finite_number(value.get("value"))}
        invalid = {key: value for key, value in resolved.items() if value <= 0}
        checked(by_code["EVALUATION_UNAVAILABLE"])
        if len(resolved) != len(values):
            findings.append(finding("EVALUATION_UNAVAILABLE", "流体材料常数未全部解析；依赖数值的检查跳过。", [f"/components/{component_index}/materials/{mi}"],
                                    evidence={"domain_ids": sorted(selected)}))
        if len(resolved) == len(values) or invalid:
            checked(by_code["INVALID_MATERIAL_PARAMETER"])
        if invalid:
            findings.append(finding("INVALID_MATERIAL_PARAMETER", "已确认流体域的密度或动力黏度常数非正；核对材料及单位。", refs,
                                    severity="Critical", evidence={"invalid_parameters": invalid, "domain_ids": sorted(selected)}))
    if blockers:
        return finish(rules, findings, refs)
    known_types = {"FluidProperties", "init", "AxialSymmetry", "Inlet", "Outlet", "Wall", "WallBC"}
    complete = all(f.get("enabled") is not None and f.get("child_feature_count") == 0 and
                   f.get("read_status") != "unread" and
                   (f.get("enabled") is False or f.get("type") in known_types) for f in features)
    boundaries = [(i, f) for i, f in enumerate(features) if f.get("enabled") is True and f.get("type") in
                  {"Inlet", "Outlet", "Wall", "WallBC", "AxialSymmetry"}]
    selections_known = complete and all(ids(f.get("selected_entity_ids")) is not None and f.get("selection_dimensions") == [1] for _, f in boundaries)
    if selections_known:
        checked(by_code["EMPTY_BOUNDARY_SELECTION"])
        for i, feature in boundaries:
            if not feature["selected_entity_ids"]:
                findings.append(finding("EMPTY_BOUNDARY_SELECTION", "已启用流动边界的有效选择为空；核对该节点与流体域。", [f"{pointer}/features/{i}"],
                                        tags=[feature["tag"]], evidence={"declared_boundary_ids": feature.get("declared_entity_ids")}))
    count = geometries[0].get("boundary_count")
    if selections_known and type(count) is int and all(ids(f.get("declared_entity_ids")) is not None for _, f in boundaries):
        checked(by_code["BC_SELECTION_OVERLAP"])
        for (li, left), (ri, right) in itertools.combinations(boundaries, 2):
            # Default axis/wall declarations can span the complete geometry.
            fallback = any(f["type"] in {"Wall", "WallBC", "AxialSymmetry"} and not f.get("named_selection")
                           and ids(f["declared_entity_ids"]) == set(range(1, count + 1)) for f in (left, right))
            overlap = ids(left["declared_entity_ids"]) & ids(right["declared_entity_ids"])
            if overlap and not fallback and left["type"] != right["type"]:
                findings.append(finding("BC_SELECTION_OVERLAP", "不同流动边界角色声明重叠；核对实际生效选择。", [f"{pointer}/features/{li}", f"{pointer}/features/{ri}"],
                                        tags=[left["tag"], right["tag"]], boundaries=overlap))
    ports = [(i, f) for i, f in enumerate(features) if f.get("type") in {"Inlet", "Outlet"} and f.get("enabled") is True]
    cases = {code: [] for code in ("BOUNDARY_PARAMETER_EVALUATION", "INLET_DIRECTION")}
    for i, feature in ports:
        parameters = feature.get("parameters", {})
        inlet = feature["type"] == "Inlet"
        verified = parameters.get("BoundaryCondition") == ("Velocity" if inlet else "PressureNoViscousStress")
        verified &= not inlet or parameters.get("ComponentWise") == "NormalInflowVelocity"
        boundaries = ids(feature.get("selected_entity_ids"))
        key = "normal_velocity" if inlet else "pressure"
        value = feature.get("evaluated_parameters", {}).get(key, {})
        ok = (complete and verified and feature.get("selection_dimensions") == [1] and boundaries is not None and bool(boundaries)
              and value.get("status") == "resolved" and flow.is_finite_number(value.get("value")))
        for code in cases:
            if code == "INLET_DIRECTION" and not inlet:
                continue
            cases[code].append({"feature_tag": feature["tag"], "status": "checked" if ok else "skipped",
                                "reason": "该端口模式及参数已核验。" if ok else "端口模式、启用选择或求值证据不足。",
                                "evidence_refs": [f"{pointer}/features/{i}"]})
        if ok and inlet and value["value"] <= 0:
            findings.append(finding("INLET_DIRECTION", "法向入口速度为零或未指向域内；核对入口符号与模式。", [f"{pointer}/features/{i}"],
                                    tags=[feature["tag"]], boundaries=boundaries, evidence={"normal_velocity_m_s": value["value"]}))
    for code, values in cases.items():
        by_code[code]["cases"] = values
        if values and all(c["status"] == "checked" for c in values):
            checked(by_code[code])
    result = finish(rules, findings, refs)
    result["reason"] = "多域流动部分检查：保留真实域/边界 ID 的材料及已核验端口结果；几何依赖规则未执行。"
    return result
