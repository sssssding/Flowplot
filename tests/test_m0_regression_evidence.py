"""Versioned M0 regression evidence preserves old payloads and independent specs."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.check_model import sha256
from flowpilot.engine_fingerprint import engine_fingerprint
from flowpilot.regression_family import SPECS

FIXTURE = ROOT / "data/fixtures/m0_regression.json"
BASELINE_SOURCES = {
    "src/flowpilot/diagnostics.py": "2a91cdcd061988106b8720a4f179652a7b315663a8b7d6d4cd9f29f90af9e616",
    "schema/diagnostic-model.schema.json": "05ebdef4c846e053a180cda4d50761a387050756c0ebd65d7c53b21ecba866ef",
    "src/comsol/ModelInventory.java": "1a3e94dc3df8598d155d56a86b9a03e1c8f262ffbe1ba244b039a1e2df2e6b84",
}


class M0RegressionEvidenceTest(unittest.TestCase):
    def test_current_sources_twenty_matches_and_honest_origins(self):
        spec = importlib.util.spec_from_file_location("m0_regression_verifier", ROOT / "scripts/verify_m0_regression.py")
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        evidence = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(evidence["schema_version"], "m0-regression-evidence-1")
        self.assertEqual(evidence["status"], "passed")
        self.assertEqual(evidence["baseline_commit"], "1241c27")
        self.assertEqual(evidence["baseline_source_sha256"], BASELINE_SOURCES)
        self.assertEqual(evidence["implementation_sha256"], {name: sha256(ROOT / name) for name in verifier.SOURCES})
        self.assertEqual(evidence["rule_engine_sha256"], engine_fingerprint())
        self.assertEqual((evidence["case_count"], evidence["fresh_cli_inventory_count"],
                          evidence["historical_inventory_replay_count"]), (20, 6, 14))
        for field in ("new_comsol_execution", "solved", "independent_acceptance_set", "expert_review"):
            self.assertIs(evidence[field], False)
        rows = evidence["cases"]
        self.assertEqual(len(rows), 20)
        self.assertEqual(sum(row["origin"] == "fresh_real_cli_inventory" for row in rows), 6)
        replay = {row["case_id"]: row for row in rows if row["origin"] == "historical_real_inventory_replay"}
        self.assertEqual(set(replay), {spec[0] for spec in SPECS})
        for name, expected, *_ in SPECS:
            self.assertEqual(replay[name]["expected_codes"], sorted(expected))
            self.assertTrue(replay[name]["independent_spec_evidence"]["passed"])
            self.assertEqual(replay[name]["independent_spec_evidence"]["mismatches"], [])
        for row in rows:
            self.assertTrue(row["legacy_payload_equal"])
            self.assertEqual(row["status"], "checked")
            self.assertEqual(row["actual_codes"], row["expected_codes"])
            for field in ("inventory_canonical_sha256", "inventory_file_sha256", "source_model_sha256",
                          "input_diagnosis_sha256", "input_run_sha256", "legacy_payload_sha256"):
                self.assertRegex(row[field], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
