"""Run current OCC review protocols, retaining explicit frozen-history replay."""
import argparse,datetime,hashlib,json,pathlib,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
def read(p):return json.loads(pathlib.Path(p).read_text())
def current_case11(parser):
 path=ROOT/'data/case11-convexity/revision.json'
 if not path.exists():parser.error('Current case 11 revision metadata is missing; refusing to fall back to the rejected frozen input')
 revision=read(path);source=revision.get('source_sha256') or revision.get('before',{}).get('brep_sha256')
 if not isinstance(source,str) or len(source)!=64 or any(c not in '0123456789abcdef' for c in source):parser.error('Current case 11 revision requires a valid source_sha256')
 generator_revision=revision.get('generator_revision') or revision.get('revision','candidate-v6')
 if generator_revision!='candidate-v6':parser.error('Unsupported current case 11 generator revision: '+str(generator_revision))
 source_brep=revision.get('source_brep')
 if not isinstance(source_brep,str) or pathlib.Path(source_brep).is_absolute():parser.error('Current case 11 requires a repository-relative canonical source_brep')
 canonical=(ROOT/source_brep).resolve()
 if not canonical.is_relative_to(ROOT) or not canonical.is_file():parser.error('Current case 11 canonical BREP is missing or outside the repository')
 if hashlib.sha256(canonical.read_bytes()).hexdigest()!=source:parser.error('Current case 11 canonical BREP does not match the registered source_sha256')
 return {'manifest':str(path.relative_to(ROOT)),'revision_id':revision.get('id'),'generator_revision':generator_revision,'expected_source_sha256':source,
  'source_brep':source_brep,'input_mode':'frozen_exact_revision_input',
  'input_creation':{'method':'frozen_exact_revision_input','parametric_reconstruction_executed':False,'source_brep':source_brep,'source_sha256':source},
  'run_dir':'case11-convexity','report':'case11-convexity/report.json',
  'radii_mm':[1,3,6],'shape_acceptance':revision.get('shape_acceptance',False),'human_status':revision.get('human_status','pending'),'source_feature_pass_claimed':False}
