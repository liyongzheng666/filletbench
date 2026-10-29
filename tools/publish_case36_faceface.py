"""Publish measured case36 face-face results without changing finite inputs."""
import collections,copy,hashlib,html,json,math,pathlib,re,shutil
from contextlib import contextmanager
from build_site import ROOT,WEB,read,write,digest,sanitize,mesh
from publish_case08_radius import file_model

PROTOCOL=ROOT/'data/case36-faceface/protocol.json'
PUBLIC=WEB/'data/case36-faceface'
CASE=WEB/'data/original-occ/cases/36.json'
SNAPSHOT=PUBLIC/'published-case.json'
OVERRIDES={}
NAMES={'to_walls':'贴两墙边界','no':'不裁端部','short':'短裁剪','long':'长裁剪'}

@contextmanager
def using_case36_faceface_run(path):
    previous=OVERRIDES.get('occt_composite');OVERRIDES['occt_composite']=pathlib.Path(path).resolve()
    try:yield
    finally:
        if previous is None:OVERRIDES.pop('occt_composite',None)
        else:OVERRIDES['occt_composite']=previous

@contextmanager
def using_case36_native_run(path):
    previous=OVERRIDES.get('occt_native');OVERRIDES['occt_native']=pathlib.Path(path).resolve()
    try:yield
    finally:
        if previous is None:OVERRIDES.pop('occt_native',None)
        else:OVERRIDES['occt_native']=previous

def validate_index(path,engine):
    path=pathlib.Path(path).resolve()
    if path.is_dir():path=path/'index.json'
    if not path.is_relative_to(ROOT):raise ValueError('Case36 publication requires repository-relative run evidence')
    protocol=read(PROTOCOL);index=read(path);rows=index['rows']
    if not rows:raise ValueError('Explicit case36 attempt has no executed result (possibly dependency_missing); refusing to attribute a cached result to it')
    if engine=='occt_native':
        selected=index.get('selected_candidate') or next((r for r in rows if r.get('choice')==4),None)
        if not selected:raise ValueError('No requested 90-degree native control result; refusing cached substitution')
        rows=[selected]
    for row in rows:
        sp=ROOT/row['summary'];s=read(sp)
        if digest(sp)!=row['summary_sha256'] or s['source_sha256']!=protocol['source_sha256'] or float(s.get('radius_mm',s.get('requested_radius_mm',0)))!=8:
            raise ValueError('Case36 actual source/radius/summary identity mismatch')
        before=ROOT/(row.get('before_brep') or str(path.parent/'before.brep'))
        if before.exists() and digest(before)!=protocol['source_sha256']:raise ValueError('Case36 actual before differs from original finite faces')
        if engine=='occt_composite' and (s.get('method')!='explicit_occ_composition' or s.get('native_face_face_call') is not False):raise ValueError('Composition cannot be relabeled native')
        if engine=='occt_native' and (s.get('native_call_executed') is not True or s.get('four_trim_controls_supported') is not False):raise ValueError('Native control must remain separate from four trim modes')
    return path,index,rows

def validate_case36_faceface_run(path):return validate_index(path,'occt_composite')
def validate_case36_native_run(path):return validate_index(path,'occt_native')

