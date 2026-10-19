import copy
import json
from pathlib import Path
import sys
import unittest

from jsonschema import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from flowpilot.diagnostics import check, diagnose_inventory, normalize, validate_diagnosis_report


def load(name='baseline'):
    return json.loads((ROOT / 'data' / 'fixtures' / 'cases' / (name + '.json')).read_text(encoding='utf-8-sig'))


def flow_scope(report, component='comp1', physics='spf'):
    return next(c for c in report['coverage'] if c['kind'] == 'physics' and
                c['source']['component_tag'] == component and c['source']['physics_tag'] == physics)


class ModularDiagnosisTests(unittest.TestCase):
    def test_original_fixtures_preserve_all_legacy_finding_payloads(self):
        for case in load('manifest')['cases']:
            with self.subTest(case=case['case_id']):
                data = load(case['case_id'])
                expected = check(normalize(data))
                report = diagnose_inventory(data)
                self.assertEqual(report['schema_version'], 'diagnosis-0.2')
                self.assertEqual(report['run_status'], 'completed')
                self.assertEqual(report['status'], 'checked')
                self.assertEqual(report['profile'], expected['profile'])
                actual = [{k: v for k, v in f.items() if k not in ('source', 'module')} for f in report['findings']]
                self.assertEqual(actual, expected['findings'])
                self.assertEqual(report['modules'][0]['model'], report['model'])
                self.assertTrue(all(r['status'] == 'checked' for r in flow_scope(report)['rules']))

    def test_proven_invalid_material_preserves_complete_configuration_checks(self):
        data = load()
        data['components'][0]['materials'][0]['dynamic_viscosity']['value'] = 0
        report = diagnose_inventory(data)
        self.assertEqual(report['status'], 'checked')
        self.assertEqual([f['code'] for f in report['findings']], ['INVALID_MATERIAL_PARAMETER'])
        rule = next(r for r in flow_scope(report)['rules'] if r['rule_id'] == 'REYNOLDS_RISK')
        self.assertEqual(rule['status'], 'checked')
        self.assertIn('Re', rule['cases'][0]['reason'])

    def test_known_invalid_material_survives_other_unresolved_constant(self):
        for invalid, missing in (('density', 'dynamic_viscosity'), ('dynamic_viscosity', 'density')):
            data = load()
            material = data['components'][0]['materials'][0]
            material[invalid]['value'] = -1
            material[missing].update(status='unresolved', value=None)
            second = copy.deepcopy(load('missing_inlet')['components'][0])
            second['tag'] = 'comp2'
            data['components'].append(second)
            report = diagnose_inventory(data)
            self.assertEqual(report['status'], 'partial')
            self.assertEqual({(f['source']['component_tag'], f['code']) for f in report['findings']},
                             {('comp1', 'INVALID_MATERIAL_PARAMETER'), ('comp1', 'EVALUATION_UNAVAILABLE'),
                              ('comp2', 'MISSING_INLET')})
            rules = {r['rule_id']: r for r in flow_scope(report)['rules']}
            self.assertEqual(rules['INVALID_MATERIAL_PARAMETER']['status'], 'checked')
            self.assertEqual(rules['REYNOLDS_RISK']['status'], 'skipped')
            self.assertEqual(flow_scope(report, 'comp2')['status'], 'checked')

    def test_unknown_interface_does_not_erase_independent_flow_findings(self):
        data = load('missing_inlet')
        data['components'][0]['physics'].append({'tag': 'ht', 'type': 'SolidMechanics', 'enabled': True})
        report = diagnose_inventory(data)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual([f['code'] for f in report['findings']], ['MISSING_INLET'])
        self.assertEqual(flow_scope(report)['status'], 'checked')
        self.assertEqual(flow_scope(report, physics='ht')['status'], 'unknown')
        self.assertNotIn('model', report)
        self.assertIn('model', report['modules'][0])

    def test_only_unknown_interface_has_completed_unsupported_coverage(self):
        data = load()
        data['components'][0]['physics'] = [{'tag': 'ht', 'type': 'SolidMechanics', 'enabled': True}]
        report = diagnose_inventory(data)
        self.assertEqual(report['run_status'], 'completed')
        self.assertEqual(report['status'], 'unsupported')
        self.assertEqual(report['findings'], [])
        self.assertEqual(flow_scope(report, physics='ht')['status'], 'unknown')

    def test_enabled_unknown_coupling_gates_dependent_rules(self):
        for scope in ('global', 'component'):
            with self.subTest(scope=scope):
                data = load('missing_inlet')
                target = data if scope == 'global' else data['components'][0]
                target['multiphysics_tags'] = ['n1']
                report = diagnose_inventory(data)
                self.assertEqual(report['status'], 'partial')
                self.assertEqual(report['findings'], [])
                rules = {r['rule_id']: r for r in flow_scope(report)['rules']}
                self.assertEqual(rules['INVALID_MATERIAL_PARAMETER']['status'], 'checked')
                for code in ('MISSING_INLET', 'MISSING_OUTLET', 'BC_SELECTION_OVERLAP', 'INLET_DIRECTION', 'REYNOLDS_RISK'):
                    self.assertEqual(rules[code]['status'], 'skipped')
                    self.assertIn('coupling_scope_and_semantics', rules[code]['dependencies'])
                    self.assertTrue(any('multiphysics' in ref for ref in rules[code]['evidence_refs']))
                coupling = next(c for c in report['coverage'] if c['kind'] == 'coupling')
                self.assertEqual(coupling['status'], 'unknown')

    def test_invalid_material_is_still_provable_when_coupling_blocks_flow(self):
        data = load('missing_inlet')
        data['multiphysics_tags'] = ['n1']
        data['components'][0]['materials'][0]['density']['value'] = -1
        report = diagnose_inventory(data)
        self.assertEqual([f['code'] for f in report['findings']], ['INVALID_MATERIAL_PARAMETER'])
        self.assertEqual(report['findings'][0]['source']['component_tag'], 'comp1')

    def test_component_coupling_leaves_another_component_independent(self):
        data = load('missing_inlet')
        second = copy.deepcopy(load('missing_outlet')['components'][0])
        second['tag'] = 'comp2'
        data['components'].append(second)
        data['components'][0]['multiphysics_tags'] = ['n1']
        report = diagnose_inventory(data)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual([(f['source']['component_tag'], f['code']) for f in report['findings']], [('comp2', 'MISSING_OUTLET')])
        self.assertEqual(flow_scope(report, 'comp2')['status'], 'checked')
        self.assertNotIn('model', report)

    def test_global_coupling_gates_every_component(self):
        data = load('missing_inlet')
        second = copy.deepcopy(data['components'][0])
        second['tag'] = 'comp2'
        data['components'].append(second)
        data['multiphysics_tags'] = ['n1']
        report = diagnose_inventory(data)
        self.assertEqual(report['findings'], [])
        self.assertTrue(all(c['status'] == 'skipped' for c in report['coverage'] if c['kind'] == 'physics'))

    def test_root_alias_uses_verified_component_owner_and_unique_model_path(self):
        data = load('missing_inlet')
        second = copy.deepcopy(load('missing_outlet')['components'][0])
        second['tag'] = 'comp2'
        data['components'].append(second)
        detail = {'tag': 'n1', 'enabled': True, 'read_status': 'read',
                  'component_tag': 'comp1', 'model_path': '/multiphysics/n1'}
        data['multiphysics_tags'] = ['n1']
        data['multiphysics'] = [copy.deepcopy(detail)]
        data['components'][0]['multiphysics_tags'] = ['n1']
        data['components'][0]['multiphysics'] = [copy.deepcopy(detail)]
        report = diagnose_inventory(data)
        couplings = [c for c in report['coverage'] if c['kind'] == 'coupling']
        self.assertEqual(len(couplings), 1)
        self.assertEqual(couplings[0]['source']['component_tag'], 'comp1')
        self.assertEqual(set(couplings[0]['evidence_refs']),
                         {'/multiphysics/0', '/components/0/multiphysics/0'})
        self.assertEqual(flow_scope(report, 'comp2')['status'], 'checked')
        self.assertEqual([(f['source']['component_tag'], f['code']) for f in report['findings']],
                         [('comp2', 'MISSING_OUTLET')])

    def test_incomplete_or_conflicting_root_ownership_remains_global(self):
        for root_patch in ({'model_path': None}, {'component_tag': None}, {'component_tag': 'unknown'},
                           {'model_path': '/different/path'}, {'read_status': 'unread'}):
            data = load('missing_inlet')
            second = copy.deepcopy(data['components'][0])
            second['tag'] = 'comp2'
            data['components'].append(second)
            detail = {'tag': 'n1', 'enabled': True, 'read_status': 'read',
                      'component_tag': 'comp1', 'model_path': '/multiphysics/n1'}
            data['multiphysics_tags'] = ['n1']
            data['multiphysics'] = [{**detail, **root_patch}]
            data['components'][0]['multiphysics_tags'] = ['n1']
            data['components'][0]['multiphysics'] = [copy.deepcopy(detail)]
            report = diagnose_inventory(data)
            self.assertEqual(report['findings'], [])
            self.assertEqual(flow_scope(report, 'comp2')['status'], 'skipped')
            self.assertTrue(any(c['kind'] == 'coupling' and c['source']['component_tag'] == ''
                                for c in report['coverage']))

    def test_disabled_coupling_needs_explicit_successful_read_evidence(self):
        for read_status in ('read', 'partial', 'unread'):
            data = load('missing_inlet')
            data['multiphysics_tags'] = ['n1']
            data['multiphysics'] = [{'tag': 'n1', 'enabled': False, 'read_status': read_status}]
            report = diagnose_inventory(data)
            self.assertEqual(report['status'], 'checked' if read_status == 'read' else 'partial')
            self.assertEqual(bool(report['findings']), read_status == 'read')

    def test_details_not_present_in_legacy_tag_list_are_not_lost(self):
        data = load('missing_inlet')
        data['components'][0]['multiphysics'] = [{'tag': 'n1', 'enabled': True, 'read_status': 'read'}]
        report = diagnose_inventory(data)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['findings'], [])
        self.assertEqual(next(c for c in report['coverage'] if c['kind'] == 'coupling')['source']['coupling_tag'], 'n1')

    def test_missing_coupling_enumeration_is_unknown_not_uncoupled(self):
        data = load('missing_inlet')
        del data['multiphysics_tags']
        report = diagnose_inventory(data)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['findings'], [])
        self.assertTrue(any(c['source'].get('coupling_tag') == '@unrecorded' for c in report['coverage']))

    def test_multiple_instances_with_same_node_tags_are_source_qualified(self):
        data = load('missing_inlet')
        second = copy.deepcopy(data['components'][0]['physics'][0])
        second['tag'] = 'spf2'
        data['components'][0]['physics'].append(second)
        report = diagnose_inventory(data)
        self.assertEqual(report['status'], 'checked')
        self.assertEqual(len(report['findings']), 2)
        self.assertEqual([f['source']['physics_tag'] for f in report['findings']], ['spf', 'spf2'])
        self.assertEqual(len(report['modules']), 2)
        self.assertNotIn('model', report)
        self.assertEqual([m['model']['source']['physics_tag'] for m in report['modules']], ['spf', 'spf2'])

    def test_axisymmetric_requires_new_evidence_and_3d_remains_unsupported(self):
        data = load()
        data['components'][0]['geometries'][0]['axisymmetric'] = True
        report = diagnose_inventory(data)
        self.assertEqual(report['status'], 'partial')
        rules = {r['rule_id']: r for r in flow_scope(report)['rules']}
        self.assertEqual(rules['AXIS_SELECTION_INCONSISTENT']['status'], 'skipped')
        self.assertEqual(rules['REYNOLDS_RISK']['status'], 'skipped')
        self.assertEqual(rules['INVALID_MATERIAL_PARAMETER']['status'], 'checked')
        data = load()
        data['components'][0]['geometries'][0]['dimension'] = 3
        report = diagnose_inventory(data)
        self.assertEqual(report['status'], 'unsupported')
        self.assertTrue(all(r['status'] == 'skipped' for r in flow_scope(report)['rules']))

    def test_missing_flow_evidence_has_traceable_skips(self):
        data = load()
        del data['components'][0]['materials'][0]['density']
        report = diagnose_inventory(data)
        self.assertEqual(report['status'], 'unsupported')
        for rule in flow_scope(report)['rules']:
            self.assertEqual(rule['status'], 'skipped')
            self.assertTrue(rule['reason'])
            self.assertTrue(rule['dependencies'])
            self.assertTrue(rule['evidence_refs'])

    def test_unresolved_evidence_is_partial_and_does_not_pass_rules(self):
        data = load()
        data['components'][0]['materials'][0]['density'].update(status='unresolved', value=None)
        report = diagnose_inventory(data)
        self.assertEqual(report['status'], 'partial')
        self.assertIn('EVALUATION_UNAVAILABLE', [f['code'] for f in report['findings']])
        rules = {r['rule_id']: r for r in flow_scope(report)['rules']}
        self.assertEqual(rules['INVALID_MATERIAL_PARAMETER']['status'], 'skipped')
        self.assertEqual(rules['REYNOLDS_RISK']['status'], 'skipped')
        self.assertEqual(rules['MISSING_INLET']['status'], 'checked')

    def test_explicitly_unused_material_does_not_block_unique_flow_material(self):
        for unused in ({'enabled': True, 'domain_ids': []}, {'enabled': False, 'domain_ids': [1]}):
            data = load()
            data['components'][0]['materials'].append({'tag': 'unused', **unused})
            report = diagnose_inventory(data)
            self.assertEqual(report['status'], 'checked')
            self.assertEqual(report['findings'], [])
            self.assertNotIn('model', report)
            self.assertIn('model', report['modules'][0])

    def test_extra_selected_or_unknown_domain_material_remains_unsupported(self):
        for domains in ([1], [2], None):
            data = load()
            extra = {'tag': 'other', 'enabled': True}
            if domains is not None:
                extra['domain_ids'] = domains
            data['components'][0]['materials'].append(extra)
            self.assertEqual(diagnose_inventory(data)['status'], 'unsupported')

    def test_additive_unresolved_scalar_reason_remains_legacy_compatible(self):
        data = load()
        value = data['components'][0]['materials'][0]['dynamic_viscosity']
        value.update(status='unresolved', value=None, reason='material has no viscosity')
        report = diagnose_inventory(data)
        self.assertEqual(report['status'], 'partial')
        self.assertNotIn('reason', report['model']['material']['dynamic_viscosity'])
        self.assertIn('EVALUATION_UNAVAILABLE', [f['code'] for f in report['findings']])

    def test_unread_active_node_is_traceably_skipped(self):
        data = load()
        data['components'][0]['physics'][0]['features'][0] = {
            'tag': 'unread1', 'type': 'Inlet', 'enabled': True,
            'read_status': 'unread', 'reason': 'API properties not readable'}
        report = diagnose_inventory(data)
        self.assertEqual(report['status'], 'unsupported')
        self.assertIn('API properties not readable', flow_scope(report)['reason'])

    def test_partial_numeric_evaluation_preserves_other_provable_findings(self):
        data = load('reversed_inlet')
        outlet = next(f for f in data['components'][0]['physics'][0]['features'] if f['type'] == 'Outlet')
        outlet['evaluated_parameters']['pressure'].update(status='unresolved', value=None)
        report = diagnose_inventory(data)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual({f['code'] for f in report['findings']}, {'EVALUATION_UNAVAILABLE', 'INLET_DIRECTION'})

    def test_disabled_unknown_physics_does_not_lower_applicable_coverage(self):
        data = load()
        data['components'][0]['physics'].append({'tag': 'ht', 'type': 'HeatTransfer', 'enabled': False})
        report = diagnose_inventory(data)
        self.assertEqual(report['status'], 'checked')
        self.assertFalse(flow_scope(report, physics='ht')['applicable'])

    def test_validator_rejects_false_clean_status(self):
        data = load()
        data['multiphysics_tags'] = ['n1']
        report = diagnose_inventory(data)
        report['status'] = 'checked'
        with self.assertRaises(ValueError):
            validate_diagnosis_report(report)

    def test_validator_rejects_missing_skip_reason_and_untraceable_dependency(self):
        for field, value in (('reason', ''), ('dependencies', []), ('evidence_refs', [])):
            data = load()
            data['multiphysics_tags'] = ['n1']
            report = diagnose_inventory(data)
            rule = flow_scope(report)['rules'][0]
            rule[field] = value
            with self.assertRaises((ValueError, ValidationError)):
                validate_diagnosis_report(report)

    def test_validator_rejects_false_checked_rule_and_unknown_finding_source(self):
        report = diagnose_inventory(load('missing_inlet'))
        flow_scope(report)['rules'][0]['status'] = 'skipped'
        with self.assertRaises(ValueError):
            validate_diagnosis_report(report)
        report = diagnose_inventory(load('missing_inlet'))
        report['findings'][0]['source'] = {'component_tag': 'comp2', 'physics_tag': 'spf'}
        with self.assertRaises(ValueError):
            validate_diagnosis_report(report)

    def test_forged_finding_for_coupling_blocked_rule_is_rejected(self):
        data = load('missing_inlet')
        forged = diagnose_inventory(data)['findings'][0]
        data['multiphysics_tags'] = ['n1']
        report = diagnose_inventory(data)
        report['findings'].append(forged)
        with self.assertRaises(ValueError):
            validate_diagnosis_report(report)

    def test_unresolved_outlet_does_not_skip_resolved_inlet_reynolds(self):
        data = load('high_reynolds')
        outlet = next(f for f in data['components'][0]['physics'][0]['features'] if f['type'] == 'Outlet')
        outlet['evaluated_parameters']['pressure'].update(status='unresolved', value=None)
        report = diagnose_inventory(data)
        rules = {r['rule_id']: r for r in flow_scope(report)['rules']}
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(rules['REYNOLDS_RISK']['status'], 'checked')
        self.assertEqual(rules['INLET_DIRECTION']['status'], 'checked')
        self.assertEqual(rules['BOUNDARY_PARAMETER_EVALUATION']['status'], 'skipped')
        self.assertIn('REYNOLDS_RISK', [f['code'] for f in report['findings']])

    def test_mixed_inlet_cases_preserve_provable_findings_and_incomplete_coverage(self):
        data = load('reversed_inlet')
        physics = data['components'][0]['physics'][0]
        second = copy.deepcopy(next(f for f in physics['features'] if f['type'] == 'Inlet'))
        second['tag'] = 'inlet_unresolved'
        second['evaluated_parameters']['normal_velocity'].update(status='unresolved', value=None)
        physics['features'].append(second)
        report = diagnose_inventory(data)
        self.assertEqual(report['status'], 'partial')
        self.assertIn('INLET_DIRECTION', [f['code'] for f in report['findings']])
        rule = next(r for r in flow_scope(report)['rules'] if r['rule_id'] == 'INLET_DIRECTION')
        self.assertEqual(rule['status'], 'skipped')
        self.assertEqual({c['feature_tag']: c['status'] for c in rule['cases']},
                         {'inl1': 'checked', 'inlet_unresolved': 'skipped'})
        forged = copy.deepcopy(next(f for f in report['findings'] if f['code'] == 'INLET_DIRECTION'))
        forged['feature_tags'] = ['inlet_unresolved']
        report['findings'].append(forged)
        with self.assertRaises(ValueError):
            validate_diagnosis_report(report)

    def test_finding_geometry_source_mismatch_has_controlled_validation_error(self):
        report = diagnose_inventory(load('missing_inlet'))
        report['findings'][0]['source'] = dict(report['findings'][0]['source'])
        del report['findings'][0]['source']['geometry_tag']
        with self.assertRaises(ValueError):
            validate_diagnosis_report(report)

    def test_validator_rejects_module_model_source_mismatch(self):
        report = copy.deepcopy(diagnose_inventory(load()))
        report['modules'][0]['model']['source']['physics_tag'] = 'other'
        with self.assertRaises(ValueError):
            validate_diagnosis_report(report)

    def test_no_instances_never_returns_clean_pass(self):
        data = load()
        data['components'] = []
        report = diagnose_inventory(data)
        self.assertEqual(report['status'], 'unsupported')
        self.assertTrue(report['coverage'])

    def test_duplicate_sources_rejected(self):
        data = load()
        data['components'].append(copy.deepcopy(data['components'][0]))
        with self.assertRaises(ValueError):
            diagnose_inventory(data)


if __name__ == '__main__':
    unittest.main()
