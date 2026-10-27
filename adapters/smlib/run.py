#!/usr/bin/env python3
"""Fresh native SMLib operation from a hash-bound, published exact NURBS fixture."""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import resource
import subprocess
import sys

from build import HERE, REPO, MissingDependency, build, configuration, sha
from exchange import encode
from geometry import infer_target, summarize, tokens, write
from verify import verify


def relative(path):
    return os.path.relpath(Path(path).resolve(), REPO)


def read(path):
    return json.loads(Path(path).read_text())


def source_path(job, key):
    value = job.get(key)
    if not isinstance(value, str) or Path(value).is_absolute():
        raise ValueError(key + " must be a repository-relative path")
    path = (REPO / value).resolve()
    if not path.is_relative_to(REPO) or not path.is_file():
        raise ValueError(key + " is missing or escapes the repository")
    return path


def checked_hash(path, expected, label):
    actual = sha(path)
    if not expected or expected != actual:
        raise ValueError(label + " SHA256 mismatch or missing expected hash")
    return actual


def child(cmd, directory, timeout, label):
    """Keep complete native logs even when a watchdog or native signal stops it."""
    record = dict(return_code=None, timeout=False, watchdog_seconds=timeout, fresh_process=True)
    with (directory / (label + ".stdout.log")).open("w") as stdout, (directory / (label + ".stderr.log")).open("w") as stderr:
        try:
            result = subprocess.run(cmd, cwd=REPO, stdout=stdout, stderr=stderr, timeout=timeout,
                                    preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0)))
            record["return_code"] = result.returncode
        except subprocess.TimeoutExpired:
            record["timeout"] = True
    return record


