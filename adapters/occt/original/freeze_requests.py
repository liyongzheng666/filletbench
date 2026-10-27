#!/usr/bin/env python3
"""Extract immutable native requests from the original private review workspace.

This one-time preparation utility needs --workspace; public replay only needs
requests.json and content-addressed data/original-occ fixtures. It never edits
private source geometry, original summaries or the current ordinary adapter.
"""
import argparse,hashlib,json,re
from pathlib import Path
import geometry as g
from OCP.TopoDS import TopoDS
from OCP.TopAbs import TopAbs_EDGE

REPO=Path(__file__).resolve().parents[3]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def token(r):return format(float(r),'.10g').replace('.','p')
def read(p):return json.loads(Path(p).read_text())
def scrub(v,workspace):
    if isinstance(v,dict):return {k:scrub(x,workspace) for k,x in v.items() if k not in ['traceback']}
    if isinstance(v,list):return [scrub(x,workspace) for x in v]
    if isinstance(v,str):
        v=v.replace(str(workspace)+'/', '')
        return re.sub(r'(?<!\w)/(?:[^/\s\"]+/)+[^/\s\"]+', '<historical-local-path>', v)
    return v

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace',type=Path,required=True);a=p.parse_args();w=a.workspace.resolve()
    review=read(w/'outputs/manual-review/review-state.json');manifest=read(w/'outputs/parasolid-preblend/manifest.json');mc={c['id']:c for c in manifest['cases']}
    frozen_cases={c['number']:read(REPO/c['path']) for c in read(REPO/'data/original-occ/index.json')['cases']}
    jobs=[];missing={}
    def fixture(path):
        path=Path(path);h=sha(path);dest='data/original-occ/fixtures/'+h+'.brep'
        if not (REPO/dest).is_file():missing[h]=str(path.relative_to(w)) if path.is_relative_to(w) else str(path)
        return dest,h
    def make(n,vid,source,targets,parameters,part_label=None,preprocess=None,operation=None,history=None,history_path=None,revision='current_original',track='current_original_native',aliases=None):
        case=frozen_cases[n];srch=sha(source);sp,sh=fixture(source)
        op,oph=fixture(operation) if operation else (None,None)
        job={'job_id':f'{n:02d}.{vid}','case_number':n,'case_id':case['id'],'original_variant_id':vid,
          'original_variant_ids':aliases or [vid],'track':track,'source_revision':revision,'source_brep':sp,'source_sha256':sh,
          'source_labels':[p['label'] for p in mc[case['id']]['parts']], 'part_label':part_label,
          'preprocess':preprocess or {'type':'none'},'targets':targets,'parameters':parameters,
          'operation_input_brep':op,'operation_input_sha256':oph,
          'historical':{'summary_sha256':sha(history_path) if history_path else None,'record':scrub(history or {},w)},
          'scope_note':'Original manual-review native control; source special semantics and appearance remain unverified.'}
        jobs.append(job);return job
    # Original planned radius sets, including requests the old stop-on-success
    # worker never reached. Recorded old attempts remain explicitly distinct.
    for path in sorted((w/'outputs/manual-review/diagnostics/batch').glob('case*/summary.json')):
        summary=read(path);n=summary['number'];case=frozen_cases[n];source=Path(summary['input_brep']);actual=sha(source)
        for serial,(part,plan) in enumerate(zip(summary['parts'],summary['plan']['parts']),1):
            if plan.get('role')=='auxiliary':continue
            targets=part.get('selected_edges') or next((x['selected_edges'] for x in part.get('attempts',[]) if x.get('selected_edges')),[])
            if not targets:continue
            preprocess=part.get('preprocess',{});pp={'type':'none'}
            if preprocess.get('type')=='external_brep':
                pp={'type':'portable_prepare_d','source_labels':preprocess['source_labels'],'operation_group':plan.get('operation_group')}
            elif preprocess.get('type') in ['sew_parts','sew_shell']:pp={'type':'sew_parts','source_labels':preprocess.get('labels',preprocess.get('source_labels'))}
            for radius in plan['radii']:
                hist=next((x for x in part.get('attempts',[]) if float(x['radius'])==float(radius)),None)
                basic=next((v['id'] for v in case['variants'] if v['id'].startswith('part%02d-r'%serial) and float(v.get('radius_mm',-1))==float(radius)),None)
                mismatch=actual!=summary['input_sha256']
                vid=(basic or f'native-baseline-part{serial:02d}-r{token(radius)}')
                if mismatch:vid=f'historical-batch-part{serial:02d}-r{token(radius)}'
                job=make(n,vid,source,targets,{'radius_mode':'constant','radius_mm':float(radius)},part['label'],pp,
                    Path(part['before_brep']),hist or {'status':'not_executed_in_historical_stop_on_success_worker'},path,
                    'source_revision_mismatch' if mismatch else 'current_original','historical_batch_native' if mismatch else 'current_original_native')
                job['historical_source_sha256']=summary['input_sha256'];job['part_serial']=serial
                if mismatch:job.update(execution_mode='frozen_prepared_input_replay',recipe_gap='Historical full base bytes are unavailable at the original path; current base SHA differs. Frozen original before.brep is replayed independently, never used as the current model default.')
    # Case 08 used its separate ordinary shell probe, not the batch worker.
    case=frozen_cases[8];source=w/'outputs/parasolid-preblend/models'/f"{case['id']}.brep";base=g.read(source);shell=g.shapes(base,g.TopAbs_SHELL)[0]
    edges=[TopoDS.Edge_s(e) for e in g.shapes(shell,TopAbs_EDGE) if len(g.edge_record(shell,TopoDS.Edge_s(e))['adjacent_faces_1based'])==2]
    assert len(edges)==1;target=g.edge_record(shell,edges[0]);history_path=w/'outputs/manual-review/diagnostics/case08/summary.json'
    for hist in read(history_path)['runs']:
        r=hist['radius_mm'];vid='local-demo' if r==12 else 'native-baseline-r'+token(r)
        make(8,vid,source,[target],{'radius_mode':'constant','radius_mm':r},preprocess={'type':'shell'},history=hist,history_path=history_path)
    def new(n,vid,docpath,source,targets,radius=None,parameters=None,preprocess=None,operation=None,history=None,aliases=None):
        return make(n,vid,source,targets,parameters or {'radius_mode':'constant','radius_mm':radius},preprocess=preprocess,
           operation=operation,history=history,history_path=docpath,aliases=aliases)
    # Same current model, full original front chain and topology controls.
    path=w/'outputs/manual-review/diagnostics/case20-patch/native-trials/runs/20261019T225952.157032/summary.json';doc=read(path);source=Path(doc['input_brep']);s=g.read(source)
    for hist in doc['trials']:
        if not hist['name'].startswith('full-front-chain-'):continue
        targets=[g.edge_record(s,TopoDS.Edge_s(g.shapes(s,TopAbs_EDGE)[i-1])) for i in hist['selected_edges']]
        r=hist['radius'];new(20,'native-'+hist['name'],path,source,targets,r,history=hist)
    path=w/'outputs/manual-review/diagnostics/case21-unders/summary.json';doc=read(path);source=Path(doc['input_brep'])
    for hist in doc['native_controls']:new(21,hist['id'],path,source,doc['selection']['root_edges'],hist['radius'],history=hist)
    # Current case24 oblique model, including the two native operation orders.
    path=w/'outputs/manual-review/diagnostics/case24-oblique/native-summary.json';doc=read(path);source=w/'outputs/parasolid-preblend/models'/f"{frozen_cases[24]['id']}.brep"
    for variant in frozen_cases[24]['variants']:
        hist=next(r for r in doc['rows'] if r['id']==variant['id']);trial=read(hist['trial_json']);roots=trial['original_roots'];targets=[]
        for key in ['convex','concave']:
            t=roots[key];points=[t['start'],t['end']];planes=[s['values'] for s in t['supports']]
            targets.append({'polyline':points,'length':g.distance(*points),'required_support_adjacency_count':2,'root_key':key,'support_planes':planes})
        job=new(24,variant['id'],path,source,targets,variant['radius_mm'],history={k:hist.get(k) for k in ['id','status','quality_status','failure_reasons','all_formats_passed']})
        if 'then' in variant['id']:
            first=0 if variant['id'].startswith('convex') else 1;job['steps']=[{'target_indices':[first]},{'target_indices':[1-first]}]
    path=w/'outputs/manual-review/diagnostics/case25-unders/native-summary.json';doc=read(path);source=Path(doc['input_brep'])
    for hist in doc['trials']:
        targets=[doc['input_edge_map'][i-1] for i in hist['target_edge_indices']]
        new(25,'native-r'+token(hist['radius']),path,source,targets,hist['radius'],history=hist)
    # Current rebuilt case31 part extraction is checked against actual A input.
    path=w/'outputs/manual-review/diagnostics/case31-aligned-v2/native-summary.json';doc=read(path);source=w/'outputs/parasolid-preblend/models'/f"{frozen_cases[31]['id']}.brep"
    for hist in doc['trials']:
        r=hist['radius'];vid='body-r'+token(r);job=new(31,vid,path,source,doc['input_front_chain']['selected_edges'],r,operation=Path(doc['input_brep']),history={k:hist.get(k) for k in ['id','radius','status','native_operation_succeeded','all_formats_passed']},aliases=[vid,vid+'-clean'])
        job['part_label']=mc[frozen_cases[31]['id']]['parts'][0]['label']
    # Case33 keeps physical near/far radius assignment, not a constant substitute.
    path=w/'outputs/manual-review/diagnostics/case33-variable/native-fitted-summary.json';doc=read(path);source=w/'outputs/parasolid-preblend/models'/f"{frozen_cases[33]['id']}.brep";target=doc['selected_edge'];params={'radius_mode':'two_end_variable','physical_start_mm':target['start'],'physical_end_mm':target['end'],'start_radius_mm':doc['radius_assignment']['start_radius'],'end_radius_mm':doc['radius_assignment']['end_radius'],'original_api':'Part.Shape.makeFillet(R_start,R_end,[common_edge])'}
    labels=[p['label'] for p in mc[frozen_cases[33]['id']]['parts']]
    new(33,'native-symmetric-control',path,source,[target],parameters=params,preprocess={'type':'sew_parts','source_labels':labels},operation=Path(doc['operation_input_brep']),history={k:doc.get(k) for k in ['method','radii','radius_assignment','native_operation_succeeded','all_three_formats_passed','interpretation_boundary']})
    path=w/'outputs/manual-review/diagnostics/case34-rho/native-summary.json';doc=read(path);source=Path(doc['input_brep']);params={'radius_mode':'two_end_variable','physical_start_mm':doc['contour_first'],'physical_end_mm':doc['contour_last'],'start_radius_mm':doc['radius_first'],'end_radius_mm':doc['radius_last'],'original_api':doc['native_call']}
    new(34,'native-circle-control',path,source,[doc['selected_edge']],parameters=params,operation=source,history={k:doc.get(k) for k in ['method_kind','native_call','native_operation_succeeded','all_three_formats_passed','native_rho_parameter_used']})
    path=w/'outputs/manual-review/diagnostics/case35-g2/native-summary.json';doc=read(path);source=Path(doc['source_brep']);labels=[p['label'] for p in mc[frozen_cases[35]['id']]['parts']]
    for hist in doc['trials']:
        params={'radius_mode':'constant','radius_mm':doc['radius_mm']}
        if hist['id'].startswith('internal-c2'):params.update(internal_continuity='C2',angular_tolerance_radians=1e-4)
        new(35,hist['id'],path,source,[doc['selected_edge']],parameters=params,preprocess={'type':'sew_parts','source_labels':labels},operation=Path(doc['operation_input_brep']),history={k:hist.get(k) for k in ['id','native_call','native_operation_succeeded','all_three_formats_G0_G1_passed','requested_support_G2_passed']})
    # A frozen request hash binds source, operation input, full target and params.
    assert len({j['job_id'] for j in jobs})==len(jobs)
    output={'schema_version':1,'suite':'original_occ_native','source_review_state_sha256':sha(w/'outputs/manual-review/review-state.json'),
      'source_manifest_sha256':sha(w/'outputs/parasolid-preblend/manifest.json'),'jobs':jobs,
      'missing_fixtures':missing,'case_count':len({j['case_number'] for j in jobs})}
    target=Path(__file__).with_name('requests.json');target.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'requests':len(jobs),'cases':output['case_count'],'missing_fixtures':missing},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
