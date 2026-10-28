"""Publish the versioned convex case11 input; never relabel legacy runs."""
import collections, copy, pathlib, shutil, json
from contextlib import contextmanager
from build_site import ROOT, WEB, read, write, digest, sanitize, mesh
from publish_case08_radius import file_model
from attach_original_smlib import from_completion

CONTRACT = ROOT/'data/case11-convexity/revision.json'
PUBLIC = WEB/'data/case11-convexity'
CASE = WEB/'data/original-occ/cases/11.json'
OCC = ROOT/'runs/case11-convexity/candidate-v6'
SDK = ROOT/'runs/case11-convexity/smlib-candidate-v6/report.json'
_OCC_OVERRIDE = None

@contextmanager
def using_occ_run(occ_run):
    """Bind the existing SMLib attachment callback to this suite's OCC run."""
    global _OCC_OVERRIDE
    previous = _OCC_OVERRIDE
    _OCC_OVERRIDE = pathlib.Path(occ_run).resolve()
    try: yield
    finally: _OCC_OVERRIDE = previous

def validate_occ_run(occ_run, contract=None):
    occ_run = pathlib.Path(occ_run).resolve()
    if not occ_run.is_relative_to(ROOT):
        raise ValueError('Case11 suite publication requires an output inside the repository for portable evidence paths')
    contract = contract or read(CONTRACT)
    report = read(occ_run/'report.json')
    if digest(occ_run/'before.brep') != contract['source_sha256'] or report['before']['brep_sha256'] != contract['source_sha256']:
        raise ValueError('Case11 suite OCC input differs from the registered revision')
    attempts = report.get('attempts', [])
    if sorted(float(a['radius_mm']) for a in attempts) != [1., 3., 6.]:
        raise ValueError('Case11 suite must retain all three R1/R3/R6 attempts')
    for attempt in attempts:
        raw = read(occ_run/f'r{attempt["radius_mm"]:g}'/'attempt.json')
        if raw['target_before_sha256'] != contract['source_sha256'] or float(raw['radius_mm']) != float(attempt['radius_mm']):
            raise ValueError('Case11 suite attempt source/radius mismatch')
        # The aggregate may add a STEP manifold audit after saving the attempt;
        # every original field, including failures, must remain unchanged.
        if any(attempt.get(k) != v for k,v in raw.items() if k != 'step') or any(attempt.get('step',{}).get(k) != v for k,v in raw.get('step',{}).items()):
            raise ValueError('Case11 aggregate report differs from its actual attempt')
        result = occ_run/f'r{attempt["radius_mm"]:g}'/'result.brep'
        expected = raw.get('artifacts',{}).get('brep_sha256')
        if expected and (not result.exists() or digest(result) != expected):
            raise ValueError('Case11 actual result BREP differs from its attempt evidence')
    return report

def bind_occ_run(contract, occ_run):
    report = validate_occ_run(occ_run, contract)
    contract = copy.deepcopy(contract)
    contract['occt_runs'] = [dict(variant_id=f'part01-r{a["radius_mm"]:g}',
        summary=(occ_run/f'r{a["radius_mm"]:g}'/'attempt.json').relative_to(ROOT).as_posix(),
        summary_sha256=digest(occ_run/f'r{a["radius_mm"]:g}'/'attempt.json')) for a in report['attempts']]
    write(ROOT/contract['geometry_report'], report)
    write(CONTRACT, contract)
    return contract

def cached_sdk(old, contract, variant_id, radius):
    """Retain only a published SDK result verified against the same input."""
    candidates = [old]
    snapshot = PUBLIC/'published-case.json'
    if snapshot.exists(): candidates.append(read(snapshot)['case'])
    for candidate in candidates:
        if candidate.get('source_sha256') != contract['source_sha256']: continue
        view = next((v for v in candidate.get('variants', []) if v['id'] == variant_id), None)
        record = (view or {}).get('smlib', {})
        if not record.get('summary'): continue
        summary_path = WEB/record['summary']
        job_path = ROOT/record['request_file']
        summary, job = read(summary_path), read(job_path)
        if (record.get('source_sha256') != contract['source_sha256'] or
            summary.get('source_sha256') != contract['source_sha256'] or
            digest(summary_path) != record.get('published_summary_sha256') or
            job['source_sha256'] != contract['source_sha256'] or
            float(job['radius_mm']) != float(radius) or
            job['job_id'] != record.get('source_job_id') or
            digest(ROOT/job['source_fixture_json']) != job['source_fixture_sha256']):
            raise ValueError('Case11 cached SDK source/request/summary identity mismatch')
        record = copy.deepcopy(record)
        record['original_case_file_sha256'] = digest(CONTRACT)
        record['source_revision_contract'] = {'path':'data/case11-convexity/revision.json','sha256':digest(CONTRACT)}
        return record
    return None

