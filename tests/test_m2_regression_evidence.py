"""Historical M2 planar regression retains its frozen engine and twenty pinned cases."""
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
from flowpilot.regression_family import SPECS


class M2PlanarEvidenceTests(unittest.TestCase):
    def test_twenty_planar_results_under_current_sources(self):
        spec = importlib.util.spec_from_file_location('m2_regression_verifier', ROOT / 'scripts/verify_m2_regression.py')
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        evidence = json.loads((ROOT / 'data/fixtures/m2_planar_regression.json').read_text(encoding='utf-8'))
        self.assertEqual(evidence['schema_version'], 'm2-planar-regression-1')
        self.assertEqual(evidence['status'], 'passed')
        self.assertEqual(evidence['implementation_sha256'], M2_SOURCES['m2_planar_regression.json'])
        self.assertEqual(evidence['rule_engine_sha256'], fingerprint_from_sources(M2_SOURCES['m2_planar_regression.json']))
        self.assertEqual(evidence['baseline_commit'], '1241c27')
        self.assertEqual((evidence['case_count'], evidence['fresh_cli_inventory_count'], evidence['historical_inventory_replay_count']), (20, 6, 14))
        for field in ('new_comsol_execution', 'solved', 'independent_acceptance_set', 'expert_review'):
            self.assertIs(evidence[field], False)
        self.assertEqual(len(evidence['cases']), 20)
        historical = {row['case_id'] for row in evidence['cases'] if row['origin'] == 'historical_real_inventory_replay'}
        self.assertEqual(historical, {spec[0] for spec in SPECS})
        for row in evidence['cases']:
            self.assertTrue(row['legacy_payload_equal'])
            self.assertEqual(row['actual_codes'], row['expected_codes'])
            self.assertEqual(row['status'], 'checked')
            if row['origin'] == 'fresh_real_cli_inventory':
                self.assertEqual(row['input_rule_engine_sha256'], fingerprint_from_sources(M2_SOURCES['m2_planar_regression.json']))
            else:
                self.assertTrue(row['independent_spec_evidence']['passed'])
                self.assertEqual(row['independent_spec_evidence']['mismatches'], [])


if __name__ == '__main__':
    unittest.main()
