import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from flowpilot.diagnostic_modules import heat, thermal_coupling
from test_heat_diagnostics import inventory


def property_value(value):
    return {"status": "read", "value_type": "String", "value": value}


class ThermalCouplingTest(unittest.TestCase):
    def setUp(self):
        self.data = inventory()
        self.component = self.data["components"][0]
        self.ht = self.component["physics"][0]
        self.ht["type"] = "HeatTransferInFluids"
        self.domain = self.ht["features"][0]
        self.domain["type"] = "FluidHeatTransferModel"
        self.domain["parameters"].update(u_src="root.comp1.u", u=["0", "0", "0"])
        self.flow = {"tag": "spf", "type": "LaminarFlow", "enabled": True, "study_active": True,
                     "features": [{"tag": "fp1", "type": "FluidProperties", "enabled": True, "selection_dimensions": [2], "selected_entity_ids": [1]}]}
        self.component["physics"].append(self.flow)
        self.coupling = {"tag": "nitf1", "type": "NonIsothermalFlow", "enabled": True, "read_status": "read",
                         "selection_dimensions": [2], "selected_entity_ids": [1], "properties": {"Fluid_physics": property_value("spf"), "Heat_physics": property_value("ht")}}
        self.component["multiphysics"].append(self.coupling)

    def run_rules(self, blockers=()):
        return thermal_coupling.run_coupling(self.data, 0, 0, blockers)

    def codes(self):
        return {f["code"] for f in self.run_rules()["findings"]}

    def rule(self, code):
        return next(r for r in self.run_rules()["rules"] if r["rule_id"] == code)

    def heat_rule(self):
        result = heat.run_instance(self.data, 0, 0, [])
        return result, next(r for r in result["rules"] if r["rule_id"] == "HEAT_ADVECTION_SOURCE")

    def test_normal_coupling_and_advection(self):
        self.assertEqual(self.run_rules()["status"], "checked")
        self.assertEqual(self.codes(), set())
        self.assertEqual(self.heat_rule()[1]["status"], "checked")

    def test_missing_reference_is_reported(self):
        self.coupling["properties"]["Fluid_physics"] = property_value("missing")
        self.assertEqual(self.codes(), {"COUPLING_REFERENCE_MISMATCH"})

    def test_unread_reference_is_skipped(self):
        self.coupling["properties"]["Fluid_physics"] = {"status": "unread", "reason": "API unavailable"}
        self.assertEqual(self.codes(), set())
        self.assertEqual(self.rule("COUPLING_REFERENCE_MISMATCH")["status"], "skipped")

    def test_empty_or_outside_coupling_domains(self):
        for selection in ([], [2]):
            self.coupling["selected_entity_ids"] = selection
            self.assertIn("COUPLING_SELECTION_MISMATCH", self.codes())

    def test_missing_selection_is_skipped(self):
        self.coupling.pop("selected_entity_ids")
        self.assertEqual(self.codes(), set())
        self.assertEqual(self.rule("COUPLING_SELECTION_MISMATCH")["status"], "skipped")

    def test_partial_coupling_selection_is_legal_but_does_not_release_scope(self):
        self.domain["selected_entity_ids"] = [1, 2]
        self.flow["features"][0]["selected_entity_ids"] = [1, 2]
        self.assertNotIn("COUPLING_SELECTION_MISMATCH", self.codes())
        self.assertFalse(self.run_rules()["semantics_verified"])

    def test_solid_heat_domains_do_not_supply_fluid_coupling_coverage(self):
        self.domain["type"] = "SolidHeatTransferModel"
        self.assertEqual(self.rule("COUPLING_SELECTION_MISMATCH")["status"], "skipped")

    def test_disabled_referenced_interface(self):
        self.flow["enabled"] = False
        self.assertIn("COUPLING_PARTICIPATION_MISMATCH", self.codes())

    def test_sequential_study_is_not_error(self):
        self.ht["study_active"] = False
        self.assertEqual(self.codes(), set())
        self.assertEqual(self.rule("COUPLING_PARTICIPATION_MISMATCH")["status"], "skipped")
        self.assertEqual(self.heat_rule()[1]["status"], "skipped")

    def test_disabled_first_step_cannot_supply_current_participation(self):
        self.data["studies"] = [
            {"study_tag": "std0", "feature_tag": "stat", "type": "Stationary", "enabled": False},
            {"study_tag": "std1", "feature_tag": "stat", "type": "Stationary", "enabled": True}]
        self.ht["heat_evidence"]["study_participation"] = [
            {**self.data["studies"][0], "active": True},
            {**self.data["studies"][1], "active": False}]
        # ModelInventory's legacy first-Stationary summary can still be true.
        self.assertTrue(self.ht["study_active"])
        self.assertIs(heat.stationary_participation(self.data, self.ht), False)
        self.assertIsNone(heat.stationary_participation(self.data, self.flow))
        self.assertEqual(self.rule("COUPLING_PARTICIPATION_MISMATCH")["status"], "skipped")
        self.assertEqual(self.rule("COUPLING_SELECTION_MISMATCH")["status"], "checked")
        self.assertEqual(self.codes(), set())
        result, advection = self.heat_rule()
        self.assertEqual(advection["status"], "skipped")
        self.assertTrue(all(r["status"] == "checked" for r in result["rules"]
                            if r["rule_id"] != "HEAT_ADVECTION_SOURCE"))
        self.assertFalse(result["findings"])

    def test_explicit_current_step_wins_over_ambiguous_legacy_summary(self):
        self.data["studies"][0].update(study_tag="std1", feature_tag="stat")
        step = self.data["studies"][0]
        self.ht["heat_evidence"]["study_participation"] = [{**step, "active": True}]
        self.ht["study_active"] = False
        self.assertIs(heat.stationary_participation(self.data, self.ht), True)
        self.assertEqual(self.heat_rule()[1]["status"], "checked")
        self.assertEqual(self.rule("COUPLING_PARTICIPATION_MISMATCH")["status"], "checked")
        self.ht["study_active"] = True
        self.ht["heat_evidence"]["study_participation"][0]["active"] = False
        self.assertIs(heat.stationary_participation(self.data, self.ht), False)
        self.assertEqual(self.heat_rule()[1]["status"], "skipped")
        self.assertEqual(self.rule("COUPLING_PARTICIPATION_MISMATCH")["status"], "skipped")
        self.ht["heat_evidence"]["study_participation"][0]["active"] = True
        self.ht["heat_evidence"]["study_participation"].append({**step, "active": False})
        self.assertIsNone(heat.stationary_participation(self.data, self.ht))
        self.assertEqual(self.heat_rule()[1]["status"], "skipped")
        self.assertEqual(self.codes(), set())

    def test_step_identity_and_read_evidence_are_required(self):
        self.data["studies"][0].update(study_tag="std1", feature_tag="stat")
        step = {**self.data["studies"][0], "active": True}
        for changes in ({"study_tag": "other"}, {"feature_tag": "other"}, {"enabled": False},
                        {"type": "Transient"}, {"read_status": "unread"}, {"active": None}):
            with self.subTest(changes=changes):
                self.ht["heat_evidence"]["study_participation"] = [{**step, **changes}]
                self.assertIsNone(heat.stationary_participation(self.data, self.ht))
                self.assertEqual(self.heat_rule()[1]["status"], "skipped")
                self.assertEqual(self.rule("COUPLING_PARTICIPATION_MISMATCH")["status"], "skipped")
                self.assertEqual(self.codes(), set())

    def test_missing_participation_and_disabled_coupling(self):
        self.flow.pop("study_active")
        self.assertEqual(self.rule("COUPLING_PARTICIPATION_MISMATCH")["status"], "skipped")
        self.coupling["enabled"] = False
        self.assertTrue(all(r["status"] == "skipped" for r in self.run_rules()["rules"]))

    def test_unknown_coupling_blocks_dependent_rules(self):
        self.assertTrue(all(r["status"] == "skipped" for r in self.run_rules(["/multiphysics/0"])["rules"]))

    def test_manual_velocity_association_requires_no_coupling(self):
        self.component["multiphysics"] = []
        self.assertEqual(self.heat_rule()[1]["status"], "checked")

    def test_given_velocity_expressions_are_accepted_without_numeric_evaluation(self):
        self.domain["parameters"].update(u_src="userdef", u=["v(T)", "0", "0"])
        self.component["physics"].remove(self.flow)
        self.component["multiphysics"] = []
        result, rule = self.heat_rule()
        self.assertEqual(rule["status"], "checked")
        self.assertFalse(result["findings"])

    def test_unknown_velocity_source_is_coverage_only(self):
        self.domain["parameters"]["u_src"] = "fromCommonDef"
        result, rule = self.heat_rule()
        self.assertEqual(rule["status"], "skipped")
        self.assertNotIn("HEAT_ADVECTION_SOURCE", {f["code"] for f in result["findings"]})

    def test_advection_domain_mismatch(self):
        self.flow["features"][0]["selected_entity_ids"] = [2]
        result, rule = self.heat_rule()
        self.assertEqual(rule["status"], "checked")
        self.assertIn("HEAT_ADVECTION_SOURCE", {f["code"] for f in result["findings"]})

    def test_existing_unsupported_reference_type_is_not_a_model_error(self):
        self.flow["type"] = "CreepingFlow"
        self.assertEqual(self.codes(), set())
        self.assertEqual(self.rule("COUPLING_REFERENCE_MISMATCH")["status"], "skipped")
        self.assertFalse(self.run_rules()["semantics_verified"])

    def test_domain_selection_dimensions_are_required_at_every_scope(self):
        for target in (self.coupling, self.domain, self.flow["features"][0]):
            for dimensions in ([1], None):
                with self.subTest(target=target["tag"], dimensions=dimensions):
                    target["selection_dimensions"] = dimensions
                    self.assertEqual(self.codes(), set())
                    self.assertEqual(self.rule("COUPLING_SELECTION_MISMATCH")["status"], "skipped")
                    self.assertFalse(self.run_rules()["semantics_verified"])
                    if target is not self.coupling:
                        self.assertEqual(self.heat_rule()[1]["status"], "skipped")
            target["selection_dimensions"] = [2]
        self.component["geometries"][0]["dimension"] = 3
        self.assertFalse(self.run_rules()["semantics_verified"])
        self.assertEqual(self.rule("COUPLING_SELECTION_MISMATCH")["status"], "skipped")

    def test_only_verified_default_modes_release_dependent_flow_semantics(self):
        self.data["studies"][0].update(study_tag="std1", feature_tag="stat")
        self.component["materials"][0]["dynamic_viscosity"] = {"status": "resolved", "value": .001}
        defaults = {"SpecifyDensity": "FromHeatTransferInterface", "SpecifyTref": "FromHeatTransferInterface",
                    "BoussinesqApproximation": "0", "includeViscousDissipation": "1",
                    "includeIrreversibleLosses": "1", "includeKineticEnergy": "0",
                    "Fluid_TurbulenceModelProperty_TurbulenceModelType": "None",
                    "Fluid_PhysicalModelProperty_Compressibility": "Incompressible", "StudyStep": "std1/stat"}
        self.coupling["properties"].update({k: property_value(v) for k, v in defaults.items()})
        self.assertTrue(self.run_rules()["semantics_verified"])
        self.coupling["properties"]["BoussinesqApproximation"] = property_value("1")
        self.assertFalse(self.run_rules()["semantics_verified"])
        self.assertEqual(self.codes(), set())


if __name__ == "__main__":
    unittest.main()