def import_component(job, fixture, binaries, provenance, timeout):
    component_index = job.get("component_index")
    if not isinstance(component_index, int) or isinstance(component_index, bool) or not 1 <= component_index <= len(fixture["components"]):
        raise ValueError("component_index must be a 1-based index into fixture.components")
    component = fixture["components"][component_index - 1]
    identity = dict(source_fixture_sha256=job["source_fixture_sha256"], component_index=component_index,
                    core_library_sha256=provenance["core_library_sha256"],
                    importer_binary_sha256=provenance["consumer_binary_sha256"]["ingest"],
                    verifier_source_sha256=sha(HERE / "verify.py"), encoder_source_sha256=sha(HERE / "exchange.py"))
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    directory = REPO / ".cache/smlib-inputs" / digest
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "import.lock").open("w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if (directory / "import.json").exists():
            report = read(directory / "import.json")
            native = directory / "component-1.smb"
            if report.get("passed") and (not native.exists() or sha(native) != report.get("native_smb_sha256")):
                raise ValueError("hash-bound cached native input changed; remove its cache directory to rebuild")
            return directory, report, component
        report = dict(identity, constructed_at=datetime.now(timezone.utc).isoformat(),
                      input_track="explicit_exact_NURBS_exchange_no_stitch_heal",
                      automatic_heal=False, stitch=False, thickening=False, passed=False)
        token = directory / "exchange.tokens"
        token.write_text(encode(component))
        report["exchange_tokens_sha256"] = sha(token)
        report["process"] = child([str(binaries["ingest"]), relative(token), relative(directory)], directory, timeout, "import")
        try:
            stats, readback = [read(directory / name) for name in ("component-1-stats.json", "component-1-readback-stats.json")]
            checks = dict(native_valid=bool(stats.get("native_valid")), native_readback_valid=bool(readback.get("native_valid")),
                          topology_counts=all(stats[k] == expected for k, expected in (
                              ("faces", sum(len(sh["faces"]) for sh in component["shells"])),
                              ("edges", len(component["edges"])), ("vertices", len(component["vertices"])))),
                          material_type=stats["material_regions"] == (1 if component["kind"] == "solid" else 0),
                          process_exit=report["process"]["return_code"] == 0 and not report["process"]["timeout"])
            report["native_gates"] = checks
            report["equivalence"] = verify(component, read(directory / "component-1-samples.json"), stats,
                                             read(directory / "component-1-volume.json"))
            report["passed"] = all(checks.values()) and report["equivalence"]["passed"]
        except Exception as error:
            report["inspection_error"] = str(error)
        native = directory / "component-1.smb"
        report["native_smb_sha256"] = sha(native) if native.exists() else None
        report["artifacts"] = {p.name: sha(p) for p in directory.iterdir() if p.is_file() and p.name not in ("import.json", "import.lock")}
        write(directory / "import.json", report)
        return directory, report, component


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", help="JSON job path; source paths inside it are relative to repository root")
    parser.add_argument("--output", "--output-dir", dest="output", help="fresh output directory")
    parser.add_argument("--timeout", type=float, default=60, help="watchdog seconds per native import/operation (maximum 60)")
    args = parser.parse_args()
    job_path = Path(args.job).resolve()
    job = read(job_path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run = Path(args.output).resolve() if args.output else REPO / "runs/smlib" / str(job["job_id"]) / stamp
    run.mkdir(parents=True, exist_ok=True)
    if any(run.iterdir()):
        raise SystemExit("Refusing to overwrite a nonempty output directory; use a fresh --output")
    write(run / "job.json", job)
    process = dict(return_code=None, timeout=False, watchdog_seconds=min(60, args.timeout), fresh_process=True,
                   started_at=datetime.now(timezone.utc).isoformat())
    outcome = None
    importer = None
    provenance = None
    try:
        if not 0 < args.timeout <= 60:
            raise ValueError("--timeout must be greater than 0 and at most 60 seconds")
        config = configuration()
        source = source_path(job, "source_brep")
        fixture_path = source_path(job, "source_fixture_json")
        checked_hash(source, job.get("source_sha256"), "source BREP")
        checked_hash(fixture_path, job.get("source_fixture_sha256"), "source fixture")
        fixture = read(fixture_path)
        if fixture.get("source_sha256") != job["source_sha256"]:
            raise ValueError("fixture and job disagree on source BREP lineage")
        if (job.get("admission") or {}).get("allowed") is False:
            outcome = "adapter_not_ready"
            raise ValueError("job admission is blocked")
        if not job.get("runnable_by_selected_edge_runner", True):
            outcome = "adapter_not_ready"
            raise ValueError(job.get("blocked_reason") or "job is not supported by selected-edge consumer")
        variable_start = job.get("variable_start_mm", job.get("variable_start"))
        variable_end = job.get("variable_end_mm", job.get("variable_end"))
        if (variable_start is None) != (variable_end is None):
            raise ValueError("variable-radius law needs both start and end radii")
        radii = [variable_start, variable_end] if variable_start is not None and variable_end is not None else [job.get("radius_mm", 0)]
        if any(not isinstance(r, (int, float)) or not 0 < r < float("inf") for r in radii):
            raise ValueError("every supplied fillet radius must be finite and positive")
        targets = [infer_target(t, i) for i, t in enumerate(job.get("targets", []))]
        if not targets:
            raise ValueError("no target geometry supplied; no native edge-index fallback")
        binaries, provenance = build(config)
        write(run / "binary-provenance.json", provenance)
        import_dir, importer, component = import_component(job, fixture, binaries, provenance, args.timeout)
        write(run / "import.json", importer)
        if not importer["passed"]:
            outcome = "import_failed"
            raise ValueError("fresh exact NURBS import failed native/equivalence gates; fillet was not called")
        native = import_dir / "component-1.smb"
        prepared = dict(job, input_smb=relative(native), input_smb_sha256=sha(native), source_stats=component["source_stats"])
        write(run / "prepared-targets.json", targets)
        token = run / "job.tokens"
        token.write_text(tokens(prepared, relative(run), targets))
        guard = sha(native)
        process.update(child([str(binaries["native_fillet_runner"]), relative(token)], run, args.timeout, "native"))
        process["source_input_smb_unchanged"] = sha(native) == guard
    except MissingDependency as error:
        outcome = "missing_dependency"
        process["preflight_error"] = str(error)
    except Exception as error:
        process["preflight_error"] = str(error)
    process["finished_at"] = datetime.now(timezone.utc).isoformat()
    write(run / "process.json", process)
    summary = summarize(run, job, process)
    if outcome:
        summary["outcome"] = outcome
    summary.update(run_dir=relative(run), job_file=relative(job_path),
                   source_brep=job.get("source_brep"), source_fixture_json=job.get("source_fixture_json"),
                   source_fixture_sha256=job.get("source_fixture_sha256"), component_index=job.get("component_index"),
                   input_import=importer, engine_version=provenance["engine_version"] if provenance else None,
                   sdk_source_commit=provenance["sdk_source_commit"] if provenance else None)
    summary["artifacts"] = {p.name: dict(path=p.name, sha256=sha(p)) for p in run.iterdir() if p.is_file() and p.name != "summary.json"}
    write(run / "summary.json", summary)
    print(json.dumps(dict(outcome=summary["outcome"], run_dir=relative(run),
                          native_api=summary["execution"].get("native_api_raw_status"), timeout=process["timeout"])))
    return 0 if summary["outcome"] == "native_candidate" else 2


if __name__ == "__main__":
    sys.exit(main())
