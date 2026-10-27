#!/usr/bin/env python3
"""Execute each published job freshly in an isolated bounded OCCT subprocess."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=Path, default=Path("data/jobs"))
    parser.add_argument("--output", type=Path, default=Path("runs/fresh-occt"))
    parser.add_argument("--workers", type=int, default=4, choices=range(1, 5))
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    jobs = sorted(args.jobs.glob("*.json"))
    if not jobs:
        parser.error("No JSON jobs found")

    def run(path):
        job = json.loads(path.read_text(encoding="utf-8"))
        destination = args.output / job["job_id"]
        process = subprocess.run([sys.executable, str(Path(__file__).with_name("run.py")),
            str(path.resolve()), "--output", str(destination.resolve()),
            "--timeout", str(args.timeout)], capture_output=True, text=True)
        summary = destination / "summary.json"
        if process.returncode or not summary.exists():
            raise RuntimeError(f"Runner infrastructure failure for {job['job_id']}: {process.stderr[-2000:]}")
        return json.loads(summary.read_text(encoding="utf-8"))

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run, path): path for path in jobs}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps({"job_id": result["job_id"], "outcome": result["outcome"],
                              "api_success": result["api_success"]}), flush=True)
    results.sort(key=lambda x: x["job_id"])
    aggregate = {"schema_version": 1, "engine": "OCCT", "engine_version": "7.9.3",
        "binding_version": "7.9.3.1.1", "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution": "fresh bounded subprocess per job; no historical result reuse",
        "workers": args.workers, "timeout_seconds": args.timeout,
        "job_count": len(results), "native_call_count": sum(x["native_call_executed"] for x in results),
        "api_success_count": sum(x["api_success"] for x in results),
        "valid_result_count": sum(x["valid"] is True for x in results),
        "outcomes": dict(Counter(x["outcome"] for x in results)),
        "only_ordinary": True, "special_feature_certified": False,
        "results": [{"job_id": x["job_id"], "outcome": x["outcome"],
            "api_success": x["api_success"], "valid": x["valid"],
            "native_call_executed": x["native_call_executed"], "reason": x["reason"],
            "summary": f"{x['job_id']}/summary.json"} for x in results]}
    (args.output / "index.json").write_text(json.dumps(aggregate, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in aggregate.items() if k != "results"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
