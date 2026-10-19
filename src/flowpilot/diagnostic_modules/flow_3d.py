"""Evidence-scoped stationary flow checks for straight three-dimensional pipes.

Domain/face geometry is proved by the geometry adapter, never by a component
bounding box. A solid wall may coexist with the single selected fluid domain.
"""
from __future__ import annotations

import itertools
import math

from . import flow
from .heat import checked, finding, finish, ids, make_rules, stationary_participation

PROFILE = "pipe-3d-v1"
# COMSOL measureFinal integrates the curved surface approximately (the native
# radius .025, height 1 cylinder differs from pi*r*r*h by about .51%). Exact
# primitive classes and sampled curvature/normals still require tight agreement.
MEASURE_RELATIVE_TOLERANCE = .01
RULES = tuple((code, group, tuple("verified_3d_flow_profile" if d == "verified_planar_flow_profile"
                               else "verified_pipe_diameter" if d == "verified_rectangle_scale" else d
                               for d in deps)) for code, group, deps in flow.RULES) + (
    ("EMPTY_BOUNDARY_SELECTION", "boundaries", ("enabled_boundary_nodes", "effective_face_selections")),
    ("FLOW_FACE_SELECTION_INCONSISTENT", "boundaries", ("verified_3d_pipe_faces", "effective_face_selections")),
)


def pipe_geometry(geometry, domain_ids):
    """Return independently checked face/domain geometry, or no scale evidence."""
    evidence = geometry.get("three_dimensional_evidence", {})
    types = geometry.get("feature_types", [])
    if (evidence.get("read_status") != "read" or evidence.get("coordinate_names") != ["Xg", "Yg", "Zg"]
            or "Cylinder" not in types or set(types) - {"Cylinder", "Union", "Finalize"}
            or len(domain_ids) != 1):
        return None
    domains = evidence.get("domains", [])
    matches = [d for d in domains if d.get("domain_id") in domain_ids]
    if len(matches) != 1:
        return None
    domain = matches[0]
    face_ids = ids(domain.get("boundary_ids"))
    faces = [f for f in evidence.get("boundaries", []) if f.get("boundary_id") in (face_ids or set())]
    if (not face_ids or len(faces) != len(face_ids) or len({f.get("boundary_id") for f in faces}) != len(face_ids)
            or any(ids(f.get("domain_ids")) is None for f in evidence.get("boundaries", []))
            or {f.get("boundary_id") for f in evidence.get("boundaries", []) if domain_ids <= ids(f["domain_ids"])} != face_ids
            or any(not domain_ids <= ids(f["domain_ids"]) for f in faces)):
        return None
    bbox = domain.get("bounding_box")
    if not isinstance(bbox, list) or len(bbox) != 6 or not all(flow.is_finite_number(v) for v in bbox):
        return None
    # Curvature supplies the numerical radius. Native bbox coordinates are
    # rounded enough to create a false Re threshold crossing at exactly 2000.
    curvatures = [abs(v) for face in faces for v in face.get("mean_curvatures", [])
                  if flow.is_finite_number(v) and abs(v) > 1e-10]
    if not curvatures:
        return None
    radius = 1/(2*curvatures[0])
    length = bbox[5] - bbox[4]
    if radius <= 0 or length <= 0:
        return None
    # Domain bounds only propose a center; independent curvature, face area,
    # coordinates and volume must all confirm the same cylinder.
    close = lambda a, b: flow.is_finite_number(a) and math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-10)
    measure_close = lambda a, b: flow.is_finite_number(a) and math.isclose(a, b, rel_tol=MEASURE_RELATIVE_TOLERANCE, abs_tol=1e-12)
    if (not close(bbox[1] - bbox[0], 2*radius) or not close(bbox[3] - bbox[2], 2*radius)
            or not measure_close(domain.get("volume"), math.pi*radius*radius*length)):
        return None
    cx, cy = (bbox[0]+bbox[1])/2, (bbox[2]+bbox[3])/2
    ends, walls, side_area = [], [], 0
    end_z = []
    for face in faces:
        points, normals = face.get("sample_coordinates"), face.get("sample_normals")
        mean, gauss = face.get("mean_curvatures"), face.get("gauss_curvatures")
        if (not isinstance(points, list) or len(points) < 9 or not isinstance(normals, list) or len(normals) != len(points)
                or not isinstance(mean, list) or len(mean) != len(points) or not isinstance(gauss, list) or len(gauss) != len(points)
                or any(not isinstance(p, list) or len(p) != 3 or not all(flow.is_finite_number(v) for v in p) for p in points+normals)
                or not all(close(v, 0) for v in gauss)):
            return None
        is_end = (all(close(p[2], points[0][2]) for p in points) and all(close(v, 0) for v in mean)
                  and all(close(n[0], 0) and close(n[1], 0) and close(abs(n[2]), 1) for n in normals)
                  and any(close(points[0][2], z) for z in (bbox[4], bbox[5]))
                  and measure_close(face.get("area"), math.pi*radius*radius))
        is_wall = (all(close(math.hypot(p[0]-cx, p[1]-cy), radius) and bbox[4]-1e-10 <= p[2] <= bbox[5]+1e-10 for p in points)
                   and all(close(abs(v), 1/(2*radius)) for v in mean)
                   and all(close(n[2], 0) and close(math.hypot(n[0], n[1]), 1)
                           and close(abs(n[0]*(p[0]-cx)+n[1]*(p[1]-cy)), radius) for p, n in zip(points, normals))
                   and flow.is_finite_number(face.get("area")) and face["area"] > 0)
        if is_end:
            ends.append(face["boundary_id"])
            end_z.append(points[0][2])
        elif is_wall:
            walls.append(face["boundary_id"])
            side_area += face["area"]
        else:
            return None
    if (len(ends) != 2 or not walls or close(end_z[0], end_z[1])
            or not measure_close(side_area, 2*math.pi*radius*length)):
        return None
    return {"diameter_m": 2*radius, "end_face_ids": sorted(ends), "wall_face_ids": sorted(walls)}


