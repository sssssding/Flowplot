"""M1 planar evidence must bind current implementation and retain all pinned results."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.check_model import sha256
from flowpilot.engine_fingerprint import fingerprint_from_sources
from m1_historical_sources import M1_SOURCES
from flowpilot.regression_family import SPECS


class M1PlanarRegressionEvidenceTest(unittest.TestCase):
    def test_current_sources_and_twenty_planar_matches(self):
        spec = importlib.util.spec_from_file_location("m1_regression_verifier", ROOT / "scripts/verify_m1_regression.py")
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        evidence = json.loads((ROOT / "data/fixtures/m1_planar_regression.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["schema_version"], "m1-planar-regression-1")
        self.assertEqual(evidence["status"], "passed")
        self.assertEqual(evidence["implementation_sha256"], M1_SOURCES["m1_planar_regression.json"])
        self.assertEqual(evidence["rule_engine_sha256"], fingerprint_from_sources(M1_SOURCES["m1_planar_regression.json"]))
        self.assertEqual(evidence["baseline_commit"], "1241c27")
        self.assertEqual((evidence["case_count"], evidence["fresh_cli_inventory_count"], evidence["historical_inventory_replay_count"]), (20, 6, 14))
        for field in ("new_comsol_execution", "solved", "independent_acceptance_set", "expert_review"):
            self.assertIs(evidence[field], False)
        rows = evidence["cases"]
        self.assertEqual(len(rows), 20)
        self.assertEqual(sum(row["origin"] == "fresh_real_cli_inventory" for row in rows), 6)
        historical = {row["case_id"]: row for row in rows if row["origin"] == "historical_real_inventory_replay"}
        self.assertEqual(set(historical), {spec[0] for spec in SPECS})
        for row in rows:
            self.assertTrue(row["legacy_payload_equal"])
            self.assertEqual(row["actual_codes"], row["expected_codes"])
            self.assertEqual(row["status"], "checked")
            if row["origin"] == "fresh_real_cli_inventory":
                self.assertEqual(row["input_rule_engine_sha256"], fingerprint_from_sources(M1_SOURCES["m1_planar_regression.json"]))
            else:
                self.assertTrue(row["independent_spec_evidence"]["passed"])
                self.assertEqual(row["independent_spec_evidence"]["mismatches"], [])


if __name__ == "__main__":
    unittest.main()
