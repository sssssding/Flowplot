"""Synthetic publication faults: no real model edits, solving, or performance claims."""
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
import test_ai_review_safety as snapshot_fixture
from flowpilot import recommend as ai, portable_recommend as portable
from flowpilot.check_model import CheckError
from flowpilot.desktop_session import load_completed_check
from flowpilot.report_package import export_package


class PublicationTest(unittest.TestCase):
    def setUp(self):
        self.fixture = snapshot_fixture.SnapshotSafetyTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.directory = self.fixture.directory
        self.loaded = load_completed_check(self.directory)
        self.rank = portable.rank
        temporary = tempfile.TemporaryDirectory(dir=ROOT / 'outputs')
        self.addCleanup(temporary.cleanup)
        self.outside = Path(temporary.name)

    def mutate_while_ranking(self, mutation):
        def rank(*args, **kwargs):
            mutation()
            return self.rank(*args, **kwargs)
        return patch.object(portable, 'rank', side_effect=rank)

    def test_metadata_changes_during_ranking_block_publication(self):
        with self.mutate_while_ranking(lambda: self.fixture.publish(filename='changed.mph')):
            with self.assertRaisesRegex(CheckError, '重新读取报告'):
                ai.recommend_report(self.directory)

    def test_diagnosis_changes_during_ranking_block_publication(self):
        with self.mutate_while_ranking(lambda: self.fixture.publish(100)):
            with self.assertRaises(CheckError):
                ai.recommend_report(self.directory, expected_fingerprints=self.fixture.identity(self.loaded))

    def test_corruption_during_ranking_is_not_successful(self):
        with self.mutate_while_ranking(lambda: (self.directory / 'run.json').write_bytes(b'broken')):
            with self.assertRaises((CheckError, ValueError)):
                ai.recommend_report(self.directory)

    def test_refusal_snapshot_is_also_rechecked(self):
        self.fixture.publish(100)
        original = ai.load_completed_check
        reads = []
        def changing(directory):
            loaded = original(directory)
            reads.append(loaded)
            if len(reads) == 1:
                self.fixture.publish()
            return loaded
        with patch.object(ai, 'load_completed_check', side_effect=changing):
            with self.assertRaises(CheckError):
                ai.recommend_report(self.directory)

    def test_ui_clears_old_result_if_change_occurs_during_refresh(self):
        app = self.fixture.app()
        self.fixture.show(app, self.loaded)
        self.assertEqual(app.ai_result['status'], 'recommended')
        with self.mutate_while_ranking(lambda: self.fixture.publish(filename='changed.mph')):
            app.refresh_recommendation()
        self.assertIsNone(app.ai_result)
        self.assertIn('重新读取报告', app.set_ai_text.call_args.args[0])

    def test_export_outside_report_binds_snapshot_and_does_not_change_input(self):
        before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        output = self.outside / 'candidate.json'
        result = ai.export_recommendation(self.directory, output)
        self.assertEqual(json.loads(output.read_text(encoding='utf-8')), result)
        self.assertEqual((result['run_sha256'], result['diagnosis_sha256']), self.fixture.identity(self.loaded))
        self.assertEqual({p.name: p.read_bytes() for p in self.directory.iterdir()}, before)

    def test_output_inside_report_rejected_before_ranker_is_read(self):
        before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        for output in (self.directory / 'candidate.json', self.directory / 'nested/new/candidate.json',
                       self.directory / '..' / self.directory.name / 'candidate.json'):
            with self.subTest(output=output), patch.object(ai, 'read_regular_file', side_effect=AssertionError('no ranker read')):
                with self.assertRaisesRegex(CheckError, '输入报告目录'):
                    ai.export_recommendation(self.directory, output)
        self.assertEqual({p.name: p.read_bytes() for p in self.directory.iterdir()}, before)

    def test_report_package_remains_readable_after_rejected_output(self):
        package = export_package(self.directory, self.outside / 'package')
        before = {p.name: p.read_bytes() for p in package.iterdir()}
        with self.assertRaises(CheckError):
            ai.export_recommendation(package, package / 'candidate.json')
        self.assertEqual({p.name: p.read_bytes() for p in package.iterdir()}, before)
        self.assertEqual(load_completed_check(package)['report'], self.loaded['report'])

    def test_existing_output_is_never_overwritten(self):
        output = self.outside / 'candidate.json'
        output.write_bytes(b'user result')
        with self.assertRaises(FileExistsError):
            ai.export_recommendation(self.directory, output)
        self.assertEqual(output.read_bytes(), b'user result')

    def test_changed_report_during_ranking_never_creates_output(self):
        output = self.outside / 'candidate.json'
        with self.mutate_while_ranking(lambda: self.fixture.publish(filename='changed.mph')):
            with self.assertRaises(CheckError):
                ai.export_recommendation(self.directory, output)
        self.assertFalse(output.exists())

    def test_changed_report_after_ranking_before_write_is_rejected(self):
        output = self.outside / 'candidate.json'
        original = ai.recommend_report
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            self.fixture.publish(filename='changed.mph')
            return result
        with patch.object(ai, 'recommend_report', side_effect=changed):
            with self.assertRaises(CheckError):
                ai.export_recommendation(self.directory, output)
        self.assertFalse(output.exists())

    def test_cli_output_uses_protected_export(self):
        result = {'status': 'recommended', 'reason': 'synthetic', 'ranking': [], 'selected': None}
        with patch.object(sys, 'argv', ['recommend.py', 'recommend', '--report', str(self.directory),
                                     '--output', str(self.outside / 'candidate.json')]), \
                patch.object(ai, 'export_recommendation', return_value=result) as export, \
                patch.object(ai, '_write_json', side_effect=AssertionError('no direct write')):
            ai.main()
        export.assert_called_once()

    def test_legacy_ranker_also_rechecks_after_computation(self):
        original = ai.rank
        def changed(*args, **kwargs):
            self.fixture.publish(filename='changed.mph')
            return original(*args, **kwargs)
        with patch.object(ai, 'rank', side_effect=changed):
            with self.assertRaises(CheckError):
                ai.recommend_report(self.directory, ai.DEFAULT_MODEL)

    def test_real_cli_exports_separate_file_without_comsol(self):
        output = self.outside / 'candidate.json'
        process = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'src/flowpilot/recommend.py'),
                                  'recommend', '--report', str(self.directory), '--output', str(output)],
                                 capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(output.read_text(encoding='utf-8'))['status'], 'recommended')
        load_completed_check(self.directory)

    def test_real_cli_rejects_package_pollution_without_writing(self):
        package = export_package(self.directory, self.outside / 'package')
        output = package / 'candidate.json'
        process = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'src/flowpilot/recommend.py'),
                                  'recommend', '--report', str(package), '--output', str(output)],
                                 capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(process.returncode, 1)
        self.assertIn('输入报告目录', process.stderr)
        self.assertFalse(output.exists())
        load_completed_check(package)


if __name__ == '__main__':
    unittest.main()
