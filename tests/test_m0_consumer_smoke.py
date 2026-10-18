"""The recorded hidden-widget smoke binds actual report origins to current sources."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.check_model import sha256
from flowpilot.engine_fingerprint import engine_fingerprint

FIXTURE = ROOT / "data/fixtures/m0_consumer_smoke.json"


class RecordedConsumerSmokeTest(unittest.TestCase):
    def test_current_sources_and_honest_evidence_scope(self):
        spec = importlib.util.spec_from_file_location("m0_consumer_verifier", ROOT / "scripts/verify_m0_consumers.py")
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        summary = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(summary["schema_version"], "m0-consumer-smoke-1")
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["rule_engine_sha256"], engine_fingerprint())
        self.assertEqual(summary["implementation_sha256"],
                         {name: sha256(ROOT / name) for name in verifier.CONSUMER_SOURCES})
        for field in ("solved", "visible_gui_acceptance", "user_acceptance"):
            self.assertIs(summary[field], False)
        self.assertIs(summary["hidden_tk_only"], True)
        rows = {row["case_id"]: row for row in summary["cases"]}
        self.assertEqual(rows["baseline"]["recommendation_status"], "recommended")
        self.assertEqual(sum(row["origin"] == "fresh_real_cli_report" for row in rows.values()), 6)
        for name in ("api_unknown_physics", "api_unknown_coupling"):
            row = rows[name]
            self.assertIn(row["status"], ("partial", "unsupported"))
            self.assertEqual(row["tone"], "incomplete")
            self.assertEqual(row["comparison_status"], "not_comparable")
            self.assertEqual(row["recommendation_status"], "unavailable")
        for row in rows.values():
            self.assertTrue(row["hidden_widgets_verified"])
            self.assertTrue(row["history_verified"])
            self.assertTrue(row["package_roundtrip_verified"])
            if row["origin"] == "historical_real_cli_report":
                self.assertEqual(row["contract"], "diagnosis-0.1")
                self.assertIsNone(row["coverage"])


if __name__ == "__main__":
    unittest.main()