def current_case36(parser):
 path=ROOT/'data/case36-faceface/protocol.json'
 if not path.exists():parser.error('Current case 36 face-face protocol is missing; refusing to substitute an old common-edge or admission-only run')
 protocol=read(path);source=protocol.get('source_sha256');source_brep=protocol.get('source_brep')
 if protocol.get('case_number')!=36 or protocol.get('id')!='case36-faceface-r8-v1':parser.error('Unknown current case 36 face-face protocol')
 if not isinstance(source,str) or len(source)!=64 or any(c not in '0123456789abcdef' for c in source):parser.error('Current case 36 requires a valid source_sha256')
 if not isinstance(source_brep,str) or pathlib.Path(source_brep).is_absolute():parser.error('Current case 36 requires a repository-relative source_brep')
 canonical=(ROOT/source_brep).resolve()
 if not canonical.is_relative_to(ROOT) or not canonical.is_file():parser.error('Current case 36 original BREP is missing or outside the repository')
 if hashlib.sha256(canonical.read_bytes()).hexdigest()!=source:parser.error('Current case 36 BREP does not match the registered original source_sha256')
 frozen_name=protocol.get('frozen_case_file')
 if not isinstance(frozen_name,str) or pathlib.Path(frozen_name).is_absolute():parser.error('Current case 36 requires a repository-relative frozen_case_file')
 frozen_file=(ROOT/frozen_name).resolve()
 if not frozen_file.is_relative_to(ROOT) or not frozen_file.is_file() or hashlib.sha256(frozen_file.read_bytes()).hexdigest()!=protocol.get('frozen_case_sha256'):parser.error('Current case 36 frozen definition hash mismatch')
 frozen=read(frozen_file)
 if frozen.get('number')!=36 or frozen.get('source_brep')!=source_brep or frozen.get('source_sha256')!=source:parser.error('Current case 36 protocol must use the original finite-face source')
 modes=[row['id'] for row in protocol['modes']]
 if set(modes)!={'to_walls','no','short','long'} or protocol.get('radius_mm')!=8:parser.error('Current case 36 requires the registered R8 four-mode protocol')
 return {'protocol':str(path.relative_to(ROOT)),'protocol_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
  'protocol_id':protocol['id'],'source_brep':source_brep,'source_sha256':source,'input_mode':'original_finite_faces',
  'radius_mm':8,'modes':modes,'variant_ids':['trim-'+mode+'-r8' for mode in modes],
  'run_dir':'case36-faceface/occt-composite',
  'scope':'Exact original unequal disjoint faces; four explicit OCC blend-patch constructions. SMLib native modes and the OCCT low-level single baseline have separate commands and evidence.'}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case',type=int);p.add_argument('--case11',dest='case',action='store_const',const=11,help='Shortcut for --case 11');p.add_argument('--case36',dest='case',action='store_const',const=36,help='Shortcut for --case 36');p.add_argument('--variant');p.add_argument('--all',action='store_true');p.add_argument('--out',type=pathlib.Path);a=p.parse_args()
 if a.all==bool(a.case):p.error('Specify either --case NN or --all')
 if a.all and a.variant:p.error('--variant requires a single --case')
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out=(a.out or ROOT/'runs/original-suite'/stamp).resolve()
 if out.exists() and any(out.iterdir()):p.error('Refusing to overwrite existing evidence; choose a fresh --out')
 casefile=ROOT/f'data/original-occ/cases/{a.case:02d}.json' if a.case else None
 if casefile and not casefile.exists():p.error('Case is absent or explicitly excluded')
 c=read(casefile) if casefile else None
 if c and not c.get('has_model'):p.error('This is an explanation page, not a modeling request')
 case11=current_case11(p) if a.all or a.case==11 else None
 case36=current_case36(p) if a.all or a.case==36 else None
 native36_requested=a.case==36 and a.variant=='native-faceface-r8'
 case36_native=None
 if case36 and native36_requested:
  case36_native=dict({k:v for k,v in case36.items() if k not in ['modes','variant_ids']},run_dir='case36-faceface/occt-native',variant_id='native-faceface-r8',four_trim_controls_supported=False,
                    scope='OCCT low-level native surface/surface R8 baseline only; the selected API has no four-trim enum. Missing SDK dependencies are recorded without a composite fallback.')
  case36=None
 if a.case==11 and a.variant:
  print('Case 11 uses the exact frozen candidate-v6 BREP and runs R1/R3/R6 together; --variant is selection metadata only. Use adapters/occt/original/run.py --requests to replay frozen historical jobs.',file=sys.stderr)
 extension=read(ROOT/'data/case08-radius/protocol.json') if (ROOT/'data/case08-radius/protocol.json').exists() else None
 extension_ids=extension['variant_ids'] if extension and a.case==8 else []
 if a.case==36 and a.variant and not native36_requested and a.variant not in case36['variant_ids']:
  p.error('Unknown current case36 face-face ID. The old R0.5/R1/R2 admission checks remain available through python tools/run_case36_input.py --variant ID --output runs/my-case36-admission')
 if a.variant and a.case not in [11,36] and a.variant not in [v['id'] for v in c['variants']]+extension_ids:p.error('Unknown original or explicitly requested variant ID')
 native=read(ROOT/'adapters/occt/original/requests.json');native['jobs']=[j for j in native['jobs'] if j['track']=='current_original_native' and j['case_number'] not in [11,36] and (a.all or j['case_number']==a.case)]
 if extension and (a.all or a.case==8):
  extjobs=read(ROOT/'data/case08-radius/occ-requests.json')['jobs'];existing={j['job_id'] for j in native['jobs']}
  native['jobs'].extend(j for j in extjobs if j['job_id'] not in existing)
 protocol=read(ROOT/'adapters/occt/original-compositions/protocol-manifest.json')['cases'];commands=[]
 if a.variant and a.case not in [11,36]:
  pr=protocol.get(str(a.case),{});variants=[v['original_variant_id'] for v in pr.get('variants',[])]
  if a.variant in variants:commands.append([sys.executable,str(ROOT/'adapters/occt/original-compositions/run.py'),'--case',str(a.case),'--variant',a.variant,'--output',str(out/'composition')]);native['jobs']=[]
  elif a.case==35 and a.variant.startswith('proxy-'):commands.append([sys.executable,str(ROOT/'adapters/occt/special/run.py'),'--case','35','--output',str(out/'g2')]);native['jobs']=[]
  elif a.variant=='blade-input':native['jobs']=[]
  else:native['jobs']=[j for j in native['jobs'] if a.variant in j.get('original_variant_ids',[j['original_variant_id']])]
 else:
  for n in sorted(map(int,protocol)):
   if n not in [11,36] and (a.all or n==a.case):commands.append([sys.executable,str(ROOT/'adapters/occt/original-compositions/run.py'),'--case',str(n),'--output',str(out/f'composition-{n:02d}')])
  if a.all or a.case==35:commands.append([sys.executable,str(ROOT/'adapters/occt/special/run.py'),'--case','35','--output',str(out/'g2')])
 case11_command=None
 if case11:
  case11_command=[sys.executable,str(ROOT/'adapters/occt/case11-convexity/build.py'),'--revision',case11['generator_revision'],'--source-brep',case11['source_brep'],'--expected-source-sha256',case11['expected_source_sha256'],'--output',str(out/'case11-convexity')]
  commands.append(case11_command)
 if case36:
  command=[sys.executable,str(ROOT/'adapters/occt/case36-faceface/composite.py'),'--output',str(out/case36['run_dir'])]
  if a.case==36 and a.variant:
   mode=a.variant.removeprefix('trim-').removesuffix('-r8');command.extend(['--mode',mode]);case36['requested_modes']=[mode]
  else:case36['requested_modes']=case36['modes']
  commands.append(command)
 if case36_native:
  commands.append([sys.executable,str(ROOT/'adapters/occt/case36-faceface/native_probe.py'),'--output',str(out/case36_native['run_dir'])])
 out.mkdir(parents=True,exist_ok=True)
 if native['jobs']:
  request=out/'native-current-requests.json';request.write_text(json.dumps(native,ensure_ascii=False,indent=2)+'\n');commands.insert(0,[sys.executable,str(ROOT/'adapters/occt/original/run.py'),'--requests',str(request),'--output',str(out/'native')])
 records=[]
 for i,cmd in enumerate(commands):
  with (out/f'controller-{i+1}.log').open('w') as log:
   try:r=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=1800);rc=r.returncode
   except subprocess.TimeoutExpired:rc=None
  record={'command':[str(pathlib.Path(x).relative_to(ROOT)) if str(x).startswith(str(ROOT)+'/') else x for x in cmd],'returncode':rc,'log':f'controller-{i+1}.log'}
  if cmd==case11_command:
   generated=out/'case11-convexity/before.brep';actual=hashlib.sha256(generated.read_bytes()).hexdigest() if generated.exists() else None
   verification={'expected_source_sha256':case11['expected_source_sha256'],'actual_source_sha256':actual,'matched':actual==case11['expected_source_sha256']}
   case11['source_verification']=verification;record['case11_source_verification']=verification
   if not verification['matched']:
    record['returncode']=1 if rc==0 else rc
    print('Current case 11 source hash mismatch or missing exact operation-input BREP; see suite-index.json',file=sys.stderr)
  records.append(record);print('original workflow',i+1,'returncode',record['returncode'],flush=True)
 if case36_native:
  native_index=out/case36_native['run_dir']/'index.json'
  if native_index.exists():
   observed=read(native_index);case36_native['observed_status']=observed.get('status','actual_native_records');case36_native['native_calls_executed']=sum(bool(r.get('native_call_executed')) for r in observed.get('rows',[]))
 result={'schema_version':1,'case':a.case,'variant':a.variant,'all':a.all,'base_geometry':'frozen original BREP inputs; current case 11 uses the exact registered revision BREP without parametric reconstruction' if case11 else 'frozen original BREP inputs; not parametrically reconstructed','current_case11':case11,'current_case36_faceface':case36,'current_case36_native':case36_native,'source_feature_pass_claimed':False,'execution_groups':records,'input_only':not commands,'scope':'Native and explicit-composition recipes are separate; current case 11 executes R1/R3/R6 on the same frozen canonical candidate-v6 input. Kernel rejections/invalid BREP/STEP failures remain in their summaries.'+(' Case36 default uses exact-input explicit face-face patches; SMLib is not automatically called by this OCC suite. The OCCT native baseline is selected only by native-faceface-r8.' if case36 or case36_native else '')};(out/'suite-index.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print('Evidence:',out)
 return 1 if any(x['returncode']!=0 for x in records) else 0
if __name__=='__main__':sys.exit(main())