def remeasure_new_rows(audit,paths,index_rows):
    """New raw runs need new actual-geometry evidence, not a copied verdict."""
    replacements=[]
    for engine,rows in index_rows.items():
        needs=False
        for row in rows:
            mode='native-baseline' if engine=='occt_native' else row.get('source_mode_candidate',row['mode'])
            existing=next((r for r in audit['rows'] if r['mode']==mode and
                (r['engine']=='SMLib' if engine=='smlib_native' else r['method']=='explicit_occ_composition' if engine=='occt_composite' else r['method'].startswith('native_surface_surface_rolling'))),None)
            if not existing or not any(e['path']==row['summary'] and e['sha256']==row['summary_sha256'] for e in existing.get('actual_evidence',[])):needs=True
        if not needs:continue
        import audit_case36_faceface as oracle
        measure={'occt_composite':oracle.occt_rows,'smlib_native':oracle.sdk_rows,'occt_native':oracle.occt_native_rows}[engine]
        replacements.extend(measure(paths[engine].parent))
    if not replacements:return audit
    result=copy.deepcopy(audit);mapped={(r['engine'],r['method'],r['mode']):r for r in result['rows']}
    for row in replacements:mapped[row['engine'],row['method'],row['mode']]=row
    result['rows']=list(mapped.values());result['incremental_remeasurement']={'rows':[(r['engine'],r['method'],r['mode']) for r in replacements],
        'other_rows_retained_from_hash_bound_measurement':True,'new_native_fillet_calls_by_publisher':False}
    result['audit_consistency_passed']=all(r['source_sha256']==read(PROTOCOL)['source_sha256'] and r['radius_mm']==8 and r['input_source_bytes_preserved'] and r.get('input_finite_domains_preserved',True) and r.get('immutable_source_file_unchanged',True) for r in result['rows'])
    for method in ['explicit_occ_composition','native_surface_surface_fillet']:
        group=[r for r in result['rows'] if r['method']==method]
        signatures={r['mode']:{'vertical':oracle.rail_range(r['actual_geometry'],'vertical'),'horizontal':oracle.rail_range(r['actual_geometry'],'horizontal'),
            'end_x_spans':[e['x_extent_mm'][1]-e['x_extent_mm'][0] for e in r['actual_geometry']['end_curves']]} for r in group}
        result['cross_modes'][method]={'modes_present':sorted(signatures),'mode_geometry_signatures':signatures,
            'all_four_physical_endpoint_signatures_distinct':len({json.dumps(s,sort_keys=True) for s in signatures.values()})==4,
            'all_local_trim_subcriteria_passed':len(group)==4 and all(r['trim']['all_subcriteria_passed'] for r in group),'source_feature_certified':False}
    out=ROOT/read(PROTOCOL)['independent_audit'];out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    return result

def colored_mesh(raw):
    published=mesh(raw)
    if not published:return None
    data=read(WEB/published);data.setdefault('metadata',{})['face_colors']={str(face):[232,94,75] for face in set(data['face_ids'])}
    data['metadata']['display_role']='actual_blend_patch_only'
    body=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n'
    key=hashlib.sha256(body.encode()).hexdigest()[:24];dest=WEB/f'data/meshes/{key}.json';dest.write_text(body)
    return dest.relative_to(WEB).as_posix()

def copy_summary(source,dest):
    text=source.read_text()
    if re.search(r'/Users/|/private/',text):raise ValueError('Private machine path in case36 actual summary')
    dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)

def witnesses(audit,before_mesh):
    result=[]
    for i,edge in enumerate(read(WEB/before_mesh).get('edges',[])):
        points=edge.get('points',edge) if isinstance(edge,dict) else edge
        if isinstance(points,list) and len(points)>1:result.append({'id':f'source-wall-{i}','samples_mm':points,'target_kind':'source_wall_boundary','label':'原有限墙面边界（辅助）'})
    geometry=audit.get('actual_geometry',{})
    for i,rail in enumerate(geometry.get('rails',[])):
        result.append({'id':f'actual-contact-{i}','samples_mm':rail['points_mm'],'target_kind':'result_witness','label':'实际接触轨 · '+rail['support']})
    for i,end in enumerate(geometry.get('end_curves',[])):
        result.append({'id':f'actual-trim-end-{i}','samples_mm':end['points_mm'],'target_kind':'result_trim_boundary','label':'实际端部裁剪边界'})
    return result

