"""Mandatory recorded M3 consumer/demo evidence, distinct from visible acceptance."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from flowpilot.check_model import sha256
from flowpilot.engine_fingerprint import engine_fingerprint


def verifier(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class M3ConsumptionEvidenceTests(unittest.TestCase):
    def evidence(self, filename):
        value = json.loads((ROOT / 'data/fixtures' / filename).read_text(encoding='utf-8'))
        self.assertEqual(value['status'], 'passed')
        self.assertFalse(value['solved'])
        self.assertFalse(value['visible_gui_acceptance'])
        self.assertFalse(value['user_acceptance'])
        self.assertEqual(value['rule_engine_sha256'], engine_fingerprint())
        return value

    def test_hidden_tk_consumer_evidence_bound_to_current_sources(self):
        module = verifier('verify_m3_consumers')
        evidence = self.evidence('m3_consumer_smoke.json')
        self.assertEqual(evidence['schema_version'], 'm3-consumer-smoke-1')
        self.assertTrue(evidence['hidden_tk_only'])
        self.assertEqual(evidence['implementation_sha256'], {name: sha256(ROOT / name) for name in module.CONSUMER_SOURCES})
        rows = evidence['cases']
        self.assertTrue(rows)
        self.assertEqual({row['contract'] for row in rows}, {'diagnosis-0.1', 'diagnosis-0.2', 'diagnosis-0.3', 'diagnosis-0.4'})
        self.assertTrue(any(row['case_id'].startswith('m2_') for row in rows))
        self.assertTrue(any(row['case_id'].startswith('m1_') for row in rows))
        for row in rows:
            for field in ('hidden_widgets_verified', 'history_verified', 'package_roundtrip_verified'):
                self.assertTrue(row[field])
            if row['origin'] != 'historical_real_cli_report':
                self.assertEqual(row['contract'], 'diagnosis-0.4')
                self.assertEqual(row['rule_engine_sha256'], engine_fingerprint())
                self.assertTrue(row['node_entity_location_verified'])
                self.assertEqual(row['recommendation_status'], 'unavailable')

    def test_three_formal_cli_demonstrations_bind_sources_models_and_packages(self):
        module = verifier('verify_m3_demo')
        evidence = self.evidence('m3_demo_evidence.json')
        self.assertEqual(evidence['schema_version'], 'm3-demo-evidence-1')
        expected = {name: sha256(ROOT / name) for name in module.SOURCES}
        self.assertEqual(evidence['implementation_sha256'], expected)
        self.assertEqual(evidence['implementation_sha256_after'], expected)
        self.assertTrue(evidence['source_models_unchanged'])
        self.assertEqual(evidence['source_model_sha256'], evidence['source_model_sha256_after'])
        self.assertEqual(evidence['api_summary_sha256'], evidence['api_summary_sha256_after'])
        self.assertEqual(set(evidence['source_model_sha256']), {'normal.mph', 'reversed_inlet.mph', 'conjugate_normal.mph'})
        self.assertEqual([row['round'] for row in evidence['cases']], [1, 1, 1, 2, 2, 2, 3, 3, 3])
        self.assertEqual([row['check'] for row in evidence['cases']], list(range(1, 10)))
        self.assertEqual({row['case_id'] for row in evidence['cases']}, {'normal', 'reversed_inlet', 'conjugate_normal'})
        for row in evidence['cases']:
            self.assertEqual(row['contract'], 'diagnosis-0.4')
            self.assertEqual(row['status'], 'checked')
            self.assertEqual(row['verified_loads'], 1)
            self.assertEqual(row['finding_codes'], ['INLET_DIRECTION'] if row['case_id'] == 'reversed_inlet' else [])
            self.assertEqual(row['rule_engine_sha256'], engine_fingerprint())
            self.assertTrue(row['node_entity_location_verified'])
            self.assertTrue(row['report_package_roundtrip_verified'])
            self.assertEqual(row['comparison_status'], 'compared')
            if row['finding_codes']:
                self.assertTrue(all(source['component_tag'] and source['physics_tag'] for source in row['finding_sources']))
                self.assertTrue(all(ids for ids in row['finding_entity_ids']))


if __name__ == '__main__':
    unittest.main()
