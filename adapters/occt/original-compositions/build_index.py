#!/usr/bin/env python3
"""Bind fresh original composition executions to the frozen review variant IDs."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

REPO=Path(__file__).resolve().parents[3]
NUMBERS=(16,17,18,19,20,21,23,33,34)


def read(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def rel(path):return str(Path(path).relative_to(REPO))


def main():
    p=argparse.ArgumentParser();p.add_argument('--runs',type=Path,default=REPO/'runs/original-occ-compositions');a=p.parse_args()
    runs=a.runs.resolve();rows=[];attempts=[];mapping={}
    for n in NUMBERS:
        path=runs/f'case{n:02d}/summary.json'
        if path.is_file():
            for trial in read(path).get('trials',[]):
                tid=trial.get('original_variant_id',trial.get('id'))
                mapping[(n,tid)]=[runs/f'case{n:02d}'/tid/'summary.json']
                attempts.append(dict(number=n,execution_id=tid,summary=rel(mapping[(n,tid)][0]),outcome=trial.get('outcome')))
    mixed=runs/'case33_34-summary.json'
    if mixed.is_file():
        summary=read(mixed)
        for key,artifacts in summary.get('original_variant_artifacts',{}).items():
            n,tid=key.split('/',1);mapping[(int(n),tid)]=[runs/x['run'] for x in artifacts]
        for t in summary.get('trials',[]):
            key=(t['case_number'],t['variant'])
            paths=mapping.get(key,[])
            attempts.append(dict(number=key[0],execution_id=key[1],summary=rel(paths[0]) if paths else None,outcome=t.get('outcome')))
    unique=set()
    for n in NUMBERS:
        corpus=read(REPO/f'data/original-occ/cases/{n:02d}.json')
        for variant in corpus['variants']:
            paths=mapping.get((n,variant['id']),[])
            executions=[]
            for path in paths:
                t=read(path);unique.add(str(path))
                okay=t.get('outcome') in ('success','ok')
                executions.append(dict(summary=rel(path),summary_sha256=sha(path),run_dir=rel(path.parent),
                    outcome=t.get('outcome'),fresh_execution=True,execution_succeeded=okay,
                    method=t.get('method_kind'),artifacts=t.get('artifacts',{}),
                    radius_mm=t.get('radius_mm',t.get('parameters',{}).get('radius_mm')),
                    parameters=t.get('parameters',{}),
                    historical_comparison=t.get('historical_comparison',t.get('historical_geometry_comparison',t.get('historical_result_comparison')))))
            row=dict(number=n,variant_id=variant['id'],method=variant['method'],
                source_sha256=corpus['source_sha256'],source_brep=corpus['source_brep'],
                reproduce=f"python adapters/occt/original-compositions/run.py --case {n:02d} --variant {variant['id']} --output runs/replay-case{n:02d}-{variant['id']}",
                fresh_run=bool(executions),execution_succeeded=bool(executions) and all(e['execution_succeeded'] for e in executions),
                source_feature_certified=False,native_special_feature_api_used=False,
                status='fresh_execution' if executions else 'historical_snapshot_not_fresh',executions=executions)
            if executions:
                row.update(summary=executions[0]['summary'],run_dir=executions[0]['run_dir'],artifacts=executions[0]['artifacts'])
            else:row['gap']='Original review variant has no matching fresh composition execution in this index.'
            rows.append(row)
    index=dict(schema_version=1,created_at=datetime.now(timezone.utc).isoformat(),
        scope='Recorded original OCC review variants only; explicit composition versus ordinary control retained',
        engine='OCCT',engine_version='7.9.3',original_runtime='FreeCAD/OCCT7.8.1',runtime_equivalence=False,
        rows=rows,execution_attempts=attempts,
        counts=dict(review_variants=len(rows),fresh_review_variants=sum(r['fresh_run'] for r in rows),
                    successful_review_variants=sum(r['execution_succeeded'] for r in rows),unique_bound_executions=len(unique),
                    all_execution_attempts=len(attempts)),
        limits='No native source-feature certificate, STEP roundtrip, cross-kernel equivalence or new human appearance acceptance is implied.')
    (runs/'index.json').write_text(json.dumps(index,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    print(json.dumps(index['counts']))


if __name__=='__main__':main()
