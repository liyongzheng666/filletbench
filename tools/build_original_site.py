# -*- coding: utf-8 -*-
"""Publish the original reviewed inputs and fresh executions as a separate series.

No PDF/artwork is copied. Frozen base, operation input and actual result remain
separate geometries. A BREP read/retessellation is never a parametric base rebuild.
"""
import argparse,collections,hashlib,importlib.util,json,pathlib,sys,shutil
from build_site import ROOT,WEB,read,write,sanitize,digest,mesh as publish_mesh
MODULE=ROOT/'adapters/occt/special/geometry.py'
spec=importlib.util.spec_from_file_location('original_display_geometry',MODULE);G=importlib.util.module_from_spec(spec);spec.loader.exec_module(G)
SOURCE=ROOT/'data/original-occ';DEST=WEB/'data/original-occ';CACHE=ROOT/'.cache/original-view-meshes';CACHE.mkdir(parents=True,exist_ok=True)

def path(p):
 if not p:return None
 p=pathlib.Path(p);return p if p.is_absolute() else ROOT/p

def public_model(bp,label,status=None):
 bp=path(bp)
 if not bp or not bp.is_file():return None
 sh=digest(bp);target=DEST/'models'/(sh+bp.suffix.lower());target.parent.mkdir(parents=True,exist_ok=True)
 if not target.exists():shutil.copyfile(bp,target)
 if digest(target)!=sh:raise ValueError('Published model identity mismatch')
 return {'label':label,'path':target.relative_to(WEB).as_posix(),'sha256':sh,'status':status}

def compact_summary(s):
 # Files remain complete under data/original-occ/history; avoid duplicating
 # megabytes of historical topology maps in every published fresh summary.
 s=dict(s);h=s.get('historical')
 if isinstance(h,dict):s['historical']={k:v for k,v in h.items() if k!='record'}
 return sanitize(s)

def mesh_brep(bp):
 bp=path(bp)
 if not bp or not bp.is_file():return None
 sh=digest(bp);out=CACHE/(sh+'.json')
 if not out.exists():
  shape=G.read(bp);G.mesh(shape,out)
  m=read(out);m.setdefault('metadata',{})['source_brep_sha256']=sh
  m['metadata']['face_colors']={str(i):[0.91,0.74,0.29] for i in range(len(G.shapes(shape,G.TopAbs_FACE)))}
  write(out,m)
 return publish_mesh(out)

def target_rows(rows,kind='native_edge'):
 result=[]
 for i,r in enumerate(rows or []):
  if isinstance(r,list):points=r;meta={}
  elif isinstance(r,dict):points=next((r[k] for k in ['samples_mm','polyline_mm','polyline','samples','sample_points_world_mm','world_endpoints_mm','endpoints'] if r.get(k)),None);meta=r
  else:continue
  if points and len(points)>=2 and isinstance(points[0],list):result.append({'id':meta.get('id',meta.get('target_id',f'target-{i+1}')),'samples_mm':points,'target_kind':meta.get('target_kind',kind),'label':meta.get('label'),'provenance':meta.get('provenance')})
 return result

