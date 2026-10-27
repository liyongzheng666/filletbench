"""Geometry-target preparation and conservative native evidence summaries."""
from pathlib import Path
import hashlib
import json
import math

sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
J = lambda p: json.loads(Path(p).read_text())
def write(p, d):
    Path(p).write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")

def norm(a):return math.sqrt(sum(v*v for v in a))
def sub(a,b):return [x-y for x,y in zip(a,b)]
def add(a,b):return [x+y for x,y in zip(a,b)]
def mul(a,s):return [x*s for x in a]
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def unit(a):return mul(a,1/norm(a))
def infer_target(t,index):
 points=t.get('samples') or t.get('samples_mm') or t.get('sample_points_world_mm') or t.get('endpoints') or t.get('endpoints_world_mm')
 if not points and t.get('center') is not None and (t.get('radius') or t.get('radius_mm')):
  center=t['center'];n=unit(t.get('normal',[0,0,1]));axis=unit(cross(n,[1,0,0] if abs(n[0])<.8 else [0,1,0]));other=cross(n,axis);r=t.get('radius',t.get('radius_mm'));points=[add(center,add(mul(axis,r*math.cos(2*math.pi*i/64)),mul(other,r*math.sin(2*math.pi*i/64)))) for i in range(65)]
 if not points or len(points)<2:raise ValueError(f'target {index}: no source samples/endpoints/circle')
 points=[[float(x) for x in p] for p in points]
 if any(len(p)!=3 or not all(math.isfinite(x) for x in p) for p in points):raise ValueError(f'target {index}: samples must be finite 3D points')
 tol=float(t.get('selector_tolerance_mm',1e-6));coverage=float(t.get('coverage_tolerance_mm',1e-5))
 if not all(math.isfinite(x) and x>0 for x in (tol,coverage)):raise ValueError(f'target {index}: selector and coverage tolerances must be finite and positive')
 center=[0,0,0];normal=[0,0,1];radius=0.;span=0.;length=-1.;kind='polyline'
 delta=sub(points[-1],points[0]);d=norm(delta)
 if d>tol and max(norm(cross(sub(p,points[0]),delta))/d for p in points)<=tol:
  kind='line';length=d
 elif len(points)>=3:
  a=points[0];b=max(points,key=lambda p:norm(sub(p,a)));u=sub(b,a);c=max(points,key=lambda p:norm(cross(u,sub(p,a))));v=sub(c,a);w=cross(u,v);w2=dot(w,w)
  if w2>1e-20:
   fitted=add(a,mul(add(mul(cross(v,w),dot(u,u)),mul(cross(w,u),dot(v,v))),1/(2*w2)));rr=norm(sub(a,fitted));nn=unit(w)
   error=max(max(abs(norm(sub(p,fitted))-rr),abs(dot(sub(p,fitted),nn))) for p in points)
   if error<=tol:
    kind='circle';center=fitted;radius=rr;normal=nn
    def swept(n):return sum(math.atan2(dot(cross(sub(p,center),sub(q,center)),n),dot(sub(p,center),sub(q,center))) for p,q in zip(points,points[1:]))
    span=swept(normal)
    if span<0:normal=mul(normal,-1);span=-span
    if norm(sub(points[-1],points[0]))<=tol:span=2*math.pi
    length=radius*span
 if kind=='polyline' and 'coverage_tolerance_mm' not in t:raise ValueError(f'target {index}: nonanalytic sample curve requires explicit coverage_tolerance_mm/chord bound, not an exact identity claim')
 if t.get('expected_length_mm') is not None and not t.get('length_is_approximation',False):
  length=float(t['expected_length_mm'])
  if not math.isfinite(length) or length<=0:raise ValueError(f'target {index}: exact expected length must be finite and positive')
 return dict(id=str(t.get('id',t.get('target_id',f'target-{index}'))),kind=kind,samples=points,selector_tolerance_mm=tol,coverage_tolerance_mm=coverage,expected_count=int(t.get('expected_count',1)),expected_length_mm=length,center=center,normal=normal,radius=radius,span=span,reference_identity='bounded fitted analytic curve' if kind!='polyline' else 'declared sampled polyline coverage; exact arbitrary curve identity unverified')

def tokens(job,run,targets):
 q=lambda x:json.dumps(str(x),ensure_ascii=False)
 lines=[f'RUN_DIR {q(run)}',f'INPUT {q(Path(job["input_smb"]).resolve())}',f'KIND {job.get("expected_input_kind","any")}',f'RADIUS {float(job.get("radius_mm",0)):.17g}']
 start=job.get('variable_start_mm',job.get('variable_start'));end=job.get('variable_end_mm',job.get('variable_end'));variable=start is not None and end is not None
 lines += [f'VARIABLE {int(variable)} {float(start or 0):.17g} {float(end or 0):.17g}',f'PARAMS {int(job.get("xsect_type",1))} {int(job.get("continuity",1))} {float(job.get("thumbweight",1)):.17g}',f'TARGETS {len(targets)}']
 for t in targets:
  vals=[t['expected_count'],t['selector_tolerance_mm'],t['coverage_tolerance_mm'],t['expected_length_mm'],*t['center'],*t['normal'],t['radius'],t['span'],len(t['samples'])]
  lines.append('TARGET '+q(t['id'])+' '+t['kind']+' '+' '.join(format(x,'.17g') for x in vals))
  lines.extend(' '.join(format(x,'.17g') for x in p) for p in t['samples'])
 ps=job.get('protected_probes',[]);lines.append(f'PROTECTED {len(ps)}')
 for k,p in enumerate(ps):
  if isinstance(p,list):p=dict(id=f'protected-{k}',point=p)
  lines.append(q(p.get('id',f'protected-{k}'))+' '+' '.join(format(float(x),'.17g') for x in p['point']))
 return '\n'.join(lines)+'\n'

