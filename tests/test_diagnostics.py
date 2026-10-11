import copy
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.diagnostics import check, diagnose_inventory, normalize, validate


def load(name):
    return json.loads((ROOT / "data" / "fixtures" / "cases" / (name + ".json")).read_text(encoding="utf-8-sig"))


class DiagnosticTest(unittest.TestCase):
    def setUp(self):
        self.inventory = load("baseline")

    def codes(self, data=None):
        return {x["code"] for x in diagnose_inventory(data or self.inventory)["findings"]}

    def feature(self, role):
        return next(x for x in self.inventory["components"][0]["physics"][0]["features"] if x["type"] == role)

    def test_saved_real_comsol_cases_match_expected_codes(self):
        manifest = load("manifest")
        for case in manifest["cases"]:
            with self.subTest(case=case["case_id"]):
                report = diagnose_inventory(load(case["case_id"]))
                self.assertEqual(report["status"], "checked")
                self.assertEqual({x["code"] for x in report["findings"]}, set(case["expected_codes"]))

    def test_default_wall_is_not_an_explicit_conflict(self):
        self.assertEqual(self.codes(), set())
        wall = next(x for x in normalize(self.inventory)["boundaries"] if x["type"] == "wall")
        self.assertEqual(wall["selection_scope"], "fallback")
        self.assertEqual(self.feature("WallBC")["declared_entity_ids"], [1, 2, 3, 4])

    def test_inactive_inlet_is_missing(self):
        self.feature("Inlet")["enabled"] = False
        self.assertEqual(self.codes(), {"MISSING_INLET"})

    def test_empty_effective_selection_is_missing(self):
        self.feature("Inlet")["selected_entity_ids"] = []
        self.assertEqual(self.codes(), {"MISSING_INLET"})

    def test_overlap_uses_declared_not_effective_selection(self):
        report = diagnose_inventory(load("selection_overlap"))
        warning = next(x for x in report["findings"] if x["code"] == "BC_SELECTION_OVERLAP")
        self.assertEqual(warning["severity"], "Warning")
        self.assertEqual(warning["boundary_ids"], [1])
        self.assertEqual(warning["feature_tags"], ["inl1", "out_conflict"])

    def test_unresolved_expression_does_not_become_zero(self):
        self.feature("Inlet")["evaluated_parameters"]["normal_velocity"].update(
            expression="u(x)", status="unresolved", value=None)
        report = diagnose_inventory(self.inventory)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(self.codes(), {"EVALUATION_UNAVAILABLE"})

    def test_stored_inactive_vector_and_pressure_are_ignored(self):
        self.feature("Inlet")["parameters"]["u0"] = ["-999[m/s]", "0", "0"]
        self.feature("Inlet")["parameters"]["p0"] = "missing_pressure"
        self.assertEqual(self.codes(), set())

    def test_zero_velocity_warns(self):
        self.feature("Inlet")["evaluated_parameters"]["normal_velocity"]["value"] = 0
        self.assertEqual(self.codes(), {"INLET_DIRECTION"})

    def test_reynolds_risk_is_warning_not_turbulence_claim(self):
        report = diagnose_inventory(load("high_reynolds"))
        finding = report["findings"][0]
        self.assertEqual(finding["code"], "REYNOLDS_RISK")
        self.assertEqual(finding["severity"], "Warning")
        self.assertAlmostEqual(finding["evidence"]["reynolds_height_based"], 5000)
        self.assertEqual(diagnose_inventory(load("high_reynolds"), reynolds_warning=6000)["findings"], [])

    def test_bad_material_does_not_divide_by_zero(self):
        self.inventory["components"][0]["materials"][0]["dynamic_viscosity"]["value"] = 0
        self.assertEqual(self.codes(), {"INVALID_MATERIAL_PARAMETER"})

    def test_unsupported_scopes_do_not_get_normal_verdict(self):
        mutations = [
            lambda d: d["components"][0]["geometries"][0].update(dimension=3),
            lambda d: d["components"][0]["geometries"][0].update(domain_count=2),
            lambda d: d["components"][0]["geometries"][0].update(feature_types=["Circle"]),
            lambda d: d["components"][0]["physics"][0].update(type="TurbulentFlow"),
            lambda d: d["components"][0]["physics"][0].update(study_active=False),
            lambda d: d["studies"][0].update(type="Transient"),
            lambda d: d.update(multiphysics_tags=["coupling1"]),
            lambda d: d["components"][0].update(multiphysics_tags=["coupling1"]),
        ]
        for mutate in mutations:
            data = copy.deepcopy(self.inventory)
            mutate(data)
            self.assertEqual(diagnose_inventory(data)["status"], "unsupported")

    def test_unsupported_boundary_mode(self):
        self.feature("Inlet")["parameters"]["BoundaryCondition"] = "MassFlow"
        self.assertEqual(diagnose_inventory(self.inventory)["status"], "unsupported")

    def test_component_velocity_is_not_confused_with_normal_velocity(self):
        self.feature("Inlet")["parameters"]["ComponentWise"] = "VelocityField"
        self.assertEqual(diagnose_inventory(self.inventory)["status"], "unsupported")

    def test_physics_override_and_non_newtonian_are_rejected(self):
        for key, value in (("rho_mat", "userdef"), ("mu_mat", "userdef"), ("Constitutiverelation", "NonNewtonian")):
            data = copy.deepcopy(self.inventory)
            fluid = next(f for f in data["components"][0]["physics"][0]["features"] if f["type"] == "FluidProperties")
            fluid["parameters"][key] = value
            self.assertEqual(diagnose_inventory(data)["status"], "unsupported")

    def test_nonfinite_evidence_is_not_a_clean_verdict(self):
        self.inventory["components"][0]["materials"][0]["density"]["value"] = math.nan
        with self.assertRaises(ValueError):
            normalize(self.inventory)

    def test_nested_nodes_are_not_silently_ignored(self):
        self.feature("Inlet")["child_feature_count"] = 1
        self.assertEqual(diagnose_inventory(self.inventory)["status"], "unsupported")

    def test_normalized_tags_come_from_api_not_hardcoded(self):
        self.inventory["components"][0]["tag"] = "different_component"
        self.inventory["components"][0]["physics"][0]["tag"] = "flow7"
        self.feature("Inlet")["tag"] = "entry9"
        model = normalize(self.inventory)
        self.assertEqual(model["source"]["physics_tag"], "flow7")
        self.assertIn("entry9", {x["feature_tag"] for x in model["boundaries"]})

    def test_schema_rejects_invalid_boundary_ids(self):
        model = normalize(self.inventory)
        model["boundaries"][0]["boundary_ids"] = [99]
        with self.assertRaises(ValidationError):
            validate(model)

    def test_resolved_null_fails_schema(self):
        model = normalize(self.inventory)
        model["material"]["density"]["value"] = None
        with self.assertRaises(ValidationError):
            validate(model)

    def test_invalid_threshold(self):
        for value in (0, -1, math.nan, math.inf):
            with self.assertRaises(ValueError):
                check(normalize(self.inventory), reynolds_warning=value)

    def test_deterministic_export_across_five_runs(self):
        first = json.dumps(diagnose_inventory(self.inventory), sort_keys=True, ensure_ascii=False)
        for _ in range(5):
            self.assertEqual(json.dumps(diagnose_inventory(self.inventory), sort_keys=True, ensure_ascii=False), first)

    def test_cli_reports_and_refuses_overwrite(self):
        (ROOT / "outputs").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as directory:
            output = Path(directory) / "diagnosis.json"
            command = [sys.executable, str(ROOT / "src" / "flowpilot" / "diagnostics.py"),
                       str(ROOT / "data" / "fixtures" / "cases" / "baseline.json"), "--output", str(output)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            before = output.read_bytes()
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
