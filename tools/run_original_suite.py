"""Run the frozen, manually reviewed OCC series using its original protocols."""
import argparse,datetime,json,pathlib,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
def read(p):return json.loads(pathlib.Path(p).read_text())
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case',type=int);p.add_argument('--variant');p.add_argument('--all',action='store_true');p.add_argument('--out',type=pathlib.Path);a=p.parse_args()
 if a.all==bool(a.case):p.error('Specify either --case NN or --all')
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out=(a.out or ROOT/'runs/original-suite'/stamp).resolve()
 if out.exists() and any(out.iterdir()):p.error('Refusing to overwrite existing evidence; choose a fresh --out')
 casefile=ROOT/f'data/original-occ/cases/{a.case:02d}.json' if a.case else None
 if casefile and not casefile.exists():p.error('Case is absent or explicitly excluded')
 c=read(casefile) if casefile else None
 if c and not c.get('has_model'):p.error('This is an explanation page, not a modeling request')
 extension=read(ROOT/'data/case08-radius/protocol.json') if (ROOT/'data/case08-radius/protocol.json').exists() else None
 extension_ids=extension['variant_ids'] if extension and a.case==8 else []
 if a.variant and a.variant not in [v['id'] for v in c['variants']]+extension_ids:p.error('Unknown original or explicitly requested variant ID')
 native=read(ROOT/'adapters/occt/original/requests.json');native['jobs']=[j for j in native['jobs'] if j['track']=='current_original_native' and (a.all or j['case_number']==a.case)]
 if extension and (a.all or a.case==8):
  extjobs=read(ROOT/'data/case08-radius/occ-requests.json')['jobs'];existing={j['job_id'] for j in native['jobs']}
  native['jobs'].extend(j for j in extjobs if j['job_id'] not in existing)
 protocol=read(ROOT/'adapters/occt/original-compositions/protocol-manifest.json')['cases'];commands=[]
 if a.variant:
  pr=protocol.get(str(a.case),{});variants=[v['original_variant_id'] for v in pr.get('variants',[])]
  if a.variant in variants:commands.append([sys.executable,str(ROOT/'adapters/occt/original-compositions/run.py'),'--case',str(a.case),'--variant',a.variant,'--output',str(out/'composition')]);native['jobs']=[]
  elif a.case==35 and a.variant.startswith('proxy-'):commands.append([sys.executable,str(ROOT/'adapters/occt/special/run.py'),'--case','35','--output',str(out/'g2')]);native['jobs']=[]
  elif a.variant=='blade-input':native['jobs']=[]
  else:native['jobs']=[j for j in native['jobs'] if a.variant in j.get('original_variant_ids',[j['original_variant_id']])]
 else:
  for n in sorted(map(int,protocol)):
   if a.all or n==a.case:commands.append([sys.executable,str(ROOT/'adapters/occt/original-compositions/run.py'),'--case',str(n),'--output',str(out/f'composition-{n:02d}')])
  if a.all or a.case==35:commands.append([sys.executable,str(ROOT/'adapters/occt/special/run.py'),'--case','35','--output',str(out/'g2')])
 out.mkdir(parents=True,exist_ok=True)
 if native['jobs']:
  request=out/'native-current-requests.json';request.write_text(json.dumps(native,ensure_ascii=False,indent=2)+'\n');commands.insert(0,[sys.executable,str(ROOT/'adapters/occt/original/run.py'),'--requests',str(request),'--output',str(out/'native')])
 records=[]
 for i,cmd in enumerate(commands):
  with (out/f'controller-{i+1}.log').open('w') as log:
   try:r=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=1800);rc=r.returncode
   except subprocess.TimeoutExpired:rc=None
  records.append({'command':[str(pathlib.Path(x).relative_to(ROOT)) if str(x).startswith(str(ROOT)+'/') else x for x in cmd],'returncode':rc,'log':f'controller-{i+1}.log'});print('original workflow',i+1,'returncode',rc,flush=True)
 result={'schema_version':1,'case':a.case,'variant':a.variant,'all':a.all,'base_geometry':'frozen original BREP inputs; not parametrically reconstructed','source_feature_pass_claimed':False,'execution_groups':records,'input_only':not commands,'scope':'Native and explicit-composition recipes are separate; kernel rejections/invalid BREP/STEP failures remain in their summaries.'};(out/'suite-index.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print('Evidence:',out)
 return 1 if any(x['returncode']!=0 for x in records) else 0
if __name__=='__main__':sys.exit(main())
