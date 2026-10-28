"""Keep the exact unequal finite faces as case36's actual input.

The old equal-width edge-fillet derivative remains archived, not a replacement
for the original face-pair operation. No fillet call is implied by preflight.
"""
import collections,copy,pathlib
from contextlib import contextmanager
from build_site import ROOT,WEB,read,write,digest,sanitize,mesh
from publish_case08_radius import file_model

PROTOCOL=ROOT/'data/case36-input/protocol.json'
PUBLIC=WEB/'data/case36-input'
CASE=WEB/'data/original-occ/cases/36.json'
CANONICAL=ROOT/'runs/case36-input/canonical'
_RUN_OVERRIDE=None

@contextmanager
def using_run36(run_dir):
    global _RUN_OVERRIDE
    previous=_RUN_OVERRIDE;_RUN_OVERRIDE=pathlib.Path(run_dir).resolve()
    try:yield
    finally:_RUN_OVERRIDE=previous

def validate_run36(run_dir):
    run_dir=pathlib.Path(run_dir).resolve()
    if not run_dir.is_relative_to(ROOT):raise ValueError('Case36 publication requires repository-relative evidence')
    protocol=read(PROTOCOL);index=read(run_dir/'index.json')
    if index['source_sha256']!=protocol['source_sha256'] or index.get('native_call_executed') is not False or index.get('source_unchanged') is not True:
        raise ValueError('Case36 input audit did not preserve the registered original')
    expected={r['id']:r['radius_mm'] for r in protocol['variants']};seen=set()
    for row in index['rows']:
        vid=row['variant_id'];sp=ROOT/row['summary'];s=read(sp)
        if vid not in expected or vid in seen or expected[vid]!=s['radius_mm'] or digest(sp)!=row['summary_sha256']:
            raise ValueError('Case36 preflight request identity mismatch')
        seen.add(vid)
        if (s['source_sha256']!=s['operation_input_sha256'] or s['source_sha256']!=protocol['source_sha256'] or
            digest(ROOT/row['before_brep'])!=protocol['source_sha256'] or s['native_call_executed'] is not False or
            s['outcome']!='blocked_no_shared_edge' or not s['operation_equals_source_bytes'] or not s['source_unchanged'] or
            not all(s['input_checks'].values())):
            raise ValueError('Case36 original finite domains or admission evidence changed')
    if not seen:raise ValueError('No actual case36 input checks')
    return index

