"""Verify the fourth-column binding without changing or invoking a kernel."""
import collections,json,pathlib,hashlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[1];WEB=ROOT/'web'
def read(p):return json.loads(pathlib.Path(p).read_text())
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()

CASE11_CONTRACT='data/case11-convexity/revision.json'
CASE11_GEOMETRY_GATES=('native','brep_roundtrip','step_roundtrip','brep_roundtrip_volume_match',
 'step_roundtrip_volume_match','A_convex_physical_material_angle','A_90_degree_physical_material_angle',
 'A_outward_normals_verified','actual_sections_completed','visible_band_convex_curvature_and_material_side','model_unchanged')

def repository_file(root,value):
 """A revision may name existing repository files, never arbitrary machine paths."""
 if not isinstance(value,str) or not value or pathlib.Path(value).is_absolute():return None
 path=(root/value).resolve()
 if not path.is_relative_to(root.resolve()) or not path.is_file():return None
 return path

def case11_revision_checks(case,root=ROOT):
 """Validate the explicit public revision while leaving frozen history separate.

 This checks the independently produced audit's identity and individual gates;
 it does not claim to rerun its geometry or accept the drawing's hidden sides.
 """
 root=pathlib.Path(root);revision=case.get('revision') or {};checks={};contract={}
 checks['registered_case11_revision']=case.get('number')==11 and revision.get('contract')==CASE11_CONTRACT
 contract_file=repository_file(root,CASE11_CONTRACT)
 checks['revision_contract_exists']=contract_file is not None
 if contract_file is None:return checks,contract
 contract=read(contract_file);digest=sha(contract_file)
 checks['revision_contract_hash']=revision.get('contract_sha256')==case.get('source_case_sha256')==digest
 checks['revision_case_number']=contract.get('case_number')==11 and isinstance(contract.get('id'),str) and bool(contract['id'])
 fields=('id','source_brep','source_sha256','previous_source_sha256','geometry_audit','target_world','previous_human_confirmation_scope')
 checks['revision_public_fields']=all(key in contract and revision.get(key)==contract[key] for key in fields) and all(revision.get(key)==value for key,value in contract.items())
 checks['revision_target_world']=bool(contract.get('target_world')) and case.get('target_world')==contract.get('target_world')
 frozen_file=repository_file(root,'data/original-occ/cases/11.json')
 frozen=read(frozen_file) if frozen_file else {}
 previous=contract.get('previous_source_sha256')
 checks['revision_previous_frozen_source']=bool(previous) and previous==frozen.get('source_sha256') and previous!=contract.get('source_sha256')
 previous_file=repository_file(root,frozen.get('source_brep'))
 checks['revision_previous_source_bytes']=previous_file is not None and sha(previous_file)==previous
 source=repository_file(root,contract.get('source_brep'))
 checks['revision_source_bytes']=source is not None and sha(source)==contract.get('source_sha256')==case.get('source_sha256')
 checks['revision_human_scope']=contract.get('previous_human_confirmation_scope')=='local_strip_only' and contract.get('shape_acceptance') is False and case.get('human_status')=='pending'
 audit_ref=contract.get('geometry_audit') or {};audit_file=repository_file(root,audit_ref.get('path'))
 checks['revision_geometry_audit_hash']=audit_file is not None and sha(audit_file)==audit_ref.get('sha256')
 audit=read(audit_file) if audit_file else {}
 checks['revision_geometry_audit_source']=audit.get('schema')=='case11.new_geometry_independent_audit.v1' and audit.get('model')==contract.get('source_brep') and audit.get('sha256')==contract.get('source_sha256') and audit.get('source_unchanged') is True
 checks['revision_geometry_target']=len(contract.get('target_world',[]))==1 and contract['target_world'][0].get('samples_mm')==audit.get('target_A',{}).get('endpoints')
 checks['revision_geometry_gates']=audit.get('author_report_used_as_evidence') is False and audit.get('automated_gates_passed') is True and all(audit.get('gates',{}).get(key) is True for key in CASE11_GEOMETRY_GATES)
 checks['revision_geometry_not_human_acceptance']=audit.get('human_appearance_status')=='pending' and audit.get('original_reference_hidden_material_status')=='inferred reconstruction; not determined by this audit'
 return checks,contract

def revised_smlib_checks(case,variant,sm,job,job_path,summary,root=ROOT):
 checks,contract=case11_revision_checks(case,root);root=pathlib.Path(root)
 checks['revision_request_path']=sm.get('request_file')==job_path.relative_to(root).as_posix()
 checks['revision_request_contract']=sm.get('source_revision_contract')=={'path':CASE11_CONTRACT,'sha256':case.get('source_case_sha256')}
 registered=[row for row in contract.get('smlib_jobs',[]) if row.get('request_file')==sm.get('request_file')]
 checks['revision_request_registered']=len(registered)==1 and registered[0].get('request_sha256')==sha(job_path)
 checks['revision_job_source']=job.get('number')==11 and job.get('source_brep')==contract.get('source_brep') and job.get('source_sha256')==contract.get('source_sha256')
 fixture_path=repository_file(root,job.get('source_fixture_json'));fixture=read(fixture_path) if fixture_path else {}
 checks['revision_fixture_source']=fixture.get('source_sha256')==contract.get('source_sha256') and fixture.get('source_brep')==contract.get('source_brep') and fixture.get('healing') is False and fixture.get('stitching') is False
 checks['revision_not_radius_template']='source_template_job_id' not in job and job.get('source_repair_fa_X_verified') is False and job.get('shape_acceptance') is False
 expected=[target.get('samples_mm') for target in contract.get('target_world',[])]
 actual=[target.get('endpoints_world_mm') for target in job.get('targets',[])]
 checks['revision_world_target']=bool(expected) and actual==expected and all(target.get('expected_count')==1 for target in job.get('targets',[]))
 checks['revision_requested_radius']=float(variant['radius_mm'])==float(job['radius_mm'])
 checks['revision_request_summary_binding']=summary.get('job_id')==job.get('job_id')==sm.get('source_job_id') and summary.get('job_file')==sm.get('request_file')
 checks['revision_execution_input_binding']=summary.get('source_brep')==job.get('source_brep') and summary.get('source_fixture_json')==job.get('source_fixture_json') and summary.get('component_index')==job.get('component_index')
 return checks

