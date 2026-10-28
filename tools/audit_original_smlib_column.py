"""Verify the fourth-column binding without changing or invoking a kernel."""
import collections,json,pathlib,hashlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[1];WEB=ROOT/'web'
def read(p):return json.loads(pathlib.Path(p).read_text())
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def main():
 baseline=read(ROOT/'docs/original-smlib-pairing-audit.json');proof={(r['number'],r['original_variant_id']):r for r in baseline['rows']};issues=[];rows=[];counts=collections.Counter()
 for cp in sorted((WEB/'data/original-occ/cases').glob('*.json')):
  case=read(cp)
  for v in case['variants']:
   sm=v['smlib'];key=(case['number'],v['id']);checks={};kind=sm['pairing_status'];counts[kind]+=1
   if kind.startswith('matched_'):
    jobid=sm['source_job_id'];jp=ROOT/f'data/original-smlib/jobs/{jobid}.json';new=jp.exists()
    if not new:jp=ROOT/f'data/jobs/{jobid}.json'
    job=read(jp);summary=read(WEB/sm['summary']);ex=summary.get('execution',{});checks['source_case']=job['source_sha256']==case['source_sha256']==sm['source_sha256']==summary['source_sha256'];checks['fixture_identity']=sha(ROOT/job['source_fixture_json'])==job['source_fixture_sha256']==summary['source_fixture_sha256'];checks['radius']=abs(float(sm['radius_mm'])-float(job['radius_mm']))<1e-12 and abs(float(summary['radius_mm'])-float(job['radius_mm']))<1e-12;checks['native_call']=ex.get('native_call_started') is True;checks['selection']=summary.get('selection_passed') is True;checks['input_admission']=summary.get('input_import',{}).get('passed') is True;checks['no_source_feature_pass']=not sm.get('source_feature_passed')
    if sm.get('mesh'):checks['mesh_exists']=(WEB/sm['mesh']).is_file()
    if new:
     template=read(ROOT/f'data/jobs/{job["source_template_job_id"]}.json');checks['template_immutable']=sha(ROOT/f'data/jobs/{job["source_template_job_id"]}.json')==job['source_template_job_sha256'];checks['radius_only_change']=all(job.get(k)==template.get(k) for k in ['source_brep','source_sha256','source_fixture_json','source_fixture_sha256','component_index','targets','expected_input_kind','xsect_type','continuity','thumbweight']);checks['original_radius']=abs(float(v['radius_mm'])-float(job['radius_mm']))<1e-12;checks['case_definition']=sha(ROOT/f'data/original-occ/cases/{case["number"]:02d}.json')==job['original_case_file_sha256']
    else:checks['audited_match']=proof[key]['matched_known_request'] and jobid in proof[key]['selected_job_ids']
    for name,ok in checks.items():
     if not ok:issues.append({'number':case['number'],'variant_id':v['id'],'gate':name})
   else:
    if sm.get('mesh'):issues.append({'number':case['number'],'variant_id':v['id'],'gate':'unmatched_result_present'})
   rows.append({'number':case['number'],'variant_id':v['id'],'pairing_status':kind,'evidence_kind':sm['evidence_kind'],'source_job_id':sm.get('source_job_id'),'checks':checks,'reason':sm.get('reason')})
 report={'schema_version':1,'passed':not issues,'scope':'Actual requested constraints and evidence identity. Finite NURBS vs analytic BREP representation and global quality remain separate; no full source-feature score.','counts':dict(counts),'baseline_pairing_audit_sha256':sha(ROOT/'docs/original-smlib-pairing-audit.json'),'rows':rows,'issues':issues};(ROOT/'docs/original-smlib-column-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'passed':not issues,'counts':dict(counts),'issues':issues},ensure_ascii=False));return bool(issues)
if __name__=='__main__':sys.exit(main())
