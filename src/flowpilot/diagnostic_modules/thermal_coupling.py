"""Static, component-scoped NonIsothermalFlow reference/selection checks."""
from __future__ import annotations

from .heat import HEAT_TYPES, checked, finding, finish, ids, make_rules, prop, stationary_participation, geometry_entities
from .flow import is_finite_number

MODULE_ID = "thermal_coupling"
RULES = (
    ("COUPLING_REFERENCE_MISMATCH", "references", ("read_coupling_references", "component_physics_instances")),
    ("COUPLING_SELECTION_MISMATCH", "selection", ("effective_coupling_domains", "referenced_physics_domains")),
    ("COUPLING_PARTICIPATION_MISMATCH", "study", ("referenced_physics_enablement", "stationary_participation")),
)


def run_coupling(inventory, component_index, coupling_index, blockers=(), **options):
    component = inventory["components"][component_index]
    coupling = component["multiphysics"][coupling_index]
    pointer = f"/components/{component_index}/multiphysics/{coupling_index}"
    refs = [pointer, f"/components/{component_index}/physics", "/studies"]
    rules = make_rules(RULES, refs)
    findings = []
    def result():
        report = finish(rules, findings, refs)
        report["semantics_verified"] = False
        return report
    if (coupling.get("type") != "NonIsothermalFlow" or coupling.get("enabled") is not True
            or coupling.get("read_status") not in {"read", "partial"} or blockers):
        return result()
    properties = coupling.get("properties", {})
    fluid_tag, heat_tag = prop(properties, "Fluid_physics"), prop(properties, "Heat_physics")
    if not isinstance(fluid_tag, str) or not isinstance(heat_tag, str):
        return result()
    checked(rules[0])
    by_tag = {p["tag"]: p for p in component.get("physics", [])}
    fluid, heat = by_tag.get(fluid_tag), by_tag.get(heat_tag)
    if not fluid or not heat:
        findings.append(finding("COUPLING_REFERENCE_MISMATCH", "流热耦合引用缺失或不匹配当前已核验的层流/传热接口；核对接口选择。", [pointer],
                                evidence={"fluid_physics": fluid_tag, "heat_physics": heat_tag}))
        return result()
    if fluid.get("type") != "LaminarFlow" or heat.get("type") not in HEAT_TYPES:
        rules[0].update(status="skipped", reason="引用存在，但接口类型超出已核验层流/传热组合；不作为引用错误。")
        return result()
    participation = [stationary_participation(inventory, p) for p in (fluid, heat)]
    if all(type(p.get("enabled")) is bool for p in (fluid, heat)):
        if any(p.get("enabled") is False for p in (fluid, heat)):
            checked(rules[2])
            findings.append(finding("COUPLING_PARTICIPATION_MISMATCH", "已启用流热耦合引用已禁用接口；核对耦合与接口启用状态。", refs,
                                    evidence={"fluid_enabled": fluid["enabled"], "heat_enabled": heat["enabled"]}))
        elif all(p is True for p in participation):
            checked(rules[2])
        else:
            # A sequential solution can deliberately activate one interface at a
            # time. Never infer an error from a single legacy study_active flag.
            rules[2].update(status="skipped", reason="未确认两接口共同参与唯一启用稳态步骤；分步研究或缺失证据不判为错误。")
    geometries = component.get("geometries", [])
    dimension = geometries[0].get("dimension") if len(geometries) == 1 else None
    try:
        geometry_domains, _ = geometry_entities(geometries[0]) if dimension in (2, 3) else (set(), set())
    except (ValueError, TypeError, KeyError):
        return result()
    domain_dimension = dimension in (2, 3)
    selected = ids(coupling.get("selected_entity_ids")) if domain_dimension and coupling.get("selection_dimensions") == [dimension] else None
    heat_nodes = [f for f in heat.get("features", []) if f.get("type") == "FluidHeatTransferModel" and f.get("enabled") is True]
    heat_selections = [ids(f.get("selected_entity_ids")) if f.get("selection_dimensions") == [dimension] else None for f in heat_nodes]
    heat_domains = (set().union(*heat_selections) if heat_selections and all(s is not None for s in heat_selections) else None)
    fluid_domains = None
    fluid_nodes = [f for f in fluid.get("features", []) if f.get("type") == "FluidProperties" and f.get("enabled") is True]
    selections = [ids(f.get("selected_entity_ids")) if f.get("selection_dimensions") == [dimension] else None for f in fluid_nodes]
    if selections and all(s is not None for s in selections):
        fluid_domains = set().union(*selections)
    if dimension == 3 and any(selection is None or not selection <= geometry_domains for selection in (selected, heat_domains, fluid_domains)):
        return result()
    if selected is not None and heat_domains is not None and fluid_domains is not None:
        checked(rules[1])
        common = heat_domains & fluid_domains
        if not selected or selected - common:
            findings.append(finding("COUPLING_SELECTION_MISMATCH", "流热耦合有效域为空或超出两接口共有域；核对流体域与耦合选择。", refs,
                                    evidence={"coupling_domain_ids": sorted(selected), "common_domain_ids": sorted(common),
                                              "fluid_domain_ids": sorted(fluid_domains), "heat_domain_ids": sorted(heat_domains)}))
        elif selected != common:
            rules[1]["reason"] = "局部耦合，未验证未耦合域语义；选域本身未见越界。"
    report = result()
    defaults = {"SpecifyDensity": "FromHeatTransferInterface", "SpecifyTref": "FromHeatTransferInterface",
                "BoussinesqApproximation": "0", "includeViscousDissipation": "1",
                "includeIrreversibleLosses": "1", "includeKineticEnergy": "0",
                "Fluid_TurbulenceModelProperty_TurbulenceModelType": "None",
                "Fluid_PhysicalModelProperty_Compressibility": "Incompressible"}
    studies = [s for s in inventory.get("studies", []) if s.get("enabled") is True]
    steady = (len(studies) == 1 and studies[0].get("type") == "Stationary"
              and prop(properties, "StudyStep") == f"{studies[0].get('study_tag')}/{studies[0].get('feature_tag')}")
    materials = [m for m in component.get("materials", []) if m.get("enabled") is True and ids(m.get("domain_ids")) is not None
                 and selected is not None and ids(m["domain_ids"]) & selected]
    constants = bool(selected) and all(
        len([m for m in materials if d in ids(m["domain_ids"])]) == 1 for d in selected)
    constants = constants and not any(m.get("enabled") is None or
        m.get("enabled") is True and ids(m.get("domain_ids")) is None for m in component.get("materials", []))
    constants = constants and all(all(m.get(key, {}).get("status") == "resolved" and
        is_finite_number(m[key].get("value")) and m[key]["value"] > 0
        for key in ("density", "dynamic_viscosity", "heat_capacity", "thermal_conductivity")) for m in materials)
    binding = bool(heat_nodes) and all(all(f.get("parameters", {}).get(key) == "from_mat"
        for key in ("rho_mat", "Cp_mat", "k_mat")) and f.get("read_status") != "unread" for f in heat_nodes)
    report["semantics_verified"] = bool(report["status"] == "checked" and not findings
                                        and selected and heat_domains is not None and fluid_domains is not None
                                        and selected == heat_domains == fluid_domains and steady
                                        and constants and binding
                                        and all(prop(properties, key) == value for key, value in defaults.items()))
    if not report["semantics_verified"] and report["status"] == "checked":
        report["reason"] = "已核验引用/选域，但耦合模式或整体作用范围尚未核验，流动依赖规则保留跳过。"
    return report
