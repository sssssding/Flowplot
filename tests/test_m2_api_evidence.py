"""Replay actual unsolved COMSOL models; synthetic counterexamples live elsewhere."""
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.check_model import sha256
from flowpilot.diagnostics import diagnose_inventory
from m2_historical_sources import M2_SOURCES


class M2ApiEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads((ROOT / "data/fixtures/m2_api_evidence.json").read_text(encoding="utf-8"))
        cls.inventories = json.loads((ROOT / "data/fixtures/m2_inventories.json").read_text(encoding="utf-8"))

    def test_actual_reader_and_repeated_unsolved_models(self):
        evidence = self.evidence
        self.assertEqual(evidence["schema_version"], "m2-api-evidence-1")
        self.assertIn("6.3", evidence["comsol_version"])
        for key in ("source_models_unchanged", "license_baseline_available"):
            self.assertIs(evidence[key], True)
        self.assertIs(evidence["solved"], False)
        self.assertEqual(evidence["reads_per_model"], 3)
        self.assertEqual(evidence["solution_sequences_per_model"], 0)
        self.assertEqual(evidence["implementation_sha256"], evidence["implementation_sha256_after"])
        self.assertEqual(evidence["implementation_sha256"], M2_SOURCES["m2_api_evidence.json"])
        manifest = json.loads((ROOT / "data/fixtures/cases/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["source_model_sha256"],
                         {Path(c["model_path"]).name: c["sha256"].lower() for c in manifest["cases"]})
        self.assertEqual(set(evidence["verified_models"]), set(self.inventories))
        for name, inventory in self.inventories.items():
            payload = json.dumps(inventory, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), evidence["inventory_sha256"][name])
            self.assertEqual(evidence["repeat_markers"][name], f"M2_READ_VERIFIED {name} 3")
            self.assertEqual(evidence["unsolved_markers"][name], f"M2_UNSOLVED_VERIFIED {name} 3")

    def test_independent_fault_labels_and_legal_alternatives(self):
        expected = {name: set() for name in (
            "normal", "invalid_k", "invalid_cp", "invalid_rho", "missing_k", "empty_heat_flux",
            "thermal_overlap", "disabled_coupling", "disabled_heat_interface", "inactive_heat_study",
            "legal_manual_velocity", "legal_prescribed_velocity", "legal_convective_flux",
            "temperature_dependent_k", "anisotropic_k", "conjugate_normal", "conjugate_missing_wall_k")}
        for name in ("invalid_k", "invalid_cp", "invalid_rho"):
            expected[name] = {"HEAT_INVALID_MATERIAL_PARAMETER"}
        expected["invalid_rho"].add("INVALID_MATERIAL_PARAMETER")
        expected["empty_heat_flux"] = {"HEAT_EMPTY_BOUNDARY_SELECTION"}
        expected["thermal_overlap"] = {"HEAT_BC_SELECTION_OVERLAP"}
        expected["disabled_heat_interface"] = {"COUPLING_PARTICIPATION_MISMATCH"}
        self.assertEqual(set(expected), set(self.inventories))
        complete = {"normal", "empty_heat_flux", "thermal_overlap",
                    "disabled_coupling", "legal_manual_velocity", "legal_prescribed_velocity"}
        for name, inventory in self.inventories.items():
            with self.subTest(name=name):
                report = diagnose_inventory(inventory)
                self.assertEqual(report["schema_version"], "diagnosis-0.3")
                self.assertEqual({f["code"] for f in report["findings"]}, expected[name])
                self.assertEqual(report["status"], "checked" if name in complete else "partial")
                if name.startswith("conjugate_"):
                    heat = next(c for c in report["coverage"] if c["module"] == "heat")
                    self.assertEqual(heat["status"], "checked" if name == "conjugate_normal" else "skipped")
                    flow = next(c for c in report["coverage"] if c["module"] == "flow")
                    self.assertTrue(any(r["status"] == "checked" for r in flow["rules"]))
                    self.assertEqual(next(r for r in flow["rules"] if r["rule_id"] == "REYNOLDS_RISK")["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
