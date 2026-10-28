# -*- coding: utf-8 -*-
"""Attach only audited, same-constraint SMLib evidence to original OCC views."""
import copy,json,pathlib,collections
from build_site import ROOT,WEB,read,write,sanitize,digest,mesh
AUDIT=ROOT/'docs/original-smlib-pairing-audit.json'

def empty_record(row):
 cat=row.get('category',row.get('classification','unknown')) if row else 'unknown'
 if cat=='no_corresponding_radius':
  reason='输入和目标已有记录，但尚无这个原版半径的 SMLib 实跑。';pairing='no_comparable_run'
 elif cat in ['unsupported_protocol','protocol_not_encoded']:
  reason='原版的组合、前处理或特殊约束尚未在 SMLib 中表达为同一协议；不拿其他工况替代。';pairing='protocol_not_encoded'
 else:
  reason='尚未验证这条原版请求与 SMLib 的对应关系。';pairing='no_comparable_run'
 return {'status':'not_run','label':'暂无同协议结果','reason':reason,'mesh':None,'before_mesh':None,'version':'10.0.0','method':'not_encoded_same_protocol','pairing_status':pairing,'evidence_kind':'not_run','source_feature_passed':False}

def from_existing(row,case,view):
 ids=row.get('selected_job_ids') or ([row.get('matched_job_id')] if row.get('matched_job_id') else [])
 if len(ids)!=1:return None
 jobid=ids[0];jobpath=ROOT/f'data/jobs/{jobid}.json'
 if not jobpath.is_file():return None
 job=read(jobpath)
 if job['source_sha256']!=case['source_sha256']:raise ValueError('SMLib source does not match the original case')
 original=read(WEB/f'data/cases/{case["number"]:02d}.json')
 source=next((v for v in original['variants'] if v['id']==jobid),None)
 if not source or not source.get('smlib',{}).get('summary'):return None
 record=copy.deepcopy(source['smlib']);record.update(source_job_id=jobid,source_sha256=job['source_sha256'],radius_mm=job['radius_mm'],parameters={k:job[k] for k in ['radius_mm','variable_start_mm','variable_end_mm','variable_physical_start','variable_physical_end'] if k in job},pairing_status='matched_constraints_different_representation',evidence_kind='matched_existing_run',source_feature_passed=False)
 record['label']='同参已实跑 · '+str(record.get('label','候选待核对'))
 record['pairing_note']='同源基础几何、同一部件和有限目标、相同所给半径约束；OCCT 解析 BREP 与 SMLib 有限 NURBS 表示不同。'
 if 'variable' in jobid:record['pairing_note']+=' 只匹配两端物理半径；完整沿程规律等价仍未验证。'
 record['reason']=record['pairing_note']+' '+str(record.get('reason',''))
 record['unchanged_input']=bool(record.get('mesh') and record.get('mesh')==record.get('before_mesh'))
 record['original_case_file_sha256']=case['source_case_sha256']
 if row.get('source_case_sha256') and row['source_case_sha256']!=case['source_case_sha256']:raise ValueError('Original definition changed after pairing audit')
 record['pairing_audit']={'path':'docs/original-smlib-pairing-audit.json','sha256':digest(AUDIT),'original_variant_id':view['id'],'source_fixture_sha256':job.get('source_fixture_sha256'),'native_edge_indices_reused':False}
 return record

