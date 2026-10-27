from pathlib import Path
from datetime import datetime
import json,sys,ctypes as C,hashlib,traceback,shutil
W=Path(__file__).resolve().parent;sys.path.insert(0,str(W));import cap_adapter as adapter
cid,kind,run_path=sys.argv[1:4];RUN=Path(run_path);RUN.mkdir(parents=True,exist_ok=True);dx=98. if kind=='sheet' else 0.
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
write=lambda p,d:Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def box(size,origin):return dict(kind='box',size=size,origin=origin)
def boolean(op,a,b):return dict(kind='boolean',operation=op,a=a,b=b)
shape=boolean('difference',boolean('union',box([70,38,12],[dx,0,0]),box([70,9,29],[dx,29,12])),box([9,11,28],[dx+29,28,15]))
def cap_x(y,z):
 if kind=='body':return 29.
 if kind=='plane':return .35*y+1.5*z-14.95
 profile=[(24,-3),(24,8),(27,15),(27,24),(24,31),(24,43)]
 for (x0,y0),(x1,y1) in zip(profile,profile[1:]):
  if y0<=y<=y1:return dx+x0+(x1-x0)*(y-y0)/(y1-y0)
 raise ValueError('outside sheet')
probes=[]
for z in [12.5,13.,14.]:
 for y in [27.,28.,28.5]:
  for x in [5.,10.,15.,20.,25.,28.,30.,35.,45.,60.,65.]:
   probes.append(dict(point=[dx+x,y,z],local_x=x,cap_x=cap_x(y,z),original_inside=False,label='added-material stop test'))
case=dict(id=f'case{cid}-{kind}-ordinary-r8',operation='fillet',a=shape,fillet=dict(radius=8.,selector='root'),probes=probes,model_tolerance=1e-7,measurement_accuracy=1e-9,point_tolerance=1e-7,mesh_path=str(RUN/'ordinary-r8-mesh.json'))
record=dict(case_number=int(cid),kind=kind,started_at=datetime.now().astimezone().isoformat(),run_dir=str(RUN),recipe=shape,case=case,native_cap_operand_supplied=False,native_cap_status='adapter_not_ready',native_cap_claim='The inspected SmApiFilletEdges bridge has no supplied plane/sheet cap parameter; this trial is ordinary circular edge fillet only. No claim SMLib core does not support caps.',cap_definition=dict(kind=kind,plane_equation='x=.35y+1.5z-14.95' if kind=='plane' else 'x=29' if kind=='body' else 'five-face piecewise x(y), offset_x=98',retained_side='x<=cap_x(y,z)'),expected_input_volume=70*38*12+70*9*29-9*9*26,original_reference_source_unchanged=True)
write(RUN/'started.json',record);write(RUN/'case.json',case)
try:
 fn=adapter._lib.smlib_caps_aux;fn.argtypes=[C.c_char_p,C.c_int,C.c_double,C.c_char_p,C.c_int];fn.restype=C.c_int;err=C.create_string_buffer(8000)
 aux_code=fn(str(RUN/'specified-cap').encode(),{'body':0,'plane':1,'sheet':2}[kind],dx,err,len(err));record['native_auxiliary_reconstruction']=dict(return_code=aux_code,error=err.value.decode(),used_as_fillet_constraint=False)
 print('AUX',cid,kind,aux_code,err.value.decode(),flush=True)
 record['result']=adapter.run_case(case);record['ordinary_trial_status']='returned_result'
 states=record['result']['point_states'];measure=[]
 for p,state in zip(probes,states):measure.append(dict(**p,state=state,outside_cap=p['point'][0]>p['cap_x']+1e-6,inside_requested_side=p['point'][0]<p['cap_x']-1e-6))
 violation=[p for p in measure if p['outside_cap'] and p['state']=='inside'];inside=[p for p in measure if p['inside_requested_side'] and p['state']=='inside'];record['cap_boundary_probe']=dict(native_cap_constraint_executed=False,ordinary_baseline_satisfies_sampled_stop=not bool(violation),outside_cap_added_material_points=len(violation),inside_kept_side_added_material_points=len(inside),samples=measure,method='SmBrep.Point3DClassify on native result; all probe coordinates outside sharp input; only tests supplied points, not whole-surface equality')
 record['input_analytic_volume_error']=abs(record['result']['before_volume']-record['expected_input_volume'])
 print('RESULT',cid,kind,record['result']['native_valid'],len(violation),flush=True)
except Exception as ex:
 record['ordinary_trial_status']='failed';record['error']=str(ex);record['error_type']=type(ex).__name__;record['traceback']=traceback.format_exc();record['details']=getattr(ex,'details',None);record['operation_stage']=getattr(ex,'operation_stage',None);print('FAILED',cid,kind,str(ex),flush=True)
record['finished_at']=datetime.now().astimezone().isoformat();record['native_cap_status']='adapter_not_ready'
record['source_hashes']={p.name:sha(p) for p in [Path(__file__),W/'cap_adapter.py',W/'cap_bridge.cpp']}
write(RUN/'result.json',record)
