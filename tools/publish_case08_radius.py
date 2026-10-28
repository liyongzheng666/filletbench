# -*- coding: utf-8 -*-
"""Add the measured radius boundary sweep without rewriting the frozen review."""
import collections,copy,json,pathlib,shutil
from build_site import ROOT,WEB,read,write,digest,sanitize,mesh
from attach_original_smlib import from_completion
BASE=WEB/'data/original-occ';PUBLIC=WEB/'data/case08-radius';CONTRACT=ROOT/'data/case08-radius/protocol.json'
def file_model(p,label,status=None):
 if not p.exists():return None
 sh=digest(p);dest=BASE/'models'/(sh+p.suffix.lower());dest.parent.mkdir(parents=True,exist_ok=True)
 if not dest.exists():shutil.copyfile(p,dest)
 return {'label':label,'path':dest.relative_to(WEB).as_posix(),'sha256':sh,'status':status}
def original_occ(row,radius):
 sp=ROOT/row['summary'];run=ROOT/row['run_dir'];s=read(sp);diag=read(run/'native-diagnostics.json');native=diag['raw']['native'];success=s['api_success'];after=mesh(run/'result.mesh.json') if (run/'result.mesh.json').exists() else None
 status='candidate_unverified' if success and after else 'api_failed';label='R12 对照 · 原生与STEP门通过' if success else f'R{radius:g} Build失败'
 reason='实际圆角尚未触及原缺口；墙面接触轨z28，原缺口上缘z27，净距1mm。' if success else f'已执行原生 R{radius:g}；Build未完成（故障轮廓{native["faultyContourCount"]}，ChFiDS_Error），无可接受的圆角结果。内核未提供更精确故障原因。'
 dest=PUBLIC/f'occ/{row["variant_id"]}';write(dest/'summary.json',sanitize(s));write(dest/'native-diagnostics.json',sanitize(diag))
 files=[file_model(run/'before.brep','实际操作输入 BREP'),file_model(run/'result.brep','实际圆角结果 BREP',status),file_model(run/'result.step','实际导出 STEP',status)]
 return {'status':status,'label':label,'reason':reason,'mesh':after,'before_mesh':mesh(run/'before.mesh.json'),'version':s['engine_version'],'method':'native_ordinary_fillet','summary':(dest/'summary.json').relative_to(WEB).as_posix(),'diagnostics':(dest/'native-diagnostics.json').relative_to(WEB).as_posix(),'evidence_kind':'fresh_run','outcome':s['outcome'],'api_success':success,'source_feature_passed':False,'source_sha256':s['source_sha256'],'operation_input_sha256':s['operation_input_sha256'],'raw_summary_sha256':digest(sp),'parameters':s['parameters'],'processing_steps':s.get('steps',[]),'metrics':{'requested_radius_mm':radius,'accepted_after_available':bool(after),'faulty_contours':native['faultyContourCount'],'faulty_vertices':native['faultyVertexCount'],'is_done':native['isDone'],'has_result':native['hasResult']},'files':[f for f in files if f],'reproduce':f'python adapters/occt/original/run.py --requests data/case08-radius/occ-requests.json --job {row["job_id"]} --output runs/replay-case08-occ-r{radius:g}'}
