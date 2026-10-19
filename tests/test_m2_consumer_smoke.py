"""Historical real API replay and report consumption retain their recorded M2 sources."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from flowpilot.check_model import sha256
from flowpilot.engine_fingerprint import fingerprint_from_sources
from m2_historical_sources import M2_SOURCES


class M2ConsumerEvidenceTests(unittest.TestCase):
    def test_real_replay_and_history_are_bound_to_current_sources(self):
        spec = importlib.util.spec_from_file_location('m2_consumer_verifier', ROOT / 'scripts/verify_m2_consumers.py')
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        evidence = json.loads((ROOT / 'data/fixtures/m2_consumer_smoke.json').read_text(encoding='utf-8'))
        self.assertEqual(evidence['schema_version'], 'm2-consumer-smoke-1')
        self.assertEqual(evidence['status'], 'passed')
        self.assertEqual(evidence['implementation_sha256'], M2_SOURCES['m2_consumer_smoke.json'])
        self.assertEqual(evidence['rule_engine_sha256'], fingerprint_from_sources(M2_SOURCES['m2_consumer_smoke.json']))
        for field in ('solved', 'visible_gui_acceptance', 'user_acceptance'):
            self.assertIs(evidence[field], False)
        self.assertIs(evidence['hidden_tk_only'], True)
        api = json.loads((ROOT / 'data/fixtures/m2_api_evidence.json').read_text(encoding='utf-8'))
        real = [row for row in evidence['cases'] if row['origin'] == 'offline_replay_of_recorded_real_api_inventory']
        self.assertEqual({row['case_id'] for row in real}, set(api['verified_models']))
        self.assertTrue(real)
        self.assertTrue(any(row['contract'] == 'diagnosis-0.3' for row in real))
        self.assertTrue(any(finding.get('coupling_tag') for row in real for finding in row['finding_sources']))
        historical = [row for row in evidence['cases'] if row['origin'] == 'historical_real_cli_report']
        self.assertTrue(any(row['contract'] == 'diagnosis-0.1' for row in historical))
        self.assertTrue(any(row['case_id'].startswith('m0_') for row in historical))
        self.assertTrue(any(row['case_id'].startswith('m1_') for row in historical))
        for row in real:
            self.assertEqual(row['recommendation_status'], 'unavailable')
            self.assertTrue(row['node_entity_location_verified'])
            self.assertEqual(row['api_summary_sha256'], evidence['api_summary_sha256'])
        for row in evidence['cases']:
            for field in ('hidden_widgets_verified', 'history_verified', 'package_roundtrip_verified'):
                self.assertTrue(row[field])
            self.assertEqual(row['comparison_status'], 'compared' if row['status'] == 'checked' else 'not_comparable')


if __name__ == '__main__':
    unittest.main()
