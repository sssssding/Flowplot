"""Evidence-scoped checks for the verified stationary heat-transfer subset.

No COMSOL expression is evaluated here. Missing evidence is coverage, not a
physical error, and default boundary declarations are not treated as conflicts.
"""
from __future__ import annotations

import itertools

from .flow import is_finite_number

MODULE_ID = "heat"
HEAT_TYPES = {"HeatTransferInFluids", "HeatTransfer"}
DOMAIN_TYPES = {"FluidHeatTransferModel": "fluid", "SolidHeatTransferModel": "solid"}
BOUNDARY_TYPES = {"TemperatureBoundary", "HeatFluxBoundary"}
RULES = (
    ("HEAT_INVALID_MATERIAL_PARAMETER", "material", ("effective_heat_material_binding", "evaluated_heat_constants")),
    ("HEAT_MATERIAL_COVERAGE", "material", ("effective_heat_domains", "material_domain_selections")),
    ("HEAT_EMPTY_BOUNDARY_SELECTION", "boundaries", ("enabled_heat_nodes", "effective_boundary_selections")),
    ("HEAT_BC_SELECTION_OVERLAP", "boundaries", ("verified_heat_boundary_modes", "declared_boundary_selections")),
    ("HEAT_DOMAIN_CONFIGURATION", "domains", ("effective_heat_domains", "effective_domain_model_selections")),
    ("HEAT_ADVECTION_SOURCE", "coupling", ("heat_velocity_source", "stationary_participation")),
)


def ids(value):
    return set(value) if isinstance(value, list) and all(type(v) is int and v > 0 for v in value) else None


def prop(properties, key):
    item = properties.get(key, {})
    return item.get("value") if item.get("status") == "read" else None


def stationary_participation(inventory, physics):
    """Resolve the one enabled stationary step without trusting a first-step flag.

    Thermal inventories carry step-specific evidence. Legacy flags are safe only
    when there is exactly one recorded step, including disabled steps.
    """
    studies = inventory.get("studies", [])
    if not studies or any(type(s.get("enabled")) is not bool for s in studies):
        return None
    active = [s for s in studies if s["enabled"]]
    if len(active) != 1 or active[0].get("type") != "Stationary":
        return None
    step = active[0]
    evidence = physics.get("heat_evidence", {})
    if "study_participation" in evidence:
        participation = evidence["study_participation"]
        if (not isinstance(participation, list)
                or not all(isinstance(step.get(k), str) and step[k] for k in ("study_tag", "feature_tag"))):
            return None
        matches = [p for p in participation if isinstance(p, dict)
                   and all(p.get(k) == step[k] for k in ("study_tag", "feature_tag"))]
        if len(matches) != 1:
            return None
        selected = matches[0]
        if (selected.get("enabled") is not True or selected.get("type") != "Stationary"
                or selected.get("read_status") == "unread" or type(selected.get("active")) is not bool):
            return None
        return selected["active"]
    legacy = physics.get("study_active")
    return legacy if len(studies) == 1 and type(legacy) is bool else None


def supported_children(feature):
    """Only explicitly read, disabled child trees are inert in this subset."""
    count = feature.get("child_feature_count")
    if count == 0:
        return feature.get("children", []) == []
    children = feature.get("children")
    if type(count) is not int or not isinstance(children, list) or len(children) != count:
        return False
    def disabled_tree(child):
        descendants = child.get("children")
        return (child.get("read_status") == "read" and child.get("enabled") is False
                and isinstance(descendants, list) and all(disabled_tree(c) for c in descendants))
    return all(disabled_tree(c) for c in children)


def finding(code, text, refs, *, tags=(), boundaries=(), evidence=None, severity="Warning", suggestion=None):
    return {"code": code, "severity": severity, "explanation": text,
            "feature_tags": sorted(set(tags)), "boundary_ids": sorted(set(boundaries)),
            "evidence": evidence or {}, "evidence_refs": list(dict.fromkeys(refs)),
            "suggestion": suggestion or text}


def finish(rules, findings, refs):
    for rule in rules:
        rule["evidence_refs"] = list(dict.fromkeys(rule["evidence_refs"]))
        for case in rule.get("cases", []):
            case["evidence_refs"] = list(dict.fromkeys(case["evidence_refs"]))
    complete = all(r["status"] == "checked" for r in rules)
    return {"status": "checked" if complete else "skipped",
            "reason": "已检查受控稳态传热证据。" if complete else "仅检查证据充分的传热/流热关联；其余见规则覆盖。",
            "rules": rules, "findings": sorted(findings, key=lambda f: (f["code"], f["feature_tags"])),
            "evidence_refs": refs}