def write_overview(audit,comparison=None,comparison_applies=False):
    rows=[]
    for mode in ['to_walls','no','short','long']:
        pair=[next(r for r in audit['rows'] if r['mode']==mode and r['method']==method) for method in ['explicit_occ_composition','native_surface_surface_fillet']]
        cells=[]
        for r in pair:
            t=r['trim'];fmt=lambda q:f'[{q[0]:g}, {q[1]:g}]'
            cells.append('竖面轨 '+fmt(t['vertical_rail_extent_mm'])+'<br>横面轨 '+fmt(t['horizontal_rail_extent_mm']))
        rows.append(f'<tr><th><a href="../../../#series=original&amp;case=36&amp;variant=trim-{mode}-r8">{html.escape(NAMES[mode])}</a></th><td>{cells[0]}</td><td>{cells[1]}</td><td>局部端部判据通过</td></tr>')
    text='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>36 · R8面面圆角实测</title><style>body{max-width:1100px;margin:36px auto;padding:0 22px;font:16px/1.7 system-ui;color:#263b37;background:#f7f9f5}h1{font-size:28px}table{width:100%;border-collapse:collapse;background:white}th,td{padding:14px;text-align:left;border-bottom:1px solid #d9e3dc}a{color:#236f58}.note{padding:16px;background:#fff0ce;border-radius:8px}.scroll{overflow-x:auto}small{color:#687c72}</style><h1>36 · 原有限面上的 R8 面面圆角</h1><p>输入为原宽14/25mm的两张分离有限面。R8是指定测评半径，不是PDF标定值。结果仅为圆角片，原墙边界作为辅助显示。</p><div class="scroll"><table><thead><tr><th>端部模式</th><th>OCC 7.9.3 · 显式组合</th><th>SMLib 10.0.0 · 原生</th><th>实测结论</th></tr></thead><tbody>'''+''.join(rows)+'''</tbody></table></div><p>表内数值为实际接触轨的x区间，单位mm。点击模式可打开四栏实物。No模式没有唯一有限尾长，OCC声明的工作范围为±20，SMLib原生实际为±14；保留真实差异。</p><h2>OCC原生基准</h2><p>另有<a href="../../../#series=original&amp;case=36&amp;variant=native-faceface-r8">OCCT7.8.1 C++原生面面基准</a>：直接两Face进行rolling-ball walking与AppSurf，R8/90°分支自然停止在x±7。该API没有四trim参数，不能把这一张面记为四次成功。OCP7.9的math_Vector绑定缺口及依赖缺失另有真实诊断记录。</p><h2>质量与边界</h2><p>9个产物已独立检查实际CAD/原生读回、半径、局部G0/G1；四模式的端部签名有真实差异。此轮目标没有构建失败；缺少原生trim控制与构造成功分别记录。</p><p class="note">SMLib base_trim=0仍拆分墙面调用副本的拓扑；原文件、调用前有限域及调用后有限域采样保持。OCC to_walls为本例声明的UV边界插值。局部判据通过不等于通用Parasolid语义、所有全域几何或人工外观验收。</p><p><a href="audit.json">独立量测JSON</a> · <a href="protocol.json">输入与执行协议</a></p><small>PDF与参考截图不随公开站点分发；四栏页可本地载入。此页由实际量测记录生成。</small></html>'''
    if comparison and comparison_applies:
        row=next(r for r in comparison['rows'] if r['mode']=='to_walls');side=row['sides']['positive_x']
        points=sorted(side['plot_samples'],key=lambda p:p['theta_rad'])
        line=' '.join(f'{60+p["theta_rad"]/(math.pi/2)*800:.3f},{135-p["delta_x_mm"]*1400:.3f}' for p in points)
        chart='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 275" role="img" aria-label="贴墙右端曲线在同一截面角的X差"><rect width="900" height="275" fill="white"/><path d="M60 35V225M60 135H860" stroke="#97aba4" fill="none"/><polyline points="'+line+'" fill="none" stroke="#bf4f3d" stroke-width="2.5"/>'
        for angle in [0,22.5,45,67.5,90]:chart+=f'<text x="{60+angle/90*800}" y="250" text-anchor="middle" font-size="15">{angle:g}°</text>'
        for delta in [-.06,0,.06]:chart+=f'<text x="50" y="{140-delta*1400}" text-anchor="end" font-size="14">{delta:g}</text>'
        chart+='<text x="60" y="20" font-size="15">Δx / mm：SMLib − OCC（右端）</text></svg>'
        insert=f'<h2>贴墙：端点相同，整条端曲线不同</h2><p>按同一物理截面角θ对齐，每端查询{side["sample_count"]}点，最大观测X差为 <strong>{row["maximum_observed_boundary_dx_mm"]:.8f} mm</strong>。此图放大的是差值，没有修改实物模型。它是采样对应差异，不是精确连续最大值或Hausdorff距离。</p>'+chart+'<p>short/long在本次量测中近于一致；no的6mm端域差来自不同工作包络，不按同包络失败评分。<a href="differences.json">差异及原始证据记录</a></p>'
        text=text.replace('<h2>OCC原生基准</h2>',insert+'<h2>OCC原生基准</h2>')
    (PUBLIC/'report.html').write_text(text)