def build_entries(case,protocol):
 occ=read(ROOT/'runs/case08-radius/occt/index.json');sdk=read(ROOT/'runs/case08-radius/smlib/index.json');audit=read(ROOT/'docs/case08-radius-audit.json')
 if not audit['audit_consistency_passed']:raise ValueError('Radius sweep audit failed')
 orows={float(r['radius_mm']):r for r in occ['rows']};srows={float(r['radius_mm']):r for r in sdk['rows']};arows={(r['engine'],float(r['radius_nominal_mm'])):r for r in audit['rows']};template=next(v for v in case['variants'] if v['id']=='local-demo');entries=[]
 for radius,vid in zip(protocol['radii_mm'],protocol['variant_ids']):
  radius=float(radius);sr=srows[radius];orr=orows[radius];sa=arows['SMLib',radius];oa=arows['OCCT',radius];na=sa.get('native_after') or {};free=na.get('actual_opening_free_edges',[]);z=free[0]['z_mm'] if free else None;depth=free[0]['original_top_minus_actual_z_mm'] if free else None;measured=na.get('measured_radius_range_mm') or []
  if sr['source_sha256']!=case['source_sha256'] or orr['source_sha256']!=case['source_sha256']:raise ValueError('Sweep source differs')
  v=copy.deepcopy(template);v.update(id=vid,radius_mm=radius,label=f'R{radius:g} · '+('原版小半径对照（未触及缺口）' if radius==12 else '临界接触缺口' if radius==13 else f'大半径挑战（理论越过{radius-13:g}mm）'),parameters={'radius_mode':'constant','radius_mm':radius,'units':protocol['units'],'target_world_mm':protocol['target_world_mm'],'preserve_notch_option_supplied':False},method='native_ordinary_fillet',method_label='普通共边圆角 · 缺口边界试验',scope_note='相同原版片体、原共边A和默认普通圆角；未提供preserve_notch专用参数，未认证原图缺口保形模式或整体外观。',input_relation='same_as_base',operation_is_derived=False,operation_relation_note='原有限片面及11条有限边保持一致，仅组织为操作壳；源BRep与实际before已独立核对。',preparation_note='同一原版两面开壳，无实体加厚、补面或缺口修复。',extension={'kind':'requested_radius_boundary_validation','protocol':'data/case08-radius/protocol.json','protocol_sha256':digest(CONTRACT),'parent_original_variant_id':'local-demo','source_sha256':case['source_sha256']})
  oc=original_occ(orr,radius);sm=from_completion(sr,case,v);sm.update(request_file=sr['request_path'],source_template_job_id='08.part01.ordinary_control.r12',source_template_job_sha256=digest(ROOT/'data/jobs/08.part01.ordinary_control.r12.json'),representation='同源有限 NURBS / 共享拓扑',preserve_notch_option_supplied=False)
  if sa['api_success'] and radius>13:
   sm['reason']=f'实际返回4面、0实体的片体；实测R≈{measured[0]:.6g}，缺口自由边z={z:g}（原为27），实际下移{depth:g}mm。原z27缺口顶边已消失；原生回读一致。未验证preserve_notch专用模式。'
   raw=read(ROOT/sr['run_dir']/'result.json');edgeid=free[0]['edge_id'];edge=next(e for e in raw['geometry']['edges'] if e['id']==edgeid)
   sm['result_witnesses']=[{'id':'measured-notch-free-edge','samples_mm':edge['points'],'target_kind':'result_witness','label':f'实际缺口自由边 z{z:g}'},{'id':'original-notch-top-reference','samples_mm':[[35,0,27],[65,0,27]],'target_kind':'auxiliary_guide','label':'原缺口上缘位置 z27（辅助）'}]
  elif radius==13:sm['reason']='R13恰在原缺口上缘临界接触；API返回1001，保留的候选与原输入相同，不是成功圆角。'
  elif radius==12:sm['reason']='R12实际圆角距缺口仍有1mm，原缺口z27自由边保留；此对照不验证大半径遭遇缺口。'
  sm['metrics']=dict(sm.get('metrics') or {},requested_radius_mm=radius,measured_fillet_radius_mm=measured[0] if measured else None,actual_notch_free_edge_z_mm=z,original_notch_top_z_mm=27,actual_crossing_depth_mm=depth,preserve_notch_option_supplied=False)
  sm['reproduce']=f'python adapters/smlib/run.py {sr["request_path"]} --output runs/replay-case08-smlib-r{radius:g}'
  v.update(operation_mesh=oc['before_mesh'],input_mesh=oc['before_mesh'],processing_steps=oc['processing_steps'],parent_control_historical_status=template.get('historical_status'),historical_status=template.get('historical_status') if radius==12 else 'new_requested_radius_validation',human_note=case.get('human_note') if radius==12 else '基础模型与选边沿用原版；此大半径结果待人工核对。',occt=oc,smlib=sm,evidence_kind='fresh_run',radius_validation={'nominal_radius_mm':radius,'theoretical_contact_z_mm':40-radius,'theoretical_crossing_depth_mm':max(0,radius-13),'theoretical_is_actual_result':False,'occt_actual_after_available':bool(oc['mesh']),'occt_actual_radius_mm':(oa.get('native_after') or {}).get('measured_radius_range_mm',[None])[0],'smlib_measured_radius_mm':measured[0] if measured else None,'smlib_actual_notch_z_mm':z,'smlib_observed_crossing_mm':depth,'original_notch_top_z_mm':27,'preserve_notch_option_supplied':False,'source_special_modes_certified':False,'audit':'data/case08-radius/audit.json'})
  for engine,record in [('occt',oc),('smlib',sm)]:
   summary_path=WEB/record['summary'];record['published_summary_sha256']=digest(summary_path)
  entries.append(v)
 write(PUBLIC/'audit.json',sanitize(audit));write(PUBLIC/'protocol.json',protocol);return entries

