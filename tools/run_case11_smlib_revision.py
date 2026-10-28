#!/usr/bin/env python3
"""Export and test a new case11 source independently of the legacy fixture.

FREECAD_CMD (or --freecad-command), SMLIB_ROOT and SMLIB_LIBRARY select local
dependencies. Each radius uses the existing native adapter in a new process.
The adapter admits filleting only after exact exchange import gates pass.
"""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys


REPO = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def relative(path):
    path = Path(path).resolve()
    if not path.is_relative_to(REPO):
        raise ValueError("Path escapes repository: " + str(path))
    return str(path.relative_to(REPO))


def invoke(command, output, label, env=None):
    with (output / (label + ".stdout.log")).open("w") as stdout, (output / (label + ".stderr.log")).open("w") as stderr:
        result = subprocess.run(command, cwd=REPO, env=env, stdout=stdout, stderr=stderr, check=False)
    return dict(return_code=result.returncode, fresh_process=True,
                stdout=relative(output / (label + ".stdout.log")),
                stderr=relative(output / (label + ".stderr.log")))


def review_attempt(run_dir, process):
    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    execution = summary.get("execution", {})
    result_path = run_dir / "result.json"
    result = json.loads(result_path.read_text()) if result_path.exists() else None
    before_path = run_dir / "before.json"
    before = json.loads(before_path.read_text()) if before_path.exists() else None
    unchanged = bool(result and before and result["native_stats"] == before["native_stats"])
    before_smb, result_smb = run_dir / "before.smb", run_dir / "result.smb"
    unchanged_native_file = bool(before_smb.exists() and result_smb.exists() and sha(before_smb) == sha(result_smb))
    if not (summary.get("input_import") or {}).get("passed"):
        status = "import_failed_fillet_not_called"
    elif not execution.get("native_api_success"):
        status = "native_api_failed_unchanged_input" if unchanged_native_file else "native_api_failed_candidate"
    elif not execution.get("result_kind_gate", {}).get("passed"):
        status = "native_invalid"
    elif not summary.get("gates", {}).get("native_readback", {}).get("passed"):
        status = "native_readback_failed"
    else:
        status = "native_candidate_pending_independent_quality_and_visual_acceptance"
    return dict(radius_mm=summary.get("radius_mm"), process=process, run_dir=relative(run_dir),
                summary=relative(summary_path) if summary_path.exists() else None,
                outcome=summary.get("outcome", "runner_failed"), review_status=status,
                import_passed=(summary.get("input_import") or {}).get("passed", False),
                selection_passed=summary.get("selection_passed"),
                native_call_started=execution.get("native_call_started", False),
                native_api_raw_status=execution.get("native_api_raw_status"),
                result_native_stats=result.get("native_stats") if result else None,
                retained_result_matches_before_metrics=unchanged,
                retained_native_file_identical_to_before=unchanged_native_file,
                native_readback_passed=summary.get("gates", {}).get("native_readback", {}).get("passed", False),
                full_quality_passed=False, source_repair_fa_X_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="new repository-local source BREP")
    parser.add_argument("--label", required=True, help="immutable revision label, e.g. candidate-v2")
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--target-json", type=Path, help="JSON list of geometric targets; defaults to new convex shoulder")
    parser.add_argument("--freecad-command", default=os.environ.get("FREECAD_CMD"))
    parser.add_argument("--timeout", type=float, default=60, help="native import/operation watchdog seconds, <=60")
    parser.add_argument("--fixture", type=Path, help="existing hash-bound fixture; skip export")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.label):
        parser.error("label must use lowercase letters, digits and hyphens")
    source = args.source.resolve()
    relative(source)
    if sha(source) != args.expected_source_sha256:
        raise ValueError("New source BREP SHA256 mismatch")
    if args.expected_source_sha256 == "9959f6889063c0ee1107e6ac5185035cba9dd48ba5b843679888baa3258ec7a8":
        raise ValueError("Legacy concave source is excluded from this revision workflow")
    output = REPO / "runs/case11-convexity" / ("smlib-" + args.label)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Refusing to overwrite a nonempty revision run directory")
    fixture = args.fixture.resolve() if args.fixture else REPO / "data/case11-convexity" / ("smlib-" + args.label + ".fixture.json")
    relative(fixture)
    record = dict(schema="case11.convexity-smlib-revision.v1", revision=args.label,
                  started_at=datetime.now(timezone.utc).isoformat(), source_brep=relative(source),
                  source_sha256=sha(source), source_fixture_json=relative(fixture),
                  source_model_status="candidate pending independent shape review", shape_acceptance=False,
                  revision_runner_source_sha256=sha(__file__),
                  exporter_source_sha256=sha(REPO / "adapters/exchange/case11_nurbs.py"),
                  source_repair_fa_X_verified=False, automatic_heal=False, stitch=False, attempts=[])
    code_dir = output / "code"
    code_dir.mkdir()
    for source_code in (Path(__file__), REPO / "adapters/exchange/case11_nurbs.py"):
        shutil.copyfile(source_code, code_dir / source_code.name)
    try:
        if not args.fixture:
            command = shlex.split(args.freecad_command) if args.freecad_command else [shutil.which("FreeCADCmd") or "FreeCADCmd"]
            export_env = dict(os.environ, FILLETBENCH_SOURCE_BREP=str(source), FILLETBENCH_FIXTURE_JSON=str(fixture))
            record["export_process"] = invoke(command + [str(REPO / "adapters/exchange/case11_nurbs.py")],
                                               output, "export", export_env)
            if record["export_process"]["return_code"] or not fixture.exists():
                raise ValueError("Exact source export failed; inspect export logs")
        fixture_data = json.loads(fixture.read_text())
        if fixture_data["source_sha256"] != record["source_sha256"] or fixture_data["source_brep"] != relative(source):
            raise ValueError("Fixture lineage does not match new source")
        if len(fixture_data["components"]) != 1 or fixture_data["components"][0]["kind"] != "solid":
            raise ValueError("This revision requires exactly one preserved solid component")
        if fixture_data.get("healing") is not False or fixture_data.get("stitching") is not False:
            raise ValueError("Revision import may not heal or stitch the source")
        record["source_fixture_sha256"] = sha(fixture)
        record["source_stats"] = fixture_data["components"][0]["source_stats"]
        record["source_topology_audit"] = fixture_data["components"][0].get("source_topology_audit")
        targets = (json.loads(args.target_json.read_text()) if args.target_json else
                   [dict(id="new-convex-shoulder", endpoints_world_mm=[[50, 0, 0], [50, -60.6, 0]],
                         expected_length_mm=60.6, expected_count=1, selector_tolerance_mm=1e-6,
                         coverage_tolerance_mm=1e-5)])
        record["targets"] = targets
        for radius in (1, 3, 6):
            job = dict(job_id="case11-convexity-" + args.label + "-r" + str(radius), number=11,
                       part_label="new convex shoulder", role="isolated_convex_reconstruction_candidate",
                       source_brep=relative(source), source_sha256=record["source_sha256"],
                       source_fixture_json=relative(fixture), source_fixture_sha256=record["source_fixture_sha256"],
                       source_stats=record["source_stats"], component_index=1, expected_input_kind="solid",
                       radius_mm=radius, xsect_type=1, continuity=1, thumbweight=1, targets=targets,
                       source_repair_fa_X_verified=False, shape_acceptance=False)
            job_path = REPO / "data/case11-convexity" / ("smlib-" + args.label + "-r" + str(radius) + ".job.json")
            if job_path.exists():
                raise ValueError("Refusing to overwrite existing revision job")
            write(job_path, job)
            run_dir = output / ("r" + str(radius))
            process = invoke([sys.executable, str(REPO / "adapters/smlib/run.py"), str(job_path),
                              "--output", str(run_dir), "--timeout", str(args.timeout)], output, "r" + str(radius))
            record["attempts"].append(review_attempt(run_dir, process))
            write(output / "report.json", record)
        record["status"] = "completed_actual_attempts"
    except Exception as error:
        record.update(status="export_or_preflight_failed", error=type(error).__name__ + ": " + str(error))
    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    record["evidence_limits"] = ["Source dimensions and shape are inferred and pending independent visual acceptance.",
                                 "Native candidates are not repair_fa_X equivalence or full geometric acceptance.",
                                 "Failed inputs stop before the fillet call; failed native candidates are retained."]
    write(output / "report.json", record)
    print(json.dumps(dict(status=record["status"], output=relative(output),
                          attempts=record["attempts"], error=record.get("error"))))
    return 0 if record["status"] == "completed_actual_attempts" else 2


if __name__ == "__main__":
    sys.exit(main())
