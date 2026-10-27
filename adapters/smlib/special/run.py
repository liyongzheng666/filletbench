#!/usr/bin/env python3
"""Replay frozen special-protocol consumers against an externally built SMLib.

Example: python3 adapters/smlib/special/run.py --job 35/pilot-smlib-thumb10
Historical claims remain historical; a fresh run has its own provenance/output.
"""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import platform
import re
import subprocess
import sys

SPECIAL = Path(__file__).resolve().parent
sys.path.insert(0, str(SPECIAL.parent))
from build import REPO, MissingDependency, configuration, sha, build as build_common
from run import child, relative, read, source_path, checked_hash, import_component
sys.path.insert(0, str(REPO / "tools"))
from export_special_evidence import mesh_data, combine, sanitize


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def jobs():
    return read(SPECIAL / "jobs.json")["jobs"]


def build_driver(config, driver):
    source = SPECIAL / ({"cap_baseline": "cap_bridge", "surface_pair": "surface_pair",
                         "surface_controls": "surface_controls"}.get(driver, driver) + ".cpp")
    inputs = [source, SPECIAL / "run.py", SPECIAL / "jobs.json"]
    if driver == "case23":
        inputs.append(SPECIAL / "base-helpers.hpp")
    if driver == "cap_baseline":
        inputs += [SPECIAL / "cap_adapter.py", SPECIAL / "cap_trial.py"]
    compiler_version = subprocess.run(config["compiler"] + ["--version"], capture_output=True,
                                      text=True, check=True).stdout.splitlines()[0]
    provenance = dict(engine="SMLib", engine_version=config["engine_version"],
                      sdk_source_commit=config["sdk_source_commit"], core_library_sha256=config["core_library_sha256"],
                      compiler=compiler_version, platform=platform.system(), architecture=platform.machine(),
                      consumer_source_sha256={p.name: sha(p) for p in inputs},
                      extra_cxxflags=config["cxxflags"], extra_ldflags=config["ldflags"])
    signature = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()
    dest = REPO / ".cache/smlib-special" / signature[:20]
    dest.mkdir(parents=True, exist_ok=True)
    binary = dest / ("cap_bridge.dylib" if platform.system() == "Darwin" else "cap_bridge.so") if driver == "cap_baseline" else dest / driver
    with (dest / "compile.lock").open("w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if not binary.is_file():
            cmd = config["compiler"] + ["-std=c++17", "-O2", "-DNDEBUG", "-DNOMINMAX", "-DSM_API_EXPORTS",
                                       "-DSM_GRAPHICS_CALLBACKS=1", "-Wno-overloaded-virtual", "-Wno-deprecated-declarations"]
            if driver == "cap_baseline":
                cmd += ["-dynamiclib"] if platform.system() == "Darwin" else ["-shared", "-fPIC"]
            cmd += config["cxxflags"] + ["-I" + str(p) for p in config["includes"]]
            cmd += [str(source), str(config["library"]), "-Wl,-rpath," + str(config["library"].parent)]
            cmd += config["ldflags"] + ["-o", str(binary)]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            (dest / "compile.stdout.log").write_text(result.stdout)
            (dest / "compile.stderr.log").write_text(result.stderr)
            if result.returncode:
                raise RuntimeError("special consumer compilation failed; inspect .cache/smlib-special logs")
    provenance["consumer_binary_sha256"] = sha(binary)
    return binary, provenance


def pair_inputs(job, config, output, timeout):
    source = source_path(job, "source_brep")
    fixture_path = source_path(job, "source_fixture_json")
    checked_hash(source, job.get("source_sha256"), "source BREP")
    checked_hash(fixture_path, job.get("source_fixture_sha256"), "source fixture")
    fixture = read(fixture_path)
    if fixture["source_sha256"] != job["source_sha256"]:
        raise ValueError("fixture source lineage mismatch")
    binaries, provenance = build_common(config)
    paths = []
    reports = []
    for side in ["left", "right"]:
        prepared = dict(job, component_index=job[side + "_component_index"])
        directory, report, _ = import_component(prepared, fixture, binaries, provenance, timeout)
        reports.append({"side": side, **report})
        if not report["passed"]:
            write(output / "input-import.json", reports)
            raise ValueError("exact NURBS pair input failed native/equivalence admission; no fillet called")
        paths.append(relative(directory / "component-1.smb"))
    write(output / "input-import.json", reports)
    selectors = []
    for side in ["left", "right"]:
        pts = job[side + "_samples_mm"]
        direction = job[side + "_offset_direction"]
        text = " ".join(map(str, direction)) + " " + str(len(pts)) + "\n"
        text += "\n".join(" ".join(map(str, p)) for p in pts) + "\n"
        path = output / (side + "-selector.tokens")
        path.write_text(text)
        selectors.append(relative(path))
    return paths + selectors


def native_command(binary, job, output, config, timeout):
    out = relative(output)
    driver = job["driver"]
    if driver == "case07":
        return [str(binary), str(job["radius_mm"]), out]
    if driver == "case08":
        return [str(binary), out, str(job["radius_mm"])]
    if driver == "case23":
        return [str(binary), out, str(job["radius_mm"]), job["order"]]
    if driver == "case34":
        return [str(binary), job["mode"], out]
    if driver == "case35":
        return [str(binary), out, str(job["radius_mm"]), str(job["xsect"]), str(job["thumbweight"])]
    if driver == "surface_controls":
        return [str(binary), str(job["case_number"]), str(job["left_sense"]), str(job["right_sense"]),
                str(job["trim"]), str(job["base_trim"]), out]
    if driver == "surface_pair":
        pair = pair_inputs(job, config, output, timeout)
        return [str(binary), *pair, str(job["radius_mm"]), out, str(job["trim"])]
    if driver == "cap_baseline":
        os.environ["FILLETBENCH_SPECIAL_BRIDGE"] = str(binary)
        os.environ["FILLETBENCH_SDK_COMMIT"] = config["sdk_source_commit"] or "unverified"
        return [sys.executable, str(SPECIAL / "cap_trial.py"), str(job["case_number"]), job["kind"], out]
    raise ValueError("unknown driver")


def display_geometry(run, job):
    driver = job["driver"]
    result = before = None
    if driver == "cap_baseline":
        path = run / "ordinary-r8-mesh.json"
        if path.is_file():
            obj = read(path)
            result, before = mesh_data(obj.get("result", {})), mesh_data(obj.get("a", {}))
    else:
        candidates = {
            "case07": ("mesh.json", "input-mesh.json", "native-edges.json", "input-edges.json"),
            "case08": ("result.json.mesh.json", "input.json.mesh.json", "result.json", "input.json"),
            "case23": ("after-mesh.json", "before-mesh.json", "after-edges.json", "before-edges.json"),
            "case34": ("result-mesh.json", "input-mesh.json", "candidate-edges.json", "input-edges.json"),
            "case35": ("result-mesh.json", "input-mesh.json", None, None),
            "surface_pair": ("mesh.json", None, "native-edges.json", None),
            "surface_controls": ("mesh.json", None, "native-edges.json", None),
        }[driver]
        def get(name, edge_name):
            if not name or not (run / name).is_file():
                return None
            edges = read(run / edge_name) if edge_name and (run / edge_name).is_file() else None
            return mesh_data(read(run / name), edges)
        result = get(candidates[0], candidates[2])
        before = get(candidates[1], candidates[3])
        if driver in ["surface_pair", "surface_controls"]:
            chunks = [get("input-" + side + "-mesh.json", "input-" + side + "-edges.json") for side in ["left", "right"]]
            before = combine([c for c in chunks if c])
    files = {}
    for name, obj in [("display-result.json", result), ("display-input.json", before)]:
        if obj and obj["triangles"]:
            write(run / name, obj)
            files[name] = {"path": name, "sha256": sha(run / name)}
    return files


def execution_record(run, job, process, geometry):
    status = None
    status_source = None
    for name, key in [("operation.json", "api_status"), ("operation.json", "native_api_status"),
                      ("operation.json", "status"), ("operation-status.json", "api_status"),
                      ("native-return.json", "status_code"), ("run.json", "call_status"),
                      ("ordinary-r8-mesh.json-api.json", "native_api_status")]:
        p = run / name
        if p.is_file():
            value = read(p).get(key)
            if isinstance(value, int):
                status, status_source = value, name + ":" + key
                break
    if status is None and job["driver"] == "case23":
        error = run / "error.json"
        if error.is_file():
            match = re.search(r"status (\d+)", read(error).get("error", ""))
            if match:
                status, status_source = int(match.group(1)), "error.json:error recorded by driver"
        elif (run / "after.smb").is_file() and process.get("return_code") == 0:
            status, status_source = 1000, "inferred from checked native roots call and after.smb persistence"
    return {"native_api_raw_status": status, "native_api_status_source": status_source,
            "native_api_success": status == 1000 if status is not None else None,
            "nonempty_result_mesh": "display-result.json" in geometry,
            "full_special_feature_passed": False}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--job", help="Frozen CASE/variant ID from --list")
    ap.add_argument("--output", "--output-dir", dest="output", type=Path)
    ap.add_argument("--timeout", type=float, default=60)
    args = ap.parse_args()
    frozen = jobs()
    if args.list:
        print(json.dumps(frozen, ensure_ascii=False, indent=2))
        return 0
    if not args.job:
        ap.error("--job or --list is required")
    job = next((j for j in frozen if j["job_id"] == args.job), None)
    if job is None:
        ap.error("unknown frozen job; use --list")
    if not 0 < args.timeout <= 60:
        ap.error("--timeout must be greater than 0 and at most 60 seconds")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run = args.output.resolve() if args.output else REPO / "runs/smlib-special" / args.job / stamp
    run.mkdir(parents=True, exist_ok=True)
    if any(run.iterdir()):
        raise SystemExit("Refusing to overwrite nonempty output; choose a fresh --output")
    write(run / "job.json", job)
    process = {"return_code": None, "timeout": False, "fresh_process": True}
    outcome = "preflight_failed"
    provenance = None
    additional = []
    try:
        config = configuration()
        binary, provenance = build_driver(config, job["driver"])
        write(run / "binary-provenance.json", provenance)
        command = native_command(binary, job, run, config, args.timeout)
        process = child(command, run, args.timeout, "native")
        outcome = "native_returned" if process["return_code"] == 0 else "native_failed"
        if process["timeout"]:
            outcome = "timeout"
        if job["driver"] == "case35" and (run / "result.smb").is_file():
            rd = run / "independent-readback"
            rd.mkdir()
            process["readback"] = child([str(binary), "--readback", relative(run / "result.smb"), relative(rd)], rd, args.timeout, "readback")
        if job.get("additional_mode"):
            rd = run / "additional-variable-control"
            rd.mkdir()
            control_job = dict(job, mode=job["additional_mode"])
            control_process = child([str(binary), job["additional_mode"], relative(rd)], rd, args.timeout, "native")
            control_geometry = display_geometry(rd, control_job)
            additional.append({"label": "native variable-radius control; rho not supplied",
                               "directory": "additional-variable-control", "process": control_process,
                               "display_geometry": control_geometry,
                               "execution": execution_record(rd, control_job, control_process, control_geometry)})
    except MissingDependency as error:
        outcome = "missing_dependency"
        process["error"] = str(error)
    except Exception as error:
        process["error"] = str(error)
    write(run / "process.json", process)
    geometry = display_geometry(run, job)
    summary = {"schema": "filletbench.special-fresh-run.v1", "job_id": args.job,
               "outcome": outcome, "process": process, "request": job,
               "freshly_executed": process["return_code"] is not None or process["timeout"],
               "historical_snapshot": False, "source_feature_passed": False,
               "full_geometry_acceptance": "not_certified_by_this_runner",
               "execution": execution_record(run, job, process, geometry),
               "engine_version": provenance["engine_version"] if provenance else None,
               "scope": "Frozen consumer protocol replay; API return and native validity do not certify complete special-feature equivalence.",
               "display_geometry": geometry,
               "additional_runs": additional,
               "artifacts": {p.name: {"path": p.name, "sha256": sha(p)} for p in run.iterdir() if p.is_file() and p.name != "summary.json"}}
    write(run / "summary.json", sanitize(summary))
    print(json.dumps({"job_id": args.job, "outcome": outcome, "run_dir": relative(run), "display_geometry": list(geometry)}))
    return 0 if outcome == "native_returned" else 2


if __name__ == "__main__":
    raise SystemExit(main())
