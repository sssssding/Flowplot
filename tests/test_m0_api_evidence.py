"""Sanitized evidence binds M0 API claims to actual runtime/source observations."""
import hashlib
import json
from pathlib import Path
import unittest
from m0_historical_sources import SOURCES as M0_SOURCES

ROOT = Path(__file__).resolve().parents[1]


class M0ApiEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads((ROOT / "data/fixtures/m0_api_evidence.json").read_text(encoding="utf-8"))

    def test_runtime_scope_and_repeated_real_reads(self):
        e = self.evidence
        self.assertEqual(e["schema_version"], "m0-api-evidence-1")
        self.assertIn("6.3", e["comsol_version"])
        self.assertIn("290", e["comsol_version"])
        self.assertIs(e["license_baseline_available"], True)
        self.assertIs(e["solved"], False)
        self.assertIs(e["source_models_unchanged"], True)
        self.assertEqual(e["reads_per_model"], 3)
        expected = {"baseline", "missing_inlet", "missing_outlet", "selection_overlap", "reversed_inlet", "high_reynolds", "unknown_physics", "unknown_coupling", "disabled_coupling", "missing_viscosity"}
        self.assertEqual(set(e["verified_models"]), expected)
        self.assertEqual(set(e["inventory_sha256"]), expected)
        self.assertEqual(e["repeat_markers"], {name: f"M0_READ_VERIFIED {name} 3" for name in expected})
        for value in (*e["inventory_sha256"].values(), e["generated_driver_sha256"]):
            self.assertRegex(value, r"^[0-9a-f]{64}$")

    def test_source_and_manifest_bindings(self):
        e = self.evidence
        self.assertEqual(set(e["implementation_sha256"]), {"src/comsol/ModelInventory.java", "src/comsol/M0ApiProbe.java.in", "scripts/verify_m0_api.py"})
        for name, expected in e["implementation_sha256"].items():
            self.assertNotIn("\\", name)
            self.assertEqual(M0_SOURCES[name], expected, name)
        manifest = json.loads((ROOT / "data/fixtures/cases/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(e["source_model_sha256"], {Path(case["model_path"]).name: case["sha256"].lower() for case in manifest["cases"]})

    def test_real_coupling_and_missing_material_evidence(self):
        e = self.evidence
        self.assertEqual(e["interface_creation_succeeded"], "HeatTransferInFluids")
        self.assertEqual(e["coupling_creation_marker"], "M0_COUPLING_CREATED NonIsothermalFlow")
        coupling, = e["coupling"]
        self.assertEqual(coupling["tag"], "nitf_m0")
        self.assertEqual(coupling["type"], "NonIsothermalFlow")
        self.assertEqual(coupling["component_tag"], "comp1")
        self.assertEqual(coupling["model_path"], "/multiphysics/nitf_m0")
        self.assertEqual(coupling["scope"], "root.comp1.nitf_m0")
        self.assertIs(coupling["enabled"], True)
        self.assertEqual(coupling["read_status"], "read")
        self.assertEqual(coupling["selection_dimensions"], [2])
        self.assertEqual(coupling["selected_entity_ids"], [1])
        for name, actual in (("Fluid_physics", "spf"), ("Heat_physics", "ht_m0"), ("StudyStep", "std1/stat")):
            self.assertEqual(coupling["properties"][name], {"status": "read", "value_type": "String", "value": actual})
        material = e["missing_viscosity"]
        self.assertEqual(material["expression"], "")
        self.assertEqual(material["status"], "unresolved")
        self.assertIsNone(material["value"])
        self.assertIn("dynamicviscosity", material["reason"])
        self.assertNotIn("D:", material["reason"])


if __name__ == "__main__":
    unittest.main()
