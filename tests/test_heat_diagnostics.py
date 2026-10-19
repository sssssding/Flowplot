"""Unit counterexamples, distinct from the real COMSOL integration evidence."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from flowpilot.diagnostic_modules import heat


def value(number):
    return {"status": "resolved", "value": number, "expression": str(number), "unit": "SI"}


def inventory():
    def node(tag, kind, selected, dimension, **parameters):
        return {"tag": tag, "type": kind, "enabled": True, "selection_dimensions": [dimension],
                "selected_entity_ids": selected, "declared_entity_ids": selected.copy(),
                "whole_geometry_selection": False, "child_feature_count": 0, "parameters": parameters}
    return {"schema_version": "inventory-0.2", "studies": [{"type": "Stationary", "enabled": True}],
            "components": [{"tag": "comp1", "geometries": [{"tag": "geom1", "dimension": 2}],
                            "materials": [{"tag": "mat1", "enabled": True, "domain_ids": [1],
                                           "density": value(1000), "heat_capacity": value(4200), "thermal_conductivity": value(.6)}],
                            "physics": [{"tag": "ht", "type": "HeatTransfer", "enabled": True, "study_active": True,
                                         "heat_evidence": {"read_status": "read", "domain_ids": [1]},
                                         "features": [node("solid1", "SolidHeatTransferModel", [1], 2, rho_mat="from_mat", Cp_mat="from_mat", k_mat="from_mat"),
                                                      node("temp1", "TemperatureBoundary", [1], 1),
                                                      node("flux1", "HeatFluxBoundary", [2], 1, HeatFluxType="GeneralInwardHeatFlux")]}],
                            "multiphysics": []}]}


class HeatDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.data = inventory()
        self.physics = self.data["components"][0]["physics"][0]
        self.material = self.data["components"][0]["materials"][0]

    def run_rules(self, blockers=()):
        return heat.run_instance(self.data, 0, 0, blockers)

    def codes(self, result=None):
        return {f["code"] for f in (result or self.run_rules())["findings"]}

    def rule(self, code):
        return next(r for r in self.run_rules()["rules"] if r["rule_id"] == code)

    def test_normal_controlled_heat_evidence(self):
        self.assertEqual(self.run_rules()["status"], "checked")
        self.assertEqual(self.codes(), set())

    def test_each_nonpositive_constant(self):
        for key in ("density", "heat_capacity", "thermal_conductivity"):
            with self.subTest(key=key):
                self.material[key]["value"] = 0
                self.assertIn("HEAT_INVALID_MATERIAL_PARAMETER", self.codes())
                self.material[key]["value"] = 1

    def test_unresolved_temperature_expression_is_coverage_gap(self):
        self.material["thermal_conductivity"].update(status="unresolved", expression="k(T)", value=None)
        self.assertNotIn("HEAT_INVALID_MATERIAL_PARAMETER", self.codes())
        self.assertEqual(self.rule("HEAT_INVALID_MATERIAL_PARAMETER")["status"], "skipped")

    def test_missing_material_selection_does_not_infer_uncovered(self):
        self.material.pop("domain_ids")
        self.assertEqual(self.codes(), set())
        self.assertEqual(self.rule("HEAT_MATERIAL_COVERAGE")["status"], "skipped")

    def test_missing_and_overlapping_materials(self):
        self.material["domain_ids"] = []
        self.assertIn("HEAT_MATERIAL_COVERAGE", self.codes())
        self.material["domain_ids"] = [1]
        duplicate = copy.deepcopy(self.material)
        duplicate["tag"] = "mat2"
        self.data["components"][0]["materials"].append(duplicate)
        self.assertIn("HEAT_MATERIAL_COVERAGE", self.codes())

    def test_unused_and_disabled_materials_do_not_contribute(self):
        duplicate = copy.deepcopy(self.material)
        duplicate.update(tag="unused", domain_ids=[2])
        duplicate["density"]["value"] = -1
        self.data["components"][0]["materials"].append(duplicate)
        self.assertEqual(self.codes(), set())
        duplicate.update(domain_ids=[1], enabled=False)
        self.assertEqual(self.codes(), set())

    def test_user_material_override_skips_material_binding(self):
        self.physics["features"][0]["parameters"]["k_mat"] = "userdef"
        self.material["thermal_conductivity"]["value"] = -1
        self.assertEqual(self.codes(), set())
        self.assertEqual(self.rule("HEAT_INVALID_MATERIAL_PARAMETER")["status"], "skipped")

    def test_empty_enabled_boundary(self):
        self.physics["features"][1]["selected_entity_ids"] = []
        self.assertIn("HEAT_EMPTY_BOUNDARY_SELECTION", self.codes())
        self.physics["features"][1]["enabled"] = False
        self.assertNotIn("HEAT_EMPTY_BOUNDARY_SELECTION", self.codes())

    def test_missing_effective_boundary_selection_skips(self):
        self.physics["features"][1].pop("selected_entity_ids")
        self.assertNotIn("HEAT_EMPTY_BOUNDARY_SELECTION", self.codes())
        self.assertEqual(self.rule("HEAT_EMPTY_BOUNDARY_SELECTION")["status"], "skipped")

    def test_overlap_uses_explicit_declarations(self):
        self.physics["features"][2]["declared_entity_ids"] = [1]
        self.assertIn("HEAT_BC_SELECTION_OVERLAP", self.codes())
        self.physics["features"][2]["whole_geometry_selection"] = True
        self.assertNotIn("HEAT_BC_SELECTION_OVERLAP", self.codes())

    def test_unknown_heat_flux_mode_skips_overlap(self):
        self.physics["features"][2]["parameters"]["HeatFluxType"] = "ConvectiveHeatFlux"
        self.assertEqual(self.rule("HEAT_BC_SELECTION_OVERLAP")["status"], "skipped")

    def test_domain_model_missing_coverage_and_unknown_selection(self):
        self.physics["features"][0]["selected_entity_ids"] = []
        self.assertIn("HEAT_DOMAIN_CONFIGURATION", self.codes())
        self.physics["features"][0].pop("selected_entity_ids")
        self.assertEqual(self.rule("HEAT_DOMAIN_CONFIGURATION")["status"], "skipped")

    def test_solid_thermal_domain_conflicts_with_active_flow_domain(self):
        self.data["components"][0]["physics"].append({"tag": "spf", "type": "LaminarFlow", "enabled": True,
            "features": [{"tag": "fp1", "type": "FluidProperties", "enabled": True, "selection_dimensions": [2], "selected_entity_ids": [1]}]})
        self.assertIn("HEAT_DOMAIN_CONFIGURATION", self.codes())

    def test_blockers_preserve_independent_material_findings(self):
        self.material["density"]["value"] = -1
        self.physics["features"][1]["selected_entity_ids"] = []
        result = self.run_rules(["/multiphysics/0"])
        self.assertEqual(self.codes(result), {"HEAT_INVALID_MATERIAL_PARAMETER"})

    def test_unsupported_geometry_and_nested_node_skip(self):
        self.data["components"][0]["geometries"][0]["dimension"] = 3
        self.assertTrue(all(r["status"] == "skipped" for r in self.run_rules()["rules"]))
        self.data["components"][0]["geometries"][0]["dimension"] = 2
        self.physics["features"][1]["child_feature_count"] = 1
        self.assertEqual(self.codes(), set())

    def test_findings_have_actionable_traceable_evidence(self):
        self.material["heat_capacity"]["value"] = -1
        result = self.run_rules()
        f = result["findings"][0]
        self.assertTrue(f["suggestion"])
        self.assertEqual(f["feature_tags"], ["mat1"])
        self.assertTrue(f["evidence_refs"])

    def test_tensor_constant_and_unread_node_do_not_pass_as_scalar_evidence(self):
        self.material["thermal_conductivity"]["value"] = [-1, 0, 0]
        self.assertNotIn("HEAT_INVALID_MATERIAL_PARAMETER", self.codes())
        self.assertEqual(self.rule("HEAT_INVALID_MATERIAL_PARAMETER")["status"], "skipped")
        self.physics["features"][1]["read_status"] = "unread"
        self.assertEqual(self.rule("HEAT_EMPTY_BOUNDARY_SELECTION")["status"], "skipped")

    def test_transient_does_not_suppress_independent_domain_selection(self):
        self.data["studies"][0]["type"] = "Transient"
        self.assertEqual(self.rule("HEAT_DOMAIN_CONFIGURATION")["status"], "checked")
        self.assertEqual(self.rule("HEAT_ADVECTION_SOURCE")["status"], "skipped")

    def test_real_default_disabled_opacity_child_is_inert_only_with_read_evidence(self):
        node = self.physics["features"][0]
        child = {"tag": "opac1", "type": "Opacity", "enabled": False, "read_status": "read", "children": []}
        node.update(child_feature_count=1, children=[child])
        self.assertEqual(self.run_rules()["status"], "checked")
        child["enabled"] = True
        self.assertEqual(self.rule("HEAT_DOMAIN_CONFIGURATION")["status"], "skipped")
        child.update(enabled=False, read_status="unread")
        self.assertEqual(self.rule("HEAT_DOMAIN_CONFIGURATION")["status"], "skipped")
        child["read_status"] = "read"
        node["children"] = []
        self.assertEqual(self.rule("HEAT_DOMAIN_CONFIGURATION")["status"], "skipped")


class MultiDomainFlowScopeTest(unittest.TestCase):
    def setUp(self):
        import json
        # Tests below use the original planar fixture, with only explicit
        # topology facts needed for the conservative independent adapter.
        self.data = json.loads((Path(__file__).resolve().parents[1] / "data/fixtures/cases/baseline.json").read_text(encoding="utf-8-sig"))
        self.component = self.data["components"][0]
        self.component["geometries"][0].update(axisymmetric=True, domain_count=2)
        material = copy.deepcopy(self.component["materials"][0])
        material.update(tag="wall_material", domain_ids=[2])
        material["density"]["value"] = -1
        self.component["materials"].append(material)

    def run_rules(self, blockers=()):
        from flowpilot.diagnostic_modules import flow_scope
        return flow_scope.run_instance(self.data, 0, 0, blockers)

    def test_multi_domain_preserves_independent_results_and_skips_scale(self):
        result = self.run_rules()
        self.assertNotIn("model", result)
        self.assertEqual(result["findings"], [])
        self.assertEqual(next(r for r in result["rules"] if r["rule_id"] == "REYNOLDS_RISK")["status"], "skipped")
        self.component["materials"][0]["density"]["value"] = -1
        self.assertIn("INVALID_MATERIAL_PARAMETER", {f["code"] for f in self.run_rules()["findings"]})

    def test_inlet_sign_keeps_real_entity_ids(self):
        inlet = next(f for f in self.component["physics"][0]["features"] if f["type"] == "Inlet")
        inlet["evaluated_parameters"]["normal_velocity"]["value"] = -1
        inlet.update(selected_entity_ids=[12], declared_entity_ids=[12])
        result = self.run_rules()
        f = next(f for f in result["findings"] if f["code"] == "INLET_DIRECTION")
        self.assertEqual(f["boundary_ids"], [12])
        self.assertNotIn("INLET_DIRECTION", {f["code"] for f in self.run_rules(["/multiphysics/0"])["findings"]})

    def test_unknown_material_selection_and_boundary_mode_are_skipped(self):
        self.component["materials"][1].pop("domain_ids")
        result = self.run_rules()
        self.assertEqual(next(r for r in result["rules"] if r["rule_id"] == "INVALID_MATERIAL_PARAMETER")["status"], "skipped")
        inlet = next(f for f in self.component["physics"][0]["features"] if f["type"] == "Inlet")
        inlet["parameters"]["BoundaryCondition"] = "MassFlow"
        result = self.run_rules()
        self.assertEqual(next(r for r in result["rules"] if r["rule_id"] == "INLET_DIRECTION")["status"], "skipped")

    def test_empty_and_overlapping_flow_boundary_declarations(self):
        physics = self.component["physics"][0]
        inlet = next(f for f in physics["features"] if f["type"] == "Inlet")
        outlet = next(f for f in physics["features"] if f["type"] == "Outlet")
        inlet["selected_entity_ids"] = []
        self.assertIn("EMPTY_BOUNDARY_SELECTION", {f["code"] for f in self.run_rules()["findings"]})
        inlet["selected_entity_ids"] = inlet["declared_entity_ids"]
        outlet["declared_entity_ids"] = inlet["declared_entity_ids"]
        self.assertIn("BC_SELECTION_OVERLAP", {f["code"] for f in self.run_rules()["findings"]})

    def test_flow_domain_dimension_must_be_explicit(self):
        fluid = next(f for f in self.component["physics"][0]["features"] if f["type"] == "FluidProperties")
        fluid["selection_dimensions"] = [1]
        result = self.run_rules()
        self.assertTrue(all(r["status"] == "skipped" for r in result["rules"]))


if __name__ == "__main__":
    unittest.main()
