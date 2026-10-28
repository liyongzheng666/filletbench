#!/usr/bin/env python3
"""Run the frozen case 08 input at five radii, retaining every native result.

Set SMLIB_ROOT and SMLIB_LIBRARY as required by adapters/smlib/run.py. The
interpreter used for this controller is also used for each fresh adapter process.
Only radius, request identity and documentary original-view lineage labels differ
from the published R12 template. No preserve_notch option is supplied by this job.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "data/jobs/08.part01.ordinary_control.r12.json"
SOURCE_SHA256 = "57ea045f7da3735141b7f21f2fbc3e3a51c39933d08a5d7c6e3374e01ab064f9"
VARIANTS = [(12, "local-demo"), (13, "r13-contact"), (14, "r14-crossing"),
            (15, "r15-crossing"), (18, "r18-crossing")]


def read(path):
    return json.loads(path.read_text())


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path):
    return path.resolve().relative_to(ROOT).as_posix()


def edge_record(edge, faces):
    points = edge.get("points", [])
    if not points:
        return None
    bounds = [min(p[i] for p in points) for i in range(3)]
    bounds += [max(p[i] for p in points) for i in range(3)]
    return dict(edge_id=edge["id"], owners=edge["owners"],
                owner_faces=[dict(id=owner, surface_type=faces[owner].get("surface_type"),
                                  bbox=faces[owner].get("bbox"))
                             for owner in edge["owners"]],
                length_mm=edge.get("length"), sample_count=len(points),
                sampled_bbox_mm=bounds, first_point_mm=points[0], last_point_mm=points[-1])


def notch_edges(snapshot):
    """Identify actual trimmed one-owner notch boundaries, without using radius."""
    tolerance = 1e-6
    faces = {f["id"]: f for f in snapshot.get("geometry", {}).get("faces", [])}
    horizontal, sidewalls = [], []
    for edge in snapshot.get("geometry", {}).get("edges", []):
        if len(edge.get("owners", [])) != 1:
            continue
        record = edge_record(edge, faces)
        if not record:
            continue
        xmin, ymin, zmin, xmax, ymax, zmax = record["sampled_bbox_mm"]
        if max(abs(ymin), abs(ymax)) > tolerance:
            continue
        if (abs(xmin - 35) <= tolerance and abs(xmax - 65) <= tolerance
                and zmax - zmin <= tolerance):
            record["measured_z_mm"] = (zmin + zmax) / 2
            horizontal.append(record)
        if (xmax - xmin <= tolerance and min(abs(xmin - 35), abs(xmin - 65)) <= tolerance
                and zmax - zmin > tolerance):
            record["measured_top_z_mm"] = zmax
            sidewalls.append(record)
    return dict(horizontal_notch_free_edges=horizontal, vertical_notch_free_edges=sidewalls)


def measure(run):
    stages = {}
    for stage in ("before", "result", "readback"):
        path = run / (stage + ".json")
        if path.exists():
            snapshot = read(path)
            stages[stage] = dict(path=relative(path), sha256=sha(path),
                                 native_stats=snapshot.get("native_stats"), **notch_edges(snapshot))
    before = stages.get("before", {}).get("horizontal_notch_free_edges", [])
    result = stages.get("result", {}).get("horizontal_notch_free_edges", [])
    back = stages.get("readback", {}).get("horizontal_notch_free_edges", [])
    source_z = before[0]["measured_z_mm"] if len(before) == 1 else None
    result_z = result[0]["measured_z_mm"] if len(result) == 1 else None
    readback_z = back[0]["measured_z_mm"] if len(back) == 1 else None
    report = dict(schema_version=1,
                  method="Read actual native_runner edge EvaluatePoint samples over actual trimmed edge intervals; select one-owner x35..65 y0 horizontal free edge and x35/x65 y0 vertical free edges. No radius formula is used.",
                  tolerance_mm=1e-6, stages=stages, original_notch_top_measured_z_mm=source_z,
                  result_notch_free_edge_measured_z_mm=result_z,
                  readback_notch_free_edge_measured_z_mm=readback_z,
                  source_to_result_notch_top_shift_mm=(source_z-result_z if source_z is not None and result_z is not None else None),
                  original_z27_horizontal_free_edge_retained=(any(abs(e["measured_z_mm"]-27) <= 1e-6 for e in result) if result else None),
                  result_readback_measurements_agree=(abs(result_z-readback_z) <= 1e-6 if result_z is not None and readback_z is not None else None),
                  preserve_notch_option_supplied=False, preserve_notch_two_modes_verified=False,
                  limitation="Sampled actual native geometry and owner-face topology establish this local boundary change; they do not establish complete source-specific preserve_notch semantics or full geometry quality.")
    write(run / "notch-measurements.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="execute all five fresh processes")
    parser.add_argument("--workers", type=int, default=3, help="one to three concurrent adapters")
    parser.add_argument("--output", type=Path, default=ROOT / "runs/case08-radius/smlib")
    args = parser.parse_args()
    if not 1 <= args.workers <= 3:
        parser.error("--workers must be between 1 and 3")
    out = args.output.resolve()
    relative(out)  # Every published pointer must stay repository-relative.
    original = ROOT / "data/original-occ/cases/08.json"
    original_sha = sha(original)
    template = read(TEMPLATE)
    if template["source_sha256"] != SOURCE_SHA256 or sha(ROOT/template["source_brep"]) != SOURCE_SHA256:
        raise ValueError("Case 08 source SHA256 mismatch")
    rows = []
    for radius, variant in VARIANTS:
        job_id = f"case08.original.r{radius}.smlib"
        request = ROOT / f"data/case08-radius/smlib-jobs/{job_id}.json"
        job = deepcopy(template)
        job.update(job_id=job_id, radius_mm=radius, job_file=relative(request),
                   original_variant_id=variant, original_case_file=relative(original),
                   original_case_file_sha256=original_sha,
                   source_template_job_id=template["job_id"], source_template_job_sha256=sha(TEMPLATE),
                   original_view_extension="case08_radius_sweep",
                   original_template_request_note_is_historical=True)
        for key, value in template.items():
            if key not in ("radius_mm", "job_id", "job_file") and job[key] != value:
                raise ValueError("Unexpected template change: " + key)
        if request.exists() and read(request) != job:
            raise ValueError("Refusing to overwrite changed request " + relative(request))
        write(request, job)
        rows.append(dict(number=8, variant_id=variant, radius_mm=radius, request_path=relative(request),
                         job_id=job_id, source_sha256=SOURCE_SHA256,
                         source_template_job_sha256=sha(TEMPLATE),
                         original_case_file_sha256=original_sha,
                         request_sha256=sha(request),
                         binding_checks=dict(source_fixture_component_world_targets_tolerances_and_native_options_unchanged=True,
                                             radius_is_only_operation_parameter_change=True),
                         summary=relative(out/job_id/"summary.json"), run_dir=relative(out/job_id)))
    plan = dict(schema_version=1, template=relative(TEMPLATE), source_sha256=SOURCE_SHA256,
                source_template_request_note="The inherited R12 request_note is historical; radius_mm is the actual run radius.",
                preserve_notch_option_supplied=False, rows=rows)
    write(ROOT / "data/case08-radius/smlib-requests.json", plan)
    if not args.run:
        print(json.dumps(dict(count=len(rows), requests="data/case08-radius/smlib-requests.json")))
        return 0
    if out.exists() and any(out.iterdir()):
        raise SystemExit("Refusing nonempty output; choose a fresh --output")
    out.mkdir(parents=True, exist_ok=True)

    def execute(row):
        run = ROOT / row["run_dir"]
        command = [sys.executable, str(ROOT/"adapters/smlib/run.py"), str(ROOT/row["request_path"]),
                   "--output", str(run), "--timeout", "60"]
        with (out/(row["job_id"]+".controller.log")).open("w") as log:
            try:
                process = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=180)
                controller = dict(return_code=process.returncode, timeout=False)
            except subprocess.TimeoutExpired:
                controller = dict(return_code=None, timeout=True)
        summary_path = ROOT / row["summary"]
        summary = read(summary_path) if summary_path.exists() else {}
        measurements = measure(run) if run.exists() else {}
        result = dict(row, controller=controller, outcome=summary.get("outcome", "controller_failed"),
                      summary_sha256=sha(summary_path) if summary_path.exists() else None,
                      source_fixture_admitted=summary.get("input_import", {}).get("passed", False),
                      selection_passed=summary.get("selection_passed"),
                      native_call_started=summary.get("execution", {}).get("native_call_started", False),
                      native_api_success=summary.get("execution", {}).get("native_api_success", False),
                      native_api_raw_status=summary.get("execution", {}).get("native_api_raw_status"),
                      result_kind=summary.get("gates", {}).get("result_kind"),
                      native_readback=summary.get("gates", {}).get("native_readback"),
                      notch_measurements=relative(run/"notch-measurements.json") if measurements else None,
                      source_to_result_notch_top_shift_mm=measurements.get("source_to_result_notch_top_shift_mm"),
                      result_notch_free_edge_measured_z_mm=measurements.get("result_notch_free_edge_measured_z_mm"),
                      original_z27_horizontal_free_edge_retained=measurements.get("original_z27_horizontal_free_edge_retained"))
        print(json.dumps({k:result.get(k) for k in ("job_id", "outcome", "native_api_success", "result_notch_free_edge_measured_z_mm", "source_to_result_notch_top_shift_mm")}), flush=True)
        return result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        completed = list(pool.map(execute, rows))
    if sha(original) != original_sha:
        raise ValueError("Frozen original case 08 changed during sweep")
    write(out/"index.json", dict(schema_version=1, finished_at=datetime.now(timezone.utc).isoformat(),
          engine="SMLib", count=len(completed), rows=completed, native_watchdog_seconds=60,
          max_parallel=args.workers, fresh_operation_processes=True, original_case_unchanged=True,
          preserve_notch_option_supplied=False, source_special_feature_passed=False,
          full_quality_passed=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
