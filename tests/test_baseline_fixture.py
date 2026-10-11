import json
import math
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data" / "fixtures" / "baseline_pipe_2d_laminar.json"


class BaselineFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_mvp_model_scope(self):
        model = self.data["model"]
        self.assertEqual(model["dimension"], 2)
        self.assertEqual(model["physics"], "laminar_flow")
        self.assertEqual(model["study"], "stationary")

    def test_boundary_partition(self):
        boundaries = self.data["boundaries"]
        by_type = {item["type"]: item for item in boundaries}
        self.assertEqual(set(by_type), {"inlet", "outlet", "wall"})
        self.assertEqual(by_type["inlet"]["boundary_ids"], [1])
        self.assertEqual(by_type["outlet"]["boundary_ids"], [4])
        self.assertEqual(by_type["wall"]["boundary_ids"], [2, 3])

        all_ids = [item for boundary in boundaries for item in boundary["boundary_ids"]]
        self.assertEqual(sorted(all_ids), [1, 2, 3, 4])
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_reynolds_number(self):
        material = self.data["material"]
        geometry = self.data["geometry"]
        inlet = next(item for item in self.data["boundaries"] if item["type"] == "inlet")
        reynolds = (
            material["density_kg_m3"]
            * inlet["parameters"]["normal_velocity_m_s"]
            * geometry["height_m"]
            / material["dynamic_viscosity_pa_s"]
        )
        self.assertTrue(math.isclose(reynolds, 500.0, rel_tol=1e-12))
        self.assertEqual(reynolds, self.data["expected_metrics"]["reynolds_number"])

    def test_fixture_matches_real_comsol_inventory(self):
        inventory = json.loads((FIXTURE.parent / "baseline_inventory.json").read_text(encoding="utf-8-sig"))
        physics = inventory["components"][0]["physics"][0]
        self.assertEqual(physics["type"], "LaminarFlow")
        features = {item["tag"]: item for item in physics["features"]}
        for boundary in self.data["boundaries"]:
            actual = features[boundary["feature_tag"]]
            self.assertEqual(actual["selected_entity_ids"], boundary["boundary_ids"])
            self.assertEqual(actual["enabled"], boundary["enabled"])
            self.assertEqual(actual["selection_dimensions"], [1])
        self.assertEqual(features["inl1"]["parameters"]["U0in"], "Uin")
        self.assertEqual(features["out1"]["parameters"]["p0"], "p_out")
        self.assertEqual(features["wallbc1"]["parameters"]["BoundaryCondition"], "NoSlip")

    def test_real_solver_mass_balance_and_repeatability(self):
        report = json.loads((FIXTURE.parent / "baseline_verification.json").read_text(encoding="utf-8-sig"))
        self.assertTrue(report["passed"])
        self.assertEqual(len(report["runs"]), 4)
        reference = report["runs"][0]
        for run in report["runs"]:
            incoming, outgoing = run["mass_in_kg_m_s"], run["mass_out_kg_m_s"]
            self.assertGreater(incoming, 0)
            self.assertGreater(outgoing, 0)
            error = abs(incoming - outgoing) / max(incoming, outgoing)
            self.assertTrue(math.isclose(error, run["mass_relative_error"], abs_tol=1e-12))
            self.assertLess(error, self.data["expected_metrics"]["mass_conservation_relative_tolerance"])
            self.assertLessEqual(run["wall_interior_speed_m_s"], 1e-8)
            self.assertGreaterEqual(run["min_u_m_s"], -1e-7)
            for metric in ("max_speed_m_s", "pressure_drop_pa", "mass_out_kg_m_s"):
                self.assertTrue(math.isclose(reference[metric], run[metric], rel_tol=1e-5))


if __name__ == "__main__":
    unittest.main()