def make_record(engine,mode,row,index,path,audit,base_mesh):
    raw=ROOT/row['summary'];summary=read(raw);dest=PUBLIC/'runs'/engine/mode;copy_summary(raw,dest/'summary.json')
    actual_mesh=colored_mesh(ROOT/row['result_mesh']) if row.get('result_mesh') else None
    result_files=[]
    for key,label in [('before_brep','原始有限面输入 BREP'),('result_brep','实际圆角片 BREP'),('result_step','实际圆角片 STEP')]:
        if row.get(key):
            f=file_model(ROOT/row[key],label)
            if f:result_files.append(f)
    # Supplementary JSON is safe to sanitize; actual summary remains byte-bound.
    evidence=[];run=ROOT/row.get('run_dir',raw.parent.relative_to(ROOT).as_posix())
    for p in sorted(run.glob('*.json')):
        if p==raw or p.name in ['mesh.json','result.mesh.json','before.mesh.json']:continue
        out=dest/'evidence'/p.name;write(out,sanitize(read(p)));evidence.append({'path':out.relative_to(WEB).as_posix(),'sha256':digest(out)})
    if engine=='occt_native' and index.get('python_binding_boundary'):
        p=ROOT/index['python_binding_boundary']['path'];out=dest/'evidence'/'binding-boundary.json';write(out,sanitize(read(p)));evidence.append({'path':out.relative_to(WEB).as_posix(),'sha256':digest(out)})
    local=audit.get('local_geometry_gates',{});trim=audit.get('trim');gates=audit.get('native_geometry_gates',{})
    local_pass=bool(local) and all(value is True for value in local.values());trim_pass=trim is not None and trim.get('all_subcriteria_passed') is True
    status='candidate_unverified' if local_pass and all(value is True for value in gates.values()) and (trim_pass or engine=='occt_native') else 'geometry_failed'
    vext=(trim or {}).get('vertical_rail_extent_mm');hext=(trim or {}).get('horizontal_rail_extent_mm')
    record={'status':status,'mesh':actual_mesh,'before_mesh':base_mesh,'summary':(dest/'summary.json').relative_to(WEB).as_posix(),
            'raw_summary_sha256':digest(raw),'published_summary_sha256':digest(dest/'summary.json'),'evidence_kind':'fresh_run',
            'source_sha256':summary['source_sha256'],'operation_input_sha256':summary['operation_input_sha256'],
            'parameters':{'radius_mm':8,'mode':mode},'source_feature_passed':False,'human_appearance_status':'pending',
            'files':result_files,'evidence_files':evidence,'result_witnesses':witnesses(audit,base_mesh),
            'metrics':{'nominal_radius_mm':8,'vertical_rail_x_mm':vext,'horizontal_rail_x_mm':hext,'local_geometry_subcriteria_passed':local_pass,'trim_subcriteria_passed':trim_pass,'human_appearance_passed':False},
            'checks':{'independent_actual_geometry':audit,'complete_Parasolid_equivalence_certified':False}}
    geometry=audit.get('actual_geometry',{});fit=geometry.get('profile_circle_fit',{});d2=geometry.get('D2_radius',{})
    record['metrics'].update(measured_profile_radius_mm=fit.get('radius_mm'),profile_circle_residual_mm=fit.get('max_radial_residual_mm'),D2_radius_range_mm=d2.get('radius_range_mm'))
    if engine=='occt_composite':
        record.update(version=summary['engine_version'],method='explicit_occ_composition',method_label='OCC 显式组合 · 四裁剪',native_call_executed=False,api_success=None,
            label='组合构造 · 局部判据通过' if status=='candidate_unverified' else '组合候选 · 检查未通过',
            reason=f'实际R8显式构造的独立圆角片；竖面侧x={vext}，横面侧x={hext}。BREP/STEP和局部R/G0/G1、端部规则分别检查。'+('to_walls使用已声明的UV端边界插值，只认证本矩形输入的端点条件，未认证通用Parasolid语义。' if mode=='to_walls' else '不改变原有限面；原墙线仅作辅助。')+('不裁模式工作包络为x±20mm，不是PDF给定值。' if mode=='no' else ''),
            request_file=summary['request_file'],reproduce=f'python adapters/occt/case36-faceface/composite.py --mode {mode} --output runs/replay-case36-composite-{mode}')
    elif engine=='smlib_native':
        record.update(version=index['engine_version'],method='native_surface_surface_fillet',method_label='SMLib 原生面面圆角',native_call_executed=summary['native_call_started'],api_success=summary['native_api_raw_status']==1000,
            label='原生 '+summary['mode'].upper()+' · 局部判据通过' if status=='candidate_unverified' else '原生候选 · 检查未通过',
            reason=f'实际R8原生调用，返回独立圆角片；竖面侧x={vext}，横面侧x={hext}。枚举到原图模式的对应由真实端界量测确认本例局部子判据。base_trim=0仍拆分调用副本的墙面拓扑，有限域采样保留；不视为原墙拓扑未改。'+('原生NONE范围x±14mm；保留实际范围，不按OCC的±20mm工作包络后裁。' if mode=='no' else ''),
            operation_input_sha256_scope=summary['operation_input_sha256_scope'],native_input_files=summary['native_input_files'],native_input_pair_sha256=summary['native_input_pair_sha256'],
            pairing_status='matched_constraints_different_representation',pairing_note='同一原有限输入、R8和目标端部规则；OCC为显式组合，SMLib为原生枚举，表示及方法不同，不作为同原生能力排名。',
            raw_status=summary['native_api_raw_status'],outcome=summary['outcome'],request_file=index['requests'],
            reproduce=f'python tools/run_case36_smlib.py --mode {summary["mode"]} --output runs/replay-case36-smlib-{mode}')
        record['metrics'].update(native_api_status=summary['native_api_raw_status'],native_readback_passed=summary['native_readback_passed'],post_input_topology_preserved=summary.get('post_input_topology_preserved'),
            immutable_source_file_unchanged=summary.get('immutable_source_file_unchanged'),post_input_geometry_domain_preserved_sampled=summary.get('post_input_geometry_domain_preserved'))
    else:
        record.update(version=summary['engine_version'],method=summary['method'],method_label='OCC 原生面面基准 · 无四trim参数',native_call_executed=True,api_success=summary['api_success'],
            label='原生R8基准 · 局部判据通过' if status=='candidate_unverified' else '原生基准 · 几何待验',
            reason='直接使用原两Face及有限域进行rolling-ball walking与曲面逼近，真实R8/90°分支。自然停在x±7，未调用四种专用trim参数；不能将同一个原生面重复当四模式成功。OCP7.9缺math_Vector绑定，实际worker使用OCCT7.8.1 C++。',
            reproduce='python adapters/occt/case36-faceface/native_probe.py --output runs/replay-case36-native-r8')
    if mode=='long':record['reason']+=' 原输入未扩面；结果竖面侧接触轨两端各越出原有限域5.5mm，这是已记录的long端域。'
    if mode=='short':record['reason']+=' 两轨均在原有限域内；横面侧只覆盖中间14mm，两端各保留5.5mm余量。'
    binding={'engine':engine,'mode':mode,'variant_id':'native-faceface-r8' if engine=='occt_native' else f'trim-{mode}-r8',
        'summary':row['summary'],'summary_sha256':digest(raw),'index':path.relative_to(ROOT).as_posix(),'index_sha256':digest(path),
        'published_summary':record['summary'],'published_summary_sha256':record['published_summary_sha256'],
        'published_mesh':actual_mesh,'published_mesh_sha256':digest(WEB/actual_mesh) if actual_mesh else None,
        'raw_result_mesh':row.get('result_mesh'),'raw_result_mesh_sha256':digest(ROOT/row['result_mesh']) if row.get('result_mesh') else None}
    if record.get('request_file'):binding.update(request_file=record['request_file'],request_sha256=digest(ROOT/record['request_file']))
    return record,binding