def build_entry(row,protocol,base_mesh):
    s=read(ROOT/row['summary']);vid=row['variant_id'];radius=s['radius_mm'];dest=PUBLIC/'runs'/vid
    write(dest/'summary.json',sanitize(s));source=protocol['source_sha256']
    params={'radius_mode':'constant','radius_mm':radius,'input_type':'original_disjoint_finite_faces','preprocess':{'type':'none'}}
    reason='原14mm竖面与25mm横面完整保留、仍然分离；没有共享拓扑边。普通边圆角适配器的前置条件未满足，本次未调用圆角API。面面圆角及原图四种trim模式尚未接入，不能据此判定内核不支持。'
    record={'status':'blocked','label':'原输入无共边 · 未调用圆角','reason':reason,'mesh':None,'before_mesh':base_mesh,
            'version':s['engine_version'],'method':'input_admission_check','method_label':'原始有限面输入检查','evidence_kind':'fresh_run',
            'summary':(dest/'summary.json').relative_to(WEB).as_posix(),'raw_summary_sha256':row['summary_sha256'],'published_summary_sha256':digest(dest/'summary.json'),
            'source_sha256':source,'operation_input_sha256':source,'source_feature_passed':False,'native_call_executed':False,'api_success':None,
            'outcome':s['outcome'],'display_input_on_missing_result':False,'parameters':params,
            'metrics':{'native_call_executed':False,'operation_equals_source_bytes':True,'original_vertical_width_mm':14,'original_horizontal_width_mm':25,'shared_edge_count':0},
            'checks':{'input':s['input_checks'],'selection':s['selection'],'theoretical_contacts':s['theoretical_circular_contacts'],'validation_boundary':s['validation_boundary']},
            'files':[file_model(ROOT/protocol['source_brep'],'原始两有限面 BREP','与实际操作输入字节相同')],
            'reproduce':f'python tools/run_case36_input.py --variant {vid} --output runs/replay-case36-input-{vid}'}
    faces=[{'face_id':0,'label':'原窄竖面 · 宽14mm'},{'face_id':1,'label':'原宽横面 · 宽25mm'}]
    return {'id':vid,'label':f'原始两有限面 · R{radius:g} · 未调用圆角','radius_mm':radius,'parameters':params,
            'method':'input_admission_check','method_label':'原始有限面输入检查','base_brep':protocol['source_brep'],'base_brep_url':record['files'][0]['path'],
            'base_sha256':source,'base_mesh':base_mesh,'operation_mesh':base_mesh,'input_mesh':base_mesh,
            'base_targets':[],'operation_targets':[],'targets':[],'base_selected_faces':faces,'operation_selected_faces':faces,'selected_faces':faces,
            'input_relation':'same_as_base','operation_is_derived':False,'operation_relation_note':'原基础与实际操作输入为相同BREP字节；保留两张分离面的位置、14/25宽度及有限边界。',
            'preparation_note':'无缝合、延伸或裁窄。原来的等宽L壳及其圆角已单独归档。',
            'scope_note':'当前完成原输入及普通共边圆角前置条件检查；未执行圆角，未验证面面圆角及四种trim。小半径理论接触轨也在原有限面域外。',
            'evidence_kind':'fresh_run','human_status':'pending','human_note':'','occt':record,
            'processing_steps':[{'step_index':0,'method':'exact_input_admission_check','preprocess':'none','native_call_executed':False,'outcome':s['outcome']}],
            'smlib':{'status':'not_run','label':'原面面协议尚未测试','reason':'原始不等宽两有限面上的对应面面／裁剪协议尚未接入SMLib当前系列；没有用普通等宽共边控制替代。','mesh':None,'before_mesh':None,'version':'10.0.0','method':'not_encoded_same_protocol','pairing_status':'protocol_not_encoded','evidence_kind':'not_run','source_feature_passed':False}}

