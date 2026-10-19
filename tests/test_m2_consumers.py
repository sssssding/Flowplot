"""Synthetic M2 report consumers; recorded real API replay is a separate gate."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from flowpilot.check_model import CheckError, _write_json, render_report, sha256
from flowpilot.compare_reports import compare_reports
from flowpilot.desktop_session import diagnosis_view, load_completed_check
from flowpilot.diagnostic_modules import heat, thermal_coupling
from flowpilot.diagnostics import validate_diagnosis_report
from flowpilot.engine_fingerprint import ENGINE_SOURCES, engine_fingerprint, fingerprint_from_sources
from flowpilot.model_overview import build_overview
from flowpilot.recommend import recommend_report
from flowpilot.report_package import export_package
from m1_historical_sources import M1_SOURCES


def thermal_report():
    report = {'schema_version': 'diagnosis-0.3', 'run_status': 'completed', 'status': 'checked',
              'profile': 'thermal-static-v1', 'findings': [], 'coverage': [], 'modules': []}
    for module, kind, source in ((heat, 'physics', {'component_tag': 'comp1', 'physics_tag': 'ht'}),
                                 (thermal_coupling, 'coupling', {'component_tag': 'comp1', 'coupling_tag': 'nitf1'})):
        rules = [{'rule_id': spec[0], 'status': 'checked', 'reason': '测试已核验',
                  'dependencies': ['test_evidence'], 'evidence_refs': ['/components/0']} for spec in module.RULES]
        report['coverage'].append({'kind': kind, 'module': module.MODULE_ID, 'source': source,
                                  'status': 'checked', 'applicable': True, 'reason': '测试覆盖',
                                  'evidence_refs': ['/components/0'], 'rules': rules})
        report['modules'].append({'module': module.MODULE_ID, 'source': source, 'status': 'checked'})
        report['findings'].append({'code': rules[0]['rule_id'], 'severity': 'Warning', 'explanation': '合成定位测试',
                                   'feature_tags': ['node1'], 'boundary_ids': [2], 'evidence': {'test_only': True},
                                   'module': module.MODULE_ID, 'source': source, 'suggestion': '核对测试节点及耦合引用。'})
    validate_diagnosis_report(report)
    return report


def write_run(directory, report):
    directory.mkdir()
    _write_json(directory / 'diagnosis.json', report)
    metadata = {'schema_version': 'check-run-0.1', 'status': 'completed', 'diagnosis_status': report['status'],
                'source': {'filename': 'synthetic-thermal.mph', 'sha256': '1' * 64},
                'diagnosis_sha256': sha256(directory / 'diagnosis.json'), 'rule_engine_sha256': engine_fingerprint(),
                'inventory_source_sha256': '2' * 64, 'comsol_version': 'COMSOL 6.3 test-only',
                'verified_loads': 1, 'settings': {'reynolds_warning': 2000}}
    _write_json(directory / 'run.json', metadata)
    return metadata


class ThermalConsumerTests(unittest.TestCase):
    def test_generic_overview_and_coupling_location(self):
        report = thermal_report()
        snapshot = copy.deepcopy(report)
        overview = build_overview(report)
        self.assertTrue(overview['available'])
        self.assertEqual(overview['module_coverage'], report['coverage'])
        self.assertIn('检查覆盖', overview['text'])
        self.assertIn('nitf1', overview['text'])
        item = diagnosis_view(report)['items'][1]
        self.assertIn('COMSOL 定位：comp1 / nitf1', item['detail'])
        self.assertIn('node1', item['nodes'])
        self.assertIn('核对测试节点及耦合引用。', item['detail'])
        self.assertEqual(report, snapshot)

    def test_package_comparison_and_recommendation_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = thermal_report()
            metadata = write_run(root / 'report', report)
            self.assertIn('检查覆盖', render_report(report, metadata))
            self.assertEqual(load_completed_check(root / 'report')['report'], report)
            package = export_package(root / 'report', root / 'package')
            comparison = compare_reports(root / 'report', package)
            self.assertEqual(comparison['status'], 'compared')
            self.assertEqual(len(comparison['rows']), 2)
            with patch('flowpilot.recommend.read_regular_file', side_effect=AssertionError('No learned model should be read')):
                result = recommend_report(root / 'report')
            self.assertEqual(result['status'], 'unavailable')
            self.assertIn('diagnosis-0.3', result['reason'])
            self.assertEqual(result['ranking'], [])

    def test_comparison_keeps_distinct_coupling_instances(self):
        report = thermal_report()
        coverage = copy.deepcopy(report['coverage'][1])
        module = copy.deepcopy(report['modules'][1])
        finding = copy.deepcopy(report['findings'][1])
        for item in (coverage, module, finding):
            item['source']['coupling_tag'] = 'nitf2'
        report['coverage'].append(coverage)
        report['modules'].append(module)
        report['findings'].append(finding)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_run(root / 'report', report)
            comparison = compare_reports(root / 'report', root / 'report')
            self.assertEqual(comparison['status'], 'compared')
            self.assertEqual(len(comparison['rows']), 3)

    def test_new_report_requires_engine_identity_and_valid_coverage(self):
        report = thermal_report()
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'report'
            metadata = write_run(directory, report)
            metadata.pop('rule_engine_sha256')
            (directory / 'run.json').write_text(json.dumps(metadata), encoding='utf-8')
            with self.assertRaises(CheckError):
                load_completed_check(directory)
        report['coverage'][0]['status'] = 'unknown'
        with self.assertRaises(CheckError):
            diagnosis_view(report)
        self.assertFalse(build_overview(report)['available'])

    def test_heat_model_without_a_registered_contract_is_rejected(self):
        report = thermal_report()
        report['modules'][0]['model'] = {}
        with self.assertRaises(CheckError):
            diagnosis_view(report)
        self.assertFalse(build_overview(report)['available'])

    def test_engine_fingerprint_includes_heat_and_preserves_m1_identity(self):
        for name in ('flow_scope.py', 'heat.py', 'thermal_coupling.py'):
            self.assertIn('src/flowpilot/diagnostic_modules/' + name, ENGINE_SOURCES)
        old = M1_SOURCES['m1_consumer_smoke.json']
        legacy = {name: old[name] for name in ENGINE_SOURCES if name in old}
        expected = hashlib.sha256(json.dumps(legacy, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(fingerprint_from_sources(old), expected)
        new = {name: sha256(ROOT / name) for name in ENGINE_SOURCES}
        baseline = fingerprint_from_sources(new)
        for name in ('flow_scope.py', 'heat.py', 'thermal_coupling.py'):
            changed = dict(new)
            changed['src/flowpilot/diagnostic_modules/' + name] = '0' * 64
            self.assertNotEqual(fingerprint_from_sources(changed), baseline)


if __name__ == '__main__':
    unittest.main()