def main():
 baseline=read(ROOT/'docs/original-smlib-pairing-audit.json');proof={(r['number'],r['original_variant_id']):r for r in baseline['rows']};issues=[];rows=[];counts=collections.Counter()
 for cp in sorted((WEB/'data/original-occ/cases').glob('*.json')):
  case=read(cp)
  faceface_checks=None
  if case.get('faceface_protocol'):
   from verify_case36_faceface import case36_faceface_checks
   faceface_checks,_=case36_faceface_checks(case,ROOT)
   faceface_checks['faceface_public_case_file']=cp.name=='36.json' and case.get('number')==36
   issues.extend({'number':case['number'],'gate':name} for name,ok in faceface_checks.items() if not ok)
  if case.get('revision'):
   revision_checks,_=case11_revision_checks(case)
   revision_checks['revision_public_case_file']=cp.name=='11.json' and case.get('number')==11
   issues.extend({'number':case['number'],'gate':name} for name,ok in revision_checks.items() if not ok)
  for v in case['variants']:
   sm=v['smlib'];key=(case['number'],v['id']);checks={};kind=sm['pairing_status'];counts[kind]+=1
   if faceface_checks is not None:
    prefix=v['id']+':smlib:'
    checks={name:ok for name,ok in faceface_checks.items() if name.startswith(prefix) or name==v['id']+':sdk_pairing_scope' or name==v['id']+':no_reused_sdk_control'}
    rows.append({'number':case['number'],'variant_id':v['id'],'pairing_status':kind,'evidence_kind':sm['evidence_kind'],'source_job_id':sm.get('source_job_id'),'checks':checks,'reason':sm.get('reason')})
    continue
   if kind.startswith('matched_'):
    jobid=sm['source_job_id'];jp=ROOT/sm['request_file'] if sm.get('request_file') else ROOT/f'data/original-smlib/jobs/{jobid}.json';new=jp.exists()
    if case.get('revision') and (not sm.get('request_file') or repository_file(ROOT,sm['request_file']) is None):
     issues.append({'number':case['number'],'variant_id':v['id'],'gate':'revision_request_missing'})
     rows.append({'number':case['number'],'variant_id':v['id'],'pairing_status':kind,'checks':{'revision_request_missing':False}})
     continue
    if not new:jp=ROOT/f'data/jobs/{jobid}.json'
    job=read(jp);summary=read(WEB/sm['summary']);ex=summary.get('execution',{});checks['source_case']=job['source_sha256']==case['source_sha256']==sm['source_sha256']==summary['source_sha256'];checks['fixture_identity']=sha(ROOT/job['source_fixture_json'])==job['source_fixture_sha256']==summary['source_fixture_sha256'];checks['radius']=abs(float(sm['radius_mm'])-float(job['radius_mm']))<1e-12 and abs(float(summary['radius_mm'])-float(job['radius_mm']))<1e-12;checks['native_call']=ex.get('native_call_started') is True;checks['selection']=summary.get('selection_passed') is True;checks['input_admission']=summary.get('input_import',{}).get('passed') is True;checks['no_source_feature_pass']=not sm.get('source_feature_passed')
    if sm.get('mesh'):checks['mesh_exists']=(WEB/sm['mesh']).is_file()
    if case.get('revision'):
     checks.update(revised_smlib_checks(case,v,sm,job,jp,summary))
    elif new:
     template=read(ROOT/f'data/jobs/{job["source_template_job_id"]}.json');checks['template_immutable']=sha(ROOT/f'data/jobs/{job["source_template_job_id"]}.json')==job['source_template_job_sha256'];checks['radius_only_change']=all(job.get(k)==template.get(k) for k in ['source_brep','source_sha256','source_fixture_json','source_fixture_sha256','component_index','targets','expected_input_kind','xsect_type','continuity','thumbweight']);checks['original_radius']=abs(float(v['radius_mm'])-float(job['radius_mm']))<1e-12;checks['case_definition']=sha(ROOT/f'data/original-occ/cases/{case["number"]:02d}.json')==job['original_case_file_sha256']
    else:checks['audited_match']=proof[key]['matched_known_request'] and jobid in proof[key]['selected_job_ids']
    for name,ok in checks.items():
     if not ok:issues.append({'number':case['number'],'variant_id':v['id'],'gate':name})
   else:
    if sm.get('mesh'):issues.append({'number':case['number'],'variant_id':v['id'],'gate':'unmatched_result_present'})
   rows.append({'number':case['number'],'variant_id':v['id'],'pairing_status':kind,'evidence_kind':sm['evidence_kind'],'source_job_id':sm.get('source_job_id'),'checks':checks,'reason':sm.get('reason')})
 report={'schema_version':1,'passed':not issues,'scope':'Actual requested constraints and evidence identity. Finite NURBS vs analytic BREP representation and global quality remain separate; no full source-feature score.','counts':dict(counts),'baseline_pairing_audit_sha256':sha(ROOT/'docs/original-smlib-pairing-audit.json'),'rows':rows,'issues':issues};(ROOT/'docs/original-smlib-column-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'passed':not issues,'counts':dict(counts),'issues':issues},ensure_ascii=False));return bool(issues)
if __name__=='__main__':sys.exit(main())
