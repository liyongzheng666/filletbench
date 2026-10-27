#!/usr/bin/env python3
"""Bounded parallel runner for all published SMLib selected-edge jobs."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import argparse
from collections import Counter
import json
import subprocess
import sys

from build import HERE, REPO
from geometry import write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", default="data/jobs")
    parser.add_argument("--output", default="runs/fresh-smlib")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--include-blocked", action="store_true")
    parser.add_argument("--resume", action="store_true", help="keep existing summaries; only start missing jobs")
    args = parser.parse_args()
    if not 1 <= args.workers <= 4:
        parser.error("--workers must be 1..4")
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    jobs = [(p, json.loads(p.read_text())) for p in sorted(Path(args.jobs).glob("*.json"))]
    blocked = [j["job_id"] for _, j in jobs if not j.get("runnable_by_selected_edge_runner", True)]
    jobs = [(p, j) for p, j in jobs if args.include_blocked or j["job_id"] not in blocked]

    def run(item):
        path, job = item
        directory = output / job["job_id"]
        summary = directory / "summary.json"
        if args.resume and summary.exists():
            return json.loads(summary.read_text())
        result = subprocess.run([sys.executable, str(HERE / "run.py"), str(path.resolve()), "--output", str(directory)],
                                capture_output=True, text=True, cwd=REPO)
        if not summary.exists():
            return dict(job_id=job["job_id"], outcome="driver_failed", driver_exit_code=result.returncode,
                        driver_stderr=result.stderr)
        return json.loads(summary.read_text())

    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(run, item) for item in jobs]
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            print(json.dumps(dict(completed=len(rows), total=len(jobs), job_id=row["job_id"], outcome=row["outcome"])), flush=True)
    report = dict(engine="SMLib", jobs=len(rows), workers=args.workers, outcomes=dict(Counter(r["outcome"] for r in rows)),
                  skipped_adapter_not_ready=blocked if not args.include_blocked else [],
                  rows=[dict(job_id=r["job_id"], outcome=r["outcome"],
                             summary=r.get("run_dir", "") + "/summary.json") for r in sorted(rows, key=lambda r: r["job_id"])])
    write(output / "batch-summary.json", report)
    print(json.dumps(report["outcomes"]))


if __name__ == "__main__":
    main()
