#!/usr/bin/env python3
"""Verify each published SMLib input/result mesh against its exact raw run file.

Identical input/result meshes are permitted: a failed native operation can leave
the input unchanged. The invariant is correct artifact lineage, not inequality.
"""
from pathlib import Path
import argparse
import hashlib
import json

REPO = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(path.read_text())


def expected_mesh(path, raw):
    if not path.exists():
        return None
    data = read(path)
    result = {key: data[key] for key in ("vertices", "triangles", "edges", "selected_edges", "metadata") if key in data}
    result["face_ids"] = data.get("face_ids", data.get("triangle_face_ids", []))
    if raw.exists() and not result.get("edges"):
        result["edges"] = [e["points"] for e in read(raw).get("geometry", {}).get("edges", []) if e.get("points")]
    return result if result.get("vertices") and result.get("triangles") else None


def check(web, runs, case=None):
    checks, failures, unchanged = 0, [], []
    files = sorted((web / "data/cases").glob("*.json"))
    for path in files:
        data = read(path)
        if case is not None and data.get("number") != case:
            continue
        for variant in data.get("variants", []):
            published = variant.get("smlib", {})
            if published.get("evidence_kind") != "fresh_run":
                continue
            job_id = variant["id"]
            run = runs / job_id
            summary = run / "summary.json"
            public_summary = web / published["summary"]
            if not summary.exists() or not public_summary.exists():
                failures.append(dict(job_id=job_id, artifact="summary", reason="source or published summary missing"))
                continue
            checks += 1
            expected_sha = hashlib.sha256(summary.read_bytes()).hexdigest()
            if read(public_summary).get("publication", {}).get("raw_summary_sha256") != expected_sha:
                failures.append(dict(job_id=job_id, artifact="summary", reason="published source hash is stale or incorrect"))
            payloads = []
            for tag, field in (("before", "before_mesh"), ("result", "mesh")):
                expected = expected_mesh(run / (tag + ".mesh.json"), run / (tag + ".json"))
                link = published.get(field)
                actual = read(web / link) if link and (web / link).is_file() else None
                checks += 1
                payloads.append(actual)
                if expected != actual:
                    failures.append(dict(job_id=job_id, artifact=field, reason="published mesh differs from its exact raw source payload"))
            if payloads[0] is not None and payloads[0] == payloads[1]:
                unchanged.append(dict(job_id=job_id, outcome=published.get("outcome")))
    return dict(checks=checks, passed=not failures, failures=failures, unchanged_mesh_candidates=unchanged)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web", type=Path, default=REPO / "web")
    parser.add_argument("--runs", type=Path, default=REPO / "runs/fresh-smlib")
    parser.add_argument("--case", type=int)
    args = parser.parse_args()
    result = check(args.web.resolve(), args.runs.resolve(), args.case)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
