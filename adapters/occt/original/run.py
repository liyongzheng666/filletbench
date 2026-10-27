#!/usr/bin/env python3
"""Replay original manual-review native requests using pinned OCP, without FreeCAD.

Run with a Python environment containing adapters/occt/requirements.txt. No SDK,
local application, private filesystem path or historical result is executed.
"""
from __future__ import annotations
import argparse,hashlib,json,math,os,platform,signal,subprocess,sys,time
from datetime import datetime,timezone
from importlib.metadata import version
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
PIN='7.9.3.1.1'
BOUNDARY='Native original-series control only. API completion, native validity and STEP roundtrip are separate gates. No source special-mode, continuity, whole-shape or human appearance acceptance is inferred.'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,d):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n');tmp.replace(p)
def now():return datetime.now(timezone.utc).isoformat()
def repo_file(value):
    p=Path(value)
    if p.is_absolute() or '..' in p.parts:raise ValueError('Only repository relative paths are allowed')
    return ROOT/p

def initial(job):
    return {'schema_version':1,'job_id':job['job_id'],'case_number':job['case_number'],'case_id':job['case_id'],
      'track':job['track'],'source_revision':job.get('source_revision','current_original'),
      'original_case_number':job['case_number'],'original_variant_id':job['original_variant_id'],'operation_label':job.get('part_label') or job['original_variant_id'],
      'original_variant_ids':job.get('original_variant_ids',[]),'part_label':job.get('part_label'),
      'engine':'OCCT','engine_version':'7.9.3','adapter':'adapters/occt/original/run.py','adapter_sha256':sha(__file__),
      'geometry_helper_sha256':sha(Path(__file__).with_name('geometry.py')),'request_sha256':hashlib.sha256(json.dumps(job,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
      'source_brep':job['source_brep'],'source_sha256':job['source_sha256'],
      'historical_source_sha256':job.get('historical_source_sha256'),
      'historical_operation_input_sha256':job.get('operation_input_sha256'),
      'historical':job.get('historical',{}),'parameters':job['parameters'],
      'scope_note':job.get('scope_note'), 'started_at':now(),'outcome':'initializing','reason':None,
      'api_success':False,'native_call_executed':False,'valid':None,'artifacts':{},'metrics':{},
      'special_feature_certified':False,'human_appearance_acceptance':'pending','G0_G1_G2_validation':'not_performed_in_this_runner',
      'validation_boundary':BOUNDARY,'environment':{'python':platform.python_version(),'platform':platform.system(),'machine':platform.machine()}}

def worker(job,out):
    summary=initial(job);start=time.monotonic()
    def checkpoint(stage):summary.update(stage=stage,duration_seconds=time.monotonic()-start);write(out/'summary.json',summary)
    checkpoint('preflight')
    try:
        import OCP,geometry as g
        from OCP.BRep import BRep_Tool
        from OCP.BRepTools import BRepTools
        from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
        from OCP.ChFi3d import ChFi3d_Rational
        from OCP.GeomAbs import GeomAbs_C2
        from OCP.STEPControl import STEPControl_Writer,STEPControl_Reader,STEPControl_AsIs,STEPControl_Controller
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.Interface import Interface_Static
        summary.update(binding_version=version('cadquery-ocp'),ocp_version=OCP.__version__)
        if summary['binding_version']!=PIN:raise ValueError('Pinned cadquery-ocp '+PIN+' required')
        source=repo_file(job['source_brep'])
        if sha(source)!=job['source_sha256']:raise ValueError('Frozen source SHA mismatch')
        base=g.read(source);summary['source_stats']=g.stats(base)
        frozen=None
        if job.get('operation_input_brep'):
            fp=repo_file(job['operation_input_brep'])
            if sha(fp)!=job['operation_input_sha256']:raise ValueError('Frozen operation input SHA mismatch')
            frozen=g.read(fp)
        mode=job.get('execution_mode','from_base')
        summary['preprocess']={'requested_recipe':job.get('preprocess',{'type':'none'}),'execution_mode':mode,'recipe_gap':None,
            'source_revision_matches_historical':job.get('historical_source_sha256',job['source_sha256'])==job['source_sha256']}
        if mode=='frozen_prepared_input_replay':
            if frozen is None:raise ValueError('Prepared replay requires frozen operation BREP')
            before=frozen;summary['preprocess']['recipe_gap']=job.get('recipe_gap','Portable base preprocessing unavailable')
        else:
            try:
                before=g.preprocess(base,job)
                if frozen is not None:
                    comparison=g.equivalent(before,frozen);summary['preprocess']['regenerated_vs_frozen']=comparison
                    if not comparison['passed']:raise ValueError('Regenerated operation input differs from original frozen input')
                summary['preprocess']['execution_mode']='from_base'
            except Exception as exc:
                if frozen is None:raise
                before=frozen;summary['preprocess'].update(execution_mode='frozen_prepared_input_replay',recipe_gap=type(exc).__name__+': '+str(exc))
        summary['input_stats']=g.stats(before)
        def save_shape(s,name,selected=()):
            path=out/(name+'.brep')
            if not BRepTools.Write_s(s,str(path)):raise ValueError('BREP write failed')
            summary['artifacts'][name+'_brep']=path.name
            write(out/(name+'.mesh.json'),g.mesh(s,selected));summary['artifacts'][name+'_mesh']=name+'.mesh.json'
            return {'sha256':sha(path),'inspection':g.inspect(g.read(path))}
        summary['operation_input_sha256']=None
        selected,selection=g.select(before,job['targets']);summary['selection']=selection
        summary['before_brep_readback']=save_shape(before,'before',selected)
        summary['operation_input_sha256']=sha(out/'before.brep')
        if len(selected)!=len(job['targets']):
            summary.update(outcome='selection_rejected',reason='Original physical target did not resolve uniquely; no index fallback');checkpoint('selection_rejected');return
        if not summary['input_stats']['valid']:
            summary.update(outcome='input_rejected',reason='Operation input BRepCheck invalid');checkpoint('input_rejected');return
        params=job['parameters'];summary['effective_parameters']={'fillet_shape':'ChFi3d_Rational','continuity':'default_internal_C1',**params}
        steps=job.get('steps') or [{'target_indices':list(range(len(selected)))}]
        summary['steps']=[];current=before;last_builder=None;retained_result=None
        for si,step in enumerate(steps):
            if si==0:edges=[selected[i] for i in step['target_indices']];selection_rows=[selection[i] for i in step['target_indices']]
            else:
                edges,selection_rows=g.select(current,[job['targets'][i] for i in step['target_indices']],allow_trimmed=True)
                if len(edges)!=len(step['target_indices']):
                    summary.update(outcome='selection_rejected',reason='Second native target is not one remaining original sharp line on both supports');checkpoint('selection_rejected');return
            row={'step_index':si,'selection':selection_rows,'parameters':params,'api_success':False};summary['steps'].append(row)
            builder=BRepFilletAPI_MakeFillet(current,ChFi3d_Rational);last_builder=builder
            if params.get('internal_continuity')=='C2':builder.SetContinuity(GeomAbs_C2,float(params['angular_tolerance_radians']));summary['effective_parameters']['continuity']='requested_internal_C2'
            if params.get('radius_mode')=='two_end_variable':
                if len(edges)!=1:raise ValueError('Two end control needs exactly one edge')
                p0,p1=params['physical_start_mm'],params['physical_end_mm'];r0,r1=params['start_radius_mm'],params['end_radius_mm']
                if not all(math.isfinite(r) and r>0 for r in [r0,r1]):raise ValueError('Invalid radii')
                builder.Add(edges[0]);ci=builder.Contour(edges[0])
                if builder.NbContours()!=1 or builder.NbEdges(ci)!=1:raise ValueError('Variable contour extends beyond original single finite edge')
                a,b=g.xyz(BRep_Tool.Pnt_s(builder.FirstVertex(ci))),g.xyz(BRep_Tool.Pnt_s(builder.LastVertex(ci)))
                fw=max(g.distance(a,p0),g.distance(b,p1))<1e-5;rv=max(g.distance(a,p1),g.distance(b,p0))<1e-5
                if fw==rv:raise ValueError('Physical end radius binding is ambiguous')
                ra,rb=(r0,r1) if fw else (r1,r0);builder.SetRadius(ra,rb,ci,1)
                row['radius_binding']={'contour_first_mm':a,'contour_last_mm':b,'contour_first_radius_mm':ra,'contour_last_radius_mm':rb,'physical_start_mm':p0,'physical_end_mm':p1,'verified':True}
                row['api']='BRepFilletAPI_MakeFillet.Add(edge); SetRadius(R_first,R_last,contour,1); Build()'
            else:
                radius=float(params['radius_mm'])
                if not math.isfinite(radius) or radius<=0:raise ValueError('Invalid radius')
                for edge in edges:builder.Add(radius,edge)
                row['api']='BRepFilletAPI_MakeFillet.Add(radius,edge); Build()'
            row['contours']=[{'index':i,'edge_count':builder.NbEdges(i),'length_mm':builder.Length(i)} for i in range(1,builder.NbContours()+1)]
            summary['native_call_executed']=True;checkpoint('native_build_'+str(si))
            t=time.monotonic();builder.Build();row.update(api_success=bool(builder.IsDone()),build_seconds=time.monotonic()-t,
                faulty_contours=builder.NbFaultyContours(),faulty_vertices=builder.NbFaultyVertices())
            if not builder.IsDone():
                row['contour_statuses']=[str(builder.StripeStatus(i)).split('.')[-1] for i in range(1,builder.NbContours()+1)]
                if builder.HasResult():
                    candidate=builder.BadShape()
                    if not candidate.IsNull():summary['partial_result_brep_readback']=save_shape(candidate,'partial-result');summary['candidate_retained']=True
                summary.update(outcome='native_rejected',reason='Native Build did not complete',api_success=False);checkpoint('native_rejected');return
            current=builder.Shape();retained_result=current;row['native']=g.inspect(current)
            if si<len(steps)-1:row['intermediate_brep_readback']=save_shape(current,'step'+str(si+1))
        summary['api_success']=True;checkpoint('native_validation')
        summary['native']=g.inspect(current);summary['result_stats']=summary['native']['stats'];summary['valid']=summary['result_stats']['valid']
        summary['candidate_retained']=True;summary['result_brep_readback']=save_shape(current,'result')
        summary['result_geometry_changes']={
          'area_changed':abs(summary['input_stats']['area_mm2']-summary['result_stats']['area_mm2'])>1e-7,
          'solid_count_preserved':summary['input_stats']['solids']==summary['result_stats']['solids']}
        checkpoint('step_export')
        settings={'write.surfacecurve.mode':1,'write.precision.mode':0,'read.surfacecurve.mode':0}
        STEPControl_Controller.Init_s()
        applied={key:bool(Interface_Static.SetIVal_s(key,value)) for key,value in settings.items()}
        effective={key:Interface_Static.IVal_s(key) for key in settings}
        summary['step_settings']={'controller_initialized':True,'requested':settings,'set_succeeded':applied,'effective':effective}
        if not all(applied.values()) or effective!=settings:raise ValueError('STEP settings not applied after controller initialization')
        step_record={'passed':False};summary['step_roundtrip']=step_record
        try:
            writer=STEPControl_Writer();transfer=writer.Transfer(current,STEPControl_AsIs)
            step_record['transfer_status']=str(transfer).split('.')[-1]
            if transfer!=IFSelect_RetDone:raise ValueError('STEP transfer failed')
            status=writer.Write(str(out/'result.step'));step_record['write_status']=str(status).split('.')[-1]
            if status!=IFSelect_RetDone:raise ValueError('STEP writer failed')
            summary['artifacts']['result_step']='result.step';step_record['sha256']=sha(out/'result.step')
            reader=STEPControl_Reader();status=reader.ReadFile(str(out/'result.step'));step_record['read_status']=str(status).split('.')[-1]
            if status!=IFSelect_RetDone or not reader.TransferRoots():raise ValueError('STEP reader failed')
            restored=reader.OneShape();step_record['inspection']=g.inspect(restored);step_record['geometry_comparison']=g.equivalent(current,restored)
            # STEP is allowed to split edge/vertex topology. Original mass, faces,
            # solids and bbox checks are still retained as separate observations.
            ref,back=summary['result_stats'],step_record['inspection']['stats']
            checks={k:abs(ref[k]-back[k])<=max(1e-5,abs(ref[k])*1e-7) for k in ['area_mm2','volume_mm3']}
            checks.update(faces=ref['faces']==back['faces'],solids=ref['solids']==back['solids'],bbox_mm=all(abs(a-b)<1e-5 for a,b in zip(ref['bbox_mm'],back['bbox_mm'])))
            step_record['mass_topology_checks']=checks;step_record['passed']=step_record['inspection']['passed'] and all(checks.values())
        except Exception as exc:step_record['error']=type(exc).__name__+': '+str(exc)
        if not summary['native']['passed']:summary.update(outcome='native_quality_failed',reason='Native candidate failed BRep/BOP checks')
        elif not all(summary['result_geometry_changes'].values()):summary.update(outcome='geometry_failed',reason='Original area change / solid preservation gate failed')
        elif not step_record['passed']:summary.update(outcome='step_roundtrip_failed',reason='Native candidate retained; STEP readback gate failed')
        else:summary.update(outcome='native_and_step_passed',reason=None)
        checkpoint('complete')
    except Exception as exc:
        summary.update(outcome='dependency_error' if isinstance(exc,ImportError) else 'exception',reason=type(exc).__name__+': '+str(exc).replace(str(ROOT),'<repo>'))
        checkpoint('exception')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--requests',type=Path,default=Path(__file__).with_name('requests.json'));p.add_argument('--job');p.add_argument('--case',type=int);p.add_argument('--output',type=Path,default=ROOT/'runs/original-occ-native');p.add_argument('--timeout',type=float,default=120);p.add_argument('--worker',action='store_true');a=p.parse_args()
    doc=json.loads(a.requests.read_text());jobs=[j for j in doc['jobs'] if (not a.job or j['job_id']==a.job) and (not a.case or j['case_number']==a.case)]
    if not jobs:p.error('No matching frozen original requests')
    if a.worker:
        if len(jobs)!=1:p.error('worker requires one job')
        a.output.mkdir(parents=True,exist_ok=True);worker(jobs[0],a.output);return
    if not math.isfinite(a.timeout) or a.timeout<=0:p.error('Positive finite timeout required')
    for job in jobs:
        out=a.output/job['job_id'];out.mkdir(parents=True,exist_ok=True)
        for name in ['before.brep','before.mesh.json','result.brep','result.mesh.json','result.step','partial-result.brep','partial-result.mesh.json','step1.brep','step1.mesh.json']:(out/name).unlink(missing_ok=True)
        write(out/'summary.json',initial(job));t=time.monotonic();timed_out=False
        cmd=[sys.executable,str(Path(__file__).resolve()),'--requests',str(a.requests.resolve()),'--job',job['job_id'],'--output',str(out.resolve()),'--worker']
        with (out/'stdout.log').open('w') as stdout,(out/'stderr.log').open('w') as stderr:
            child=subprocess.Popen(cmd,stdout=stdout,stderr=stderr,start_new_session=os.name=='posix',cwd=ROOT)
            try:child.wait(timeout=a.timeout)
            except subprocess.TimeoutExpired:
                timed_out=True
                if os.name=='posix':os.killpg(child.pid,signal.SIGKILL)
                else:child.kill()
                child.wait()
        result=json.loads((out/'summary.json').read_text());result['process']={'returncode':child.returncode,'timed_out':timed_out,'timeout_seconds':a.timeout,'wall_seconds':time.monotonic()-t}
        if timed_out:result.update(outcome='timeout',reason='Worker exceeded timeout')
        elif child.returncode:result.update(outcome='crash',reason='Worker process returned '+str(child.returncode))
        result['finished_at']=now();write(out/'summary.json',result)
        print(json.dumps({'job_id':job['job_id'],'outcome':result['outcome'],'api_success':result['api_success'],'mode':result.get('preprocess',{}).get('execution_mode'),'reason':result.get('reason')},ensure_ascii=False),flush=True)
    entries=[]
    for job in doc['jobs']:
        f=a.output/job['job_id']/'summary.json'
        if not f.is_file():continue
        d=json.loads(f.read_text());entries.append({'case_number':job['case_number'],'number':job['case_number'],'variant_id':job['original_variant_id'],'original_case_number':job['case_number'],'original_variant_id':job['original_variant_id'],'operation_label':job.get('part_label') or job['original_variant_id'],'run_dir':str(f.parent.relative_to(ROOT)) if f.is_relative_to(ROOT) else f.parent.name,'job_id':job['job_id'],'track':job['track'],'original_variant_ids':job.get('original_variant_ids',[]),'source_revision':job.get('source_revision','current_original'),'summary':str(f.relative_to(ROOT)) if f.is_relative_to(ROOT) else f.name,'summary_sha256':sha(f),'outcome':d['outcome'],'api_success':d['api_success'],'native_call_executed':d['native_call_executed'],'valid':d['valid'],'execution_mode':d.get('preprocess',{}).get('execution_mode'),'parameters':d['parameters'],'artifacts':d['artifacts']})
    from collections import Counter
    write(a.output/'index.json',{'schema_version':1,'suite':'original_occ_native','updated_at':now(),'request_sha256':sha(a.requests),'scope':BOUNDARY,'counts':dict(Counter(x['outcome'] for x in entries)),'case_count':len(set(x['case_number'] for x in entries)),'entries':entries,'rows':entries})
if __name__=='__main__':main()