def main():
 if not CONTRACT.exists():return
 casepath=BASE/'cases/08.json'
 if not casepath.exists():return
 case=read(casepath);protocol=read(CONTRACT)
 if case['source_sha256']!=protocol['base_sha256']:raise ValueError('Radius extension cannot change source')
 snapshot=PUBLIC/'published-variants.json';raw=(ROOT/'runs/case08-radius/occt/index.json').exists() and (ROOT/'runs/case08-radius/smlib/index.json').exists() and (ROOT/'docs/case08-radius-audit.json').exists()
 if raw:
  entries=build_entries(case,protocol);write(snapshot,{'schema_version':1,'original_case_file_sha256':case['source_case_sha256'],'base_sha256':case['source_sha256'],'protocol_sha256':digest(CONTRACT),'variants':entries})
 elif snapshot.exists():
  saved=read(snapshot)
  if saved['base_sha256']!=case['source_sha256'] or saved['original_case_file_sha256']!=case['source_case_sha256'] or saved['protocol_sha256']!=digest(CONTRACT):raise ValueError('Published extension lineage stale')
  entries=saved['variants']
  for v in entries:
   for r in [v['occt'],v['smlib']]:
    if digest(WEB/r['summary'])!=r['published_summary_sha256']:raise ValueError('Published sweep summary mismatch')
 else:return
 case['variants']=entries;case['original_default_variant']='local-demo';case['default_variant']='r15-crossing';case['radius_extension']={'original_views':1,'added_views':4,'protocol':'data/case08-radius/protocol.json','default_requested_radius_mm':15};case['question']='R15大半径实际越过缺口后，分别检查OCC和SMLib的构建与裁边；R12/13/14/18作边界对照。';write(casepath,case)
 catalog=read(BASE/'catalog.json');counter=collections.Counter();pairing=collections.Counter();total=0
 for row in catalog['cases']:
  c=read(WEB/row['data']);row['variant_count']=len(c['variants']);row['default_variant']=c['default_variant'];total+=len(c['variants'])
  for v in c['variants']:
   r=v['occt'];counter[r['evidence_kind']]+=1;counter['status:'+r['status']]+=1
   if v.get('smlib'):pairing[v['smlib']['pairing_status']]+=1;pairing['evidence:'+v['smlib']['evidence_kind']]+=1
 catalog['counts']={'cases':len(catalog['cases']),'models':34,'variants':total,**dict(counter)};catalog['original_review_variant_count']=129;catalog['requested_extension_variant_count']=4;catalog['smlib_pairing']['counts']=dict(pairing);write(BASE/'catalog.json',catalog);print('case08: R12/13/14/15/18 published; default R15; original frozen source unchanged')
if __name__=='__main__':main()