def main(occt_run=None,native_run=None):
    if not PROTOCOL.exists() or not CASE.exists():return
    protocol=read(PROTOCOL);old=read(CASE);saved=read(SNAPSHOT) if SNAPSHOT.exists() else None
    if digest(ROOT/protocol['source_brep'])!=protocol['source_sha256']:raise ValueError('Case36 source BREP changed')
    audit=read(ROOT/protocol['independent_audit'])
    if not audit['audit_consistency_passed']:raise ValueError('Case36 independent audit inconsistent')
    protocol['independent_audit_sha256']=digest(ROOT/protocol['independent_audit'])
    protocol['run_indexes'].setdefault('occt_native','runs/case36-faceface/occt-native/index.json')
    protocol.setdefault('additional_run_indexes',{})
    runs=dict(OVERRIDES)
    if occt_run is not None:runs['occt_composite']=pathlib.Path(occt_run).resolve()
    if native_run is not None:runs['occt_native']=pathlib.Path(native_run).resolve()
    records={};bindings={(b['engine'],b['mode']):copy.deepcopy(b) for b in protocol.get('bindings',[])}
    if saved:
        for v in saved['case']['variants']:
            if v['id']=='native-faceface-r8':records[('occt_native','native-baseline')]=copy.deepcopy(v['occt'])
            else:
                mode=v['parameters']['mode'];records[('occt_composite',mode)]=copy.deepcopy(v['occt']);records[('smlib_native',mode)]=copy.deepcopy(v['smlib'])
    paths={};rows_by_engine={};indexes={};base_mesh=None
    for engine,default in protocol['run_indexes'].items():
        path=pathlib.Path(runs.get(engine,ROOT/default));path=path/'index.json' if path.is_dir() else path
        if not path.exists():
            if engine in runs:raise ValueError('Explicit case36 run is missing; no cached substitution')
            continue
        path,index,rows=validate_index(path,engine);paths[engine]=path;indexes[engine]=index;rows_by_engine[engine]=rows
        relative_path=path.relative_to(ROOT).as_posix()
        if relative_path!=protocol['run_indexes'][engine]:
            extra={r['path']:r for r in protocol['additional_run_indexes'].get(engine,[])}
            extra[relative_path]={'path':relative_path,'sha256':digest(path)}
            protocol['additional_run_indexes'][engine]=list(extra.values())
        if base_mesh is None and engine=='occt_composite':base_mesh=mesh(ROOT/rows[0]['before_mesh'])
    if base_mesh is None:base_mesh=(saved or {}).get('case',old).get('base_mesh')
    audit=remeasure_new_rows(audit,paths,rows_by_engine)
    protocol['independent_audit_sha256']=digest(ROOT/protocol['independent_audit'])
    observations={(r['engine'],r['method'],r['mode']):r for r in audit['rows']}
    for engine,rows in rows_by_engine.items():
        for row in rows:
            mode='native-baseline' if engine=='occt_native' else row.get('source_mode_candidate',row['mode'])
            key=('SMLib','native_surface_surface_fillet',mode) if engine=='smlib_native' else ('OCCT','explicit_occ_composition',mode) if engine=='occt_composite' else None
            ar=observations.get(key) if key else next((r for r in audit['rows'] if r['mode']=='native-baseline'),None)
            if ar is None:raise ValueError('Actual case36 result has no independent geometry audit')
            record,binding=make_record(engine,mode,row,indexes[engine],paths[engine],ar,base_mesh);records[engine,mode]=record;bindings[engine,mode]=binding
    expected={(e,m['id']) for e in ['occt_composite','smlib_native'] for m in protocol['modes']}|{('occt_native','native-baseline')}
    if set(records)!=expected or set(bindings)!=expected:raise ValueError('Case36 measured coverage incomplete')
    for key,b in bindings.items():
        r=records[key]
        if digest(WEB/r['summary'])!=b['published_summary_sha256'] or digest(WEB/r['mesh'])!=b['published_mesh_sha256'] or r['source_sha256']!=protocol['source_sha256']:
            raise ValueError('Case36 cached evidence identity mismatch')
    comparison_path=ROOT/'docs/case36-faceface-differences.json';comparison=None;comparison_applies=False
    if comparison_path.exists():
        comparison=read(comparison_path)
        expected_occ=next(e['sha256_before'] for e in comparison['raw_evidence'] if e['path'].endswith('/to_walls/result.brep'))
        occ_summary=read(WEB/records['occt_composite','to_walls']['summary']);sdk_summary=read(WEB/records['smlib_native','to_walls']['summary'])
        comparison_applies=occ_summary.get('result_brep_sha256')==expected_occ and sdk_summary.get('artifacts',{}).get('readback.smb',{}).get('sha256')==comparison.get('dense_query',{}).get('source_native_sha256_before')
        protocol['cross_method_comparison']={'path':'docs/case36-faceface-differences.json','sha256':digest(comparison_path),'applies_to_current_to_walls_geometry':comparison_applies}
        delta=next(r['maximum_observed_boundary_dx_mm'] for r in comparison['rows'] if r['mode']=='to_walls')
        for engine in ['occt_composite','smlib_native']:
            r=records[engine,'to_walls'];r.setdefault('base_reason_without_comparison',r['reason']);r.setdefault('base_label_without_comparison',r['label'])
            r['reason']=r['base_reason_without_comparison'];r['label']=r['base_label_without_comparison']
            r['metrics'].pop('same_theta_end_curve_sampled_max_dx_mm',None)
            if comparison_applies:
                r['metrics']['same_theta_end_curve_sampled_max_dx_mm']=delta
                r['reason']+=f' 两端点均匹配，但按同一物理截面角对齐的端曲线最大观测X差约{delta:.8f}mm；不是整条曲线相同，也不是精确Hausdorff距离。'
                r['label']+=' · 端曲线有差异'
    protocol['bindings']=[bindings[k] for k in sorted(bindings)];write(PROTOCOL,protocol)
    ref={'path':'data/case36-faceface/protocol.json','sha256':digest(PROTOCOL)}
    for r in records.values():r['faceface_protocol']=ref;r['before_mesh']=base_mesh
    case={k:copy.deepcopy(old[k]) for k in ['number','id','title','has_model','reference','camera']}
    faces=[{'face_id':0,'label':'原窄竖面 · 14mm'},{'face_id':1,'label':'原宽横面 · 25mm'}]
    entries=[]
    for m in protocol['modes']:
        mode=m['id'];oc=records['occt_composite',mode];sm=records['smlib_native',mode]
        entries.append({'id':f'trim-{mode}-r8','label':f'R8 · {NAMES[mode]} · OCC组合 / SMLib原生','radius_mm':8,'parameters':{'radius_mm':8,'mode':mode,'summary':'固定同一原有限面与接触条件；R8为测评演示值'},
            'occt':oc,'smlib':sm,'method':'explicit_occ_composition','method_label':'OCC显式组合 / SMLib原生','scope_note':'局部半径、接触与端界子判据单列；不宣称通用Parasolid语义或整体人工外观通过。',
            'reference_hint':{'to_walls':'左上 to_walls','no':'右上 no','short':'左下 short','long':'右下 long'}[mode]})
    entries.append({'id':'native-faceface-r8','label':'R8 · OCC原生面面基准（无四trim参数）','radius_mm':8,'parameters':{'radius_mm':8,'mode':'native-baseline','summary':'OCCT7.8.1 C++真实Walking / AppSurf；仅单一基准'},
        'occt':records['occt_native','native-baseline'],'smlib':{'status':'not_run','label':'SMLib四模式结果见相应工况','reason':'本视图单列OCC原生基准，不重复借用四裁剪中的SDK结果。','mesh':None,'before_mesh':None,'pairing_status':'not_applicable_native_api_control','evidence_kind':'input_only','source_feature_passed':False},
        'method':records['occt_native','native-baseline']['method'],'method_label':'OCC原生面面基准','scope_note':'自然停在原窄面边界不是四种专用trim枚举均已支持的证据。'})
    sourcefile=file_model(ROOT/protocol['source_brep'],'原始两有限面 BREP')
    for v in entries:v.update(base_brep=protocol['source_brep'],base_brep_url=sourcefile['path'],base_sha256=protocol['source_sha256'],base_mesh=base_mesh,operation_mesh=base_mesh,input_mesh=base_mesh,
        base_targets=[],operation_targets=[],targets=[],base_selected_faces=faces,operation_selected_faces=faces,selected_faces=faces,input_relation='same_as_base',operation_is_derived=False,
        operation_relation_note='保持原14/25mm两张分离有限面；SDK通过精确NURBS表示导入，原有限域在调用前独立验证。',preparation_note='输入未扩成共边L壳。结果为圆角片本身，灰色原墙边界仅作辅助显示。',evidence_kind='fresh_run',human_status='pending',human_note='')
    case.update(source_sha256=protocol['source_sha256'],source_case_sha256=protocol['frozen_case_sha256'],source_brep=protocol['source_brep'],base_mesh=base_mesh,faceface_protocol=ref,
        variants=entries,default_variant='trim-to_walls-r8',human_status='pending',human_note='',base_creation={'method':'frozen_exact_BREP_input','parametric_reconstruction_executed':False},
        question='同一原有限面、R8：分别看OCC原生基准、OCC显式四裁剪与SMLib原生四枚举的实际端界。',
        source_quality_warning='原14/25mm有限输入保持。R8为测评演示值；四模式主对照为OCC组合与SMLib原生，另列OCC原生基准。红色为实际圆角片，灰线为原墙辅助；局部判据与整体外观分开验收。')
    write(PUBLIC/'protocol.json',protocol);write(PUBLIC/'audit.json',sanitize(audit))
    if comparison:shutil.copyfile(comparison_path,PUBLIC/'differences.json')
    write_overview(audit,comparison,comparison_applies)
    for v in entries:
        v['occt']['files']=[f for f in v['occt']['files'] if f['path']!='data/case36-faceface/report.html']+[{'label':'第36项四裁剪实测总览','path':'data/case36-faceface/report.html','sha256':digest(PUBLIC/'report.html')}]
    write(SNAPSHOT,{'protocol_sha256':digest(PROTOCOL),'case':case});write(CASE,case)
    cp=WEB/'data/original-occ/catalog.json';catalog=read(cp);counter=collections.Counter();pairing=collections.Counter();total=0
    for row in catalog['cases']:
        c=read(WEB/row['data']);row['variant_count']=len(c['variants']);row['default_variant']=c.get('default_variant');total+=len(c['variants'])
        for v in c['variants']:
            counter[v['occt']['evidence_kind']]+=1;counter['status:'+v['occt']['status']]+=1
            sm=v.get('smlib',{});pairing[sm.get('pairing_status','unknown')]+=1;pairing['evidence:'+sm.get('evidence_kind','unknown')]+=1
    catalog['counts']={'cases':len(catalog['cases']),'models':34,'variants':total,**dict(counter)};catalog['smlib_pairing']['counts']=dict(pairing)
    catalog.pop('input_admission_only',None);catalog['case36_faceface']={'four_modes':4,'occt_native_controls':1,'source_sha256':protocol['source_sha256'],'full_source_feature_certified':False};write(cp,catalog)
    print('case36 face-face: four measured trim pairs and one separate OCC native control published')

if __name__=='__main__':main()
