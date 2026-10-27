#!/usr/bin/env python3
"""FilletBench portable command line. Kernel results are observations, not passes."""
import argparse, json, pathlib, subprocess, sys, datetime, http.server, functools
ROOT = pathlib.Path(__file__).resolve().parent

def jobs():
    return [json.loads(p.read_text()) for p in sorted((ROOT/'data/jobs').glob('*.json'))]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='cmd',required=True)
    ls=sub.add_parser('list');ls.add_argument('--case',type=int)
    run=sub.add_parser('run');run.add_argument('--engine',choices=['occt','smlib','both'],default='both');run.add_argument('--case',type=int);run.add_argument('--job');run.add_argument('--radius',type=float);run.add_argument('--out',type=pathlib.Path);run.add_argument('--timeout',type=int,default=180)
    special=sub.add_parser('special');special.add_argument('--engine',choices=['occt','smlib'],required=True);special.add_argument('--case',type=int);special.add_argument('--job');special.add_argument('--out',type=pathlib.Path)
    original=sub.add_parser('original');original.add_argument('--case',type=int);original.add_argument('--variant');original.add_argument('--all',action='store_true');original.add_argument('--out',type=pathlib.Path)
    sub.add_parser('verify');sub.add_parser('build-site');build_original=sub.add_parser('build-original');build_original.add_argument('--suite-run',type=pathlib.Path)
    serve=sub.add_parser('serve');serve.add_argument('--port',type=int,default=8740)
    a=p.parse_args()
    if a.cmd=='original':
        cmd=[sys.executable,str(ROOT/'tools/run_original_suite.py')]
        if a.case:cmd+=['--case',str(a.case)]
        if a.variant:cmd+=['--variant',a.variant]
        if a.all:cmd+=['--all']
        if a.out:cmd+=['--out',str(a.out)]
        return subprocess.call(cmd,cwd=ROOT)
    if a.cmd=='build-original':
        cmd=[sys.executable,str(ROOT/'tools/build_original_site.py')]
        if a.suite_run:cmd+=['--suite-run',str(a.suite_run)]
        return subprocess.call(cmd,cwd=ROOT)
    if a.cmd=='verify':return subprocess.call([sys.executable,str(ROOT/'tools/verify.py')])
    if a.cmd=='build-site':return subprocess.call([sys.executable,str(ROOT/'tools/build_site.py')])
    if a.cmd=='special':
        cmd=[sys.executable,str(ROOT/f'adapters/{a.engine}/special/run.py')]
        if a.engine=='occt':
            if not a.case:p.error('OCCT special requires --case')
            cmd+=['--case',str(a.case)]
        else:
            if not a.job:p.error('SMLib special requires --job CASE/variant; see adapters/smlib/special/run.py --list')
            cmd+=['--job',a.job]
        if a.out:cmd+=['--output',str(a.out)]
        return subprocess.call(cmd,cwd=ROOT)
    if a.cmd=='serve':
        handler=functools.partial(http.server.SimpleHTTPRequestHandler,directory=str(ROOT/'web'))
        print(f'Open http://127.0.0.1:{a.port}/',flush=True)
        http.server.ThreadingHTTPServer(('127.0.0.1',a.port),handler).serve_forever();return 0
    chosen=[j for j in jobs() if not a.case or j['number']==a.case]
    if a.cmd=='list':
        for j in chosen:print(j['job_id'],f'R{j["radius_mm"]:g}', 'ready' if j['runnable_by_selected_edge_runner'] else 'blocked: '+str(j.get('blocked_reason')))
        return 0
    if a.job:chosen=[j for j in chosen if j['job_id']==a.job]
    if a.radius is not None:chosen=[j for j in chosen if abs(j['radius_mm']-a.radius)<1e-9]
    if not (a.case or a.job):p.error('Specify --case or --job; use an explicit case to avoid accidental full sweeps.')
    if not chosen:p.error('No matching job. Use list --case NN.')
    out=(a.out or ROOT/'runs'/datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')).resolve()
    out.mkdir(parents=True,exist_ok=True);records=[]
    for j in chosen:
        for engine in (['occt','smlib'] if a.engine=='both' else [a.engine]):
            target=out/engine/j['job_id'];target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists() and any(target.iterdir()):raise SystemExit('Refusing to overwrite evidence: '+str(target))
            controller_log=target.parent/(j['job_id']+'.controller.log')
            cmd=[sys.executable,str(ROOT/f'adapters/{engine}/run.py'),str(ROOT/f'data/jobs/{j["job_id"]}.json'),'--output',str(target)]
            with controller_log.open('w') as log:
                try:
                    r=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=a.timeout)
                    rc=r.returncode;state='completed' if rc==0 else 'adapter_error'
                except subprocess.TimeoutExpired:rc=None;state='controller_timeout'
            target.mkdir(parents=True,exist_ok=True)
            controller_log.replace(target/'controller.log')
            summary=target/'summary.json'
            if summary.exists():state=json.loads(summary.read_text()).get('outcome',state)
            if not summary.exists():
                summary.write_text(json.dumps({'engine':engine,'job_id':j['job_id'],'outcome':state,'returncode':rc,'reason':'Inspect controller.log; no kernel pass inferred.'},indent=2)+'\n')
            records.append({'engine':engine,'job_id':j['job_id'],'status':state,'summary':str(summary.relative_to(out))})
            print(engine,j['job_id'],state,flush=True)
    (out/'index.json').write_text(json.dumps({'schema_version':1,'runs':records},indent=2)+'\n')
    print('Evidence:',out)
    return 0
if __name__=='__main__':sys.exit(main())
