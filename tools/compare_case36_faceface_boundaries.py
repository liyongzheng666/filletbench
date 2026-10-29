"""Read-only, same-physical-section comparison of actual case36 end curves."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,math,subprocess,sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from audit_case36_faceface import read_brep,shapes,sha
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.TopAbs import TopAbs_EDGE
from OCP.TopoDS import TopoDS

def xyz(p):return [p.X(),p.Y(),p.Z()]
def theta(p):return math.atan2(8-p[2],8-p[1])
def ranges(points):return [min(p[0] for p in points),max(p[0] for p in points)]
def occ_end_curves(path):
    out={}
    for edge in shapes(read_brep(path),TopAbs_EDGE):
        curve=BRepAdaptor_Curve(TopoDS.Edge_s(edge));a,b=curve.FirstParameter(),curve.LastParameter()
        points=[xyz(curve.Value(a+(b-a)*i/32)) for i in range(33)]
        if max(abs(p[1]) for p in points)<1e-6 or max(abs(p[2]) for p in points)<1e-6:continue
        side='negative_x' if sum(p[0] for p in points)<0 else 'positive_x'
        out[side]=(curve,a,b)
    if set(out)!={'negative_x','positive_x'}:raise ValueError('Missing actual OCC end boundaries')
    return out
def at_theta(curve_data,target):
    curve,a,b=curve_data;ta,tb=theta(xyz(curve.Value(a))),theta(xyz(curve.Value(b)))
    if ta>tb:a,b=b,a;ta,tb=tb,ta
    target=min(tb,max(ta,target))
    if abs(target-ta)<1e-14:return xyz(curve.Value(a))
    if abs(target-tb)<1e-14:return xyz(curve.Value(b))
    for _ in range(80):
        mid=(a+b)/2;p=xyz(curve.Value(mid));tm=theta(p)
        if abs(tm-target)<1e-14:return p
        if tm<target:a=mid
        else:b=mid
    return xyz(curve.Value((a+b)/2))
def sdk_end_points(path,key):
    obj=json.loads(path.read_text());edges=obj[key]['edges'] if key else obj['edges'];out={}
    for e in edges:
        points=e['points']
        if max(abs(p[1]) for p in points)<1e-6 or max(abs(p[2]) for p in points)<1e-6:continue
        side='negative_x' if sum(p[0] for p in points)<0 else 'positive_x';out[side]=points
    if set(out)!={'negative_x','positive_x'}:raise ValueError('Missing actual SDK end boundaries')
    return out
def compare(occ,sdk):
    rows=[]
    for p in sorted(sdk,key=theta):
        t=min(math.pi/2,max(0.,theta(p)));q=at_theta(occ,t);dx=p[0]-q[0]
        rows.append({'theta_rad':t,'theta_deg':math.degrees(t),'sdk_point_mm':p,'occ_point_mm':q,'signed_dx_sdk_minus_occ_mm':dx,
                     'absolute_dx_mm':abs(dx),'same_theta_3d_distance_mm':math.dist(p,q)})
    peak=max(rows,key=lambda r:r['absolute_dx_mm'])
    radial=max(abs(math.hypot(p[1]-8,p[2]-8)-8) for p in sdk)
    return {'sample_count':len(rows),'max_observed_same_theta_absolute_dx_mm':peak['absolute_dx_mm'],
            'max_observed_same_theta_3d_distance_mm':max(r['same_theta_3d_distance_mm'] for r in rows),
            'sampled_peak':peak,'endpoint_same_theta_distance_mm':[rows[0]['same_theta_3d_distance_mm'],rows[-1]['same_theta_3d_distance_mm']],
            'sdk_profile_radial_residual_to_nominal_R8_mm':radial,'samples':rows}
def query_dense_sdk(native_file,output):
    """Build a read-only consumer through the existing external SDK settings."""
    spec=importlib.util.spec_from_file_location('case36_boundary_sdk_build',ROOT/'adapters/smlib/build.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);c=module.configuration()
    source=ROOT/'adapters/smlib/case36-faceface/readonly_curve_query.cpp'
    signature=hashlib.sha256((sha(source)+c['core_library_sha256']).encode()).hexdigest()[:20]
    cache=ROOT/'.cache/case36-boundary-query'/signature;cache.mkdir(parents=True,exist_ok=True);binary=cache/'readonly_curve_query'
    if not binary.exists():
        command=c['compiler']+['-std=c++17','-O2','-DNDEBUG','-DNOMINMAX','-DSM_API_EXPORTS','-DSM_GRAPHICS_CALLBACKS=1','-Wno-overloaded-virtual','-Wno-deprecated-declarations']
        command+=c['cxxflags']+['-I'+str(p) for p in c['includes']]+[str(source),str(c['library']),'-Wl,-rpath,'+str(c['library'].parent)]+c['ldflags']+['-o',str(binary)]
        proc=subprocess.run(command,capture_output=True,text=True,check=False)
        (cache/'compile.stdout.log').write_text(proc.stdout);(cache/'compile.stderr.log').write_text(proc.stderr)
        if proc.returncode:raise RuntimeError('Read-only query consumer compilation failed; see .cache/case36-boundary-query')
    output.parent.mkdir(parents=True,exist_ok=True);before=sha(native_file)
    subprocess.run([str(binary),str(native_file.resolve()),str(output.resolve())],check=True,capture_output=True,text=True)
    after=sha(native_file)
    if before!=after:raise RuntimeError('Saved native model bytes changed during read-only query')
    provenance={'query_only':True,'fresh_native_fillet_called':False,'source_native_file':str(native_file.relative_to(ROOT)),
                'source_native_sha256_before':before,'source_native_sha256_after':after,'query_source_sha256':sha(source),
                'query_binary_sha256':sha(binary),'sdk_source_commit':c['sdk_source_commit'],'core_library_sha256':c['core_library_sha256']}
    output.with_suffix('.provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    return provenance
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--occ-root',type=Path,default=ROOT/'runs/case36-faceface/occt-composite')
    ap.add_argument('--sdk-root',type=Path,default=ROOT/'runs/case36-faceface/smlib')
    ap.add_argument('--dense-sdk-json',type=Path,default=ROOT/'runs/case36-faceface/readonly-boundaries/sdk-bevel-dense-endpoints.json')
    ap.add_argument('--query-sdk',action='store_true',help='Read saved readback.smb through external SMLIB_ROOT/SMLIB_LIBRARY; never calls fillet')
    ap.add_argument('--output',type=Path,default=ROOT/'docs/case36-faceface-differences.json')
    args=ap.parse_args()
    for name in ['occ_root','sdk_root','dense_sdk_json','output']:setattr(args,name,getattr(args,name).resolve())
    main_audit_before=sha(ROOT/'docs/case36-faceface-audit.json');query=None
    if args.query_sdk:query=query_dense_sdk(args.sdk_root/'bevel-base0/readback.smb',args.dense_sdk_json)
    elif args.dense_sdk_json.with_suffix('.provenance.json').exists():query=json.loads(args.dense_sdk_json.with_suffix('.provenance.json').read_text())
    modes={'to_walls':'bevel','short':'minimal','long':'maximal','no':'none'};entries=[];files=[];before_hashes={}
    for p in [args.dense_sdk_json,args.dense_sdk_json.with_suffix('.provenance.json')]:
        if p.exists():before_hashes[p]=sha(p)
    for mode,native_mode in modes.items():
        oc=args.occ_root/mode/'result.brep';dense=args.sdk_root/(native_mode+'-base0')/'readback-edges.json'
        coarse=args.sdk_root/(native_mode+'-base0')/'readback.json'
        for p in [oc,dense,coarse]:before_hashes[p]=sha(p)
        standard_dense=sdk_end_points(dense,None)
        files.extend([oc,dense,coarse]);occ=occ_end_curves(oc);sdk=sdk_end_points(args.dense_sdk_json,None) if mode=='to_walls' and args.dense_sdk_json.exists() else standard_dense;sdk65=sdk_end_points(coarse,'geometry')
        sides={side:compare(occ[side],sdk[side]) for side in occ};coarse_sides={side:compare(occ[side],sdk65[side]) for side in occ}
        for side in sides:
            sides[side]['coarse_65_max_observed_dx_mm']=coarse_sides[side]['max_observed_same_theta_absolute_dx_mm']
            sides[side]['observed_max_change_65_to_129_mm']=abs(sides[side]['max_observed_same_theta_absolute_dx_mm']-sides[side]['coarse_65_max_observed_dx_mm'])
            sides[side]['occ_x_extent_mm']=ranges([xyz(occ[side][0].Value(occ[side][1]+(occ[side][2]-occ[side][1])*i/128)) for i in range(129)])
            sides[side]['sdk_x_extent_mm']=ranges(sdk[side])
            reference129=compare(occ[side],standard_dense[side])
            sides[side]['standard_129_max_observed_dx_mm']=reference129['max_observed_same_theta_absolute_dx_mm']
            sides[side]['observed_max_change_65_to_129_mm']=abs(reference129['max_observed_same_theta_absolute_dx_mm']-sides[side]['coarse_65_max_observed_dx_mm'])
            sides[side]['observed_max_change_129_to_current_samples_mm']=abs(sides[side]['max_observed_same_theta_absolute_dx_mm']-sides[side]['standard_129_max_observed_dx_mm'])
            if len(sdk[side])>129:
                reference4097=compare(occ[side],sdk[side][::2]);sides[side]['reference_4097_max_observed_dx_mm']=reference4097['max_observed_same_theta_absolute_dx_mm']
                sides[side]['observed_max_change_4097_to_8193_mm']=abs(sides[side]['max_observed_same_theta_absolute_dx_mm']-reference4097['max_observed_same_theta_absolute_dx_mm'])
            stride=max(1,(len(sides[side]['samples'])-1)//128)
            actual=sides[side]['samples'];plot=actual[::stride]
            if len(actual)>129:
                plot+=[actual[i] for i in range(1,len(actual)-1) if actual[i]['absolute_dx_mm']>=actual[i-1]['absolute_dx_mm'] and actual[i]['absolute_dx_mm']>=actual[i+1]['absolute_dx_mm']]
            plot=sorted({s['theta_rad']:s for s in plot}.values(),key=lambda s:s['theta_rad'])
            sides[side]['plot_samples']=[{'theta_rad':s['theta_rad'],'delta_x_mm':s['signed_dx_sdk_minus_occ_mm']} for s in plot]
            sides[side]['samples']=plot;sides[side]['retained_plot_sample_count']=len(plot)
        maximum=max(q['max_observed_same_theta_absolute_dx_mm'] for q in sides.values())
        entries.append({'mode':mode,'radius_mm':8,'sides':sides,'maximum_observed_boundary_dx_mm':maximum,
            'exceeds_0p01_mm':maximum>0.01,'same_finite_working_extent':mode!='no',
            'interpretation':('No-trim working domains differ: OCC explicit x±20, SMLib native x±14. The6mm side offset is an envelope difference, not a trim-mode failure or a fair same-envelope score.' if mode=='no' else
                'Endpoints and local contacts match, but complete to_walls end curves are not identical under common physical theta. Endpoint/G0/G1 subcriteria do not establish whole-curve equivalence.' if mode=='to_walls' else
                'Actual constant-x end curves agree to the measured tolerance under the common physical section angle.')})
    if args.dense_sdk_json.exists():files+=[args.dense_sdk_json,args.dense_sdk_json.with_suffix('.provenance.json')]
    main_audit_after=sha(ROOT/'docs/case36-faceface-audit.json')
    if main_audit_before!=main_audit_after:raise RuntimeError('Frozen main audit changed during boundary comparison')
    report={'schema':'case36.actual-cross-method-end-curve-differences.v1','radius_mm':8,'measurement_tool_sha256':sha(__file__),'dense_query':query,
        'common_physical_coordinate':'theta=atan2(8-z,8-y), theta0 at vertical y0,z8 contact, pi/2 at floor y8,z0 contact',
        'method':'Each actual SMLib SMB-readback edge sample defines a physical theta. Evaluate the actual OCC BREP end curve at that theta by monotone bisection. Compare x and paired3D positions; no fillet called. to_walls may use8193 independent read-only native-curve queries per end; other modes use129. Plot arrays retain about129 representative points plus measured local extrema.',
        'sampling_boundary':'The reported maximum is observed over native samples, with sample_count stated per side. It is not exact continuous maximum or Hausdorff distance. Coarse-to-dense changes are convergence hints, not certified error bounds. OCC inversion tolerance is1e-14rad; raw SDK coordinates retain their own native curve tolerance.',
        'fresh_fillet_call_executed':False,'main_audit_modified':False,'same_endpoints_do_not_prove_whole_curve_identity':True,
        'rows':entries,'raw_evidence':[{'path':str(p.relative_to(ROOT)),'sha256_before':before_hashes[p],'sha256_after':sha(p)} for p in files if p.exists()],
        'main_audit_sha256_before':main_audit_before,'main_audit_sha256_after':main_audit_after,'main_audit_sha256_unchanged':main_audit_after}
    dest=args.output;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    md=['# 第36项跨方法端曲线差异','', '固定R8，按物理截面角对齐原生SMB回读采样和真实OCC BREP边界；不重跑圆角。','', '| 模式 | 端侧 | 最大观测Δx mm | SDK采样峰值θ° | 129→当前采样最大值变化 mm |','|---|---|---:|---:|---:|']
    for row in entries:
        for side,m in row['sides'].items():md.append(f'| {row["mode"]} | {side} | {m["max_observed_same_theta_absolute_dx_mm"]:.12g} | {m["sampled_peak"]["theta_deg"]:.8g} | {m["observed_max_change_129_to_current_samples_mm"]:.6g} |')
    md+=['', 'to_walls两端点及局部G0/G1通过，但两条完整端曲线不同。OCC显式构造按物理θ线性插值端部x；SMLib BEVEL原生边界的x(θ)不呈同样线性规律。此差异没有证明哪种通用trim law正确，不能仅按端点一致宣布完整形状等价。',
         '', 'short/long为相同物理端域的对照。no的工作包络不同（OCC ±20、SDK ±14），6mm差是包络差异，不是同包络的模式失败评分。',
         '', 'to_walls主最大值使用每端8193个只读原生曲线查询点（如dense_query已提供）；short/long/no使用129点。绘图仅保留129个代表点。它不是精确连续最大值或Hausdorff距离；粗细采样变化仅为收敛线索，不是严格误差上界。']
    dest.with_suffix('.md').write_text('\n'.join(md)+'\n')
    print(json.dumps({'rows':[{k:r[k] for k in ['mode','maximum_observed_boundary_dx_mm','exceeds_0p01_mm','same_finite_working_extent']} for r in entries]},indent=2))
if __name__=='__main__':main()
