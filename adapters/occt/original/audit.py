#!/usr/bin/env python3
"""Independently audit original-suite execution coverage and parameter binding."""
import argparse,hashlib,json,math
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dist(a,b):return math.sqrt(sum((x-y)**2 for x,y in zip(a,b)))
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--requests',type=Path,default=Path(__file__).with_name('requests.json'));parser.add_argument('--runs',type=Path,default=ROOT/'runs/original-occ-native');args=parser.parse_args()
    doc=json.loads(args.requests.read_text());issues=[];rows=[];cases=set();completed=set();modes=Counter();outcomes=Counter()
    for job in doc['jobs']:
        job_id=job['job_id'];p=args.runs/job_id/'summary.json'
        def require(ok,message):
            if not ok:issues.append({'job_id':job_id,'message':message})
        require(p.is_file(),'Summary missing')
        if not p.is_file():continue
        d=json.loads(p.read_text());outcomes[d['outcome']]+=1;cases.add(job['case_number']);modes[d.get('preprocess',{}).get('execution_mode','unknown')]+=1
        require(d.get('process',{}).get('returncode')==0,'Worker process did not exit cleanly')
        require(d['request_sha256']==hashlib.sha256(json.dumps(job,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),'Actual execution request hash differs')
        require(d['parameters']==job['parameters'],'Actual parameters differ from request')
        require(d.get('adapter_sha256')==sha(Path(__file__).with_name('run.py')),'Final adapter source hash differs')
        require(d.get('geometry_helper_sha256')==sha(Path(__file__).with_name('geometry.py')),'Final geometry helper source hash differs')
        require(d['source_sha256']==job['source_sha256']==sha(ROOT/job['source_brep']),'Source hash binding differs')
        require(d['original_case_number']==job['case_number'] and d['original_variant_id']==job['original_variant_id'],'Original case/variant identity differs')
        require(d.get('special_feature_certified') is False,'Native control improperly certifies source special mode')
        require(d.get('human_appearance_acceptance')=='pending','Human appearance state was upgraded without review')
        require(d['outcome'] not in ['initializing','exception','crash','dependency_error'],'Execution infrastructure did not complete')
        before=p.parent/'before.brep';require(before.is_file(),'Actual operation BREP not preserved')
        if before.is_file():require(d.get('operation_input_sha256')==sha(before),'Actual operation input hash not bound')
        for selection in d.get('selection',[]):require(selection['candidate_count']==1,'Original finite target was not resolved uniquely')
        if d['native_call_executed']:
            completed.add(job['case_number'])
            effective=d.get('effective_parameters',{});require(all(effective.get(k)==v for k,v in job['parameters'].items()),'Effective call parameters differ')
        if job.get('source_revision')=='source_revision_mismatch':
            require(job['track']=='historical_batch_native','Old source revision admitted as current default')
            require(d.get('preprocess',{}).get('execution_mode')=='frozen_prepared_input_replay','Unavailable historical base incorrectly marked from_base')
        if job['parameters']['radius_mode']=='two_end_variable':
            for step in d.get('steps',[]):
                b=step.get('radius_binding',{});require(b.get('verified'),'Physical endpoint radius binding not verified')
                if not b:continue
                points=[b['contour_first_mm'],b['contour_last_mm']];radii=[b['contour_first_radius_mm'],b['contour_last_radius_mm']]
                for point,radius in [(job['parameters']['physical_start_mm'],job['parameters']['start_radius_mm']),(job['parameters']['physical_end_mm'],job['parameters']['end_radius_mm'])]:
                    matches=[r for p,r in zip(points,radii) if dist(point,p)<1e-5]
                    require(len(matches)==1 and abs(matches[0]-radius)<1e-10,'Effective physical endpoint radius changed')
        if d['api_success']:
            require((p.parent/'result.brep').is_file(),'Native candidate BREP was dropped')
            require((p.parent/'result.mesh.json').is_file(),'Native candidate mesh was dropped')
            require(bool(d.get('native')),'Native validation gate absent')
            require('step_roundtrip' in d,'STEP readback gate absent')
            step_settings=d.get('step_settings',{})
            require(step_settings.get('controller_initialized') is True,'STEP controller initialization absent')
            require(step_settings.get('effective')==step_settings.get('requested') and all(step_settings.get('set_succeeded',{}).values()),'STEP settings were not actually applied')
            if d['outcome']=='native_and_step_passed':require(d['native']['passed'] and d['step_roundtrip']['passed'],'Published pass does not match separate gates')
        for key,name in d.get('artifacts',{}).items():
            path=p.parent/name;require(path.is_file(),'Missing recorded artifact '+key)
            if key.endswith('_mesh') and path.is_file():
                m=json.loads(path.read_text());require(all(k in m for k in ['vertices','triangles','face_ids','edges','selected_edges']),'Mesh schema mismatch')
                require(len(m['triangles'])==len(m['face_ids']),'Mesh face IDs do not cover triangles')
                require(all(len(t)==3 and all(type(i)is int and 0<=i<len(m['vertices']) for i in t) for t in m['triangles']),'Mesh has invalid triangle indices')
        rows.append({'job_id':job_id,'case_number':job['case_number'],'outcome':d['outcome'],'summary_sha256':sha(p)})
    expected={j['case_number'] for j in doc['jobs']}
    if expected-completed:issues.append({'message':'Cases with no actual native build','cases':sorted(expected-completed)})
    report={'schema_version':1,'request_count':len(doc['jobs']),'summary_count':len(rows),'expected_case_count':len(expected),'native_build_case_count':len(completed),'outcomes':dict(outcomes),'execution_modes':dict(modes),'issues':issues,'passed':not issues,'rows':rows}
    (args.runs/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},ensure_ascii=False,indent=2));return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