def build_case(old, contract, occ_run=None):
    occ_run = pathlib.Path(occ_run) if occ_run is not None else OCC
    report = validate_occ_run(occ_run, contract)
    if report['before']['brep_sha256'] != contract['source_sha256']:
        raise ValueError('case11 OCC report uses another source')
    audit = read(ROOT/contract['geometry_audit']['path'])
    if not audit['automated_gates_passed'] or audit['sha256'] != contract['source_sha256']:
        raise ValueError('case11 independent material audit failed')
    section = occ_run/'section.svg'
    section_origin = 'selected OCC run'
    if not section.exists():
        previous = read(PUBLIC/'revision.json') if (PUBLIC/'revision.json').exists() else {}
        if previous.get('source_sha256') != contract['source_sha256'] or not (PUBLIC/'section.svg').exists():
            raise ValueError('Case11 suite has no section SVG or verified same-source published auxiliary')
        section = PUBLIC/'section.svg'; section_origin = 'same-source published input auxiliary; not regenerated by this suite'
    svg = section.read_text().replace('viewBox="0 0 980 460"','viewBox="0 0 980 560"')
    for name in ['revision.json','geometry-audit.json','geometry-report.json','old-geometry-audit.json']:
        write(PUBLIC/name, sanitize(read(CONTRACT.parent/name)))
    (PUBLIC/'section.svg').write_text(svg)
    (PUBLIC/'section.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>11 · 实际材料截面</title><style>body{max-width:1000px;margin:2rem auto;padding:1rem;font:18px system-ui;background:#fcfcf8}svg{width:100%}</style><h1>11 · 实际材料截面</h1><p>由修正版BREP求交生成；红点A周围仅左下象限为材料，对应90°外凸肩棱。此图是几何检查辅助，原始PDF图请在四栏页本地载入。</p>'+svg+'<p>独立复现：python adapters/occt/case11-convexity/audit_material.py</p></html>')
    base_mesh = mesh(occ_run/'before.mesh.json')
    source_file = file_model(ROOT/contract['source_brep'], '修正后基础模型 BREP', '凸性修正版 · 待人工核对')
    case = {k:copy.deepcopy(old[k]) for k in ['number','id','has_model','reference']}
    warning = '第11项已重建凹凸关系：目标A为90°实体凸棱，已有窄带为外凸曲面。旧凹根输入及其结果已隔离。尺寸、隐藏连接及整体外观仍待人工核对。'
    case.update(title='自交修复输入 · 凸肩与外凸窄过渡带（修正版）',source_sha256=contract['source_sha256'],source_case_sha256=digest(CONTRACT),
                source_brep=contract['source_brep'],base_mesh=base_mesh,camera=contract['camera'],target_world=contract['target_world'],
                human_status='pending',human_note='',shape_acceptance=False,source_quality_warning=warning,
                question='先核对凸肩A、外凸窄带和短横舌的整体对应，再检查普通圆角与自交；原图 repair_fa_X 专用修复仍未验证。',
                revision=dict(contract,contract='data/case11-convexity/revision.json',contract_sha256=digest(CONTRACT)),
                base_creation={'method':'parametric_convex_reconstruction','parametric_reconstruction_executed':True,'generator':'adapters/occt/case11-convexity/build.py','generator_revision':'candidate-v6'},
                source_review_state_sha256=read(ROOT/'data/original-occ/index.json')['source_review_state_sha256'],
                section_provenance={'source_sha256':contract['source_sha256'],'origin':section_origin,'processing_result':False},
                default_variant='part01-r3',variants=[])
    sdk_report = read(SDK) if SDK.exists() else None
    if sdk_report and sdk_report['source_sha256'] != contract['source_sha256']:
        raise ValueError('case11 SDK report uses another source')
    sdk_rows = {float(r['radius_mm']):r for r in (sdk_report or {}).get('attempts',[]) if r.get('radius_mm') is not None}
    for a in sorted(report['attempts'], key=lambda row:-row['radius_mm']):
        r = a['radius_mm']; rid=f'r{r:g}'; vid='part01-'+rid; run=occ_run/rid
        dest=PUBLIC/'occ'/rid
        summary=dict(a,source_sha256=contract['source_sha256'],source_brep=contract['source_brep'],engine_version='7.9.3',
                     source_repair_fa_X_verified=False,shape_acceptance=False,parameters={'radius_mm':r},source_revision_contract={'path':'data/case11-convexity/revision.json','sha256':digest(CONTRACT)})
        write(dest/'summary.json',sanitize(summary))
        good=a['status']=='native_candidate' and a['inspection']['passed'] and a['step']['readback']['passed']
        reason = (f'实际 R{r:g}：BREP、流形、BOP自交检查和STEP回读通过；整体外观与原repair_fa_X修复功能尚未验收。' if good else
                  f'实际 R{r:g}：Build返回模型，但BREP/BOP检查发现自交，STEP回读也未通过。保留真实无效候选，未用组合构造替代。')
        parameters={'radius_mode':'constant','radius_mm':r,'units':'mm','target_world_mm':contract['target_world'][0]['samples_mm'],'repair_fa_X_option_supplied':False}
        steps=[{'step_index':0,'selection':report['target_selection'],'api':a['api'],'parameters':parameters,'native_done':a['native_done'],'status':a['status']}]
        files=[source_file,file_model(ROOT/'data/case11-convexity/candidate-v6.step','基础 STEP'),file_model(run/'result.brep','实际结果 BREP',a['status']),file_model(run/'result.step','实际 STEP（质量见状态）',a['status'])]
        files += [{'label':'凹凸截面辅助图','path':'data/case11-convexity/section.html','sha256':digest(PUBLIC/'section.html')},
                  {'label':'独立材料侧与凸性检查','path':'data/case11-convexity/geometry-audit.json','sha256':digest(PUBLIC/'geometry-audit.json')}]
        oc=dict(status='candidate_unverified' if good else 'geometry_failed',label='R1 · 几何门通过 · 待人工核对' if good else f'R{r:g} · 自交无效候选',reason=reason,
                mesh=mesh(run/'result.mesh.json'),before_mesh=base_mesh,version='7.9.3',method='native_ordinary_fillet',method_label='OCC 原生普通边圆角',summary=(dest/'summary.json').relative_to(WEB).as_posix(),
                evidence_kind='fresh_run',outcome=a['status'],api_success=a['native_done'],source_feature_passed=False,source_sha256=contract['source_sha256'],operation_input_sha256=contract['source_sha256'],
                source_revision_contract={'path':'data/case11-convexity/revision.json','sha256':digest(CONTRACT)},
                raw_summary_sha256=digest(run/'attempt.json'),published_summary_sha256=digest(dest/'summary.json'),parameters=parameters,processing_steps=steps,
                metrics={'requested_radius_mm':r,'native_done':a['native_done'],'brep_bop_passed':a['inspection']['passed'],'manifold_passed':a['manifold_audit']['passed'],'step_readback_passed':a['step']['readback']['passed'],'source_repair_fa_X_verified':False,'human_appearance_passed':False},
                checks={'inspection':a['inspection'],'manifold':a['manifold_audit']['passed'],'step_readback':a['step']['readback']['passed']},files=[f for f in files if f],
                reproduce=f'python adapters/occt/case11-convexity/build.py --revision candidate-v6 --output runs/replay-case11-convex')
        v=dict(id=vid,label=f'凸性修正版 · R{r:g} · '+('几何门通过' if good else '自交挑战'),radius_mm=r,method='native_ordinary_fillet',method_label='原生普通圆角 · 修正版输入',parameters=parameters,
               base_brep=contract['source_brep'],base_brep_url=source_file['path'],base_sha256=contract['source_sha256'],base_mesh=base_mesh,operation_mesh=base_mesh,input_mesh=base_mesh,
               base_targets=contract['target_world'],operation_targets=contract['target_world'],targets=contract['target_world'],selected_faces=[],human_status='pending',human_note='',
               scope_note='凸性修正版候选；原图未给定尺寸和隐藏结构，整体外观待人工核对。仅测试普通共边圆角，未验证repair_fa_X专用修复。',
               preparation_note='真实笛卡尔坐标实体；不对模型做仿射剪切。已有窄带属于基础输入，不是本次生成的主圆角。',
               input_relation='same_as_base',operation_is_derived=False,operation_relation_note='直接使用本轮重建的凸性修正版输入；基础与操作输入为同一BREP。',
               revision_id=contract['id'],evidence_kind='fresh_run',processing_steps=steps,occt=oc)
        if r in sdk_rows:
            row=sdk_rows[r];job_path=ROOT/f'data/case11-convexity/smlib-candidate-v6-{rid}.job.json'
            sm=from_completion(dict(summary=row['summary'],request_path=job_path),case,v)
            status=row['review_status'];good_sdk=status=='native_candidate_pending_independent_quality_and_visual_acceptance'
            sm.update(request_file=job_path.relative_to(ROOT).as_posix(),source_revision_contract={'path':'data/case11-convexity/revision.json','sha256':digest(CONTRACT)},
                      review_status=status,api_success=read(ROOT/row['summary']).get('execution',{}).get('native_api_success'),
                      unchanged_input=row['retained_native_file_identical_to_before'],
                      checks={'input_import':row['import_passed'],'native_readback':row['native_readback_passed'],'full_quality_passed':False,'human_appearance_passed':False},
                      status='candidate_unverified' if good_sdk else 'api_failed' if 'api_failed' in status else 'geometry_failed',
                      reason=(f'新凸性输入上实际 R{r:g}：输入导入、原生结果类型与SMB回读门通过，完整独立几何和人工外观仍待核对。' if good_sdk else
                              f'新凸性输入上实际 R{r:g}：{status}；API返回{row["native_api_raw_status"]}。'+('保留的SMB与输入字节相同，不能视为圆角。' if row['retained_native_file_identical_to_before'] else '保留实际失败候选；类型或回读门未通过，不能视为有效圆角。')))
            v['smlib']=sm
        else:
            v['smlib']=cached_sdk(old,contract,vid,r) or {'status':'not_run','label':'新版输入尚无SDK结果','reason':'旧SDK输入凹凸错误，不能复用；等待本轮新输入实跑。','mesh':None,'before_mesh':None,'source_feature_passed':False,'pairing_status':'no_comparable_run','evidence_kind':'not_run'}
        case['variants'].append(v)
    return case