def load_runs(suite=None):
 found={};extra=[]
 for name in ['original-occ-native','original-occ-compositions']:
  ip=(suite/'native/index.json') if suite and name=='original-occ-native' else (suite/'nonexistent-composition-index.json') if suite else ROOT/'runs'/name/'index.json'
  if not ip.exists():continue
  for r in read(ip).get('rows',[]):
   if r.get('track')=='historical_batch_native':continue
   n=r['number'];ids=r.get('original_variant_ids') or [r.get('original_variant_id') or r['variant_id']]
   for vid in ids:found[(n,vid)]=r
   extra.append(r)
 # Re-run the original degree-9 proxy / native controls with their original IDs.
 if suite:
  for rp in suite.glob('composition*/routing-summary.json'):
   route=read(rp);n=route['requested_case']
   for view in route.get('variants',[]):
    ex=[e for e in view.get('executions',[]) if e.get('summary')]
    if not ex:continue
    sp=rp.parent/ex[0]['summary'];found[(n,view['original_variant_id'])]={'number':n,'variant_id':view['original_variant_id'],'summary':str(sp),'run_dir':str(sp.parent),'method':view.get('method'),'fresh_run':True,'executions':[{'summary':str(rp.parent/e['summary']),'run_dir':str((rp.parent/e['summary']).parent)} for e in ex]}
 idx=(suite/'g2/index.json') if suite else ROOT/'runs/original-occ-g2/index.json'
 single=(suite/'g2/summary.json') if suite else ROOT/'runs/original-occ-g2/summary.json'
 if not single.exists():single=ROOT/'runs/original-occ-g2/case35/summary.json'
 ids={'g2-proxy-label-1p0':'proxy-s1p0','g2-proxy-label-0p1':'proxy-s0p1','g2-proxy-label-10p0':'proxy-s10p0','native-circle-r13':'default-circle-r13','internal-c2-r13':'internal-c2-circle-r13'}
 if idx.exists():
  g2rows=[(r,(idx.parent/r['summary']).relative_to(ROOT)) for r in read(idx)['results']]
 elif single.exists():
  g2rows=[(r,(single.parent/r['job_id'].split('special.')[-1]/'summary.json').relative_to(ROOT)) for r in read(single)['trials']]
 else:g2rows=[]
 for r,sp in g2rows:
  suffix=r['job_id'].split('special.')[-1];vid=ids.get(suffix)
  if vid:found.setdefault((35,vid),{'number':35,'variant_id':vid,'summary':str(sp),'run_dir':str(sp.parent),'method':r['method_kind'],'fresh_run':True})
 return found,extra

def fresh(r,n,vid):
 sp=path(r.get('summary'));run=path(r.get('run_dir')) or sp.parent
 if not sp or not sp.exists():return None
 s=read(sp);art=s.get('artifacts') or {};method=r.get('method',s.get('method_kind','native_ordinary_fillet'))
 result_file=run/art.get('result_mesh','result.mesh.json');before_file=run/art.get('before_mesh','before.mesh.json')
 after=publish_mesh(result_file) if result_file.exists() else mesh_brep(run/art.get('result_brep','result.brep'))
 before=publish_mesh(before_file) if before_file.exists() else mesh_brep(run/art.get('before_brep','before.brep'))
 outcome=s.get('outcome',s.get('execution_status'));api=s.get('api_success');stats=s.get('result_stats') or (s.get('result') or {}).get('stats') or {};valid=s.get('valid',stats.get('valid'))
 if valid is None:valid=s.get('result',{}).get('readback_stats',{}).get('valid')
 if not after:status='api_failed';label='处理失败'
 elif valid is False or outcome in ['native_quality_failed','invalid_result']:status='geometry_failed';label='几何检查未通过'
 elif outcome in ['step_roundtrip_failed','step_export_failed']:status='export_failed';label='BREP候选 · STEP未通过'
 elif api is False:status='api_failed';label='调用失败 · 保留候选'
 else:status='candidate_unverified';label='本次处理已有结果'
 reason=s.get('reason') or '按原版输入与参数重新执行；几何、导出和原图功能分别验收。'
 if 'compos' in method:reason='原版显式组合构造复跑；不计原生自动功能通过。'+str(reason)
 dst=DEST/f'runs/{n:02d}/{vid}';pub=compact_summary(s);pub['publication']={'raw_summary_sha256':digest(sp),'stage':'fresh processing of frozen original input','base_parametric_creation_claimed':False};write(dst/'summary.json',pub)
 extras=[]
 for i,e in enumerate(r.get('executions',[])):
  ep=path(e['summary']);ed=path(e.get('run_dir')) or ep.parent
  if not ep.exists():continue
  es=read(ep);ea=es.get('artifacts',{});em=publish_mesh(ed/ea.get('result_mesh','result.mesh.json'))
  esummary=dst/f'comparison-{i+1}.json';write(esummary,compact_summary(es));extras.append({'mesh':em,'summary':esummary.relative_to(WEB).as_posix(),'outcome':es.get('outcome'),'label':es.get('variant',es.get('id',f'result-{i+1}'))})
 files=[public_model(run/art.get('before_brep','before.brep'),'实际操作输入 BREP'),public_model(run/art.get('result_brep','result.brep'),'实际结果 BREP（检查未全通过）' if status in ['api_failed','geometry_failed','export_failed'] else '实际结果 BREP',status),public_model(run/art.get('result_step','result.step'),'STEP（回读未通过）' if status=='export_failed' else '导出 STEP',status)]
 files=[f for f in files if f]
 targets=target_rows(s.get('selection',[]))
 pp=s.get('preprocess',{});steps=s.get('processing_steps',s.get('steps',[]))
 return {'status':status,'label':label,'reason':reason,'mesh':after,'before_mesh':before,'version':s.get('engine_version','7.9.3'),'method':method,'summary':(dst/'summary.json').relative_to(WEB).as_posix(),'evidence_kind':'fresh_run','outcome':outcome,'source_feature_passed':False,'metrics':s.get('result_stats',s.get('result',{}).get('stats',{})),'parameters':s.get('parameters'),'source_sha256':s.get('source_sha256',r.get('source_sha256')),'operation_input_sha256':s.get('operation_input_sha256',s.get('before',{}).get('brep_sha256')),'raw_summary_sha256':digest(sp),'files':files,'additional_results':extras,'processing_steps':steps,'preprocess':pp,'operation_targets':targets,'reproduce':r.get('reproduce') or (f'python adapters/occt/original/run.py --job {s["job_id"]} --output runs/replay-{n:02d}-{vid}' if 'job_id' in s and s.get('adapter','').endswith('original/run.py') else f'python adapters/occt/original-compositions/run.py --case {n} --output runs/replay-original-{n:02d}')}

