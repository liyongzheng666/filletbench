#!/usr/bin/env python3
"""Fresh native four-trim surface-surface calls on the original case36 faces."""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ADAPTER = HERE.parent
REPO = ADAPTER.parents[1]
sys.path.insert(0, str(ADAPTER))
from build import configuration, build as build_common, sha
from run import import_component, child


def read(path):
    return json.loads(Path(path).read_text())


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def relative(path):
    path = Path(path).resolve()
    if not path.is_relative_to(REPO):
        raise ValueError("Evidence path escapes repository")
    return str(path.relative_to(REPO))


def build_worker(config):
    sources = [HERE / "worker.cpp", HERE / "run.py", ADAPTER / "native_runner.cpp", ADAPTER / "json_value.h"]
    provenance = dict(engine="SMLib", engine_version=config["engine_version"],
                      sdk_source_commit=config["sdk_source_commit"], core_library_sha256=config["core_library_sha256"],
                      compiler=subprocess.run(config["compiler"] + ["--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0],
                      architecture=platform.machine(), platform=platform.system(),
                      consumer_source_sha256={relative(p): sha(p) for p in sources},
                      extra_cxxflags=config["cxxflags"], extra_ldflags=config["ldflags"])
    signature = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()
    cache = REPO / ".cache/smlib-case36-faceface" / signature[:20]
    cache.mkdir(parents=True, exist_ok=True)
    binary = cache / "worker"
    with (cache / "compile.lock").open("w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if not binary.exists():
            command = config["compiler"] + ["-std=c++17", "-O2", "-DNDEBUG", "-DNOMINMAX", "-DSM_API_EXPORTS",
                        "-DSM_GRAPHICS_CALLBACKS=1", "-Wno-overloaded-virtual", "-Wno-deprecated-declarations"]
            command += config["cxxflags"] + ["-I" + str(p) for p in config["includes"]]
            command += [str(HERE / "worker.cpp"), str(config["library"]), "-Wl,-rpath," + str(config["library"].parent)]
            command += config["ldflags"] + ["-o", str(binary)]
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            (cache / "compile.stdout.log").write_text(result.stdout)
            (cache / "compile.stderr.log").write_text(result.stderr)
            if result.returncode:
                raise RuntimeError("Case36 worker compilation failed: " + relative(cache / "compile.stderr.log"))
    provenance["consumer_binary_sha256"] = sha(binary)
    write(cache / "provenance.json", provenance)
    return binary, provenance


def combine_before(directory):
    vertices, triangles, owners = [], [], []
    for side_id, side in enumerate(("left", "right")):
        path = directory / ("input-" + side + ".mesh.json")
        if not path.exists():
            return None
        mesh = read(path)
        if not mesh.get("face_mapping_verified"):
            raise ValueError("Input mesh CAD-face mapping failed")
        offset = len(vertices)
        vertices += mesh["vertices"]
        triangles += [[i + offset for i in tri] for tri in mesh["triangles"]]
        owners += [side_id] * len(mesh["triangles"])
    path = directory / "before.mesh.json"
    write(path, dict(vertices=vertices, triangles=triangles, triangle_face_ids=owners,
                     face_mapping_verified=True, geometry_role="both original finite input faces; no preprocessing",
                     source="SmApiTessellate on native copies with verified CAD-face IDs"))
    return relative(path)


def evaluated_summary(directory, job, process, request, imports):
    operation = read(directory / "operation.json") if (directory / "operation.json").exists() else {}
    native = read(directory / "native.json") if (directory / "native.json").exists() else {}
    readback = read(directory / "readback.json") if (directory / "readback.json").exists() else {}
    native_stats, readback_stats = native.get("native_stats", {}), readback.get("native_stats", {})
    equality, native_inputs, post_metrics = {}, [], {}
    for side in ("left", "right"):
        before, after = directory / ("input-" + side + ".smb"), directory / ("post-" + side + ".smb")
        raw_before, raw_after = directory / ("source-" + side + "-before.smb"), directory / ("source-" + side + "-after.smb")
        equality[side] = dict(call_input_unchanged=before.exists() and after.exists() and sha(before) == sha(after),
                              raw_source_unchanged=raw_before.exists() and raw_after.exists() and sha(raw_before) == sha(raw_after),
                              input_smb_sha256=sha(before) if before.exists() else None,
                              post_smb_sha256=sha(after) if after.exists() else None)
        if before.exists():
            native_inputs.append(dict(side=side, path=relative(before), sha256=sha(before),
                                      role="Serialized actual finite NURBS call component before native operation; SDK native SMB"))
        before_stats_path, after_stats_path = directory / ("input-" + side + ".json"), directory / ("post-" + side + ".json")
        if before_stats_path.exists() and after_stats_path.exists():
            a, b = read(before_stats_path)["native_stats"], read(after_stats_path)["native_stats"]
            post_metrics[side] = dict(before=a, after=b,
                area_preserved=abs(a["area"]-b["area"])<=1e-6,
                bbox_preserved=max(abs(x-y) for x,y in zip(a["bbox"],b["bbox"]))<=1e-6,
                topology_counts_unchanged=all(a[k]==b[k] for k in ("faces", "edges", "vertices")),
                finite_domain_preservation_scope="Area and bounding box only; full finite masks require independent oracle")
    readback_ok = bool(native_stats and readback_stats and readback_stats.get("valid"))
    for key in ("faces", "edges", "vertices", "components", "material_regions", "manifold_solid"):
        readback_ok = readback_ok and native_stats.get(key) == readback_stats.get(key)
    for key in ("area", "volume"):
        a, b = native_stats.get(key), readback_stats.get(key)
        readback_ok = readback_ok and (a is None and b is None or a is not None and b is not None and abs(a-b)<=max(1e-6,abs(a)*1e-7))
    native_bounds, bounds = native_stats.get("bbox", []), readback_stats.get("bbox", [])
    readback_ok = readback_ok and len(bounds) == 6 and len(native_bounds) == 6 and max(abs(a-b) for a,b in zip(native_bounds,bounds)) <= 1e-6
    envelope = request["diagnostic_working_envelope_mm"]
    outside_envelope = len(bounds) == 6 and any(bounds[i] < envelope[i]-1e-6 or bounds[i+3] > envelope[i+3]+1e-6 for i in range(3))
    input_gates = read(directory / "input-gates.json") if (directory / "input-gates.json").exists() else {}
    post_domain_path = directory / "post-domain-audit.json"
    post_domains = read(post_domain_path) if post_domain_path.exists() else {}
    post_domain_passed = all(post_domains.get(side, {}).get("passed", False) for side in ("left", "right"))
    native_valid = bool(native_stats.get("valid"))
    sheet = native_valid and native_stats.get("material_regions") == 0 and not native_stats.get("manifold_solid") and native_stats.get("faces", 0) > 0
    candidate = operation.get("native_api_success", False) and sheet and readback_ok
    result_mesh = directory / "result.mesh.json"
    status = ("native_candidate_pending_trim_function_and_visual_acceptance" if candidate else
              "timeout" if process.get("timeout") else "native_invalid" if native_stats and not native_valid else
              "native_failed_or_no_patch")
    summary = dict(schema="case36.smlib-faceface-summary.v1", case_number=36, mode=job["mode"],
                   source_mode_candidate=job["source_mode_candidate"], trim_enum=job["trim_enum"], base_trim=job["base_trim"],
                   radius_mm=8, source_brep=request["source_brep"], source_sha256=request["source_sha256"],
                   source_fixture_json=request["source_fixture_json"], source_fixture_sha256=request["source_fixture_sha256"],
                   operation_input_sha256=sha(directory / "before.brep"), run_dir=relative(directory), process=process,
                   operation_input_sha256_scope="canonical_source_brep_fingerprint; SDK reads admitted native SMB components, not this BREP",
                   native_input_files=native_inputs,
                   native_input_pair_sha256=hashlib.sha256(json.dumps([{"side":p["side"],"sha256":p["sha256"]} for p in native_inputs],sort_keys=True,separators=(",", ":")).encode()).hexdigest(),
                   native_input_pair_sha256_scope="SHA256 of ordered side-and-file-SHA256 list; not a single file hash",
                   canonical_before_brep_role="Byte-identical source lineage copy; not the native SDK operation representation",
                   fresh_native_process=True, native_call_started=operation.get("native_call_started", False),
                   native_api_raw_status=operation.get("native_api_raw_status"), operation=operation,
                   outcome=status, candidate_validity_passed=candidate, result_kind="independent_blend_sheet" if sheet else "unverified",
                   native_stats=native_stats, native_readback_stats=readback_stats, native_readback_passed=readback_ok,
                   input_imports=imports, finite_input_gate=input_gates, input_post_hash_checks=equality,
                   input_post_finite_domain_metrics=post_metrics,
                   immutable_source_file_unchanged=sha(REPO / request["source_brep"]) == request["source_sha256"],
                   precall_finite_domains_match_source=input_gates.get("passed", False) and all(i["passed"] for i in imports),
                   post_input_geometry_domain_preserved=post_domain_passed,
                   post_input_geometry_domain_preservation_scope="Native area/bbox plus 17x17 original-mask coverage and 129 samples per actual post-boundary edge; sampled domain proof",
                   post_input_topology_preserved=bool(post_metrics) and all(i["topology_counts_unchanged"] for i in post_metrics.values()),
                   post_input_domain_evidence=dict(path=relative(post_domain_path), sha256=sha(post_domain_path)) if post_domain_path.exists() else None,
                   original_finite_input_admitted=input_gates.get("passed", False),
                   result_mesh=relative(result_mesh) if result_mesh.exists() else None,
                   before_mesh=combine_before(directory), solver_contact_tolerance_mm=1e-6,
                   approximation_accuracy_parameter=.001, cross_section="exact rational circular", approximation_enabled=False,
                   explicit_post_crop=False, diagnostic_working_envelope_mm=envelope, outside_diagnostic_working_envelope=outside_envelope,
                   actual_native_bbox_mm=bounds, base_trim_behavior="Requested base_trim0. Return is measured independently; call copies may split wall topology. Raw source objects remain separate.",
                   trim_function_passed=False, trim_function_status="requires independent end/rail oracle; enum name is a candidate mapping",
                   source_special_feature_passed=False, full_quality_passed=False, human_appearance_status="pending")
    summary["artifacts"] = {p.name: dict(path=relative(p), sha256=sha(p)) for p in directory.iterdir() if p.is_file() and p.name != "summary.json"}
    write(directory / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=Path, default=REPO / "data/case36-faceface/smlib-requests.json")
    parser.add_argument("--output", type=Path, default=REPO / "runs/case36-faceface/smlib")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    if not 0 < args.timeout <= 60:
        parser.error("Native watchdog must be >0 and <=60 seconds")
    output = args.output.resolve(); relative(output)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        parser.error("Refusing to overwrite existing native evidence")
    request = read(args.requests)
    source, fixture_path = REPO / request["source_brep"], REPO / request["source_fixture_json"]
    if sha(source) != request["source_sha256"] or sha(fixture_path) != request["source_fixture_sha256"]:
        raise ValueError("Original source/fixture hash mismatch")
    fixture = read(fixture_path)
    if fixture["source_sha256"] != request["source_sha256"] or fixture["source_brep"] != request["source_brep"]:
        raise ValueError("Original exact fixture lineage mismatch")
    shutil.copyfile(source, output / "before.brep")
    assert sha(output / "before.brep") == request["source_sha256"]
    write(output / "requests.json", request)
    config = configuration(); binary, provenance = build_worker(config)
    write(output / "binary-provenance.json", provenance)
    binaries, importer_provenance = build_common(config)
    native_paths, imports = [], []
    for side in ("left", "right"):
        prepared = dict(component_index=request[side + "_component_index"], source_fixture_sha256=sha(fixture_path))
        directory, report, _ = import_component(prepared, fixture, binaries, importer_provenance, args.timeout)
        imports.append(dict(side=side, import_dir=relative(directory), **report))
        if not report["passed"]:
            write(output / "input-import.json", imports)
            raise ValueError("Exact original finite input import failed; no fillet called")
        native_paths.append(directory / "component-1.smb")
    write(output / "input-import.json", imports)
    index = dict(schema="case36.smlib-faceface-index.v1", source_brep=request["source_brep"], source_sha256=request["source_sha256"],
                 source_fixture_json=request["source_fixture_json"], source_fixture_sha256=request["source_fixture_sha256"],
                 requests=relative(args.requests), requests_sha256=sha(args.requests),
                 scope_root=relative(output), engine_version=provenance["engine_version"], sdk_source_commit=provenance["sdk_source_commit"],
                 core_library_sha256=provenance["core_library_sha256"], rows=[], native_calls_executed=0,
                 trim_modes_functionally_passed=0, explicit_post_crop=False)
    code = output / "code"; code.mkdir()
    for path in (HERE / "worker.cpp", HERE / "run.py", REPO / "tools/run_case36_smlib.py"):
        shutil.copyfile(path, code / path.name)
    for job in request["variants"]:
        directory = output / (job["mode"] + "-base" + str(job["base_trim"]))
        directory.mkdir();shutil.copyfile(source, directory / "before.brep");write(directory / "job.json", dict(request, variant=job))
        process = child([str(binary), *[str(p) for p in native_paths], str(job["trim_enum"]), str(job["base_trim"]), str(directory)], directory, args.timeout, "native")
        summary = evaluated_summary(directory, job, process, request, imports)
        summary_path = directory / "summary.json"
        index["rows"].append({key: summary[key] for key in ["mode", "source_mode_candidate", "radius_mm", "run_dir", "source_sha256", "operation_input_sha256", "operation_input_sha256_scope", "native_input_files", "native_input_pair_sha256", "result_mesh", "before_mesh", "native_call_started", "native_api_raw_status", "native_readback_passed", "result_kind", "outcome", "candidate_validity_passed", "actual_native_bbox_mm", "outside_diagnostic_working_envelope", "immutable_source_file_unchanged", "precall_finite_domains_match_source", "post_input_geometry_domain_preserved", "post_input_geometry_domain_preservation_scope", "post_input_topology_preserved", "post_input_domain_evidence"]})
        index["rows"][-1].update(summary=relative(summary_path), summary_sha256=sha(summary_path))
        index["native_calls_executed"] += int(summary["native_call_started"])
        write(output / "index.json", index)
        print(json.dumps(index["rows"][-1]), flush=True)
    index["completed_at"] = datetime.now(timezone.utc).isoformat();write(output / "index.json", index)
    return 0


if __name__ == "__main__":
    sys.exit(main())
