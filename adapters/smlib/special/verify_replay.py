#!/usr/bin/env python3
"""Audit fresh replay coverage and compare explicit historical/fresh mesh data."""
from pathlib import Path
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import platform
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "tools"))
from export_special_evidence import sanitize


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mesh(path):
    if not path or not path.is_file():
        return None
    value = read(path)
    nv = len(value["vertices"])
    assert nv and value["triangles"]
    assert all(len(t) == 3 and min(t) >= 0 and max(t) < nv for t in value["triangles"])
    assert len(value["face_ids"]) in [0, len(value["triangles"])]
    canonical = {k: value[k] for k in ["vertices", "triangles", "face_ids", "edges"]}
    points = value["vertices"]
    return {"file_sha256": sha(path), "vertices": nv, "triangles": len(value["triangles"]),
            "bbox": [min(p[k] for p in points) for k in range(3)] + [max(p[k] for p in points) for k in range(3)],
            "normalized_content_sha256": hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, default=REPO / "docs/special-reproducibility.json")
    args = ap.parse_args()
    frozen = read(HERE / "jobs.json")["jobs"]
    history = read(REPO / "web/data/supplemental/index.json")
    old = {f"{n}/{v['id']}": v for n, vs in history["cases"].items() for v in vs}
    rows, provenance = [], {}
    for job in frozen:
        key = job["job_id"]
        directory = args.runs_root / key
        p = directory / "summary.json"
        if not p.is_file():
            rows.append({"job_id": key, "supported": True, "tested": False, "driver": job["driver"]})
            continue
        fresh = read(p)
        baseline = old[key]
        historical = mesh(REPO / "web" / baseline["smlib"]["mesh"]) if baseline["smlib"]["mesh"] else None
        actual = mesh(directory / "display-result.json")
        before = mesh(directory / "display-input.json")
        binary = read(directory / "binary-provenance.json") if (directory / "binary-provenance.json").is_file() else None
        if binary:
            provenance[job["driver"]] = binary
        status = fresh["execution"]["native_api_raw_status"]
        rows.append({"job_id": key, "supported": True, "tested": fresh["freshly_executed"], "driver": job["driver"],
                     "outcome": fresh["outcome"], "native_execution": fresh["execution"],
                     "historical_category": baseline["smlib"]["status"],
                     "historical_api_status": baseline["smlib"]["api_status"],
                     "same_recorded_api_status": status == baseline["smlib"]["api_status"],
                     "historical_mesh": historical, "fresh_mesh": actual, "fresh_input_mesh": before,
                     "same_result_mesh_availability": bool(historical) == bool(actual),
                     "normalized_mesh_data_identical": historical["normalized_content_sha256"] == actual["normalized_content_sha256"] if historical and actual else None,
                     "fresh_summary_sha256": sha(p),
                     "historical_summary_sha256": sha(REPO / "web" / baseline["smlib"]["summary"]),
                     "additional_runs": fresh.get("additional_runs", []),
                     "replay_command": "python3 adapters/smlib/special/run.py --job " + key,
                     "source_feature_passed": False})
    tested = [r for r in rows if r["tested"]]
    outcomes = Counter(r["outcome"] for r in tested)
    record = {"schema": "filletbench.special-replay-verification.v1",
              "generated_at": datetime.now(timezone.utc).isoformat(),
              "tested_host": {"system": platform.system(), "architecture": platform.machine()},
              "scope": "All 51 frozen consumer requests have a fresh runtime path. This audit checks execution evidence, API status and explicit mesh data only; it does not certify full special-feature geometry or cross-kernel equivalence.",
              "counts": {"supported": len(frozen), "tested": len(tested), "driver_programs": len(provenance),
                         "case_families": len({j['case_number'] for j in frozen}),
                         "process_outcomes": dict(outcomes),
                         "native_api_success": sum(r['native_execution']['native_api_success'] is True for r in tested),
                         "native_api_failure": sum(r['native_execution']['native_api_success'] is False for r in tested),
                         "nonempty_result_meshes": sum(bool(r.get('fresh_mesh')) for r in tested),
                         "input_meshes": sum(bool(r.get('fresh_input_mesh')) for r in tested),
                         "same_recorded_api_status": sum(r['same_recorded_api_status'] for r in tested),
                         "same_result_mesh_availability": sum(r['same_result_mesh_availability'] for r in tested),
                         "normalized_mesh_data_identical": sum(r['normalized_mesh_data_identical'] is True for r in tested)},
              "untested_platforms": ["Linux", "Windows"], "sdk_and_compiler_provenance_by_driver": provenance,
              "consumer_source_provenance": "adapters/smlib/special/source-provenance.json",
              "comparison_boundary": "Identical normalized data means identical ordered vertices/triangles/face IDs/edge samples. A different data hash is not, by itself, a geometric mismatch. Historical and fresh file SHA values are always recorded separately.",
              "rows": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sanitize(record), ensure_ascii=False, indent=2) + "\n")
    public = REPO / "web/data/supplemental/replay-verification.json"
    public.write_text(json.dumps(sanitize(record), ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps(record["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
