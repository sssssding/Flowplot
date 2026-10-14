"""Synthetic benchmark failure-path checks, never substitute for actual COMSOL."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from flowpilot import benchmark_portable as bench
from flowpilot import recommend as ai
from flowpilot.check_model import CheckError,sha256
from flowpilot.diagnostics import normalize
from flowpilot.desktop_session import load_completed_check
from flowpilot.report_package import export_package


class BenchmarkTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/"outputs")
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.model=self.root/"base.mph"; self.model.write_bytes(b"synthetic MPH")
        self.digest=sha256(self.model)
        self.manifest=self.root/"manifest.json"
        self.manifest.write_text(json.dumps({"cases":[{"case_id":"baseline","sha256":self.digest}]}))
        self.diagnostic=normalize(ai.read_json(ROOT/"data/fixtures/cases/baseline.json"))
        self.comsol=self.root/"comsol"; (self.comsol/"bin/win64").mkdir(parents=True)
        self.output=self.root/"run"
        self.batch_solves=0

    def inspect(self,path,**kwargs):
        model=copy.deepcopy(self.diagnostic)
        length,height=(.5,.02) if Path(path).stem=="short_narrow" else (2.,.1)
        model["geometry"]={"length_m":length,"height_m":height}
        return {"status":"checked","findings":[],"model":model}

    def simulate(self,command,*,cwd,log,timeout):
        if Path(command[0]).name=="comsolcompile.exe":
            (cwd/(Path(command[1]).stem+".class")).write_bytes(b"synthetic class")
            Path(log).touch(); return
        if Path(command[2]).stem=="PortableFamily":
            for name in ("short_narrow","long_wide"):
                (cwd/"models"/(name+".mph")).write_bytes(("synthetic "+name).encode())
            Path(log).write_text("FLOWPLOT_PORTABLE_SAVED short_narrow\nFLOWPLOT_PORTABLE_SAVED long_wide\nFLOWPLOT_PORTABLE_VERIFIED 2\n")
            return
        self.batch_solves+=1
        c=next(c for c in ai.CANDIDATES if c["id"]==cwd.parent.name)
        height=.02 if cwd.parent.parent.name=="short_narrow" else .1
        payload=copy.deepcopy(ai.read_json(ai.DEFAULT_MODEL)["dataset"]["observations"][0]["evidence"])
        payload["solve_seconds"]=.001
        payload["metrics"]={"mass_in_kg_m_s":10*height,"mass_out_kg_m_s":10*height*.9999,
                            "max_speed_m_s":.015,"wall_interior_speed_m_s":0.,"min_u_m_s":0.,"pressure_drop_pa":.1}
        Path(log).write_text(f"FLOWPLOT_TOLERANCE {c['stol']}\nFLOWPILOT_SOLUTION_CLEARED\nFLOWPILOT_SOLVE_JSON "+json.dumps(payload)+"\nFLOWPILOT_SOLVE_VERIFIED\n")
        (cwd/"solved.mph").write_bytes(b"synthetic"*40); (cwd/"batch.log").write_bytes(b"synthetic native log")

    def run_benchmark(self,runner=None):
        loaded={"directory":self.root/"reports", "metadata":{"source":{"sha256":self.digest}},"report":{"status":"checked","findings":[],"model":self.diagnostic}}
        with patch.object(bench,"MANIFEST",self.manifest), patch.object(bench,"load_completed_check",return_value=loaded), \
                patch.object(bench,"check_model",side_effect=self.inspect),patch.object(bench,"_run",side_effect=runner or self.simulate), \
                patch.object(bench.time,"monotonic",side_effect=range(0,1000,10)):
            return bench.benchmark(baseline=self.model,baseline_report="unused",comsol_root=self.comsol,output_dir=self.output)

    def test_measurements_cover_two_new_models_and_source_is_preserved(self):
        initial=self.model.read_bytes()
        result=self.run_benchmark()
        self.assertEqual(self.batch_solves,24)
        self.assertEqual(len(result["data"]["cases"]),3)
        self.assertEqual(self.model.read_bytes(),initial)
        self.assertFalse(result["independent_validation"])

    def test_bad_strict_reference_stops_after_first_solve(self):
        def bad(command,**kwargs):
            self.simulate(command,**kwargs)
            log=kwargs["log"]
            if Path(command[0]).name=="comsolbatch.exe" and Path(command[2]).stem=="CandidateSolve":
                text=Path(log).read_text().replace('"solver_warning": ""','"solver_warning": "synthetic warning"')
                Path(log).write_text(text)
        with self.assertRaisesRegex(CheckError,"Reference candidate failed"):
            self.run_benchmark(bad)
        self.assertEqual(self.batch_solves,1)
        self.assertFalse((self.output/"model.json").exists())
        self.assertEqual(ai.read_json(self.output/"run.json")["status"],"failed")

    def test_modified_baseline_and_existing_output_do_not_start(self):
        self.model.write_bytes(b"local user edit")
        with self.assertRaises(CheckError): self.run_benchmark()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.batch_solves,0)
        self.model.write_bytes(b"synthetic MPH"); self.output.mkdir()
        with self.assertRaises(FileExistsError): self.run_benchmark()

    def write_report(self):
        directory = self.root / "reports"
        directory.mkdir()
        report = {"schema_version": "diagnosis-0.1", "profile": "rectangular-channel-v1",
                  "status": "checked", "findings": [], "model": self.diagnostic}
        (directory / "diagnosis.json").write_text(json.dumps(report), encoding="utf-8")
        metadata = {"schema_version": "check-run-0.1", "status": "completed",
                    "source": {"filename": "base.mph", "sha256": self.digest},
                    "diagnosis_status": "checked", "diagnosis_sha256": sha256(directory / "diagnosis.json")}
        (directory / "run.json").write_text(json.dumps(metadata), encoding="utf-8")
        return directory

    def assert_input_tree_protected(self, report, output):
        before = {p.relative_to(report): p.read_bytes() for p in report.rglob("*") if p.is_file()}
        with patch.object(bench, "MANIFEST", self.manifest), patch.object(bench, "_run") as run:
            with self.assertRaisesRegex(CheckError, "输入报告目录"):
                bench.benchmark(baseline=self.model, baseline_report=report, comsol_root=self.comsol, output_dir=output)
            run.assert_not_called()
        self.assertFalse(output.exists())
        self.assertEqual(before, {p.relative_to(report): p.read_bytes() for p in report.rglob("*") if p.is_file()})
        load_completed_check(report)

    def test_new_output_inside_regular_report_is_rejected_before_writes(self):
        report = self.write_report()
        self.assert_input_tree_protected(report, report / "new-output")

    def test_new_output_inside_report_package_is_rejected_without_pollution(self):
        report = export_package(self.write_report(), self.root / "package")
        self.assert_input_tree_protected(report, report / "new-output")

    def test_deep_nested_output_does_not_create_parents_in_input_tree(self):
        report = self.write_report()
        self.assert_input_tree_protected(report, report / "new-parent" / "new-output")
        self.assertFalse((report / "new-parent").exists())

    def test_resolved_output_alias_cannot_bypass_input_tree_check(self):
        report = self.write_report()
        alias = self.root / "output-alias"
        original = Path.resolve
        def resolve(path, *args, **kwargs):
            return report / "new-output" if path == alias else original(path, *args, **kwargs)
        with patch.object(Path, "resolve", resolve):
            self.assert_input_tree_protected(report, alias)
        self.assertFalse((report / "new-output").exists())


if __name__=="__main__": unittest.main()