def from_completion(row,case,view):
 sp=pathlib.Path(row['summary']);sp=sp if sp.is_absolute() else ROOT/sp
 run=sp.parent;s=read(sp);ex=s.get('execution',{});jobfile=pathlib.Path(row.get('request_path',row.get('request','')));jobfile=jobfile if jobfile.is_absolute() else ROOT/jobfile
 job=read(jobfile)
 if job['source_sha256']!=case['source_sha256'] or abs(float(job['radius_mm'])-float(view['radius_mm']))>1e-12:raise ValueError('Completion source/radius mismatch')
 before=mesh(run/'before.mesh.json',run/'before.json');after=mesh(run/'result.mesh.json',run/'result.json');result=read(run/'result.json') if (run/'result.json').is_file() else {};stats=result.get('native_stats',{})
 if 'crash' in s.get('outcome',''):status='crash';label='原生进程崩溃'
 elif ex.get('native_api_success') is False:status='api_failed';label='API失败 · 保留候选'
 elif stats.get('valid') is False or s.get('gates',{}).get('result_kind',{}).get('passed') is False:status='geometry_failed';label='几何检查未通过'
 elif after:status='candidate_unverified';label='新同参候选 · 待核对'
 else:status='not_run';label='未获得实际输出'
 diagnostic='按原版相同输入／目标补跑此半径；不代表源图特殊功能或人工外观通过。'
 if status=='crash':diagnostic=f'输入和选边门已通过；原生进程在 {s.get("raw_phase","unknown")} 阶段终止（返回码 {s.get("process",{}).get("return_code")}），未获得圆角结果。'
 elif status=='api_failed':diagnostic=f'SMLib API 返回 {ex.get("native_api_raw_status")}；实际失败候选已保留，内核未给出更细原因。'
 elif status=='geometry_failed':diagnostic='API 有返回，但有效性或预期体／片类型检查未通过；这里保留实际候选。'
 dest=WEB/f'data/original-smlib/runs/{job["job_id"]}';write(dest/'summary.json',sanitize(s));write(dest/'request.json',sanitize(job))
 return {'status':status,'label':label,'reason':diagnostic,'mesh':after,'before_mesh':before,'summary':(dest/'summary.json').relative_to(WEB).as_posix(),'version':s.get('engine_version','10.0.0'),'method':ex.get('native_api','native_edge_fillet'),'source_job_id':job['job_id'],'source_sha256':job['source_sha256'],'radius_mm':job['radius_mm'],'pairing_status':'matched_constraints_different_representation','pairing_note':'同一来源部件、同一世界目标及半径；内核输入表示不同。','evidence_kind':'fresh_run','source_feature_passed':False,'unchanged_input':bool(after and after==before),'raw_status':ex.get('native_api_raw_status'),'outcome':s.get('outcome'),'metrics':stats,'parameters':{'radius_mm':job['radius_mm']},'reproduce':f'python adapters/smlib/run.py {jobfile.relative_to(ROOT).as_posix()} --output runs/replay-{job["job_id"]}','raw_summary_sha256':digest(sp),'published_summary_sha256':digest(dest/'summary.json'),'original_case_file_sha256':case['source_case_sha256']}

def main():
 if not AUDIT.is_file():raise SystemExit('Missing independent pairing audit; no speculative linking performed')
 audit=read(AUDIT);rows={(r['number'],r.get('original_variant_id',r.get('variant_id'))):r for r in audit['rows']}
 completed={};index=ROOT/'runs/original-smlib-radius-completion/index.json'
 if index.exists():completed={(r['number'],r['variant_id']):r for r in read(index).get('rows',[])}
 saved_file=WEB/'data/original-smlib/published-completions.json';saved=read(saved_file).get('bindings',[]) if saved_file.exists() else [];saved_records={(r['number'],r['variant_id']):r['record'] for r in saved}
 counts=collections.Counter();catalog=read(WEB/'data/original-occ/catalog.json')
 for c in catalog['cases']:
  cp=WEB/c['data'];case=read(cp)
  for v in case['variants']:
   key=(case['number'],v['id']);row=rows.get(key);record=None
   if key in completed:
    record=from_completion(completed[key],case,v);saved_records[key]=record
   elif key in saved_records:
    candidate=saved_records[key];sp=WEB/candidate['summary']
    if candidate.get('original_case_file_sha256')==case['source_case_sha256'] and sp.is_file() and digest(sp)==candidate.get('published_summary_sha256'):record=copy.deepcopy(candidate)
   if record is None and row and (row.get('matched_known_request') or row.get('classification')=='matched_constraints_different_representation'):record=from_existing(row,case,v)
   if not record:record=empty_record(row)
   if v.get('occt',{}).get('status')=='input_only':record={'status':'not_run','label':'仅输入 · 未请求圆角','reason':'原版此视图只保留辅助输入，没有圆角处理请求。','mesh':None,'before_mesh':None,'version':'10.0.0','method':'input_only','pairing_status':'not_applicable_input_only','evidence_kind':'input_only','source_feature_passed':False}
   v['smlib']=record;counts[record['pairing_status']]+=1;counts['evidence:'+record['evidence_kind']]+=1
  write(cp,case)
 if saved_records:write(saved_file,{'schema_version':1,'bindings':[{'number':n,'variant_id':vid,'record':r} for (n,vid),r in sorted(saved_records.items())]})
 catalog['smlib_pairing']={'counts':dict(counts),'audit_sha256':digest(AUDIT),'policy':'Never substitute another radius, part, finite target or special construction protocol.'};write(WEB/'data/original-occ/catalog.json',catalog);print(json.dumps(dict(counts),ensure_ascii=False))
if __name__=='__main__':main()