def historical(v,n):
 results=v.get('historical_results',[]);bp=next((r.get('brep') for r in results if r.get('brep')),None);after=mesh_brep(bp);state=v.get('historical_status');status='historical_snapshot' if after else 'api_failed'
 if 'fail' in str(state) and after:label='历史候选 · 原检查未全通过'
 else:label='历史记录 · 尚未复跑' if after else '原记录未获得结果'
 return {'status':status,'label':label,'reason':v.get('scope_note') or '保留原人工核对记录；没有把历史快照称作本次新执行。','mesh':after,'version':'7.8.1 (historical)','method':v.get('method'),'evidence_kind':'historical_snapshot','outcome':state,'source_feature_passed':False,'summary':None,'reproduce':None}

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--suite-run',type=pathlib.Path,help='Output of bench.py original; preserve unrelated published views');args=parser.parse_args()
 suite=args.suite_run.resolve() if args.suite_run else None
 suite_case11=None
 suite_metadata={}
 if suite and (suite/'suite-index.json').exists():
  suite_metadata=read(suite/'suite-index.json');current=suite_metadata.get('current_case11')
  if current:
   import publish_case11_revision
   suite_case11=(suite/current.get('run_dir','case11-convexity')).resolve()
   publish_case11_revision.validate_occ_run(suite_case11)
 if suite and (suite/'case11-convexity/report.json').exists() and suite_case11 is None:
  raise ValueError('Case11 suite output has no current_case11 manifest binding; refusing to publish an unrelated cached run')
 if suite_case11 is not None and suite_metadata.get('case')==11 and not suite_metadata.get('all'):
  publish_case11_revision.main(occ_run=suite_case11);return
 ip=read(SOURCE/'index.json');runs,_=load_runs(suite);cases=[];counts=collections.Counter()
 if not runs and (DEST/'catalog.json').exists():
  if suite_case11 is not None:
   publish_case11_revision.main(occ_run=suite_case11);return
  print('No fresh local runs; retaining the published original-series snapshot.');return
 legacy=ROOT.parent/'outputs/parasolid-preblend/manifest.json'
 # Original recipe metadata is optional; each mesh is still made from the
 # verified public BREP, never from source screenshots.
 original_manifest=ROOT.parent/'outputs/parasolid-preblend/manifest.json'
 meta={r['id']:r for r in read(original_manifest)['cases']} if original_manifest.exists() else {}
 for row in ip['cases']:
  cp=path(row.get('path',row.get('data')));c=read(cp);n=c['number'];has=c.get('has_model',n!=32);base=mesh_brep(c.get('source_brep')) if has else None
  camera=meta.get(c['id'],{}).get('camera',[-45,25]);out={k:c.get(k) for k in ['number','id','title','has_model','source_sha256','human_status','human_note','reference','default_variant']};out.update(question='沿用原版基础几何、原选边／选面和原参数，分开核对实际操作输入与处理结果。',base_mesh=base,camera=camera,variants=[],source_case_sha256=digest(cp),base_creation={'method':'frozen_exact_BREP_input','parametric_reconstruction_executed':False},source_review_state_sha256=ip['source_review_state_sha256'])
  if n==32:
   out['reference']={'page':1356,'page_numbering':'one-based physical PDF page','suggested_crop':None,'local_only':True,'expected_pdf_sha256':'4f01858f600e10bb096e69e6f79ad04c383a3bc6d3db8ffc5ad4dca74d7f4460','scope':'explanation page only; no independent geometry'}
  previous_file=DEST/f'cases/{n:02d}.json';previous=read(previous_file) if previous_file.exists() else {};prior={v['id']:v for v in previous.get('variants',[])} if previous.get('source_case_sha256')==digest(cp) else {}
  for v in c['variants']:
   vid=v['id']
   if suite and (n,vid) not in runs and vid in prior:
    pv=prior[vid];out['variants'].append(pv);counts[pv['occt']['evidence_kind']]+=1;counts['status:'+pv['occt']['status']]+=1;continue
   sel=v.get('selection',{});bs=sel.get('base') or {};ops=sel.get('operation') or [];op0=ops[0] if isinstance(ops,list) and ops else ops if isinstance(ops,dict) else {};operation=v.get('operation_inputs') or [];operation0=operation[0] if operation else {}
   operation_mesh=mesh_brep(operation0.get('brep'));record=fresh(runs[(n,vid)],n,vid) if (n,vid) in runs else historical(v,n)
   if record.get('before_mesh'):operation_mesh=record['before_mesh']
   base_targets=target_rows(bs.get('targets',[]));operation_targets=record.get('operation_targets') or target_rows(op0.get('targets',operation0.get('selected_edges',[])))
   prep=v.get('preprocess_note') or c.get('source_spec',{}).get('scope_notice') or v.get('scope_note') or '基础模型与操作输入分别保存；仅以实际处理记录判断是否经过前处理。'
   pv={'id':vid,'label':v.get('label',vid),'method':v.get('method'),'method_label':'显式组合构造' if 'compos' in str(v.get('method')) else '原生调用／原版对照','parameters':v.get('parameters'),'radius_mm':v.get('radius_mm'),'base_brep':c.get('source_brep'),'base_sha256':c.get('source_sha256'),'base_mesh':base,'operation_mesh':operation_mesh,'input_mesh':operation_mesh or base,'base_targets':base_targets,'operation_targets':operation_targets,'targets':base_targets,'base_selected_faces':bs.get('selected_faces',[]),'operation_selected_faces':op0.get('selected_faces',[]),'selected_faces':bs.get('selected_faces',[]),'historical_status':v.get('historical_status'),'human_status':v.get('human_status'),'human_note':c.get('human_note'),'scope_note':v.get('scope_note') or prep,'preparation_note':prep,'evidence_kind':record['evidence_kind'],'processing_steps':record.get('processing_steps',[]),'occt':record}
   params=v.get('parameters') or {};construction=params.get('construction') or {}
   original_camera=construction.get('camera') or params.get('camera')
   if isinstance(original_camera,(list,dict)):pv['camera']=original_camera
   pp=record.get('preprocess') or {};recipe=pp.get('requested_recipe') or {};rtype=recipe.get('type')
   if rtype=='none':
    raw=read(WEB/record['summary']) if record.get('summary') else {};srcstats=raw.get('source_stats') or {};instats=raw.get('input_stats') or {}
    same=bool(srcstats and instats and all(srcstats.get(k)==instats.get(k) for k in ['faces','edges','vertices']))
    pv['input_relation']='same_as_base' if same else 'part_selection'
    pv['operation_is_derived']=False
    pv['operation_relation_note']='原基础几何，仅序列化或容器表示不同。' if same else '从原基础模型中提取本次操作部件；未改变该部件几何。'
   elif rtype:
    pv['input_relation']='derived';pv['operation_is_derived']=True;pv['operation_relation_note']='按原版记录执行前处理后得到操作输入；完整原基础模型仍单独保留。'
   else:
    pv['input_relation']='recorded_combination_input';pv['operation_is_derived']=None;pv['operation_relation_note']='此处为原组合流程入口；内部的分割、原生调用及布尔步骤见实际处理记录。'
   if len(operation)>1:pv['additional_operation_inputs']=[{'label':o.get('label'),'mesh':mesh_brep(o.get('brep')),'sha256':o.get('sha256')} for o in operation[1:]]
   base_download=public_model(c.get('source_brep'),'原版基础模型 BREP')
   pv['base_brep_url']=base_download['path'] if base_download else None
   if base_download:record.setdefault('files',[]).insert(0,base_download)
   if n==36 and not pv['base_selected_faces']:
    shape=G.read(path(c['source_brep']));faces=G.shapes(shape,G.TopAbs_FACE)
    if len(faces)==2:
     pv['base_selected_faces']=[{'face_id':0,'label':'原窄竖墙面'},{'face_id':1,'label':'原宽横墙面'}]
     pv['selected_faces']=pv['base_selected_faces']
     pv['base_selection_note']='原配方选用的两张分离支撑面；基础模型中没有公共边。'
   record['reproduce']=f'python bench.py original --case {n} --variant {vid} --out runs/replay-original-{n:02d}-{vid}'
   if vid=='blade-input':record.update(status='input_only',label='仅基础模型／辅助输入',reason='原版保留的独立叶片输入，未请求圆角处理。',mesh=None,evidence_kind='input_only');pv['evidence_kind']='input_only'
   out['variants'].append(pv);counts[record['evidence_kind']]+=1;counts['status:'+record['status']]+=1
  if out['variants'] and out['default_variant'] not in [v['id'] for v in out['variants']]:out['default_variant']=out['variants'][0]['id']
  write(DEST/f'cases/{n:02d}.json',out);cases.append({'number':n,'id':c['id'],'title':c['title'],'question':out['question'],'family':'原版人工核对','has_model':has,'data':f'data/original-occ/cases/{n:02d}.json','variant_count':len(out['variants']),'default_variant':out['default_variant']})
 catalog={'schema_version':1,'series':'original','title':'原版 OCC 人工核对系列','model_groups':34,'explanation_only':[32],'excluded':[29],'source_review_state_sha256':ip['source_review_state_sha256'],'cases':cases,'counts':{'cases':len(cases),'models':34,'variants':sum(c['variant_count'] for c in cases),**dict(counts)},'scope':'Frozen original base inputs; fresh processing is distinguished from historical snapshots. No parametric base regeneration or full source-feature acceptance is claimed.'}
 write(DEST/'catalog.json',catalog);print(json.dumps(catalog['counts'],ensure_ascii=False))
 if (ROOT/'docs/original-smlib-pairing-audit.json').exists():
  import attach_original_smlib
  if suite_case11 is not None:
   with publish_case11_revision.using_occ_run(suite_case11):attach_original_smlib.main()
  else:attach_original_smlib.main()
 elif suite_case11 is not None:publish_case11_revision.main(occ_run=suite_case11)
if __name__=='__main__':main()
