"""Mandatory replay of real, repeatedly read unsolved COMSOL 3D samples."""
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.diagnostics import diagnose_inventory

SAMPLES = set("normal missing_inlet missing_outlet selection_overlap empty_inlet reversed_inlet high_reynolds wall_on_inlet slip_wall invalid_viscosity invalid_k empty_heat_flux thermal_overlap disabled_coupling conjugate_normal conjugate_missing_wall_k".split())


class M3ApiEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads((ROOT / "data/fixtures/m3_api_evidence.json").read_text(encoding="utf-8"))
        cls.inventories = json.loads((ROOT / "data/fixtures/m3_inventories.json").read_text(encoding="utf-8"))

    def test_actual_current_reader_repeated_unsolved_models(self):
        e = self.evidence
        self.assertEqual(e["schema_version"], "m3-api-evidence-1")
        self.assertIn("6.3", e["comsol_version"])
        self.assertIs(e["source_models_unchanged"], True)
        self.assertIs(e["license_baseline_available"], True)
        self.assertIs(e["solved"], False)
        self.assertEqual(e["solution_sequences_per_model"], 0)
        self.assertEqual(e["reads_per_model"], 3)
        self.assertEqual(e["implementation_sha256"], e["implementation_sha256_after"])
        for path, expected in e["implementation_sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), expected)
        self.assertEqual(set(e["implementation_sha256"]), {"src/comsol/ModelInventory.java", "src/comsol/M3ApiProbe.java.in", "scripts/verify_m3_api.py"})
        manifest = json.loads((ROOT / "data/fixtures/cases/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(e["source_model_sha256"], {Path(c["model_path"]).name: c["sha256"].lower() for c in manifest["cases"]})
        self.assertEqual(set(e["verified_models"]), SAMPLES)
        self.assertEqual(set(self.inventories), SAMPLES)
        self.assertEqual(set(e["output_model_sha256"]), SAMPLES)
        for name, inventory in self.inventories.items():
            payload = json.dumps(inventory, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), e["inventory_sha256"][name])
            self.assertEqual(e["repeat_markers"][name], f"M3_READ_VERIFIED {name} 3")
            self.assertEqual(e["unsolved_markers"][name], f"M3_UNSOLVED_VERIFIED {name} 3")
            g = inventory["components"][0]["geometries"][0]
            self.assertEqual(g["dimension"], 3)
            self.assertEqual(g["three_dimensional_evidence"]["read_status"], "read")
            self.assertEqual(g["domain_count"], 2 if name.startswith("conjugate_") else 1)

    def test_independent_fault_labels_and_legal_alternatives(self):
        # The mutations are defined in M3ApiProbe, independent of diagnostic output.
        # COMSOL filters inlet effective selection when a later outlet/wall overrides it.
        expected = {name: set() for name in SAMPLES}
        expected["missing_inlet"] = {"MISSING_INLET"}
        expected["missing_outlet"] = {"MISSING_OUTLET"}
        expected["empty_inlet"] = {"EMPTY_BOUNDARY_SELECTION", "MISSING_INLET"}
        expected["selection_overlap"] = expected["empty_inlet"] | {"BC_SELECTION_OVERLAP"}
        expected["wall_on_inlet"] = expected["selection_overlap"] | {"FLOW_FACE_SELECTION_INCONSISTENT"}
        expected["reversed_inlet"] = {"INLET_DIRECTION"}
        expected["high_reynolds"] = {"REYNOLDS_RISK"}
        expected["invalid_viscosity"] = {"INVALID_MATERIAL_PARAMETER"}
        expected["invalid_k"] = {"HEAT_INVALID_MATERIAL_PARAMETER"}
        expected["empty_heat_flux"] = {"HEAT_EMPTY_BOUNDARY_SELECTION"}
        expected["thermal_overlap"] = {"HEAT_BC_SELECTION_OVERLAP"}
        complete = {"normal", "reversed_inlet", "high_reynolds", "empty_heat_flux", "thermal_overlap", "disabled_coupling", "conjugate_normal"}
        for name, inventory in self.inventories.items():
            with self.subTest(name=name):
                report = diagnose_inventory(inventory)
                self.assertEqual(report["schema_version"], "diagnosis-0.4")
                self.assertEqual({f["code"] for f in report["findings"]}, expected[name])
                self.assertEqual(report["status"], "checked" if name in complete else "partial")
        # Missing wall conductivity and a legal slip wall represent missing evidence
        # / unsupported geometric premises, and are never manufactured model errors.
        for name in ("slip_wall", "conjugate_missing_wall_k"):
            self.assertEqual(diagnose_inventory(self.inventories[name])["findings"], [])

    def test_face_domain_adjacency_matches_each_direction(self):
        for name in ("normal", "conjugate_normal"):
            g = self.inventories[name]["components"][0]["geometries"][0]
            proof = g["three_dimensional_evidence"]
            domains = {d["domain_id"]: set(d["boundary_ids"]) for d in proof["domains"]}
            for face in proof["boundaries"]:
                self.assertEqual(set(face["domain_ids"]), {d for d, faces in domains.items() if face["boundary_id"] in faces})
                self.assertGreater(face["area"], 0)
                self.assertEqual(len(face["sample_coordinates"]), 25)
                self.assertTrue(all(len(p) == 3 for p in face["sample_coordinates"]))


if __name__ == "__main__":
    unittest.main()
