"""M3 consumers and explicit 3D thermal geometry counterexamples (synthetic)."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from flowpilot.check_model import CheckError, render_report
from flowpilot.compare_reports import compare_reports
from flowpilot.desktop_session import diagnosis_view, load_completed_check
from flowpilot.diagnostic_modules import heat
from flowpilot.diagnostics import validate_diagnosis_report
from flowpilot.engine_fingerprint import ENGINE_SOURCES, fingerprint_from_sources
from flowpilot.model_overview import build_overview
from flowpilot.recommend import recommend_report
from flowpilot.report_package import export_package
from test_m2_consumers import thermal_report, write_run
from test_heat_diagnostics import inventory


def spatial_report():
    report = thermal_report()
    report.update(schema_version='diagnosis-0.4', profile='static-3d-v1')
    validate_diagnosis_report(report)
    return report


def spatial_heat():
    result = inventory()
    geometry = result['components'][0]['geometries'][0]
    geometry.update(dimension=3, domain_count=1, boundary_count=2,
                    three_dimensional_evidence={'read_status': 'read',
                        'domains': [{'domain_id': 1, 'boundary_ids': [1, 2], 'volume': 1.0}],
                        'boundaries': [{'boundary_id': i, 'domain_ids': [1], 'area': 1.0} for i in (1, 2)]})
    for feature in result['components'][0]['physics'][0]['features']:
        feature['selection_dimensions'] = [3] if feature['type'] in heat.DOMAIN_TYPES else [2]
    return result


class SpatialConsumerTests(unittest.TestCase):
    def test_envelope_location_package_compare_and_recommendation(self):
        report = spatial_report()
        original = copy.deepcopy(report)
        self.assertTrue(build_overview(report)['available'])
        item = diagnosis_view(report)['items'][1]
        self.assertIn('COMSOL 定位：comp1 / nitf1', item['detail'])
        self.assertIn('node1', item['nodes'])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            metadata = write_run(root / 'report', report)
            rendered = render_report(report, metadata)
            self.assertIn('检查覆盖', rendered)
            self.assertIn('受控直圆管及流体/管壁传热配置', rendered)
            self.assertIn('已核验流体管径 D', rendered)
            self.assertIn('规则覆盖及面、材料、端口证据为准', rendered)
            self.assertNotIn('流动检查限已核验的二维', rendered)
            self.assertNotIn('矩形模板以通道高度 H', rendered)
            legacy = thermal_report()
            legacy_rendered = render_report(legacy, metadata)
            self.assertIn('流动检查限已核验的二维平面或二维轴对称配置', legacy_rendered)
            self.assertIn('矩形模板以通道高度 H', legacy_rendered)
            self.assertEqual(load_completed_check(root / 'report')['report'], report)
            package = export_package(root / 'report', root / 'package')
            self.assertEqual(load_completed_check(package)['report'], report)
            self.assertEqual(compare_reports(root / 'report', package)['status'], 'compared')
            with patch('flowpilot.recommend.read_regular_file', side_effect=AssertionError('No calibration access')):
                recommendation = recommend_report(root / 'report')
            self.assertEqual(recommendation['status'], 'unavailable')
            self.assertIn('diagnosis-0.4', recommendation['reason'])
            self.assertEqual(recommendation['ranking'], [])
        self.assertEqual(report, original)

    def test_3d_contract_rejects_wrong_profile_and_missing_engine(self):
        report = spatial_report()
        report['profile'] = 'thermal-static-v1'
        with self.assertRaises(ValueError):
            validate_diagnosis_report(report)
        report = spatial_report()
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'report'
            metadata = write_run(directory, report)
            metadata.pop('rule_engine_sha256')
            (directory / 'run.json').write_text(json.dumps(metadata), encoding='utf-8')
            with self.assertRaises(CheckError):
                load_completed_check(directory)

    def test_3d_module_overview_exposes_material_ports_and_face_selections(self):
        from test_3d_flow import inventory as flow_inventory
        from flowpilot.diagnostics import diagnose_inventory
        report = diagnose_inventory(flow_inventory())
        overview = build_overview(report)
        self.assertTrue(overview['available'])
        self.assertEqual(len(overview['boundaries']), len(report['modules'][0]['model']['boundaries']))
        for text in ('声明面', '实际生效面', '流体材料参数', '入口法向速度', '出口压力'):
            self.assertIn(text, overview['text'])
        for version in ('diagnosis-0.2', 'diagnosis-0.3'):
            downgraded = copy.deepcopy(report)
            downgraded.update(schema_version=version, profile='thermal-static-v1')
            with self.assertRaisesRegex(ValueError, 'diagnosis-0.4'):
                validate_diagnosis_report(downgraded)
            self.assertFalse(build_overview(downgraded)['available'])

    def test_m3_engine_manifest_requires_the_m2_dependencies(self):
        hashes = {name: '1' * 64 for name in ENGINE_SOURCES}
        for name in ('flow_scope.py', 'heat.py', 'thermal_coupling.py'):
            hashes.pop('src/flowpilot/diagnostic_modules/' + name)
        with self.assertRaises(KeyError):
            fingerprint_from_sources(hashes)

    def test_face_and_domain_dimensions_are_distinct(self):
        data = spatial_heat()
        self.assertEqual(heat.run_instance(data, 0, 0, [])['status'], 'checked')
        data['components'][0]['physics'][0]['features'][1]['selection_dimensions'] = [1]
        result = heat.run_instance(data, 0, 0, [])
        self.assertEqual(next(r for r in result['rules'] if r['rule_id'] == 'HEAT_EMPTY_BOUNDARY_SELECTION')['status'], 'skipped')

    def test_missing_or_contradictory_geometry_skips_without_false_findings(self):
        for mutation in ('missing', 'partial', 'zero_volume', 'zero_area', 'adjacency', 'reverse_adjacency', 'foreign_face'):
            with self.subTest(mutation=mutation):
                data = spatial_heat()
                geometry = data['components'][0]['geometries'][0]
                evidence = geometry['three_dimensional_evidence']
                if mutation == 'missing':
                    del geometry['three_dimensional_evidence']
                elif mutation == 'partial':
                    evidence['read_status'] = 'partial'
                elif mutation == 'zero_volume':
                    evidence['domains'][0]['volume'] = 0
                elif mutation == 'zero_area':
                    evidence['boundaries'][0]['area'] = 0
                elif mutation == 'adjacency':
                    evidence['boundaries'][0]['domain_ids'] = [2]
                elif mutation == 'reverse_adjacency':
                    geometry['domain_count'] = 2
                    evidence['domains'].append({'domain_id': 2, 'boundary_ids': [1], 'volume': 1.0})
                else:
                    data['components'][0]['physics'][0]['features'][1]['selected_entity_ids'] = [99]
                result = heat.run_instance(data, 0, 0, [])
                self.assertTrue(all(r['status'] == 'skipped' for r in result['rules']))
                self.assertEqual(result['findings'], [])

    def test_old_engine_generations_hash_their_complete_recorded_sets(self):
        from m2_historical_sources import M2_SOURCES
        import hashlib
        old = M2_SOURCES['m2_consumer_smoke.json']
        selected = {name: old[name] for name in ENGINE_SOURCES if name in old}
        expected = hashlib.sha256(json.dumps(selected, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(fingerprint_from_sources(old), expected)


if __name__ == '__main__':
    unittest.main()
