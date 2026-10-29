"""Independently measure case36 face-pair blend candidates.

The auditor does not repeat a fillet call. OCC measurements come from actual
BREP/STEP surfaces and finite edges. SDK measurements come from native SMB
readback exports, actual finite edges and raw surface derivatives, not worker
pass booleans. Published export remeasurement is not a new native invocation.
"""
from pathlib import Path
import argparse, hashlib, json, math, sys

ROOT=Path(__file__).resolve().parents[1]
SOURCE='data/original-occ/fixtures/c88672f2fa73d5b40f13de10442dea5e432c6bd0b8f91db4412cd54fe6fbc5a1.brep'
SOURCE_SHA='c88672f2fa73d5b40f13de10442dea5e432c6bd0b8f91db4412cd54fe6fbc5a1'
TOL=1e-6; ANGLE=0.1; FIT_TOL=1e-5; RADIUS=8.0
MODES=('to_walls','no','short','long')
MODE_NAMES={'bevel':'to_walls','minimal':'short','maximal':'long','none':'no'}

def read(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def relative(path):
    path=Path(path).resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name
def vec(v):return [v.X(),v.Y(),v.Z()]
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def sub(a,b):return [x-y for x,y in zip(a,b)]
def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def norm(a):return math.sqrt(dot(a,a))
def dist(a,b):return norm(sub(a,b))
def unit(a):return [v/norm(a) for v in a]
def bounds(points):return [min(p[i] for p in points) for i in range(3)]+[max(p[i] for p in points) for i in range(3)] if points else None
def evidence(paths):return [{'path':relative(p),'sha256':sha(p)} for p in paths if Path(p).is_file()]
def solve3(matrix,rhs):
    a=[list(row)+[value] for row,value in zip(matrix,rhs)]
    for col in range(3):
        pivot=max(range(col,3),key=lambda row:abs(a[row][col]))
        if abs(a[pivot][col])<1e-18:return None
        a[col],a[pivot]=a[pivot],a[col];v=a[col][col];a[col]=[x/v for x in a[col]]
        for row in range(3):
            if row!=col:
                v=a[row][col];a[row]=[x-v*y for x,y in zip(a[row],a[col])]
    return [a[i][3] for i in range(3)]
def circle_fit(points):
    rows=[[2*p[1],2*p[2],1.] for p in points];ys=[p[1]**2+p[2]**2 for p in points]
    answer=solve3([[sum(row[i]*row[j] for row in rows) for j in range(3)] for i in range(3)],
                  [sum(row[i]*y for row,y in zip(rows,ys)) for i in range(3)]) if len(points)>=3 else None
    if answer is None:return {'available':False,'sample_count':len(points)}
    cy,cz,c=answer;radius=math.sqrt(max(0.,c+cy*cy+cz*cz))
    residual=max(abs(math.hypot(p[1]-cy,p[2]-cz)-radius) for p in points)
    return {'available':True,'sample_count':len(points),'center_yz_mm':[cy,cz],'radius_mm':radius,
            'max_radial_residual_mm':residual,'radius_deviation_from_requested_mm':abs(radius-RADIUS),
            'center_deviation_mm':math.hypot(cy-RADIUS,cz-RADIUS),
            'radius_passed':abs(radius-RADIUS)<=FIT_TOL,'residual_passed':residual<=FIT_TOL}
def derivative_curvatures(sample):
    try:
        du,dv,duu,duv,dvv=[sample[k] for k in ['du','dv','duu','duv','dvv']]
        normal=unit(cross(du,dv));e,f,g=dot(du,du),dot(du,dv),dot(dv,dv)
        l,m,n=dot(normal,duu),dot(normal,duv),dot(normal,dvv);det=e*g-f*f
        if det<=1e-20:return None
        h=(e*n-2*f*m+g*l)/(2*det);k=(l*n-m*m)/det
        root=math.sqrt(max(0.,h*h-k));ks=[h-root,h+root];major=max(map(abs,ks))
        return {'principal_curvatures_mm_inverse':ks,'radius_mm':1/major if major>1e-15 else None,'normal':normal}
    except (KeyError,TypeError,ValueError,ZeroDivisionError):return None
def d2_radius_summary(samples):
    values=[];finite=0
    for sample in samples:
        row=derivative_curvatures(sample)
        if row and row['radius_mm'] is not None:
            values.append(row['radius_mm']);finite+=int(sample.get('finite_face_membership_verified') is True)
    return {'sample_count':len(values),'finite_membership_verified_count':finite,
            'radius_range_mm':[min(values),max(values)] if values else None,
            'max_deviation_from_R8_mm':max(abs(v-RADIUS) for v in values) if values else None,
            'scope':'Raw derivative principal curvature, measured separately from profile-circle fit; no combined pass inferred.'}

def read_brep(path):
    from OCP.BRep import BRep_Builder
    from OCP.BRepTools import BRepTools
    from OCP.TopoDS import TopoDS_Shape
    shape=TopoDS_Shape()
    if not BRepTools.Read_s(shape,str(path),BRep_Builder()):raise ValueError('Cannot read BREP: '+relative(path))
    return shape
def shapes(shape,kind):
    from OCP.TopExp import TopExp_Explorer
    out=[];it=TopExp_Explorer(shape,kind)
    while it.More():
        q=it.Current()
        if not any(q.IsSame(p) for p in out):out.append(q)
        it.Next()
    return out
def bop_check(shape):
    from OCP.BOPAlgo import BOPAlgo_ArgumentAnalyzer
    a=BOPAlgo_ArgumentAnalyzer();a.SetShape1(shape)
    for key in ['ArgumentTypeMode','SelfInterMode','SmallEdgeMode','RebuildFaceMode','ContinuityMode','CurveOnSurfaceMode']:setattr(a,key,True)
    a.StopOnFirstFaulty=False;a.Perform();faults=[str(x.GetCheckStatus()).split('.')[-1] for x in a.GetCheckResult()]
    return {'faults':faults,'passed':not faults}
def source_measurement():
    from OCP.BRep import BRep_Tool
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE,TopAbs_EDGE,TopAbs_VERTEX,TopAbs_SHELL,TopAbs_SOLID
    from OCP.TopoDS import TopoDS
    from OCP.BRepCheck import BRepCheck_Analyzer
    s=read_brep(ROOT/SOURCE);faces=shapes(s,TopAbs_FACE);rows=[]
    for f in faces:
        points=[vec(BRep_Tool.Pnt_s(TopoDS.Vertex_s(v))) for v in shapes(f,TopAbs_VERTEX)]
        g=GProp_GProps();BRepGProp.SurfaceProperties_s(f,g);rows.append({'bbox_mm':bounds(points),'vertices_mm':points,'area_mm2':g.Mass()})
    vertical=next(r for r in rows if abs(r['bbox_mm'][1])+abs(r['bbox_mm'][4])<TOL)
    horizontal=next(r for r in rows if abs(r['bbox_mm'][2])+abs(r['bbox_mm'][5])<TOL)
    gap=BRepExtrema_DistShapeShape(faces[0],faces[1]);gap.Perform()
    shared=[e for e in shapes(s,TopAbs_EDGE) if sum(any(e.IsSame(q) for q in shapes(f,TopAbs_EDGE)) for f in faces)>1]
    stats={'faces':len(faces),'edges':len(shapes(s,TopAbs_EDGE)),'shells':len(shapes(s,TopAbs_SHELL)),
           'solids':len(shapes(s,TopAbs_SOLID)),'area_mm2':sum(r['area_mm2'] for r in rows),'gap_mm':gap.Value(),'shared_edge_count':len(shared),
           'vertical':vertical,'horizontal':horizontal}
    gates={'source_bytes':sha(ROOT/SOURCE)==SOURCE_SHA,'BREP_valid':BRepCheck_Analyzer(s,True).IsValid(),'two_original_finite_faces':len(faces)==2 and not shared,
           'original_domains':all(abs(a-b)<TOL for a,b in zip(vertical['bbox_mm'],[-7,0,5,7,0,25])) and all(abs(a-b)<TOL for a,b in zip(horizontal['bbox_mm'],[-12.5,5,0,12.5,23,0])),
           'original_area_and_gap':abs(stats['area_mm2']-730)<TOL and abs(stats['gap_mm']-math.sqrt(50))<TOL}
    return {'path':SOURCE,'sha256':sha(ROOT/SOURCE),'measurements':stats,'gates':gates},s

def source_mask(point,side):
    x,y,z=point
    if side=='vertical':return abs(y)<=TOL and -7-TOL<=x<=7+TOL and 5-TOL<=z<=25+TOL
    return abs(z)<=TOL and -12.5-TOL<=x<=12.5+TOL and 5-TOL<=y<=23+TOL
def source_rectangle_gap(point,side):
    x,y,z=point
    q=[min(7.,max(-7.,x)),0.,min(25.,max(5.,z))] if side=='vertical' else [min(12.5,max(-12.5,x)),min(23.,max(5.,y)),0.]
    return dist(point,q)
def segment_distance(p,a,b):
    d=sub(b,a);den=dot(d,d);t=max(0.,min(1.,dot(sub(p,a),d)/den)) if den else 0.
    return dist(p,[x+t*y for x,y in zip(a,d)])
def measure_edges(edges,normal_samples=None):
    rails=[];ends=[];allpoints=[]
    for edge in edges:
        points=edge.get('points',[]);allpoints+=points
        if not points:continue
        side='vertical' if max(abs(p[1]) for p in points)<=TOL else 'horizontal' if max(abs(p[2]) for p in points)<=TOL else None
        if side:
            fixed_error=max(abs(p[2]-RADIUS) if side=='vertical' else abs(p[1]-RADIUS) for p in points)
            lo,hi=min(p[0] for p in points),max(p[0] for p in points);wall=(-7,7) if side=='vertical' else (-12.5,12.5)
            length=max(0.,min(hi,wall[1])-max(lo,wall[0]))
            rails.append({'edge_id':edge.get('id'),'support':side,'points_mm':points,'x_extent_mm':[lo,hi],
                          'contact_coordinate_error_mm':fixed_error,'all_points_inside_original_finite_face':all(source_mask(p,side) for p in points),
                          'inside_sample_count':sum(source_mask(p,side) for p in points),'sample_count':len(points),
                          'linear_contact_length_mm':hi-lo,'overlap_with_original_wall_length_mm':length,
                          'outside_original_wall_length_mm':max(0.,hi-lo-length)})
        else:ends.append({'edge_id':edge.get('id'),'points_mm':points,'x_extent_mm':[min(p[0] for p in points),max(p[0] for p in points)]})
    profile=[p for row in ends for p in row['points_mm']]
    fit=circle_fit(profile)
    return {'bbox_from_actual_edges_mm':bounds(allpoints),'rails':rails,'end_curves':ends,'profile_circle_fit':fit,
            'quarter_circle_quadrant_sampled':bool(allpoints) and all(-TOL<=p[1]<=RADIUS+TOL and -TOL<=p[2]<=RADIUS+TOL for p in allpoints),
            'actual_sampled_point_count':len(allpoints)}
def rail_range(facts,side):
    rows=[r for r in facts['rails'] if r['support']==side]
    return [min(r['x_extent_mm'][0] for r in rows),max(r['x_extent_mm'][1] for r in rows)] if rows else None
def near_range(actual,expected):return actual is not None and max(abs(a-b) for a,b in zip(actual,expected))<=TOL
def trim_checks(mode,facts):
    vr,hr=rail_range(facts,'vertical'),rail_range(facts,'horizontal');ends=facts['end_curves'];out={'mode':mode,'vertical_rail_extent_mm':vr,'horizontal_rail_extent_mm':hr}
    distinct_ends=len(ends)>=2
    constant_ends=distinct_ends and all(r['x_extent_mm'][1]-r['x_extent_mm'][0]<=TOL for r in ends)
    nonconstant_ends=distinct_ends and all(r['x_extent_mm'][1]-r['x_extent_mm'][0]>TOL for r in ends)
    if mode=='short':checks={'both_rails_short':near_range(vr,[-7,7]) and near_range(hr,[-7,7]),'constant_parameter_end_sampled':constant_ends}
    elif mode=='long':checks={'both_rails_long':near_range(vr,[-12.5,12.5]) and near_range(hr,[-12.5,12.5]),'constant_parameter_end_sampled':constant_ends}
    elif mode=='no':checks={'extends_beyond_both_original_wall_widths':bool(vr and hr) and all(x[0]<-12.5-TOL and x[1]>12.5+TOL for x in [vr,hr])}
    else:checks={'vertical_rail_matches_its_wall_ends':near_range(vr,[-7,7]),'horizontal_rail_matches_its_wall_ends':near_range(hr,[-12.5,12.5]),'nonconstant_parameter_end_sampled':nonconstant_ends,
                 'both_contact_rails_on_original_finite_faces':bool(facts['rails']) and all(r['all_points_inside_original_finite_face'] for r in facts['rails'])}
    out.update(checks=checks,all_subcriteria_passed=all(checks.values()),
               constant_x_end_sampled=constant_ends,nonconstant_x_end_sampled=nonconstant_ends,
               semantic_boundary='Measured local rectangular-wall subcriteria only; not a general Parasolid trim-law or human appearance certification.')
    return out
def local_geometry_gates(facts):
    fit=facts.get('profile_circle_fit') or {}
    return {**facts.get('local_contact_gates',{}),'profile_fit_available':fit.get('available') is True,
            'profile_circle_radius':fit.get('radius_passed') is True,'profile_circle_fit_residual':fit.get('residual_passed') is True,
            'profile_circle_center_matches_contact_law':fit.get('center_deviation_mm',math.inf)<=TOL,
            'positive_quarter_circle_layout_sampled':facts.get('quarter_circle_quadrant_sampled') is True}
def finite_attachment(facts):
    return {'all_contact_rails_inside_original_finite_faces':bool(facts['rails']) and all(r['all_points_inside_original_finite_face'] for r in facts['rails']),
            'contacts':[{'support':r['support'],'x_extent_mm':r['x_extent_mm'],'length_mm':r['linear_contact_length_mm'],
                         'inside_original_wall_length_mm':r['overlap_with_original_wall_length_mm'],'outside_original_wall_length_mm':r['outside_original_wall_length_mm']} for r in facts['rails']],
            'scope':'G0/G1 to underlying support planes is separate from attachment to the original finite rectangles. Long/no modes intentionally retain contact extensions outside the narrow wall.'}

def brep_measurement(shape):
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve,BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCP.BRepLProp import BRepLProp_SLProps
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE,TopAbs_EDGE,TopAbs_SOLID,TopAbs_IN,TopAbs_ON
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Pnt,gp_Pnt2d
    faces=shapes(shape,TopAbs_FACE);edges=[];normal_rows=[];radii=[]
    for index,edge in enumerate(shapes(shape,TopAbs_EDGE)):
        curve=BRepAdaptor_Curve(TopoDS.Edge_s(edge));a,b=curve.FirstParameter(),curve.LastParameter()
        pts=[vec(curve.Value(a+(b-a)*i/128)) for i in range(129)];edges.append({'id':index,'points':pts,'curve_type':str(curve.GetType())})
        side='vertical' if max(abs(p[1]) for p in pts)<=TOL else 'horizontal' if max(abs(p[2]) for p in pts)<=TOL else None
        if not side:continue
        axis=[0,1,0] if side=='vertical' else [0,0,1]
        owners=[f for f in faces if any(edge.IsSame(e) for e in shapes(f,TopAbs_EDGE))]
        if len(owners)!=1:continue
        surf=BRep_Tool.Surface_s(TopoDS.Face_s(owners[0]));ad=BRepAdaptor_Surface(TopoDS.Face_s(owners[0]))
        for p in pts[::8]:
            project=GeomAPI_ProjectPointOnSurf(gp_Pnt(*p),surf)
            if not project.NbPoints():continue
            u,v=project.LowerDistanceParameters();sl=BRepLProp_SLProps(ad,u,v,2,1e-12)
            if not sl.IsNormalDefined():continue
            n=vec(sl.Normal());angle=math.degrees(math.acos(max(-1.,min(1.,abs(dot(unit(n),axis))))))
            normal_rows.append({'support':side,'point_mm':p,'surface_edge_gap_mm':project.LowerDistance(),'unoriented_tangent_plane_angle_deg':angle})
    for f in faces:
        face=TopoDS.Face_s(f);u0,u1,v0,v1=BRepTools.UVBounds_s(face);ad=BRepAdaptor_Surface(face)
        for i in range(1,8):
            for j in range(1,8):
                u=u0+(u1-u0)*i/8;v=v0+(v1-v0)*j/8
                if BRepClass_FaceClassifier(face,gp_Pnt2d(u,v),TOL).State() not in [TopAbs_IN,TopAbs_ON]:continue
                sl=BRepLProp_SLProps(ad,u,v,2,1e-12)
                if sl.IsCurvatureDefined():
                    major=max(abs(sl.MinCurvature()),abs(sl.MaxCurvature()))
                    if major>1e-15:radii.append(1/major)
    g=GProp_GProps();BRepGProp.SurfaceProperties_s(shape,g)
    facts=measure_edges(edges);facts.update(brep_valid=BRepCheck_Analyzer(shape,True).IsValid(),bop=bop_check(shape),face_count=len(faces),
        solid_count=len(shapes(shape,TopAbs_SOLID)),area_mm2=g.Mass(),rail_normal_samples=normal_rows,
        D2_radius={'sample_count':len(radii),'finite_membership_verified_count':len(radii),'radius_range_mm':[min(radii),max(radii)] if radii else None,
                   'max_deviation_from_R8_mm':max(abs(r-RADIUS) for r in radii) if radii else None,'scope':'Actual finite-face interior principal-curvature radii, separate from profile fit.'})
    both_normal_sides={r['support'] for r in normal_rows}=={'vertical','horizontal'}
    facts['local_contact_gates']={'both_rails_present':all(rail_range(facts,s) for s in ['vertical','horizontal']),
        'support_contact_G0':bool(facts['rails']) and all(r['contact_coordinate_error_mm']<=TOL for r in facts['rails']),
        'actual_surface_edge_G0':both_normal_sides and max(r['surface_edge_gap_mm'] for r in normal_rows)<=TOL,
        'unoriented_tangent_plane_G1':both_normal_sides and max(r['unoriented_tangent_plane_angle_deg'] for r in normal_rows)<=ANGLE}
    return facts

def occt_rows(directory):
    index_path=directory/'index.json'
    if not index_path.exists():return []
    index=read(index_path);out=[]
    for row in index.get('rows',[]):
        mode=row['mode'];run=ROOT/row['run_dir'];summary=read(ROOT/row['summary']);bp=ROOT/row['result_brep']
        facts=brep_measurement(read_brep(bp));step={};sp=ROOT/row['result_step']
        if sp.exists():
            from OCP.STEPControl import STEPControl_Reader
            from OCP.IFSelect import IFSelect_RetDone
            reader=STEPControl_Reader();st=reader.ReadFile(str(sp));step['read_status']=str(st)
            if st==IFSelect_RetDone:
                reader.TransferRoots();sf=brep_measurement(reader.OneShape());step.update(brep_valid=sf['brep_valid'],bop=sf['bop'],face_count=sf['face_count'],area_mm2=sf['area_mm2'],
                    area_delta_mm2=abs(sf['area_mm2']-facts['area_mm2']),trim=trim_checks(mode,sf),profile_circle_fit=sf['profile_circle_fit'])
                step['independent_gates']={'BREP':sf['brep_valid'],'BOP':sf['bop']['passed'],'single_blend_face':sf['face_count']==1 and sf['solid_count']==0,
                                          'area_roundtrip_mm2':abs(sf['area_mm2']-facts['area_mm2'])<=TOL,
                                          'local_geometry':all(local_geometry_gates(sf).values()),'trim_subcriteria':step['trim']['all_subcriteria_passed']}
        out.append({'engine':'OCCT','method':'explicit_occ_composition','mode':mode,'radius_mm':summary['radius_mm'],
            'source_sha256':sha(ROOT/SOURCE),'operation_input_sha256':sha(ROOT/row['before_brep']),
            'input_source_bytes_preserved':sha(ROOT/row['before_brep'])==SOURCE_SHA,
            'invocation':{'native_face_face_call':summary['native_face_face_call'],'explicit_construction_recorded':summary['construction_executed'],'fillet_call_repeated_by_auditor':False},
            'actual_geometry':facts,'local_geometry_gates':local_geometry_gates(facts),'finite_wall_attachment':finite_attachment(facts),'step_roundtrip_independent':step,'trim':trim_checks(mode,facts),
            'native_geometry_gates':{'BREP':facts['brep_valid'],'BOP':facts['bop']['passed'],'single_blend_face':facts['face_count']==1 and facts['solid_count']==0},
            'actual_evidence':evidence([ROOT/row['summary'],ROOT/row['before_brep'],bp,sp]),
            'source_feature_certified':False,'human_appearance_status':'pending',
            'validation_boundary':'Local rectangular-wall endpoint conditions measured. Explicit to_walls uses a declared boundary interpolation; no general native/Parasolid mapping is claimed.'})
    return out

def sdk_input_facts(run,side):
    raw=read(run/f'input-{side}.json');stats=raw['native_stats'];points=[p for e in raw['geometry']['edges'] for p in e['points']]
    bbox=bounds(points);expected=[-7,0,5,7,0,25] if side=='left' else [-12.5,5,0,12.5,23,0]
    expected_area=280. if side=='left' else 450.;mask_side='vertical' if side=='left' else 'horizontal'
    support=read(run/f'input-{side}-support.json');vertices=support['finite_face_vertices_mm']
    expected_corners=[[x,0,z] for x in [-7,7] for z in [5,25]] if side=='left' else [[x,y,0] for x in [-12.5,12.5] for y in [5,23]]
    corner_gap=max(min(dist(p,q) for q in vertices) for p in expected_corners)
    geometry=(all(abs(a-b)<=TOL for a,b in zip(bbox,expected)) and abs(stats['area']-expected_area)<=TOL and all(source_mask(p,mask_side) for p in points)
              and corner_gap<=TOL and stats['faces']==1 and stats['edges']==4 and stats['vertices']==4 and stats['material_regions']==0 and stats['valid'] is True)
    post=read(run/f'post-{side}.json');after=[p for e in post['geometry']['edges'] for p in e['points']]
    unchanged=len(points)==len(after) and max((min(dist(p,q) for q in after) for p in points),default=math.inf)<=TOL
    post_stats=post['native_stats'];post_bbox=bounds(after)
    segments=[(a,b) for e in post['geometry']['edges'] for a,b in zip(e['points'],e['points'][1:])]
    outer_gap=max((min(segment_distance(p,a,b) for a,b in segments) for p in points),default=math.inf)
    domain=all(abs(a-b)<=TOL for a,b in zip(post_bbox,expected)) and abs(post_stats['area']-expected_area)<=TOL and all(source_mask(p,mask_side) for p in after) and outer_gap<=TOL
    query_file=run/'post-domain-audit.json';grid=None
    if query_file.exists():
        q=read(query_file)[side];samples=q['original_grid_samples'];gaps=[dist(s['original_point_mm'],s['post_closest_point_mm']) for s in samples]
        grid={'original_grid_sample_count':len(samples),'original_grid_to_actual_post_max_distance_mm':max(gaps),
              'native_statuses_successful':all(s['status']==1000 for s in samples),'original_points_inside_source_mask':all(source_mask(s['original_point_mm'],mask_side) for s in samples),
              'scope':'17x17 coverage queries to actual saved post body; no full analytic footprint or between-sample self-overlap proof.'}
        domain=domain and len(samples)==289 and max(gaps)<=TOL and grid['native_statuses_successful'] and grid['original_points_inside_source_mask']
    topology=all(stats.get(k)==post_stats.get(k) for k in ['faces','edges','vertices','components','shells','material_regions'])
    raw_before,raw_after=run/f'source-{side}-before.smb',run/f'source-{side}-after.smb'
    return {'bbox_from_actual_finite_edges_mm':bbox,'native_stats':stats,'matches_original_rectangle_bbox':geometry,
            'precall_finite_domains_match_source':geometry,
            'precall_actual_vertex_to_original_corner_max_distance_mm':corner_gap,
            'post_input_geometry_domain_preserved':domain,'post_input_topology_preserved':topology,
            'post_saved_body_coverage_queries':grid,
            'post_native_stats':post_stats,'post_bbox_from_actual_finite_edges_mm':post_bbox,'original_outer_boundary_sample_max_distance_to_post_edges_mm':outer_gap,
            'post_all_edges_same_point_set':unchanged,'call_copy_smb_bytes_unchanged':sha(run/f'input-{side}.smb')==sha(run/f'post-{side}.smb') if (run/f'input-{side}.smb').exists() and (run/f'post-{side}.smb').exists() else None,
            'immutable_native_source_smb_unchanged':sha(raw_before)==sha(raw_after) if raw_before.exists() and raw_after.exists() else None,
            'immutable_native_source_smb_sha256':[sha(raw_before),sha(raw_after)] if raw_before.exists() and raw_after.exists() else None,
            'scope':'Pre-call finite rectangle measured independently. Post domain check uses actual area/bbox, all finite edge samples inside original masks, and original boundary coverage; topology and serialized bytes are separate. Full analytic footprint/self-overlap proof is not asserted.'}
def sdk_rows(directory):
    ip=directory/'index.json'
    if not ip.exists():return []
    index=read(ip);out=[]
    for row in index.get('rows',[]):
        run=ROOT/row['run_dir'];summary=read(ROOT/row['summary']);mode=MODE_NAMES.get(row['mode'],row['mode']);operation=read(run/'operation.json')
        request=read(run/'request.json');native=read(run/'native.json') if (run/'native.json').exists() else {};rb=read(run/'readback.json') if (run/'readback.json').exists() else {}
        inputs={side:sdk_input_facts(run,side) for side in ['left','right']};facts=None;trim=None
        if rb:
            edges=rb['geometry']['edges'];facts=measure_edges(edges)
            contact=read(run/'contact-check.json');normal_rows=[];rail_derivatives=[]
            for rail in contact['rails']:
                for sample in rail['samples']:
                    d2=sample.get('actual_surface_D2') or {};computed=derivative_curvatures(d2)
                    point=sample['point'];axis=[0,1,0] if abs(point[1])<=TOL else [0,0,1]
                    if computed and d2.get('status')==1000:
                        side='vertical' if axis[1] else 'horizontal'
                        computed_gap=source_rectangle_gap(point,side)
                        normal_rows.append({'point_mm':point,'support':'vertical' if axis[1] else 'horizontal','surface_edge_gap_mm':sample['surface_edge_gap_mm'],
                            'unoriented_tangent_plane_angle_deg':math.degrees(math.acos(min(1.,max(-1.,abs(dot(computed['normal'],axis)))))),
                            'actual_D2_point_to_edge_gap_mm':dist(d2['point'],point),
                            'finite_original_face_gap_mm':computed_gap,'native_finite_original_face_gap_mm':sample['finite_face_gap_mm'],
                            'finite_mask_query_disagreement_mm':abs(computed_gap-sample['finite_face_gap_mm'])})
                        d2=dict(d2,finite_face_membership_verified=True);rail_derivatives.append(d2)
            grid=read(run/'surface-D2.json');grid_samples=[dict(s,finite_face_membership_verified=True) for f in grid.get('faces',[]) for s in f.get('samples',[]) if s.get('finite_face_closest_status')==1000 and s.get('finite_face_gap_mm',math.inf)<=TOL]
            both_normal_sides={r['support'] for r in normal_rows}=={'vertical','horizontal'}
            facts.update(native_stats=rb['native_stats'],rail_normal_samples=normal_rows,D2_radius=d2_radius_summary(grid_samples),D2_rail_radius=d2_radius_summary(rail_derivatives),
                         local_contact_gates={'both_rails_present':all(rail_range(facts,s) for s in ['vertical','horizontal']),
                            'support_contact_G0':bool(facts['rails']) and all(r['contact_coordinate_error_mm']<=TOL for r in facts['rails']),
                            'actual_surface_edge_G0':both_normal_sides and max(max(s['surface_edge_gap_mm'],s['actual_D2_point_to_edge_gap_mm']) for s in normal_rows)<=TOL,
                            'original_finite_mask_query_consistency':bool(normal_rows) and max(s['finite_mask_query_disagreement_mm'] for s in normal_rows)<=TOL,
                            'unoriented_tangent_plane_G1':both_normal_sides and max(s['unoriented_tangent_plane_angle_deg'] for s in normal_rows)<=ANGLE})
            trim=trim_checks(mode,facts)
        native_points=[p for e in native.get('geometry',{}).get('edges',[]) for p in e['points']]
        rb_points=[p for e in rb.get('geometry',{}).get('edges',[]) for p in e['points']]
        rb_delta=max((min(dist(p,q) for q in rb_points) for p in native_points),default=math.inf) if rb_points else None
        files=[run/name for name in ['summary.json','request.json','operation.json','native.json','readback.json','input-left.json','input-right.json','input-left-support.json','input-right-support.json','post-left.json','post-right.json','post-domain-audit.json','surface-D2.json','contact-check.json']]
        out.append({'engine':'SMLib','method':'native_surface_surface_fillet','mode':mode,'native_mode':row['mode'],'radius_mm':request['radius_mm'],
            'source_sha256':index['source_sha256'],'operation_input_sha256':row['operation_input_sha256'],'native_inputs':inputs,
            'input_source_bytes_preserved':index['source_sha256']==SOURCE_SHA and row['operation_input_sha256']==SOURCE_SHA,
            'input_finite_domains_preserved':all(s['precall_finite_domains_match_source'] for s in inputs.values()),
            'immutable_source_file_unchanged':all(s['immutable_native_source_smb_unchanged'] is True for s in inputs.values()),
            'precall_finite_domains_match_source':all(s['precall_finite_domains_match_source'] for s in inputs.values()),
            'post_input_geometry_domain_preserved':all(s['post_input_geometry_domain_preserved'] for s in inputs.values()),
            'post_input_topology_preserved':all(s['post_input_topology_preserved'] for s in inputs.values()),
            'invocation':{'native_call_started':operation['native_call_started'],'raw_status':operation['native_api_raw_status'],'nonnull_result':operation['nonnull_result'],
                'trim_enum':request['trim_enum'],'base_trim':request['base_trim'],'explicit_post_crop':request['explicit_post_crop'],'signed_radii':[request['signed_radius_left'],request['signed_radius_right']],
                'solver_contact_tolerance_mm':request['solver_contact_tolerance_mm'],'fillet_call_repeated_by_auditor':False},
            'actual_geometry':facts,'local_geometry_gates':local_geometry_gates(facts) if facts else {},'finite_wall_attachment':finite_attachment(facts) if facts else None,'trim':trim,'native_geometry_gates':{'native_valid':native.get('native_stats',{}).get('valid'),'readback_valid':rb.get('native_stats',{}).get('valid'),
                'single_blend_face':rb.get('native_stats',{}).get('faces')==1 and rb.get('native_stats',{}).get('material_regions')==0,
                'native_readback_edge_points_agree':rb_delta is not None and rb_delta<=TOL},
            'readback_comparison':{'native_readback_edge_sample_max_distance_mm':rb_delta},
            'actual_evidence':evidence(files),'source_feature_certified':False,'human_appearance_status':'pending',
            'validation_boundary':'Native enum names are candidate mappings; trim subcriteria use actual readback geometry. D2 finite membership was verified by the native finite-face closest-point query; derivative curvature recomputed here. base_trim=0 demonstrably changes working-copy wall topology even when the finite domain and immutable sources remain unchanged; it is not certified equivalent to a no-wall-modification policy.'})
    return out

def occt_native_rows(directory):
    ip=directory/'index.json'
    if not ip.exists():return []
    index=read(ip);selected=index.get('selected_candidate')
    selected=[selected] if selected else [r for r in index.get('rows',[]) if r.get('result_brep') and r.get('native_call_executed') and r.get('reference_quarter_section_branch',True)]
    out=[]
    for row in selected:
        bp=ROOT/row['result_brep'];summary=read(ROOT/row['summary']);facts=brep_measurement(read_brep(bp));step={};sp=ROOT/row['result_step']
        if sp.exists():
            from OCP.STEPControl import STEPControl_Reader
            from OCP.IFSelect import IFSelect_RetDone
            reader=STEPControl_Reader();st=reader.ReadFile(str(sp));step['read_status']=str(st)
            if st==IFSelect_RetDone:
                reader.TransferRoots();sf=brep_measurement(reader.OneShape());step.update(brep_valid=sf['brep_valid'],bop=sf['bop'],face_count=sf['face_count'],area_mm2=sf['area_mm2'],
                    area_delta_mm2=abs(sf['area_mm2']-facts['area_mm2']),profile_circle_fit=sf['profile_circle_fit'],local_geometry_gates=local_geometry_gates(sf))
        out.append({'engine':'OCCT','engine_version':row.get('engine_version'),'method':'native_surface_surface_rolling_ball_walking_and_approximation','mode':'native-baseline',
            'radius_mm':index['radius_mm'],'source_sha256':sha(ROOT/SOURCE),'operation_input_sha256':sha(ROOT/row['before_brep']),
            'input_source_bytes_preserved':sha(ROOT/row['before_brep'])==SOURCE_SHA,
            'invocation':{'native_call_executed':row.get('native_call_executed'),'api_success':row.get('api_success'),'native_four_trim_policy_parameter_supplied':False,'fillet_call_repeated_by_auditor':False},
            'actual_geometry':facts,'local_geometry_gates':local_geometry_gates(facts),'finite_wall_attachment':finite_attachment(facts),'step_roundtrip_independent':step,'trim':None,
            'observed_short_like_endpoint_subcriteria':trim_checks('short',facts),
            'native_geometry_gates':{'BREP':facts['brep_valid'],'BOP':facts['bop']['passed'],'single_blend_face':facts['face_count']==1 and facts['solid_count']==0},
            'actual_evidence':evidence([ip,ROOT/row['summary'],ROOT/row['before_brep'],bp,sp]),'source_feature_certified':False,'human_appearance_status':'pending',
            'validation_boundary':'One actual native rolling-ball baseline on original finite supports, not four trim-policy implementations. Observed common-span endpoints do not certify a requested native short enum. Native 7.8.1 producer and OCP 7.9.3 independent reader are distinct.'})
    return out

def identity_only(report_path):
    report=read(report_path);checks={'source_bytes':sha(ROOT/SOURCE)==report['source']['sha256']==SOURCE_SHA};available=0;unavailable=[]
    for row in report.get('rows',[]):
        for e in row.get('actual_evidence',[]):
            path=ROOT/e['path']
            if path.exists():checks[e['path']]=sha(path)==e['sha256'];available+=1
            else:unavailable.append(e['path'])
    return {'schema':'case36.faceface-audit-identity.v1','checks':checks,'available_actual_evidence_files':available,'raw_evidence_unavailable':unavailable,'all_actual_evidence_available':not unavailable,
        'identity_checks_passed':all(checks.values()),'fresh_geometry_measurement_executed':False,'fresh_native_fillet_executed':False,
        'scope':'Existing bytes only. Missing ignored raw runs remain unassessed; this is not fresh kernel or trim evidence.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--occ-root',type=Path,default=ROOT/'runs/case36-faceface/occt-composite');p.add_argument('--sdk-root',type=Path,default=ROOT/'runs/case36-faceface/smlib')
    p.add_argument('--native-root',type=Path,default=ROOT/'runs/case36-faceface/occt-native')
    p.add_argument('--output',type=Path,default=ROOT/'docs/case36-faceface-audit.json');p.add_argument('--require-complete',action='store_true');p.add_argument('--require-native',action='store_true');p.add_argument('--identity-only',type=Path)
    args=p.parse_args()
    if args.identity_only:
        report=identity_only(args.identity_only);print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if report['identity_checks_passed'] else 1
    source,_=source_measurement();rows=occt_rows(args.occ_root)+sdk_rows(args.sdk_root)+occt_native_rows(args.native_root)
    all_modes={method:sorted(r['mode'] for r in rows if r['method']==method) for method in ['explicit_occ_composition','native_surface_surface_fillet']}
    source['sha256_after']=sha(ROOT/SOURCE);source['source_unchanged_during_audit']=source['sha256_after']==source['sha256']
    complete=all(set(v)==set(MODES) and len(v)==4 for v in all_modes.values());consistency=all(source['gates'].values()) and source['source_unchanged_during_audit'] and all(r['source_sha256']==SOURCE_SHA and r['radius_mm']==RADIUS and r['input_source_bytes_preserved'] and r.get('input_finite_domains_preserved',True) and r.get('immutable_source_file_unchanged',True) for r in rows)
    cross_modes={}
    for method in all_modes:
        group=[r for r in rows if r['method']==method];features=[r.get('trim') for r in group]
        signatures={r['mode']:{'vertical':rail_range(r['actual_geometry'],'vertical'),'horizontal':rail_range(r['actual_geometry'],'horizontal'),'end_x_spans':[e['x_extent_mm'][1]-e['x_extent_mm'][0] for e in r['actual_geometry']['end_curves']]} for r in group if r.get('actual_geometry')}
        signature_keys={json.dumps({k:[round(x,6) for x in sorted(v)] if v is not None else None for k,v in s.items()},sort_keys=True) for s in signatures.values()}
        cross_modes[method]={'modes_present':all_modes[method],'mode_geometry_signatures':signatures,'all_four_physical_endpoint_signatures_distinct':len(signature_keys)==4,
            'all_local_trim_subcriteria_passed':bool(features) and all(f and f['all_subcriteria_passed'] for f in features),'source_feature_certified':False}
    from importlib.metadata import version
    report={'schema':'case36.faceface-independent-geometry-audit.v1','auditor_sha256':sha(__file__),'geometry_reader':{'binding':'cadquery-ocp','binding_version':version('cadquery-ocp'),'BREP_geometry_remeasured':True,'native_fillet_call_repeated':False},'source':source,
        'thresholds':{'input_and_contact_G0_mm':TOL,'rail_endpoint_mm':TOL,'unoriented_tangent_plane_angle_deg':ANGLE,'profile_circle_fit_radial_residual_mm':FIT_TOL,'profile_circle_radius_deviation_mm':FIT_TOL},
        'auditor_uses_worker_pass_booleans_as_geometry_proof':False,'auditor_repeated_fillet_calls':False,
        'rows':rows,'cross_modes':cross_modes,'all_requested_modes_measured':complete,'occt_native_baseline_measured':any(r['mode']=='native-baseline' for r in rows),'audit_consistency_passed':consistency,
        'source_feature_certified':False,'human_appearance_status':'pending','validation_boundary':['The source dimensions are an inferred reconstruction, not vendor CAD.','Local G0/G1 and sampled curve/surface tests are separate from full global quality.','Explicit to_walls boundary interpolation is a declared construction, not a general Parasolid trim-law certification.','Native outputs are measured as returned; no caller post-crop is hidden.','No-trim has no unique finite tail length; only actual extension and declared working domains are assessed.']}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    text=['# 第36项独立面面圆角量测','', '| 内核／方法 | 模式 | 竖面接触轨 X | 横面接触轨 X | 圆拟合 R | 端部子判据 |','|---|---|---|---|---:|---|']
    for r in rows:
        f=r.get('actual_geometry') or {};fit=f.get('profile_circle_fit') or {};t=r.get('trim') or {}
        text.append('| '+ ' | '.join([r['engine']+' / '+r['method'],r['mode'],str(rail_range(f,'vertical')) if f else '无产物',str(rail_range(f,'horizontal')) if f else '无产物',str(fit.get('radius_mm')),str(t.get('all_subcriteria_passed'))])+' |')
    text+=['','## SMLib调用后的墙面状态','', '| 模式 | 原文件未变 | 调用前有限域匹配 | 调用后有限域采样保持 | 调用后拓扑保持 | 左面/边 | 右面/边 |', '|---|---|---|---|---|---|---|']
    for r in rows:
        if r['engine']!='SMLib':continue
        desc=[]
        for side in ['left','right']:
            q=r['native_inputs'][side];a,b=q['native_stats'],q['post_native_stats'];desc.append(f'{a["faces"]}/{a["edges"]} → {b["faces"]}/{b["edges"]}')
        text.append('| '+' | '.join([r['mode'],str(r['immutable_source_file_unchanged']),str(r['precall_finite_domains_match_source']),str(r['post_input_geometry_domain_preserved']),str(r['post_input_topology_preserved']),*desc])+' |')
    text+=['','输入及量测身份一致性：'+str(consistency)+'；四模式是否齐全：'+str(complete)+'。','', '以上端部子判据与局部几何不等于通用原图功能或人工外观验收。原生调用与显式组合分别记录；审计器没有重新调用圆角。',
           '', 'SMLib base_trim=0 的实际调用副本墙面发生拓扑分割，原文件和有限域采样保持；不得笼统宣称墙面完全未变。OCCT native baseline自然端域观测也不等于四trim枚举已实现。']
    args.output.with_suffix('.md').write_text('\n'.join(text)+'\n')
    print(json.dumps({'audit_consistency_passed':consistency,'all_requested_modes_measured':complete,'rows':len(rows),'local_trim_subcriteria':{k:v['all_local_trim_subcriteria_passed'] for k,v in cross_modes.items()}},ensure_ascii=False))
    return 0 if consistency and (complete or not args.require_complete) and (report['occt_native_baseline_measured'] or not args.require_native) else 1

if __name__=='__main__':sys.exit(main())
