"""Real API replay and two historical contracts must pass the current consumer stack."""
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


class M1ConsumerEvidenceTest(unittest.TestCase):
    def test_current_sources_and_real_replay_history_boundaries(self):
        spec = importlib.util.spec_from_file_location("m1_consumer_verifier", ROOT / "scripts/verify_m1_consumers.py")
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        evidence = json.loads((ROOT / "data/fixtures/m1_consumer_smoke.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["schema_version"], "m1-consumer-smoke-1")
        self.assertEqual(evidence["status"], "passed")
        self.assertEqual(evidence["implementation_sha256"], M1_SOURCES["m1_consumer_smoke.json"])
        self.assertEqual(evidence["rule_engine_sha256"], fingerprint_from_sources(M1_SOURCES["m1_consumer_smoke.json"]))
        for field in ("solved", "visible_gui_acceptance", "user_acceptance"):
            self.assertIs(evidence[field], False)
        self.assertIs(evidence["hidden_tk_only"], True)
        historical = [row for row in evidence["cases"] if row["origin"] == "historical_real_cli_report"]
        self.assertEqual(sum(row["contract"] == "diagnosis-0.1" for row in historical), 6)
        self.assertEqual(sum(row["contract"] == "diagnosis-0.2" for row in historical), 6)
        real = [row for row in evidence["cases"] if row["origin"] == "offline_replay_of_recorded_real_api_inventory"]
        self.assertEqual({row["case_id"] for row in real}, {"normal", "missing_inlet", "missing_outlet", "empty_inlet", "selection_overlap", "axis_wrong_selection", "legal_explicit_selection", "legal_slip_wall", "unsupported_inlet_mode", "closed_flow", "high_reynolds", "reversed_inlet", "invalid_material"})
        self.assertTrue(any(row["axis_coordinates_verified"] for row in real))
        for row in real:
            self.assertEqual(row["recommendation_status"], "unavailable")
            self.assertTrue(row["node_entity_location_verified"])
            self.assertEqual(row["api_summary_sha256"], evidence["api_summary_sha256"])
        for row in evidence["cases"]:
            self.assertTrue(row["hidden_widgets_verified"])
            self.assertTrue(row["history_verified"])
            self.assertTrue(row["package_roundtrip_verified"])
            self.assertEqual(row["comparison_status"], "compared" if row["status"] == "checked" else "not_comparable")


if __name__ == "__main__":
    unittest.main()