def normalize(inventory, component_index=0, physics_index=0):
    component = inventory["components"][component_index]
    physics = component["physics"][physics_index]
    geometries = component.get("geometries", [])
    flow._require(inventory.get("schema_version") == "inventory-0.2" and len(geometries) == 1,
                  "三维检查需要单几何 inventory-0.2 证据。")
    geometry = geometries[0]
    count, bbox = geometry.get("boundary_count"), geometry.get("bounding_box")
    flow._require(geometry.get("dimension") == 3 and geometry.get("axisymmetric") is not True
                  and geometry.get("length_unit") == "m" and type(count) is int and count > 0
                  and isinstance(bbox, list) and len(bbox) == 6 and all(flow.is_finite_number(x) for x in bbox)
                  and all(bbox[i+1] > bbox[i] for i in (0, 2, 4)), "三维米制几何范围证据不可用。")
    flow._require(physics.get("type") == "LaminarFlow" and physics.get("enabled") is True
                  and stationary_participation(inventory, physics) is True,
                  "仅验证明确参与单一定常研究的 LaminarFlow。")
    features = [f for f in physics.get("features", []) if f.get("enabled") is not False]
    fluids = [f for f in features if f.get("type") == "FluidProperties"]
    selected = ids(fluids[0].get("selected_entity_ids")) if len(fluids) == 1 else None
    flow._require(selected is not None and len(selected) == 1 and fluids[0].get("enabled") is True
                  and fluids[0].get("selection_dimensions") == [3], "需要明确选择单个三维流体域。")
    domain_count = geometry.get("domain_count")
    flow._require(type(domain_count) is int and all(d <= domain_count for d in selected), "流体域编号超出几何范围。")
    candidates, uncertain = [], False
    for material in component.get("materials", []):
        if material.get("enabled") is False:
            continue
        domains = ids(material.get("domain_ids"))
        uncertain |= domains is None or material.get("enabled") is not True
        if domains is not None and domains & selected:
            candidates.append(material)
    params = fluids[0].get("parameters", {})
    binding = (not uncertain and len(candidates) == 1 and fluids[0].get("read_status") != "unread"
               and fluids[0].get("child_feature_count") == 0 and params.get("Constitutiverelation") == "Newtonian"
               and params.get("rho_mat") == "from_mat" and params.get("mu_mat") == "from_mat")
    missing = lambda unit: {"expression": "", "unit": unit, "status": "unresolved", "value": None}
    material = {key: flow._legacy_evaluation(candidates[0][key]) if binding and key in candidates[0] else missing(unit)
                for key, unit in (("density", "kg/m^3"), ("dynamic_viscosity", "Pa*s"))}
    boundaries, complete = [], True
    valid_ids = set(range(1, count+1))
    for feature in features:
        kind = feature.get("type")
        if kind in {"FluidProperties", "init"}:
            complete &= feature.get("enabled") is True and feature.get("read_status") != "unread" and feature.get("child_feature_count") == 0
            continue
        role = flow.ROLES.get(kind, "unknown")
        effective, declared = ids(feature.get("selected_entity_ids")), ids(feature.get("declared_entity_ids"))
        known = (feature.get("enabled") is True and feature.get("read_status") != "unread"
                 and feature.get("selection_dimensions") == [2] and effective is not None and effective <= valid_ids)
        p = feature.get("parameters", {})
        mode = p.get("BoundaryCondition")
        verified = (known and feature.get("child_feature_count") == 0 and role != "unknown"
                    and mode in {"inlet": {"Velocity"}, "outlet": {"PressureNoViscousStress"}, "wall": {"NoSlip", "Slip"}}.get(role, set())
                    and (role != "inlet" or p.get("ComponentWise") == "NormalInflowVelocity"))
        complete &= verified
        fallback = role == "wall" and not feature.get("named_selection") and declared == valid_ids
        boundaries.append({"feature_tag": feature["tag"], "label": feature.get("label", ""), "feature_type": kind,
                           "type": role, "boundary_ids": sorted(effective) if known else [],
                           "declared_boundary_ids": sorted(declared) if declared is not None and declared <= valid_ids else None,
                           "selection_scope": "fallback" if fallback else "explicit", "selection_known": known,
                           "mode": mode if isinstance(mode, str) else None, "verified_mode": bool(verified),
                           "parameters": {k: flow._legacy_evaluation(v) for k, v in feature.get("evaluated_parameters", {}).items()
                                          if k in {"normal_velocity", "pressure"}}})
    proof = pipe_geometry(geometry, selected)
    result = {"schema_version": "diagnostic-0.3", "profile": PROFILE,
              "source": {"comsol_version": inventory.get("comsol_version", ""), "component_tag": component["tag"],
                         "physics_tag": physics["tag"], "study_tag": next(s["study_tag"] for s in inventory["studies"] if s["enabled"])},
              "geometry": {"bounding_box_m": bbox, "boundary_count": count, "fluid_domain_ids": sorted(selected),
                           "pipe_diameter_m": proof["diameter_m"] if proof else None,
                           "end_face_ids": proof["end_face_ids"] if proof else None,
                           "wall_face_ids": proof["wall_face_ids"] if proof else None},
              "material": material, "material_binding_verified": bool(binding), "boundary_inventory_complete": bool(complete),
              "boundaries": sorted(boundaries, key=lambda b: b["feature_tag"])}
    flow.validate(result)
    return result


