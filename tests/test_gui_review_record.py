"""Consistency of recorded observations, not automation of COMSOL or expert approval."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.diagnostics import diagnose_inventory


class GuiReviewRecordTest(unittest.TestCase):
    def setUp(self):
        self.record = json.loads((ROOT / "data/fixtures/comsol_gui_review.json").read_text(encoding="utf-8"))
        self.manifest = json.loads((ROOT / "data/fixtures/cases/manifest.json").read_text(encoding="utf-8"))

    def test_plot_source_and_acceptance_boundaries(self):
        record = self.record
        self.assertEqual(record["reviewer_kind"], "coding_agent")
        self.assertEqual(record["expert_review_status"], "pending")
        self.assertIsNone(record["expert_reviewed_by"])
        self.assertIsNone(record["expert_reviewed_date"])
        for key in ("solver_run", "model_saved", "independent_acceptance_set"):
            self.assertFalse(record[key])
        baseline = next(case for case in self.manifest["cases"] if case["case_id"] == "baseline")
        plots = record["baseline_plots"]
        self.assertEqual(plots["original_source_sha256"], baseline["sha256"].lower())
        self.assertEqual(plots["solution_tag"], "sol1")
        self.assertEqual(plots["surface_expression"], "spf.U")
        self.assertEqual(plots["surface_unit"], "m/s")
        self.assertEqual(plots["profiles_x_m"], [0.1, 0.25, 0.5, 0.9])

    def test_all_role_observations_have_versioned_model_identity(self):
        self.assertTrue(self.record["role_specific_gui_review_complete"])
        expected = {item["case_id"]: item for item in self.manifest["cases"] if item["case_id"] != "baseline"}
        self.assertEqual(len(self.record["cases"]), len(expected))
        self.assertEqual({item["case_id"] for item in self.record["cases"]}, set(expected))
        for case in self.record["cases"]:
            with self.subTest(case=case["case_id"]):
                self.assertIn(case["gui_status"], ("partial", "completed"))
                self.assertEqual(case["sha256"], expected[case["case_id"]]["sha256"].lower())

    def test_recorded_missing_inlet_matches_versioned_api_evidence(self):
        case = next(case for case in self.record["cases"] if case["case_id"] == "missing_inlet")
        inventory = json.loads((ROOT / "data/fixtures/cases/missing_inlet.json").read_text(encoding="utf-8"))
        model = diagnose_inventory(inventory)["model"]
        boundaries = model["boundaries"]
        self.assertFalse(any(item["type"] == "inlet" for item in boundaries))
        self.assertFalse(case["inlet_node_present"])
        for role in ("outlet", "wall"):
            node = next(item for item in boundaries if item["type"] == role)
            self.assertEqual(case[role + "_declared_boundary_ids"], node["declared_boundary_ids"])
            self.assertEqual(case[role + "_effective_boundary_ids"], node["boundary_ids"])
            self.assertEqual(case[role + "_mode"], node["mode"])
        outlet = next(item for item in boundaries if item["type"] == "outlet")
        self.assertEqual(case["outlet_pressure_expression"], outlet["parameters"]["pressure"]["expression"])
        self.assertEqual(case["outlet_pressure_unit"], outlet["parameters"]["pressure"]["unit"])
        self.assertIn(case["gui_status"], ("partial", "completed"))

    def test_recorded_missing_outlet_matches_versioned_api_evidence(self):
        case = next(case for case in self.record["cases"] if case["case_id"] == "missing_outlet")
        inventory = json.loads((ROOT / "data/fixtures/cases/missing_outlet.json").read_text(encoding="utf-8"))
        boundaries = diagnose_inventory(inventory)["model"]["boundaries"]
        self.assertFalse(any(item["type"] == "outlet" for item in boundaries))
        self.assertFalse(case["outlet_node_present"])
        manifest_case = next(item for item in self.manifest["cases"] if item["case_id"] == "missing_outlet")
        self.assertEqual(case["sha256"], manifest_case["sha256"].lower())
        for role in ("inlet", "wall"):
            node = next(item for item in boundaries if item["type"] == role)
            self.assertEqual(case[role + "_declared_boundary_ids"], node["declared_boundary_ids"])
            self.assertEqual(case[role + "_effective_boundary_ids"], node["boundary_ids"])
            self.assertEqual(case[role + "_mode"], node["mode"])
        velocity = next(item for item in boundaries if item["type"] == "inlet")["parameters"]["normal_velocity"]
        self.assertEqual(case["inlet_velocity_expression"], velocity["expression"])
        self.assertEqual(case["inlet_velocity_unit"], velocity["unit"])
        self.assertEqual(case["inlet_velocity_value_m_s"], velocity["value"])
        inlet_feature = next(item for item in inventory["components"][0]["physics"][0]["features"] if item["type"] == "Inlet")
        self.assertEqual(case["inlet_component_mode"], inlet_feature["parameters"]["ComponentWise"])

    def test_recorded_node_lists_match_versioned_api_evidence(self):
        for case in self.record["cases"]:
            if "nodes" not in case:
                continue
            inventory = json.loads((ROOT / "data/fixtures/cases" / (case["case_id"] + ".json")).read_text(encoding="utf-8"))
            features = inventory["components"][0]["physics"][0]["features"]
            for observed in case["nodes"]:
                with self.subTest(case=case["case_id"], label=observed["gui_label"]):
                    # Match this fixed fixture by label, not by inventing an internal tag from GUI text.
                    node = next(item for item in features if item["label"] == observed["gui_label"])
                    self.assertEqual(observed["declared_boundary_ids"], node["declared_entity_ids"])
                    self.assertEqual(observed["effective_boundary_ids"], node["selected_entity_ids"])
                    self.assertEqual(observed["mode"], node["parameters"]["BoundaryCondition"])
                    if "expression" in observed:
                        parameter = "normal_velocity" if node["type"] == "Inlet" else "pressure"
                        self.assertEqual(observed["expression"], node["evaluated_parameters"][parameter]["expression"])
                        self.assertEqual(observed["unit"], node["evaluated_parameters"][parameter]["unit"])

    def test_recorded_signed_velocity_and_reynolds_conventions(self):
        for case in self.record["cases"]:
            if "gui_signed_re_h" not in case:
                continue
            inventory = json.loads((ROOT / "data/fixtures/cases" / (case["case_id"] + ".json")).read_text(encoding="utf-8"))
            features = inventory["components"][0]["physics"][0]["features"]
            inlet = next(item for item in features if item["type"] == "Inlet")
            self.assertEqual(case["inlet_component_mode"], inlet["parameters"]["ComponentWise"])
            velocity = inlet["evaluated_parameters"]["normal_velocity"]["value"]
            self.assertEqual(case["inlet_velocity_value_m_s"], velocity)
            # GUI uses signed Uin; diagnostics use its magnitude and separate the direction warning.
            self.assertAlmostEqual(case["gui_signed_re_h"], 1000 * velocity * 0.05 / 0.001)
            self.assertEqual(case["diagnostic_absolute_re_h"], abs(case["gui_signed_re_h"]))


if __name__ == "__main__":
    unittest.main()
