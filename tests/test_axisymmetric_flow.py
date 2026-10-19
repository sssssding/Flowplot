"""Unit evidence probes; real COMSOL integration evidence is tested separately."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

from jsonschema import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.diagnostics import diagnose_inventory, normalize, check, validate, validate_diagnosis_report
from flowpilot.diagnostic_modules.flow import AXIS_RULES, RULES
from flowpilot.portable_recommend import model_features


def inventory():
    data = json.loads((ROOT / "data/fixtures/cases/baseline.json").read_text(encoding="utf-8-sig"))
    geometry = data["components"][0]["geometries"][0]
    geometry.update(axisymmetric=True, bounding_box=[0, .025, 0, 1], rectangle_rotation_expression="0")
    geometry["axisymmetric_evidence"] = {
        "read_status": "read", "coordinate_names": ["Rg", "PHIg", "Zg"], "spatial_coordinate_names": ["r", "phi", "z"],
        "vertex_coordinates": [[0, 0, .025, .025], [0, 1, 0, 1]],
        "boundaries": [
            {"boundary_id": 1, "vertex_ids": [1, 2], "domain_ids": [1], "sample_coordinates": [[0, 0], [0, .5], [0, 1]]},
            {"boundary_id": 2, "vertex_ids": [1, 3], "domain_ids": [1], "sample_coordinates": [[0, 0], [.0125, 0], [.025, 0]]},
            {"boundary_id": 3, "vertex_ids": [2, 4], "domain_ids": [1], "sample_coordinates": [[0, 1], [.0125, 1], [.025, 1]]},
            {"boundary_id": 4, "vertex_ids": [3, 4], "domain_ids": [1], "sample_coordinates": [[.025, 0], [.025, .5], [.025, 1]]},
        ]}
    for node in data["components"][0]["physics"][0]["features"]:
        ids = {"Inlet": [2], "Outlet": [3], "WallBC": [4], "Wall": [4]}.get(node["type"])
        if ids:
            node["selected_entity_ids"] = ids
            if node["type"] in {"Inlet", "Outlet"}:
                node["declared_entity_ids"] = ids
    data["components"][0]["physics"][0]["features"].append({
        "tag": "axi1", "label": "轴对称 1", "type": "AxialSymmetry", "enabled": True,
        "selection_dimensions": [1], "selected_entity_ids": [1], "declared_entity_ids": [1, 2, 3, 4],
        "named_selection": "", "child_feature_count": 0, "parameters": {}, "evaluated_parameters": {}})
    return data


def node(data, role):
    return next(f for f in data["components"][0]["physics"][0]["features"] if f["type"] == role)


def scope(report):
    return next(c for c in report["coverage"] if c["kind"] == "physics")


def rules(report):
    return {r["rule_id"]: r for r in scope(report)["rules"]}


class AxisymmetricFlowTests(unittest.TestCase):
    def test_verified_normal_pipe_has_new_contract_and_no_findings(self):
        report = diagnose_inventory(inventory())
        self.assertEqual(report["status"], "checked")
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["model"]["schema_version"], "diagnostic-0.2")
        self.assertEqual(report["model"]["profile"], "axisymmetric-pipe-v1")
        self.assertEqual(report["model"]["geometry"]["axis_boundary_ids"], [1])
        self.assertEqual(report["model"]["geometry"]["pipe_diameter_m"], .05)
        self.assertEqual(set(rules(report)), {r[0] for r in AXIS_RULES})
        validate_diagnosis_report(report)
        validate(report["model"])

    def test_new_model_is_rejected_by_legacy_recommendation(self):
        with self.assertRaisesRegex(ValueError, "rectangle"):
            model_features(normalize(inventory()))

    def test_legacy_check_api_requires_modular_axisymmetric_report(self):
        with self.assertRaisesRegex(ValueError, "diagnose_inventory"):
            check(normalize(inventory()))

    def test_axis_declared_all_is_managed_not_a_role_conflict(self):
        report = diagnose_inventory(inventory())
        axis = next(b for b in report["model"]["boundaries"] if b["type"] == "axis")
        self.assertEqual(axis["selection_scope"], "fallback")
        self.assertEqual(report["findings"], [])

    def test_explicit_wall_declares_axis_but_comsol_filters_effective_selection(self):
        data = inventory()
        wall = copy.deepcopy(node(data, "WallBC"))
        wall.update(tag="axis_wall", named_selection="axis", selected_entity_ids=[], declared_entity_ids=[1])
        data["components"][0]["physics"][0]["features"].append(wall)
        report = diagnose_inventory(data)
        finding = next(f for f in report["findings"] if f["code"] == "AXIS_SELECTION_INCONSISTENT")
        self.assertEqual(finding["feature_tags"], ["axis_wall"])
        self.assertEqual(finding["boundary_ids"], [1])
        self.assertEqual(finding["evidence"]["effective_boundary_ids"], [])
        self.assertEqual(rules(report)["REYNOLDS_RISK"]["status"], "skipped")

    def test_axis_on_non_axis_boundary_is_reported(self):
        data = inventory()
        node(data, "AxialSymmetry").update(selected_entity_ids=[4], declared_entity_ids=[4], named_selection="outer")
        report = diagnose_inventory(data)
        self.assertIn("AXIS_SELECTION_INCONSISTENT", {f["code"] for f in report["findings"]})
        self.assertEqual(rules(report)["REYNOLDS_RISK"]["status"], "skipped")

    def test_axis_without_effective_coverage_reports_missing_axis(self):
        data = inventory()
        node(data, "AxialSymmetry")["enabled"] = False
        report = diagnose_inventory(data)
        self.assertEqual([f["code"] for f in report["findings"]], ["AXIS_SELECTION_INCONSISTENT"])
        self.assertEqual(report["findings"][0]["boundary_ids"], [1])

    def test_missing_topology_skips_axis_missing_ports_and_scale_only(self):
        data = inventory()
        del data["components"][0]["geometries"][0]["axisymmetric_evidence"]
        report = diagnose_inventory(data)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["findings"], [])
        for code in ("AXIS_SELECTION_INCONSISTENT", "MISSING_INLET", "MISSING_OUTLET", "REYNOLDS_RISK"):
            self.assertEqual(rules(report)[code]["status"], "skipped")
        self.assertEqual(rules(report)["INVALID_MATERIAL_PARAMETER"]["status"], "checked")

    def test_incomplete_or_wrong_coordinate_evidence_does_not_establish_axis(self):
        for change in ({"read_status": "unread"}, {"coordinate_names": ["x", "y"]}, {"boundaries": []}):
            data = inventory()
            data["components"][0]["geometries"][0]["axisymmetric_evidence"].update(change)
            report = diagnose_inventory(data)
            self.assertEqual(rules(report)["AXIS_SELECTION_INCONSISTENT"]["status"], "skipped")
            self.assertIsNone(report["model"]["geometry"]["pipe_diameter_m"])

    def test_empty_explicit_inlet_is_reported_and_missing_port_checks_apply(self):
        data = inventory()
        node(data, "Inlet").update(selected_entity_ids=[], declared_entity_ids=[])
        report = diagnose_inventory(data)
        self.assertEqual({f["code"] for f in report["findings"]}, {"EMPTY_BOUNDARY_SELECTION", "MISSING_INLET"})
        self.assertEqual(rules(report)["EMPTY_BOUNDARY_SELECTION"]["status"], "checked")

    def test_empty_fallback_wall_is_legal_when_overridden(self):
        data = inventory()
        node(data, "WallBC")["selected_entity_ids"] = []
        report = diagnose_inventory(data)
        self.assertNotIn("EMPTY_BOUNDARY_SELECTION", {f["code"] for f in report["findings"]})

    def test_unread_selection_only_skips_dependent_rules(self):
        data = inventory()
        node(data, "Inlet")["read_status"] = "unread"
        report = diagnose_inventory(data)
        self.assertEqual(rules(report)["EMPTY_BOUNDARY_SELECTION"]["status"], "skipped")
        self.assertEqual(rules(report)["MISSING_INLET"]["status"], "skipped")
        self.assertEqual(rules(report)["INVALID_MATERIAL_PARAMETER"]["status"], "checked")
        self.assertEqual(report["findings"], [])

    def test_missing_one_port_is_checked_but_closed_flow_is_not_forced_open(self):
        for absent in ("Inlet", "Outlet"):
            data = inventory()
            node(data, absent)["enabled"] = False
            report = diagnose_inventory(data)
            self.assertEqual([f["code"] for f in report["findings"]], ["MISSING_" + absent.upper()])
        data = inventory()
        node(data, "Inlet")["enabled"] = node(data, "Outlet")["enabled"] = False
        report = diagnose_inventory(data)
        self.assertEqual(report["findings"], [])
        self.assertEqual(rules(report)["MISSING_INLET"]["status"], "skipped")
        self.assertEqual(rules(report)["MISSING_OUTLET"]["status"], "skipped")

    def test_explicit_mixed_role_overlap_reports_warning(self):
        data = inventory()
        node(data, "WallBC").update(named_selection="explicit", declared_entity_ids=[2, 4])
        report = diagnose_inventory(data)
        self.assertIn("BC_SELECTION_OVERLAP", {f["code"] for f in report["findings"]})

    def test_missing_declared_selection_skips_conflict_rule(self):
        data = inventory()
        node(data, "Inlet")["declared_entity_ids"] = None
        report = diagnose_inventory(data)
        self.assertEqual(rules(report)["BC_SELECTION_OVERLAP"]["status"], "skipped")
        self.assertNotIn("BC_SELECTION_OVERLAP", {f["code"] for f in report["findings"]})

    def test_unknown_coupling_retains_independent_material_error(self):
        data = inventory()
        data["multiphysics_tags"] = ["unknown"]
        data["components"][0]["materials"][0]["density"]["value"] = -1
        report = diagnose_inventory(data)
        self.assertEqual([f["code"] for f in report["findings"]], ["INVALID_MATERIAL_PARAMETER"])
        self.assertEqual(rules(report)["AXIS_SELECTION_INCONSISTENT"]["status"], "skipped")

    def test_unsupported_inlet_mode_does_not_invent_direction_or_missing_ports(self):
        data = inventory()
        node(data, "Inlet")["parameters"]["BoundaryCondition"] = "MassFlow"
        report = diagnose_inventory(data)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["findings"], [])
        self.assertEqual(rules(report)["INLET_DIRECTION"]["status"], "skipped")
        self.assertEqual(rules(report)["MISSING_OUTLET"]["status"], "skipped")

    def test_user_defined_fluid_constants_are_not_confused_with_material(self):
        data = inventory()
        node(data, "FluidProperties")["parameters"]["rho_mat"] = "userdef"
        data["components"][0]["materials"][0]["density"]["value"] = -1
        report = diagnose_inventory(data)
        self.assertEqual(rules(report)["INVALID_MATERIAL_PARAMETER"]["status"], "skipped")
        self.assertNotIn("INVALID_MATERIAL_PARAMETER", {f["code"] for f in report["findings"]})

    def test_slip_is_legal_but_does_not_claim_verified_reynolds(self):
        data = inventory()
        node(data, "WallBC")["parameters"]["BoundaryCondition"] = "Slip"
        report = diagnose_inventory(data)
        self.assertEqual(report["findings"], [])
        self.assertEqual(rules(report)["AXIS_SELECTION_INCONSISTENT"]["status"], "checked")
        self.assertEqual(rules(report)["REYNOLDS_RISK"]["status"], "skipped")

    def test_inlet_direction_and_diameter_based_reynolds_reuse_verified_rules(self):
        data = inventory()
        node(data, "Inlet")["evaluated_parameters"]["normal_velocity"]["value"] = -.1
        report = diagnose_inventory(data)
        self.assertEqual({f["code"] for f in report["findings"]}, {"INLET_DIRECTION", "REYNOLDS_RISK"})
        re = next(f for f in report["findings"] if f["code"] == "REYNOLDS_RISK")
        self.assertEqual(re["evidence"]["reynolds_diameter_based"], 5000)

    def test_unresolved_parameter_retains_skipped_node_coverage(self):
        data = inventory()
        node(data, "Inlet")["evaluated_parameters"]["normal_velocity"].update(status="unresolved", value=None)
        report = diagnose_inventory(data)
        self.assertEqual([f["code"] for f in report["findings"]], ["EVALUATION_UNAVAILABLE"])
        self.assertEqual(rules(report)["INLET_DIRECTION"]["status"], "skipped")
        validate_diagnosis_report(report)

    def test_legacy_reports_keep_original_rule_registry(self):
        data = json.loads((ROOT / "data/fixtures/cases/baseline.json").read_text(encoding="utf-8-sig"))
        report = diagnose_inventory(data)
        self.assertEqual(set(rules(report)), {r[0] for r in RULES})
        self.assertEqual(report["model"]["schema_version"], "diagnostic-0.1")
        validate_diagnosis_report(report)

    def test_schema_rejects_axis_model_claiming_old_version_and_invalid_ids(self):
        for change in ({"schema_version": "diagnostic-0.1"}, {"profile": "rectangular-channel-v1"}):
            model = normalize(inventory())
            model.update(change)
            with self.assertRaises(ValidationError):
                validate(model)
        model = normalize(inventory())
        model["geometry"]["axis_boundary_ids"] = [5]
        with self.assertRaises(ValidationError):
            validate(model)

    def test_new_profile_must_have_exact_axis_rule_set(self):
        report = diagnose_inventory(inventory())
        scope(report)["rules"] = [r for r in scope(report)["rules"] if r["rule_id"] != "AXIS_SELECTION_INCONSISTENT"]
        with self.assertRaises(ValueError):
            validate_diagnosis_report(report)

    def test_wrong_pipe_port_location_does_not_enable_reynolds_screen(self):
        data = inventory()
        node(data, "Inlet").update(selected_entity_ids=[4], declared_entity_ids=[4])
        report = diagnose_inventory(data)
        self.assertFalse(report["model"]["reynolds_profile_verified"])
        self.assertEqual(rules(report)["REYNOLDS_RISK"]["status"], "skipped")


class AxisymmetricRealEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # These are mandatory committed API captures, never replace with synthetic
        # data or skip because the developer's COMSOL installation is absent.
        cls.captured = json.loads((ROOT / "data/fixtures/m1_inventories.json").read_text(encoding="utf-8"))
        cls.summary = json.loads((ROOT / "data/fixtures/m1_api_evidence.json").read_text(encoding="utf-8"))

    def test_real_unsolved_captures_are_hash_bound_and_repeated(self):
        summary = self.summary
        self.assertEqual(summary["schema_version"], "m1-api-evidence-1")
        self.assertEqual(summary["reads_per_model"], 3)
        self.assertFalse(summary["solved"])
        self.assertEqual(summary["solution_sequences_per_model"], 0)
        self.assertTrue(summary["source_models_unchanged"])
        self.assertEqual(set(summary["verified_models"]), set(self.captured))
        self.assertEqual(summary["implementation_sha256"], summary["implementation_sha256_after"])
        from m1_historical_sources import M1_SOURCES
        self.assertEqual(summary["implementation_sha256"], M1_SOURCES["m1_api_evidence.json"])
        for name, data in self.captured.items():
            serialized = json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
            self.assertEqual(hashlib.sha256(serialized).hexdigest(), summary["inventory_sha256"][name], name)
            self.assertEqual(summary["repeat_markers"][name], f"M1_READ_VERIFIED {name} 3")
            self.assertEqual(summary["unsolved_markers"][name], f"M1_UNSOLVED_VERIFIED {name} 3")

    def test_all_thirteen_real_captures_have_independent_expected_results(self):
        expected = {
            "normal": ("checked", []),
            "missing_inlet": ("checked", ["MISSING_INLET"]),
            "missing_outlet": ("partial", ["MISSING_OUTLET"]),
            "empty_inlet": ("checked", ["EMPTY_BOUNDARY_SELECTION", "MISSING_INLET"]),
            "selection_overlap": ("checked", ["BC_SELECTION_OVERLAP", "EMPTY_BOUNDARY_SELECTION", "MISSING_INLET"]),
            "axis_wrong_selection": ("partial", ["AXIS_SELECTION_INCONSISTENT", "EMPTY_BOUNDARY_SELECTION"]),
            "legal_explicit_selection": ("checked", []),
            "legal_slip_wall": ("partial", []),
            "unsupported_inlet_mode": ("partial", []),
            "closed_flow": ("partial", []),
            "high_reynolds": ("checked", ["REYNOLDS_RISK"]),
            "reversed_inlet": ("checked", ["INLET_DIRECTION"]),
            "invalid_material": ("checked", ["INVALID_MATERIAL_PARAMETER"]),
        }
        self.assertEqual(set(self.captured), set(expected))
        for name, data in self.captured.items():
            with self.subTest(name=name):
                report = diagnose_inventory(data)
                self.assertEqual((report["status"], [f["code"] for f in report["findings"]]), expected[name])
                self.assertEqual(report["model"]["schema_version"], "diagnostic-0.2")
                validate_diagnosis_report(report)
                with self.assertRaises(ValueError):
                    model_features(report["model"])


if __name__ == "__main__":
    unittest.main()