def main(occ_run=None):
    selected_run = pathlib.Path(occ_run).resolve() if occ_run is not None else _OCC_OVERRIDE
    if not CONTRACT.exists() or not CASE.exists():
        if selected_run is not None: raise ValueError('Case11 suite publication requires the registered revision and published base case')
        return
    contract=read(CONTRACT)
    if digest(ROOT/contract['source_brep'])!=contract['source_sha256'] or digest(ROOT/contract['geometry_audit']['path'])!=contract['geometry_audit']['sha256']:
        raise ValueError('case11 revision contract lineage mismatch')
    if selected_run is not None: contract=bind_occ_run(contract,selected_run)
    actual_occ = selected_run if selected_run is not None else OCC
    old=read(CASE);snapshot=PUBLIC/'published-case.json';legacy=PUBLIC/'legacy-concave-case.json'
    if old['source_sha256']==contract['previous_source_sha256'] and not legacy.exists():
        archived=copy.deepcopy(old);archived['source_quality_warning']='历史输入重建的凹凸性错误；仅保存旧证据，不再代表第11项原图。';archived['superseded_by']=contract['id'];write(legacy,archived)
    if (actual_occ/'report.json').exists():
        case=build_case(old,contract,actual_occ);write(snapshot,{'contract_sha256':digest(CONTRACT),'case':case})
    elif snapshot.exists():
        saved=read(snapshot)
        if saved['contract_sha256']!=digest(CONTRACT):raise ValueError('case11 cached revision stale')
        case=saved['case']
        for v in case['variants']:
            for engine in ['occt','smlib']:
                result=v[engine]
                if result.get('summary') and digest(WEB/result['summary'])!=result['published_summary_sha256']:raise ValueError('case11 cached summary changed')
    else:raise ValueError('case11 revision has no actual evidence snapshot')
    write(CASE,case)
    # The independent ordinary collection retains the old bytes as historical evidence.
    for p in [ROOT/'data/cases/11.json',WEB/'data/cases/11.json']:
        history=read(p);history['source_quality_warning']='旧版第11项输入凹凸性与原图不符；此处仅保留历史实验。请切换“原版OCC人工核对系列”查看凸性修正版。';history['superseded_by']=contract['id']
        if p == ROOT/'data/cases/11.json':p.write_text(json.dumps(history,ensure_ascii=False,indent=2)+'\n')
        else:write(p,history)
    catalog_path=WEB/'data/original-occ/catalog.json';catalog=read(catalog_path);counter=collections.Counter();pairing=collections.Counter();total=0
    for row in catalog['cases']:
        c=read(WEB/row['data']);row['variant_count']=len(c['variants']);row['default_variant']=c['default_variant'];total+=len(c['variants'])
        if row['number']==11:row.update(title=c['title'],source_sha256=c['source_sha256'],revision_id=contract['id'])
        for v in c['variants']:
            counter[v['occt']['evidence_kind']]+=1;counter['status:'+v['occt']['status']]+=1
            sm=v.get('smlib',{});pairing[sm.get('pairing_status','unknown')]+=1;pairing['evidence:'+sm.get('evidence_kind','unknown')]+=1
    catalog['counts']={'cases':len(catalog['cases']),'models':34,'variants':total,**dict(counter)};catalog['smlib_pairing']['counts']=dict(pairing)
    catalog['active_input_revisions']={'11':{'id':contract['id'],'source_sha256':contract['source_sha256'],'previous_source_sha256':contract['previous_source_sha256'],'human_status':'pending'}}
    write(catalog_path,catalog);print('case11: convex-v6 source and fresh results published; old concave results quarantined; human review pending')

if __name__=='__main__':main()