def main(run_dir=None):
    if not PROTOCOL.exists() or not CASE.exists():return
    protocol=read(PROTOCOL);source=protocol['source_sha256']
    if digest(ROOT/protocol['source_brep'])!=source or digest(ROOT/protocol['geometry_audit']['path'])!=protocol['geometry_audit']['sha256']:
        raise ValueError('Case36 protocol source or independent geometry audit mismatch')
    old=read(CASE);snapshot=PUBLIC/'published-case.json';legacy=PUBLIC/'legacy-derived-case.json'
    if not old.get('input_correction') and not legacy.exists():
        archived=copy.deepcopy(old);archived['source_quality_warning']='历史等宽L壳替代控制：有限域已扩展和裁窄，不代表原不等宽两面输入。';write(legacy,archived)
    saved=read(snapshot)['case'] if snapshot.exists() else None
    selected=pathlib.Path(run_dir).resolve() if run_dir is not None else _RUN_OVERRIDE
    selected=selected if selected is not None else CANONICAL
    rows=[]
    if (selected/'index.json').exists():
        index=validate_run36(selected);rows=index['rows']
        registered={r['id']:r for r in protocol['variants']}
        for row in rows:registered[row['variant_id']].update(summary=row['summary'],summary_sha256=row['summary_sha256'])
        write(PROTOCOL,protocol)
    elif run_dir is not None or _RUN_OVERRIDE is not None:raise ValueError('Explicit case36 run is missing its index; refusing cached substitution')
    elif saved is None:raise ValueError('No case36 input-check evidence or verified snapshot')
    case={k:copy.deepcopy(old[k]) for k in ['number','id','title','has_model','reference','camera']}
    base_mesh=mesh(ROOT/rows[0]['before_mesh']) if rows else saved['base_mesh']
    available={v['id']:copy.deepcopy(v) for v in (saved or {}).get('variants',[])}
    for row in rows:available[row['variant_id']]=build_entry(row,protocol,base_mesh)
    entries=[]
    for registered in protocol['variants']:
        v=available[registered['id']];r=v['occt']
        if r['source_sha256']!=source or r['operation_input_sha256']!=source or r['raw_summary_sha256']!=registered['summary_sha256'] or digest(WEB/r['summary'])!=r['published_summary_sha256']:
            raise ValueError('Case36 cached input audit differs from the registered source/request')
        v.update(base_mesh=base_mesh,operation_mesh=base_mesh,input_mesh=base_mesh);r['before_mesh']=base_mesh
        entries.append(v)
    case.update(source_sha256=source,source_brep=protocol['source_brep'],source_case_sha256=protocol['frozen_case_sha256'],base_mesh=base_mesh,
                human_status='pending',human_note='',default_variant='part01-r1p0',variants=entries,
                base_creation={'method':'frozen_exact_BREP_input','parametric_reconstruction_executed':False},
                question='先核对原14/25不等宽两张有限面。当前普通边圆角无共边、未调用；面面圆角四种裁剪模式待接入。',
                source_quality_warning='第36项已恢复原有限面输入：竖面宽14mm、横面宽25mm，位置和间隙保持不变。旧等宽替代结果已隔离；当前仅完成输入检查，未执行圆角。',
                input_protocol={'path':'data/case36-input/protocol.json','sha256':digest(PROTOCOL)},
                input_correction={'id':protocol['id'],'source_sha256':source,'operation_input_sha256':source,'geometry_audit':protocol['geometry_audit'],'native_call_executed':False,'legacy_archive':'data/case36-input/legacy-derived-case.json'})
    for name in ['protocol.json','geometry-audit.json']:write(PUBLIC/name,sanitize(read(PROTOCOL.parent/name)))
    references=[{'label':'原输入与旧替代输入的独立量测','path':'data/case36-input/geometry-audit.json','sha256':digest(PUBLIC/'geometry-audit.json')},
                {'label':'历史等宽替代结果记录（不作为本项结果）','path':'data/case36-input/legacy-derived-case.json','sha256':digest(legacy)}]
    for v in entries:
        v['occt']['files']=[f for f in v['occt']['files'] if f['path'] not in {r['path'] for r in references}]+copy.deepcopy(references)
    from audit_case36_input import case36_input_checks
    checks,_=case36_input_checks(case,ROOT)
    if not all(checks.values()):raise ValueError('Case36 public input verification failed: '+', '.join(k for k,ok in checks.items() if not ok))
    write(CASE,case);write(snapshot,{'protocol_sha256':digest(PROTOCOL),'case':case})
    cp=WEB/'data/original-occ/catalog.json';catalog=read(cp);counter=collections.Counter();pairing=collections.Counter();total=0
    for row in catalog['cases']:
        c=read(WEB/row['data']);row['variant_count']=len(c['variants']);row['default_variant']=c.get('default_variant');total+=len(c['variants'])
        for v in c['variants']:
            counter[v['occt']['evidence_kind']]+=1;counter['status:'+v['occt']['status']]+=1
            sm=v.get('smlib',{});pairing[sm.get('pairing_status','unknown')]+=1;pairing['evidence:'+sm.get('evidence_kind','unknown')]+=1
    catalog['counts']={'cases':len(catalog['cases']),'models':34,'variants':total,**dict(counter)};catalog['smlib_pairing']['counts']=dict(pairing)
    catalog['input_admission_only']={'36':{'variants':3,'native_call_executed':False,'source_sha256':source}}
    write(cp,catalog);print('case36: original finite domains preserved; old equal-band results archived; no fillet call claimed')

if __name__=='__main__':main()