def run_instance(inventory, component_index, physics_index, blockers=(), *, reynolds_warning=2000.0, **options):
    base = f"/components/{component_index}"
    pointer = f"{base}/physics/{physics_index}"
    refs = [pointer, base + "/geometries", base + "/materials", "/studies"]
    rules, findings = make_rules(RULES, refs), []
    by_code = {r["rule_id"]: r for r in rules}
    try:
        model = normalize(inventory, component_index, physics_index)
    except (flow.UnsupportedModel, KeyError, flow.ValidationError, ValueError) as error:
        for rule in rules:
            rule["reason"] = str(error)
        result = finish(rules, findings, refs)
        result["reason"] = str(error)
        return result
    if not flow.is_finite_number(reynolds_warning) or reynolds_warning <= 0:
        raise ValueError("Reynolds warning threshold must be finite and positive")
    geometry, boundaries = model["geometry"], model["boundaries"]
    complete, binding = model["boundary_inventory_complete"], model["material_binding_verified"]
    material = model["material"]
    resolved = all(v["status"] == "resolved" for v in material.values())
    checked(by_code["EVALUATION_UNAVAILABLE"], "已检查所用标量的记录求值状态；缺失绑定不冒充材料已验证。")
    if binding:
        if resolved or any(v["status"] == "resolved" and v["value"] <= 0 for v in material.values()):
            checked(by_code["INVALID_MATERIAL_PARAMETER"])
        for key, value in material.items():
            if value["status"] != "resolved":
                findings.append(finding("EVALUATION_UNAVAILABLE", "流体材料常数无法求值；依赖此值的规则跳过。", refs, evidence={"quantity": key}))
        if any(v["status"] == "resolved" and v["value"] <= 0 for v in material.values()):
            findings.append(finding("INVALID_MATERIAL_PARAMETER", "已验证牛顿流体的密度或动力黏度非正；核对材料及单位。", refs,
                                    severity="Critical", evidence={k: v["value"] for k, v in material.items()}))
    if not blockers:
        ends, walls = ids(geometry["end_face_ids"]), ids(geometry["wall_face_ids"])
        geometric = ends is not None and walls is not None
        open_pipe = geometric and complete and any(b["type"] in {"inlet", "outlet"} for b in boundaries)
        if open_pipe:
            for role in ("inlet", "outlet"):
                code = "MISSING_" + role.upper()
                checked(by_code[code])
                nodes = [b for b in boundaries if b["type"] == role]
                if not any(b["boundary_ids"] for b in nodes):
                    findings.append(finding(code, "已验证开口三维圆管缺少有效" + ("入口。" if role == "inlet" else "出口。"), refs,
                                            severity="Critical", tags=[b["feature_tag"] for b in nodes], evidence={"required_role": role}))
        if all(b["selection_known"] for b in boundaries):
            checked(by_code["EMPTY_BOUNDARY_SELECTION"])
            for b in boundaries:
                if not b["boundary_ids"] and b["selection_scope"] != "fallback":
                    findings.append(finding("EMPTY_BOUNDARY_SELECTION", "启用边界的有效面选择为空；核对选择与覆盖。", refs, tags=[b["feature_tag"]]))
        declared_known = complete and all(b["declared_boundary_ids"] is not None for b in boundaries)
        if declared_known:
            checked(by_code["BC_SELECTION_OVERLAP"])
            for left, right in itertools.combinations(boundaries, 2):
                overlap = set(left["declared_boundary_ids"]) & set(right["declared_boundary_ids"])
                if overlap and left["type"] != right["type"] and "fallback" not in {left["selection_scope"], right["selection_scope"]}:
                    findings.append(finding("BC_SELECTION_OVERLAP", "不同流动角色声明相同面；核对节点优先级及有效选择。", refs,
                                            tags=[left["feature_tag"], right["feature_tag"]], boundaries=overlap))
        face_consistent = open_pipe and declared_known
        if face_consistent:
            checked(by_code["FLOW_FACE_SELECTION_INCONSISTENT"])
            for b in boundaries:
                selected = set(b["boundary_ids"]) | (set(b["declared_boundary_ids"]) if b["selection_scope"] == "explicit" else set())
                expected = (walls | ends if b["selection_scope"] == "fallback" else walls) if b["type"] == "wall" else ends
                bad = selected - expected
                if bad:
                    face_consistent = False
                    findings.append(finding("FLOW_FACE_SELECTION_INCONSISTENT", "流动角色与已验证圆管端面/侧面不一致；核对面选择。", refs,
                                            tags=[b["feature_tag"]], boundaries=bad, evidence={"role": b["type"], "expected_face_ids": sorted(expected)}))
        no_slip = (geometric and not any(b["type"] == "wall" and b["boundary_ids"] and b["mode"] != "NoSlip" for b in boundaries)
                   and set().union(*(set(b["boundary_ids"]) for b in boundaries if b["type"] == "wall" and b["mode"] == "NoSlip")) == walls)
        inlet_faces = set().union(*(set(b["boundary_ids"]) for b in boundaries if b["type"] == "inlet"))
        outlet_faces = set().union(*(set(b["boundary_ids"]) for b in boundaries if b["type"] == "outlet"))
        paired_ports = (geometric and len(inlet_faces) == len(outlet_faces) == 1 and inlet_faces.isdisjoint(outlet_faces)
                        and inlet_faces | outlet_faces == ends and all(len(b["boundary_ids"]) == 1 for b in boundaries if b["type"] in {"inlet", "outlet"}))
        positive_material = resolved and all(v["value"] > 0 for v in material.values())
        cases = {code: [] for code in ("BOUNDARY_PARAMETER_EVALUATION", "INLET_DIRECTION", "REYNOLDS_RISK")}
        for b in boundaries:
            if b["type"] not in {"inlet", "outlet"} or not b["boundary_ids"]:
                continue
            key = "normal_velocity" if b["type"] == "inlet" else "pressure"
            value = b["parameters"].get(key, {})
            ok = complete and b["verified_mode"] and value.get("status") == "resolved"
            reynolds, error = None, None
            re_ok = ok and open_pipe and face_consistent and no_slip and paired_ports and binding and positive_material
            if re_ok and all(v["value"] > 0 for v in material.values()) and b["type"] == "inlet":
                reynolds, error = flow._reynolds_number(material["density"]["value"], value["value"], geometry["pipe_diameter_m"], material["dynamic_viscosity"]["value"])
                re_ok &= error is None
            for code in cases:
                if code != "BOUNDARY_PARAMETER_EVALUATION" and b["type"] != "inlet":
                    continue
                usable = re_ok if code == "REYNOLDS_RISK" else ok
                cases[code].append({"feature_tag": b["feature_tag"], "status": "checked" if usable else "skipped",
                                    "reason": "所需面、模式及数值证据已核验。" if usable else "缺少已验证模式、圆管面/尺度、无滑移壁面或常数证据。", "evidence_refs": refs})
            if ok and b["type"] == "inlet" and value["value"] <= 0:
                findings.append(finding("INLET_DIRECTION", "法向入口速度为零或未指向域内；核对入口符号。", refs, tags=[b["feature_tag"]], boundaries=b["boundary_ids"], evidence={"normal_velocity_m_s": value["value"]}))
            if b["verified_mode"] and value.get("status") != "resolved":
                findings.append(finding("EVALUATION_UNAVAILABLE", "端口参数无法求值；相关数值规则跳过。", refs, tags=[b["feature_tag"]], evidence={"quantity": key}))
            margin = flow.REYNOLDS_THRESHOLD_GUARD_ULPS * math.ulp(float(reynolds_warning))
            if reynolds is not None and reynolds > reynolds_warning and reynolds - reynolds_warning > margin:
                findings.append(finding("REYNOLDS_RISK", "按已验证三维圆管直径计算的名义 Reynolds 数超过筛查阈值；核对层流假设。", refs,
                                        tags=[b["feature_tag"]], boundaries=b["boundary_ids"], evidence={"reynolds_diameter_based": reynolds, "pipe_diameter_m": geometry["pipe_diameter_m"], "threshold": reynolds_warning, "numerical_comparison_margin": margin}))
        for code, values in cases.items():
            by_code[code]["cases"] = values
            if complete and all(c["status"] == "checked" for c in values) and (code != "REYNOLDS_RISK" or open_pipe and face_consistent and no_slip and paired_ports and binding and positive_material):
                checked(by_code[code])
    else:
        for code, group, _ in RULES:
            if group not in {"material", "evaluation"}:
                by_code[code]["reason"] = "未知或未支持耦合可能改变流动语义；依赖规则跳过。"
                by_code[code]["dependencies"].append("coupling_scope_and_semantics")
                by_code[code]["evidence_refs"] += list(blockers)
    result = finish(rules, findings, refs)
    result.update(model=model, numeric_policy={"reynolds_threshold_guard_ulps": flow.REYNOLDS_THRESHOLD_GUARD_ULPS},
                  reason="三维流动规则按实际流体域与面证据执行；未验证项见规则覆盖。")
    return result