def make_rules(spec, refs):
    return [{"rule_id": code, "status": "skipped", "reason": "缺少已核验的 API 证据或不适用。",
             "dependencies": list(deps), "evidence_refs": list(refs)} for code, _, deps in spec]


def checked(rule, reason="所需证据可用，规则已执行。"):
    rule.update(status="checked", reason=reason)


def geometry_entities(geometry):
    """Require final 3D topology and positive API measures, never just ndim=3."""
    if geometry.get("dimension") == 2:
        return None, None
    evidence = geometry.get("three_dimensional_evidence", {})
    if geometry.get("dimension") != 3 or evidence.get("read_status") != "read":
        raise ValueError("Unverified 3D geometry")
    domains, faces = evidence.get("domains", []), evidence.get("boundaries", [])
    domain_ids = ids([d.get("domain_id") for d in domains])
    face_ids = ids([f.get("boundary_id") for f in faces])
    if (not domain_ids or not face_ids or len(domain_ids) != len(domains) or len(face_ids) != len(faces)
            or geometry.get("domain_count") != len(domain_ids) or geometry.get("boundary_count") != len(face_ids)):
        raise ValueError("Missing final topology")
    for domain in domains:
        selection = ids(domain.get("boundary_ids"))
        if not selection or not selection <= face_ids or not is_finite_number(domain.get("volume")) or domain["volume"] <= 0:
            raise ValueError("Unverified 3D domain")
    for face in faces:
        adjacent = ids(face.get("domain_ids"))
        if not adjacent or not adjacent <= domain_ids or not is_finite_number(face.get("area")) or face["area"] <= 0:
            raise ValueError("Unverified 3D face")
        if any(face["boundary_id"] not in next(d["boundary_ids"] for d in domains if d["domain_id"] == domain) for domain in adjacent):
            raise ValueError("Inconsistent 3D adjacency")
    for domain in domains:
        if any(domain["domain_id"] not in next(f["domain_ids"] for f in faces if f["boundary_id"] == face) for face in domain["boundary_ids"]):
            raise ValueError("Inconsistent 3D domain adjacency")
    return domain_ids, face_ids


