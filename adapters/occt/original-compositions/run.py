#!/usr/bin/env python3
"""Route original review variant IDs to their immutable fresh geometry recipes.

--variant selects the original view to verify and report. Existing driver batch
granularity is retained and recorded; case33/34 execute their seven recipes.
No historical run directory is required. Use a fresh --output for every run.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
MANIFEST=HERE/'protocol-manifest.json'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text())
def write(path,data):Path(path).write_text(json.dumps(data,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def verify_execution(out,relative):
    """Verify the actual requested result, never promote process exit to pass."""
    path=out/relative
    if not path.is_file():return dict(summary=relative,passed=False,reason='Expected fresh summary was not produced')
    trial=read(path)
    artifacts=trial.get('artifacts',{})
    files={}
    for key in ('before_brep','before_mesh','result_brep','result_mesh'):
        artifact=artifacts.get(key)
        file=path.parent/artifact if artifact else None
        files[key]=dict(path=str(file.relative_to(out)) if file else None,exists=bool(file and file.is_file()),sha256=sha(file) if file and file.is_file() else None)
    result=trial.get('result',{})
    stats=result.get('readback_stats',result.get('stats',{}))
    mesh=result.get('mesh',{})
    okay=trial.get('outcome') in ('ok','success') and all(f['exists'] for f in files.values()) and stats.get('valid') is True and mesh.get('status')=='ok'
    return dict(summary=relative,summary_sha256=sha(path),passed=okay,
        outcome=trial.get('outcome'),source_sha256=trial.get('source_sha256'),
        method=trial.get('method_kind'),artifacts=files,
        result_readback_valid=stats.get('valid'),result_mesh_status=mesh.get('status'))


def main():
    manifest=read(MANIFEST)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',required=True,type=int,choices=tuple(map(int,manifest['cases'])))
    parser.add_argument('--variant',help='Exact original review variant ID; default all views for --case')
    parser.add_argument('--output',required=True,type=Path,help='Fresh output root; must not contain files')
    args=parser.parse_args()
    case=manifest['cases'][str(args.case)]
    variants=[v for v in case['variants'] if args.variant is None or v['original_variant_id']==args.variant]
    if not variants:parser.error('Unknown original variant for this case; choose '+', '.join(v['original_variant_id'] for v in case['variants']))
    if version(manifest['binding'])!=manifest['binding_version']:raise RuntimeError('Requires pinned '+manifest['binding']+'=='+manifest['binding_version'])
    driver=manifest['drivers'][case['driver_id']]
    script=REPO/driver['script']
    if sha(script)!=driver['driver_sha256']:raise RuntimeError('Immutable driver SHA differs from protocol manifest; review the protocol before running')
    source=REPO/case['source_brep']
    if sha(source)!=case['source_sha256']:raise RuntimeError('Frozen original source SHA differs from protocol manifest')
    out=args.output.resolve()
    if out.exists() and any(out.iterdir()):raise RuntimeError('Output is nonempty; choose a fresh --output')
    out.mkdir(parents=True,exist_ok=True)
    placeholders={'case':str(args.case),'output':str(out)}
    command=[sys.executable,str(script)]+[x.format(**placeholders) for x in driver['arguments']]
    record=dict(schema_version=1,created_at=datetime.now(timezone.utc).isoformat(),
        requested_case=args.case,requested_variant=args.variant,
        protocol_manifest='adapters/occt/original-compositions/protocol-manifest.json',protocol_manifest_sha256=sha(MANIFEST),
        umbrella_sha256=sha(__file__),driver=driver['script'],driver_sha256=driver['driver_sha256'],
        driver_arguments=driver['arguments'],execution_scope=driver['execution_scope'],
        source_sha256=case['source_sha256'],engine=manifest['engine'],engine_version=manifest['engine_version'],
        binding_version=manifest['binding_version'],selected_original_variant_ids=[v['original_variant_id'] for v in variants],
        source_feature_certified=False,native_special_feature_api_used=False,outcome='started')
    write(out/'routing-summary.json',record)
    result=subprocess.run(command,cwd=REPO,text=True,capture_output=True)
    (out/'driver.stdout.log').write_text(result.stdout.replace(str(REPO),'<repo>').replace(str(out),'<output>'))
    (out/'driver.stderr.log').write_text(result.stderr.replace(str(REPO),'<repo>').replace(str(out),'<output>'))
    record['process_returncode']=result.returncode
    record['variants']=[]
    for variant in variants:
        executions=[verify_execution(out,p) for p in variant['summary_files']]
        record['variants'].append(dict(original_variant_id=variant['original_variant_id'],method=variant['method'],
            executions=executions,passed=all(e['passed'] for e in executions)))
    record['selected_unique_execution_count']=len({e['summary'] for v in record['variants'] for e in v['executions']})
    record['selected_review_view_count']=len(record['variants'])
    record['outcome']='ok' if result.returncode==0 and all(v['passed'] for v in record['variants']) else 'failed'
    record['finished_at']=datetime.now(timezone.utc).isoformat()
    write(out/'routing-summary.json',record)
    print(json.dumps(dict(case=args.case,variant=args.variant,outcome=record['outcome'],driver=driver['script'],
        execution_scope=driver['execution_scope'],selected_review_view_count=record['selected_review_view_count'],
        selected_unique_execution_count=record['selected_unique_execution_count'],routing_summary=str(args.output/'routing-summary.json'))),flush=True)
    return 0 if record['outcome']=='ok' else 2


if __name__=='__main__':sys.exit(main())
