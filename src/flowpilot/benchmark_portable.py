"""Measure controlled geometry variants for portable ranking, never independent acceptance."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot.check_model import ROOT, CheckError, check_model, _run, _write_json, sha256
from flowpilot.calibrate_solver import driver
from flowpilot.desktop_session import load_completed_check
from flowpilot.recommend import CANDIDATES, DEFAULT_MODEL, read_json, environment_id, validate_dataset
from flowpilot.portable_recommend import model_features, solution_checks, fit
from flowpilot.review_baseline import MANIFEST

GENERATOR = ROOT / "src/comsol/PortableFamily.java"


def make_case(name, digest, model, rows, cohort):
    f = model_features(model)
    reference = next(r for r in rows if r["candidate"]["id"] == "strict-2" and r["repeat"] == 1)["evidence"]["metrics"]
    rows = copy.deepcopy(rows)
    for row in rows:
        row["quality"] = solution_checks(row["evidence"], reference, f)
    return {"id": name, "source_sha256": digest, "diagnostic_model": model, "features": f,
            "environment_id": cohort, "reference_metrics": reference, "observations": rows}


def benchmark(*, baseline, baseline_report, comsol_root, output_dir, timeout=300):
    if type(timeout) not in (int,float) or not 0 < timeout <= 3600:
        raise ValueError("Invalid process timeout")
    baseline = Path(baseline).resolve(strict=True)
    digest = sha256(baseline)
    expected = next(c for c in read_json(MANIFEST)["cases"] if c["case_id"] == "baseline")["sha256"].lower()
    if digest != expected:
        raise CheckError("Only the canonical baseline copy is allowed; preserve local edits")
    loaded = load_completed_check(baseline_report)
    if loaded["metadata"]["source"]["sha256"].lower() != digest or loaded["report"]["status"] != "checked" or loaded["report"]["findings"]:
        raise CheckError("Expected matching clean baseline report")
    old = read_json(DEFAULT_MODEL)["dataset"]
    validate_dataset(old)
    output = Path(output_dir)
    if output.exists() or output.is_symlink() or output.is_junction():
        raise FileExistsError("Use a new output directory")
    output = output.resolve()
    report_root = loaded["directory"]
    if output == report_root or report_root in output.parents:
        raise CheckError("测量输出不能位于输入报告目录内，请选择独立的新目录。")
    output.mkdir(parents=True, exist_ok=False)
    (output/"models").mkdir()
    comsol = Path(comsol_root).resolve(strict=True)
    compiler, batch = (comsol/"bin/win64"/n for n in ("comsolcompile.exe","comsolbatch.exe"))
    data = {"schema_version":"solver-transfer-data-0.1", "status":"running", "development_only":True,
            "independent_validation":False, "started_at":datetime.now(timezone.utc).isoformat(), "cases":[],
            "generator_sha256":sha256(GENERATOR), "benchmark_sha256":sha256(Path(__file__))}
    try:
        data["cases"].append(make_case("baseline",digest,loaded["report"]["model"],old["observations"],old["environment_id"]))
        shutil.copyfile(baseline,output/"input.mph")
        if sha256(output/"input.mph") != digest:
            raise CheckError("Source changed during snapshot")
        java = output/"PortableFamily.java"
        shutil.copyfile(GENERATOR,java)
        _run([str(compiler),str(java)],cwd=output,log=output/"compile.log",timeout=timeout)
        compiled = output/"PortableFamily.class"
        if not compiled.is_file() or not compiled.stat().st_size:
            raise CheckError("Missing family compiler artifact")
        _run([str(batch),"-inputfile",str(compiled),"-nosave","-batchlog",str(output/"generation.log"),"-np","2"],
             cwd=output,log=output/"generation-console.log",timeout=timeout)
        markers = [s for s in (output/"generation-console.log").read_text(encoding="utf-8",errors="replace").splitlines()
                   if s.startswith("FLOWPLOT_PORTABLE_")]
        if markers != ["FLOWPLOT_PORTABLE_SAVED short_narrow","FLOWPLOT_PORTABLE_SAVED long_wide","FLOWPLOT_PORTABLE_VERIFIED 2"]:
            raise CheckError("Missing or ambiguous family completion markers")
        classes = {}
        for c in CANDIDATES:
            directory=output/c["id"]; directory.mkdir()
            source=directory/"CandidateSolve.java"
            with source.open("x",encoding="utf-8") as stream: stream.write(driver(c))
            _run([str(compiler),str(source)],cwd=directory,log=directory/"compile.log",timeout=timeout)
            classes[c["id"]]=directory/"CandidateSolve.class"
            if not classes[c["id"]].is_file() or not classes[c["id"]].stat().st_size:
                raise CheckError("Missing candidate compiler artifact")
        for name in ("short_narrow","long_wide"):
            model=output/"models"/(name+".mph")
            initial=sha256(model)
            report=check_model(model,comsol_root=comsol,output_dir=output/"checks"/name,loads=2,timeout=timeout)
            if report["status"] != "checked" or report["findings"]:
                raise CheckError("Variant diagnosis is not clean")
            f=model_features(report["model"])
            rows=[]; reference=None
            for repeat in (1,2,3):
                # Start strict-2 first to bind this geometry's own reference; rotate later rounds.
                order=(CANDIDATES[1],CANDIDATES[0],CANDIDATES[2],CANDIDATES[3]) if repeat==1 else CANDIDATES[repeat-1:]+CANDIDATES[:repeat-1]
                for c in order:
                    child=output/"solves"/name/c["id"]/f"repeat-{repeat}"; child.mkdir(parents=True)
                    shutil.copyfile(model,child/"input.mph")
                    console=child/"console.log"; native=child/"batch.log"
                    started=time.monotonic()
                    _run([str(batch),"-inputfile",str(classes[c["id"]]),"-nosave","-batchlog",str(native),
                          "-batchlogout","-np",str(c["threads"])],cwd=child,log=console,timeout=timeout)
                    elapsed=time.monotonic()-started
                    from flowpilot.solve_baseline import _read_payload
                    payload=_read_payload(console)
                    applied=[s for s in console.read_text(encoding="utf-8",errors="replace").splitlines() if s.startswith("FLOWPLOT_TOLERANCE ")]
                    if len(applied)!=1 or float(applied[0].split()[1])!=c["stol"]:
                        raise CheckError("Actual tolerance does not match request")
                    if reference is None: reference=payload["metrics"]
                    quality=solution_checks(payload,reference,f)
                    if sha256(model)!=initial or sha256(child/"input.mph")!=initial:
                        raise CheckError("Variant or snapshot changed")
                    solved=child/"solved.mph"
                    if not solved.is_file() or solved.stat().st_size<=128 or not native.is_file() or not native.stat().st_size:
                        raise CheckError("Missing solve artifacts")
                    row={"candidate":c,"repeat":repeat,"evidence":payload,"quality":quality,"process_seconds":elapsed,
                         "solved_sha256":sha256(solved),"console_sha256":sha256(console),"batch_sha256":sha256(native)}
                    _write_json(child/"observation.json",row); rows.append(row)
                    print(f"{name} {c['id']} repeat {repeat}: {payload['solve_seconds']:.3f}s quality={quality['passed']}",flush=True)
                    if c["id"]=="strict-2" and not quality["passed"]:
                        raise CheckError("Reference candidate failed fixed engineering checks; stopping this benchmark")
            data["cases"].append(make_case(name,initial,report["model"],rows,environment_id()))
        if (sha256(baseline)!=digest or sha256(output/"input.mph")!=digest or sha256(GENERATOR)!=data["generator_sha256"]
                or sha256(Path(__file__))!=data["benchmark_sha256"]):
            raise CheckError("Baseline or generator changed")
        data.update(status="completed",finished_at=datetime.now(timezone.utc).isoformat())
        learned=fit(data)
        _write_json(output/"dataset.json",data); _write_json(output/"model.json",learned)
        return learned
    except Exception as error:
        data.update(status="failed",error=str(error)); raise
    except KeyboardInterrupt:
        data.update(status="cancelled"); raise
    finally:
        _write_json(output/"run.json",data)


def main():
    parser=argparse.ArgumentParser(description="Measure portable ranking data on controlled baseline geometry copies")
    parser.add_argument("--baseline",type=Path,required=True)
    parser.add_argument("--baseline-report",type=Path,required=True)
    parser.add_argument("--comsol-root",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args()
    try: benchmark(baseline=args.baseline,baseline_report=args.baseline_report,comsol_root=args.comsol_root,output_dir=args.output_dir)
    except (OSError,ValueError,TypeError,KeyError,CheckError) as error: parser.exit(1,f"Portable benchmark failed: {error}\n")


if __name__=="__main__": main()
