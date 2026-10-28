"""Complete only audited radius-only SMLib gaps; never change input/targets/options."""
import argparse,collections,concurrent.futures,copy,hashlib,json,pathlib,subprocess,sys,datetime
ROOT=pathlib.Path(__file__).resolve().parents[1]
def read(p):return json.loads(pathlib.Path(p).read_text())
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def write(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',action='store_true');p.add_argument('--workers',type=int,default=4);p.add_argument('--output',type=pathlib.Path,default=ROOT/'runs/original-smlib-radius-completion');a=p.parse_args();audit=read(ROOT/'docs/original-smlib-pairing-audit.json');rows=[]
 for row in audit['rows']:
  if row.get('category')!='no_corresponding_radius':continue
  n,vid=row['number'],row['original_variant_id'];casefile=ROOT/f'data/original-occ/cases/{n:02d}.json';case=read(casefile)
  if sha(casefile)!=row['source_case_sha256']:raise ValueError('Original case definition changed after audit')
  eligible=[c for c in row.get('candidate_evidence',[]) if c.get('source_revision_matches_current_original') and all(c.get('binding_checks',{}).values()) and c.get('targets',{}).get('matched') and c.get('input',{}).get('finite_input_comparable') and c.get('input',{}).get('literal_preprocess_same') and c.get('parameters',{}).get('mode')=='constant']
  if not eligible:raise ValueError(f'No strictly radius-only template for {n}/{vid}')
  cand=sorted(eligible,key=lambda c:c['job_id'])[0];template=ROOT/f'data/jobs/{cand["job_id"]}.json';job=copy.deepcopy(read(template))
  if job['source_sha256']!=case['source_sha256'] or sha(template)!=cand['request_sha256']:raise ValueError('Template binding mismatch')
  if any(k.startswith('variable_') for k in job):raise ValueError('Variable-radius jobs cannot be constant radius templates')
  oldradius=job['radius_mm'];radius=float(row['radius_mm']);jobid=f'original.{n:02d}.{vid}.smlib';job.update(job_id=jobid,radius_mm=radius,role='original_radius_completion',original_variant_id=vid,original_case_file_sha256=sha(casefile),source_template_job_id=cand['job_id'],source_template_job_sha256=sha(template),request_note='Audited original-view radius-only completion; no source/target/SDK-option alteration')
  # Assert the only operation input/target/parameter change is the scalar radius.
  for key in ['source_sha256','source_brep','source_fixture_json','source_fixture_sha256','component_index','targets','expected_input_kind','xsect_type','continuity','thumbweight']:
   if job.get(key)!=read(template).get(key):raise ValueError('Unexpected change: '+key)
  request=ROOT/f'data/original-smlib/jobs/{jobid}.json';write(request,job);rows.append({'number':n,'variant_id':vid,'job_id':jobid,'source_template_job_id':cand['job_id'],'request_path':request.relative_to(ROOT).as_posix(),'source_sha256':job['source_sha256'],'radius_mm':radius,'template_radius_mm':oldradius,'original_case_file_sha256':sha(casefile),'checks':{'template_sha256':True,'same_input_part_targets_and_options':True,'radius_is_only_operation_parameter_change':True},'pairing_status':'matched_constraints_different_representation'})
 write(ROOT/'data/original-smlib/radius-completion-plan.json',{'schema_version':1,'audit_sha256':sha(ROOT/'docs/original-smlib-pairing-audit.json'),'count':len(rows),'rows':rows})
 if not a.run:print('Audited jobs:',len(rows));return 0
 out=a.output.resolve()
 if out.exists() and any(out.iterdir()):raise SystemExit('Refusing nonempty output; choose a new --output')
 out.mkdir(parents=True,exist_ok=True)
 def execute(row):
  dest=out/row['job_id'];cmd=[sys.executable,str(ROOT/'adapters/smlib/run.py'),str(ROOT/row['request_path']),'--output',str(dest),'--timeout','60'];logfile=out/(row['job_id']+'.controller.log')
  with logfile.open('w') as log:
   try:r=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=180);rc=r.returncode
   except subprocess.TimeoutExpired:rc=None
  sp=dest/'summary.json';summary=read(sp) if sp.exists() else {};result=dict(row,run_dir=dest.relative_to(ROOT).as_posix(),summary=sp.relative_to(ROOT).as_posix(),controller_returncode=rc,outcome=summary.get('outcome','controller_failed'),native_call_started=summary.get('execution',{}).get('native_call_started',False),source_fixture_admitted=summary.get('input_import',{}).get('passed',False),actual_radius_mm=summary.get('execution',{}).get('radius_mm'),summary_sha256=sha(sp) if sp.exists() else None)
  print(row['job_id'],result['outcome'],flush=True);return result
 with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,min(a.workers,4))) as pool:completed=list(pool.map(execute,rows))
 report={'schema_version':1,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'count':len(completed),'counts':dict(collections.Counter(r['outcome'] for r in completed)),'actual_native_calls':sum(r['native_call_started'] for r in completed),'input_admitted':sum(r['source_fixture_admitted'] for r in completed),'rows':completed,'source_feature_pass_claimed':False};write(out/'index.json',report);print(json.dumps({k:report[k] for k in ['count','counts','actual_native_calls','input_admitted']}));return 0
if __name__=='__main__':sys.exit(main())