def run_instance(inventory, component_index, physics_index, blockers, **options):
    component = inventory["components"][component_index]
    physics = component["physics"][physics_index]
    base = f"/components/{component_index}"
    pointer = f"{base}/physics/{physics_index}"
    refs = [pointer, base + "/materials", base + "/geometries", "/studies"]
    rules = make_rules(RULES, refs)
    by_code = {r["rule_id"]: r for r in rules}
    findings = []
    geometries = component.get("geometries", [])
    he = physics.get("heat_evidence", {})
    if (physics.get("type") not in HEAT_TYPES or physics.get("enabled") is not True
            or len(geometries) != 1 or geometries[0].get("dimension") not in (2, 3)
            or he.get("read_status") not in {"read", "partial"}):
        return finish(rules, findings, refs)
    dimension = geometries[0]["dimension"]
    try:
        geometry_domains, geometry_faces = geometry_entities(geometries[0])
    except (ValueError, TypeError, KeyError):
        return finish(rules, findings, refs)
    domains = ids(he.get("domain_ids"))
    features = physics.get("features", [])
    if dimension == 3:
        if domains is None or not domains <= geometry_domains:
            return finish(rules, findings, refs)
        for feature in features:
            if feature.get("enabled") is not True:
                continue
            expected = geometry_domains if feature.get("type") in DOMAIN_TYPES else geometry_faces if feature.get("type") in BOUNDARY_TYPES else None
            if expected is not None and (ids(feature.get("selected_entity_ids")) is None or not ids(feature["selected_entity_ids"]) <= expected):
                return finish(rules, findings, refs)
    active = [(i, f) for i, f in enumerate(features) if f.get("enabled") is True]
    domain_nodes = [(i, f) for i, f in active if f.get("type") in DOMAIN_TYPES]
    boundary_nodes = [(i, f) for i, f in active if f.get("type") in BOUNDARY_TYPES]
    unknown = any(f.get("enabled") is None or f.get("enabled") is True and not supported_children(f)
                  or f.get("enabled") is True and f.get("read_status") == "unread" for f in features)
    unknown |= any(f.get("type") not in set(DOMAIN_TYPES) | BOUNDARY_TYPES |
                   {"init", "ThermalInsulation", "AxialSymmetry", "Continuity"} for _, f in active)
    unknown |= any(f.get("selection_dimensions") != [dimension] for _, f in domain_nodes)
    # The binding must be from material for all three quantities. Overrides and
    # tensor/temperature-dependent laws are left for later verified profiles.
    required = (("density", "rho_mat"), ("heat_capacity", "Cp_mat"), ("thermal_conductivity", "k_mat"))
    binding = bool(domain_nodes) and not unknown and all(
        all(f.get("parameters", {}).get(key) == "from_mat" for _, key in required)
        for _, f in domain_nodes)
    materials = [(i, m) for i, m in enumerate(component.get("materials", [])) if m.get("enabled") is True]
    material_selections = [ids(m.get("domain_ids")) for _, m in materials]
    material_enablement_known = all(m.get("enabled") is not None for m in component.get("materials", []))
    if domains is not None and domains and binding and material_enablement_known and all(s is not None for s in material_selections):
        coverage_rule = by_code["HEAT_MATERIAL_COVERAGE"]
        checked(coverage_rule)
        bad = {d: [m["tag"] for (_, m), selection in zip(materials, material_selections) if d in selection]
               for d in sorted(domains)}
        bad = {d: tags for d, tags in bad.items() if len(tags) != 1}
        if bad:
            findings.append(finding(coverage_rule["rule_id"], "热域缺少唯一可确认的材料覆盖；核对材料域及覆盖优先级。", refs,
                                    evidence={"domain_material_candidates": {str(d): tags for d, tags in bad.items()}}))
        cases = []
        for (mi, material), selection in zip(materials, material_selections):
            used = domains & selection
            if not used or any(d in bad for d in used):
                continue
            ref = f"{base}/materials/{mi}"
            values = {key: material.get(key, {}) for key, _ in required}
            resolved = {key: value for key, value in values.items()
                        if value.get("status") == "resolved" and is_finite_number(value.get("value"))}
            invalid = {key: value["value"] for key, value in resolved.items() if value["value"] <= 0}
            complete = len(resolved) == len(required)
            cases.append({"feature_tag": material["tag"], "status": "checked" if complete or invalid else "skipped",
                          "reason": "已核验正值要求。" if complete or invalid else "存在非恒定、未解析或非标量热参数；不把表达式判为错误。",
                          "evidence_refs": [ref]})
            if invalid:
                findings.append(finding("HEAT_INVALID_MATERIAL_PARAMETER", "已解析的热材料常数非正；核对密度、定压热容和导热率及单位。",
                                        [ref], tags=[material["tag"]], severity="Critical",
                                        evidence={"invalid_parameters": invalid, "domain_ids": sorted(used)}))
        rule = by_code["HEAT_INVALID_MATERIAL_PARAMETER"]
        rule["cases"] = cases
        if cases and all(c["status"] == "checked" for c in cases) and not bad:
            checked(rule)
    if not blockers and not unknown:
        if domains is not None and domain_nodes and all(ids(f.get("selected_entity_ids")) is not None for _, f in domain_nodes):
            checked(by_code["HEAT_DOMAIN_CONFIGURATION"])
            assignments = {d: [f["tag"] for _, f in domain_nodes if d in ids(f["selected_entity_ids"])] for d in domains}
            bad = {d: tags for d, tags in assignments.items() if len(tags) != 1}
            outside = sorted(set().union(*(ids(f["selected_entity_ids"]) for _, f in domain_nodes)) - domains)
            solid_domains = set().union(*(ids(f["selected_entity_ids"]) for _, f in domain_nodes if DOMAIN_TYPES[f["type"]] == "solid"))
            flow_nodes = [f for p in component.get("physics", []) if p.get("type") == "LaminarFlow" and p.get("enabled") is True
                          for f in p.get("features", []) if f.get("type") == "FluidProperties" and f.get("enabled") is True]
            flow_domains = set().union(*(ids(f["selected_entity_ids"]) for f in flow_nodes if ids(f.get("selected_entity_ids")) is not None and f.get("selection_dimensions") == [dimension]))
            solid_flow_overlap = sorted(solid_domains & flow_domains)
            if bad or outside or solid_flow_overlap:
                findings.append(finding("HEAT_DOMAIN_CONFIGURATION", "热域与流体/固体传热模型的有效选择不一致；核对域归属。", refs,
                                        evidence={"domain_model_candidates": {str(d): tags for d, tags in bad.items()},
                                                  "outside_domain_ids": outside, "solid_flow_overlap_domain_ids": solid_flow_overlap}))
        valid_boundary = all(ids(f.get("selected_entity_ids")) is not None and
                             f.get("selection_dimensions") == [dimension - 1] for _, f in boundary_nodes)
        if valid_boundary:
            checked(by_code["HEAT_EMPTY_BOUNDARY_SELECTION"])
            for i, feature in boundary_nodes:
                if not feature["selected_entity_ids"]:
                    findings.append(finding("HEAT_EMPTY_BOUNDARY_SELECTION", "已启用的温度/热流节点有效选择为空；核对选择及被覆盖关系。",
                                            [f"{pointer}/features/{i}"], tags=[feature["tag"]],
                                            evidence={"declared_boundary_ids": feature.get("declared_entity_ids")}))
        # Only explicit Temperature and GeneralInwardHeatFlux declarations are
        # compared. Default insulation and cross-physics boundaries are excluded.
        modes = all(f["type"] == "TemperatureBoundary" or f.get("parameters", {}).get("HeatFluxType") == "GeneralInwardHeatFlux"
                    for _, f in boundary_nodes)
        if valid_boundary and modes and all(ids(f.get("declared_entity_ids")) is not None for _, f in boundary_nodes):
            checked(by_code["HEAT_BC_SELECTION_OVERLAP"])
            for (li, left), (ri, right) in itertools.combinations(boundary_nodes, 2):
                overlap = ids(left["declared_entity_ids"]) & ids(right["declared_entity_ids"])
                if overlap and not left.get("whole_geometry_selection") and not right.get("whole_geometry_selection"):
                    findings.append(finding("HEAT_BC_SELECTION_OVERLAP", "同一热物理场的显式温度/热流声明重叠；核对优先级与实际生效条件。",
                                            [f"{pointer}/features/{li}", f"{pointer}/features/{ri}"],
                                            tags=[left["tag"], right["tag"]], boundaries=overlap,
                                            evidence={"effective_left": left["selected_entity_ids"], "effective_right": right["selected_entity_ids"]}))
        advection = by_code["HEAT_ADVECTION_SOURCE"]
        fluid_nodes = [(i, f) for i, f in domain_nodes if DOMAIN_TYPES[f["type"]] == "fluid"]
        if stationary_participation(inventory, physics) is not True:
            advection["reason"] = "未确认当前唯一启用稳态步骤的传热参与；分步或缺失证据不判为错误。"
        elif not fluid_nodes:
            checked(advection, "无流体热域，无需对流速度关联。")
        else:
            cases = []
            flows = [p for p in component.get("physics", []) if p.get("type") == "LaminarFlow" and p.get("enabled") is True]
            for i, feature in fluid_nodes:
                parameters = feature.get("parameters", {})
                source = parameters.get("u_src")
                ref = f"{pointer}/features/{i}"
                ok, reason = False, "速度来源或分步研究证据未核验；缺少显式耦合本身不构成错误。"
                if source == "userdef" and isinstance(parameters.get("u"), list) and parameters["u"]:
                    ok, reason = True, "已明确给定速度表达式；不要求显式流热耦合，不在 Python 中求值。"
                elif source == f"root.{component['tag']}.u" and len(flows) == 1:
                    flow = flows[0]
                    selections = [ids(f.get("selected_entity_ids")) if f.get("selection_dimensions") == [dimension] else None
                                  for f in flow.get("features", []) if f.get("type") == "FluidProperties" and f.get("enabled") is True]
                    heat_selection = ids(feature.get("selected_entity_ids"))
                    if (selections and all(s is not None for s in selections) and heat_selection is not None
                            and stationary_participation(inventory, flow) is True):
                        ok, reason = True, "已确认同组件流场速度来源、稳态参与及域选择。"
                        flow_domains = set().union(*selections)
                        if heat_selection - flow_domains:
                            findings.append(finding("HEAT_ADVECTION_SOURCE", "流体热域引用的当前流场速度未覆盖该热域；核对速度来源和流体域。", [ref],
                                                    tags=[feature["tag"]], evidence={"velocity_source": source,
                                                    "heat_domain_ids": sorted(heat_selection), "flow_domain_ids": sorted(flow_domains)}))
                cases.append({"feature_tag": feature["tag"], "status": "checked" if ok else "skipped", "reason": reason, "evidence_refs": [ref]})
            advection["cases"] = cases
            if all(c["status"] == "checked" for c in cases):
                checked(advection)
    if blockers:
        for code, group, _ in RULES:
            if group != "material":
                by_code[code]["reason"] = "未知耦合可能改变热语义；依赖规则跳过。"
                by_code[code]["evidence_refs"] += list(blockers)
    return finish(rules, findings, refs)
