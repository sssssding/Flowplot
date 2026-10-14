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
        loaded={"metadata":{"source":{"sha256":self.digest}},"report":{"status":"checked","findings":[],"model":self.diagnostic}}
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


if __name__=="__main__": unittest.main()