def summarize(run,job,process):
 execution=J(run/'execution.json') if (run/'execution.json').exists() else {};before=J(run/'before.json') if (run/'before.json').exists() else None;result=J(run/'result.json') if (run/'result.json').exists() else None;readback=J(run/'readback.json') if (run/'readback.json').exists() else None
 gates={};gates['input_kind']=execution.get('input_kind_gate',dict(passed=False,reason='input not inspected'));gates['result_kind']=execution.get('result_kind_gate',dict(passed=False,reason='no result inspected'));gates['whole_body']=execution.get('preservation_gate',dict(whole_body_type_passed=False));gates['native_api']=dict(passed=execution.get('native_api_success',False),raw_status=execution.get('native_api_raw_status'))
 if before and result and job.get('protected_probes'):
  bs={p['id']:p for p in before['protected_probes']};rs={p['id']:p for p in result['protected_probes']};checks=[]
  for k,p in enumerate(job['protected_probes']):
   ident=p.get('id',f'protected-{k}') if isinstance(p,dict) else f'protected-{k}';a,b=bs.get(ident),rs.get(ident);checks.append(dict(id=ident,passed=bool(a and b and a['state']!='unknown' and a['state']==b['state']),before=a,after=b))
  gates['non_target_geometry']=dict(status='passed' if all(c['passed'] for c in checks) else 'failed',checks=checks,coverage='only caller-declared protected probes, not entire original faces')
 else:gates['non_target_geometry']=dict(status='unverified',reason='No caller-declared protected-region probes; component/material count alone does not prove source non-target preservation')
 if result and readback:
  a,b=result['native_stats'],readback['native_stats'];checks={k:a.get(k)==b.get(k) for k in ['faces','edges','vertices','material_regions','components']};checks['valid']=bool(b.get('valid'));checks['type']=b.get('manifold_solid')==a.get('manifold_solid')
  for key in ['area','volume']:
   x,y=a.get(key),b.get(key);checks[key]=x is not None and y is not None and abs(x-y)<=max(1e-6,abs(x)*1e-7)
  checks['bbox']=len(a.get('bbox',[]))==6 and len(b.get('bbox',[]))==6 and all(abs(x-y)<=1e-6 for x,y in zip(a['bbox'],b['bbox']))
  gates['native_readback']=dict(passed=all(checks.values()),checks=checks)
 else:gates['native_readback']=dict(passed=False,reason='No native readback evidence')
 source=job.get('source_stats') or job.get('expected_source_stats') or job.get('admission',{}).get('source_stats');checks={}
 if source and before:
  a=before['native_stats']
  for key in ['area','volume']:
   if source.get(key) is not None and a.get(key) is not None:checks[key]=abs(source[key]-a[key])<=max(1e-5,abs(source[key])*1e-7)
  if source.get('bbox') is not None:checks['bbox']=len(a.get('bbox',[]))==6 and all(abs(x-y)<=1e-5 for x,y in zip(source['bbox'],a['bbox']))
  if source.get('solids') is not None:checks['material_regions']=source['solids']==a.get('material_regions')
  if source.get('faces') is not None:checks['finite_face_count']=source['faces']==a.get('faces')
  gates['input_source_equivalence']=dict(status='passed_basic_metrics_only' if checks and all(checks.values()) else 'failed',checks=checks,not_certified='exact finite trimming/partition equivalence needs independent input oracle')
 else:gates['input_source_equivalence']=dict(status='unverified',reason='source SHA lineage is not a geometry-equivalence oracle; no source metrics supplied')
 gates['G0_G1_G2']=dict(status='unverified',reason='Raw real junction samples emitted; only independently mapped new fillet/support edges may require G1/G2. Existing sharp joins are not automatic failures.')
 phase=J(run/'phase.json').get('stage') if (run/'phase.json').exists() else 'preflight';rc=process.get('return_code');signal=-rc if isinstance(rc,int) and rc<0 else None;selection=J(run/'selection.json') if (run/'selection.json').exists() else None
 if process.get('timeout'):outcome='timeout'
 elif signal:outcome='native_phase_crash' if execution.get('native_call_started') else 'process_crash'
 elif result:outcome='native_candidate' if execution.get('native_api_success') else 'native_api_failed_candidate'
 elif selection is not None and not selection.get('passed'):outcome='selection_failed'
 elif execution.get('native_call_started'):outcome='native_call_or_inspection_failed'
 else:outcome='input_or_process_failed'
 r=dict(schema_version=1,job_id=job.get('job_id'),number=job.get('number'),part_label=job.get('part_label'),radius_mm=job.get('radius_mm'),engine='SMLib',engine_version=execution.get('engine_version', 'unverified'),source_sha256=job.get('source_sha256',job.get('source_sha')),role=job.get('role'),run_dir=str(run),outcome=outcome,raw_phase=phase,process_signal=signal,selection_passed=selection.get('passed') if selection else None,process=process,execution=execution,gates=gates,source_special_feature_passed=False,full_quality_passed=False,full_quality_reason='Target source feature and finite protected regions require independent contract oracles, not native validity alone.',artifacts={p.name:dict(path=str(p),sha256=sha(p)) for p in run.iterdir() if p.is_file() and p.name not in ['summary.json']})
 write(run/'summary.json',r);return r
