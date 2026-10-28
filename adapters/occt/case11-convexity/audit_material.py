#!/usr/bin/env python3
"""Independent, read-only case11 candidate material/topology audit.

Usage: python adapters/occt/case11-convexity/audit_material.py
No author report or pass boolean is used as evidence.
"""
import argparse,collections,hashlib,json,math,tempfile,time
from pathlib import Path
import numpy as np
from OCP.BRep import BRep_Builder,BRep_Tool
from OCP.BRepTools import BRepTools
from OCP.TopoDS import TopoDS_Shape,TopoDS
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID,TopAbs_SHELL,TopAbs_FACE,TopAbs_EDGE,TopAbs_IN,TopAbs_OUT,TopAbs_ON,TopAbs_REVERSED
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepAdaptor import BRepAdaptor_Curve,BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
from OCP.gp import gp_Pnt,gp_Pnt2d,gp_Pln,gp_Dir,gp_Vec
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.BOPAlgo import BOPAlgo_ArgumentAnalyzer
from OCP.STEPControl import STEPControl_Reader,STEPControl_Controller
from OCP.IFSelect import IFSelect_RetDone

ap=argparse.ArgumentParser()
ap.add_argument('--candidate',default='candidate-v6')
ap.add_argument('--source',type=Path,default=Path('data/case11-convexity/candidate-v6.brep'))
ap.add_argument('--step',type=Path,default=Path('data/case11-convexity/candidate-v6.step'))
ap.add_argument('--output',type=Path,default=Path('runs/case11-material-audit'))
args=ap.parse_args()
ROOT=Path(__file__).resolve().parents[3];OUT=args.output
MODEL=args.source;STEP=args.step
def arr(p):return np.array([p.X(),p.Y(),p.Z()],dtype=float)
def point(p):return gp_Pnt(*map(float,p))
def unit(v):return v/np.linalg.norm(v)
def raw_shapes(s,typ):
    result=[];it=TopExp_Explorer(s,typ)
    while it.More():result.append(it.Current());it.Next()
    return result
def shapes(s,typ):
    result=[]
    for q in raw_shapes(s,typ):
        if not any(q.IsSame(x) for x in result):result.append(q)
    return result
def load_brep(path):
    s=TopoDS_Shape();assert BRepTools.Read_s(s,str(path),BRep_Builder());return s
def mass(s):
    g=GProp_GProps();BRepGProp.VolumeProperties_s(s,g);return g.Mass()
def bop(s):
    check=BOPAlgo_ArgumentAnalyzer();check.SetShape1(s)
    for key in ['ArgumentTypeMode','SelfInterMode','SmallEdgeMode','RebuildFaceMode','ContinuityMode','CurveOnSurfaceMode']:setattr(check,key,True)
    check.StopOnFirstFaulty=False;check.Perform()
    faults=[str(q.GetCheckStatus()).split('.')[-1] for q in check.GetCheckResult()]
    return {'faults':faults,'passed':not faults,'modes':['ArgumentType','SelfInter','SmallEdge','RebuildFace','Continuity','CurveOnSurface']}
def topology(s):
    faces=shapes(s,TopAbs_FACE);edges=shapes(s,TopAbs_EDGE);rows=[]
    for i,e in enumerate(edges):
        ownerids=[];uses=0
        for j,f in enumerate(faces):
            n=sum(q.IsSame(e) for q in raw_shapes(f,TopAbs_EDGE))
            if n:ownerids.append(j+1);uses+=n
        rows.append({'edge':i+1,'owners':ownerids,'owner_count':len(ownerids),'loop_use_count':uses})
    return {'solid_count':len(shapes(s,TopAbs_SOLID)),'shell_count':len(shapes(s,TopAbs_SHELL)),
      'face_count':len(faces),'edge_count':len(edges),'edge_rows':rows,
      'edge_owner_histogram':dict(collections.Counter(q['owner_count'] for q in rows)),
      'edge_loop_use_histogram':dict(collections.Counter(q['loop_use_count'] for q in rows)),
      'all_edges_two_owners_two_loop_uses':all(q['owner_count']==q['loop_use_count']==2 for q in rows)}
def native(s):
    solids=shapes(s,TopAbs_SOLID)
    classifier=BRepClass3d_SolidClassifier(TopoDS.Solid_s(solids[0])) if len(solids)==1 else None
    if classifier:classifier.PerformInfinitePoint(1e-7)
    return {'brepcheck_valid':BRepCheck_Analyzer(s,True).IsValid(),'signed_volume_mm3':mass(s),
      'single_solid':len(solids)==1,'infinite_point_state':str(classifier.State()).split('.')[-1] if classifier else None,
      'topology':topology(s),'bop':bop(s)}
def normal(face,p):
    f=TopoDS.Face_s(face);surf=BRep_Tool.Surface_s(f)
    proj=GeomAPI_ProjectPointOnSurf(point(p),surf);u,v=proj.LowerDistanceParameters()
    pnt=gp_Pnt();du=gp_Vec();dv=gp_Vec();surf.D1(u,v,pnt,du,dv)
    n=unit(np.cross(arr(du),arr(dv)))
    if f.Orientation()==TopAbs_REVERSED:n=-n
    return n,arr(pnt),[u,v]
def curvatures(face,u,v):
    ad=BRepAdaptor_Surface(TopoDS.Face_s(face));p=arr(ad.Value(u,v));n,_,_=normal(face,p);h=1e-4;ks=[]
    for delta in [(h,0),(0,h)]:
        pu=arr(ad.Value(u+delta[0],v+delta[1]));mu=arr(ad.Value(u-delta[0],v-delta[1]));d=(pu-mu)/(2*h)
        ks.append(float(np.dot(n,(pu-2*p+mu)/(h*h))/np.dot(d,d)))
    return p,n,ks
def curve_points(e,count=33):
    ad=BRepAdaptor_Curve(TopoDS.Edge_s(e));lo,hi=ad.FirstParameter(),ad.LastParameter()
    return [arr(ad.Value(lo+t*(hi-lo))).tolist() for t in np.linspace(0,1,count)]
def section(s,p,n):
    sec=BRepAlgoAPI_Section(s,gp_Pln(point(p),gp_Dir(*map(float,n))),False);sec.Build()
    return {'done':sec.IsDone(),'edge_polylines_world':[curve_points(q) for q in shapes(sec.Shape(),TopAbs_EDGE)]}

started=time.monotonic();sha_before=hashlib.sha256(MODEL.read_bytes()).hexdigest();s=load_brep(MODEL)
solids=shapes(s,TopAbs_SOLID);assert len(solids)==1
solid=TopoDS.Solid_s(solids[0]);cls=BRepClass3d_SolidClassifier(solid)
def state(p,tol=1e-8):
    cls.Perform(point(p),tol);return {TopAbs_IN:'IN',TopAbs_OUT:'OUT',TopAbs_ON:'ON'}.get(cls.State(),'UNKNOWN')
report={'schema':'case11.new_geometry_independent_audit.v1','candidate':args.candidate,'model':str(MODEL),
  'sha256':sha_before,'engine':'OCP 7.9.3.1','author_report_used_as_evidence':False,
  'source_geometry_or_web_modified':False,
  'scope':'Independent BREP material/topology and STEP gates; no source hidden-material certainty or human appearance acceptance implied.'}
report['native']=native(s)
print(args.candidate,'native completed',flush=True)
with tempfile.TemporaryDirectory(prefix='case11-brep-readback-') as tmp:
    p=Path(tmp)/'readback.brep';BRepTools.Write_s(s,str(p));restored=load_brep(p)
    report['brep_roundtrip']=native(restored)
    report['brep_roundtrip']['relative_volume_delta']=abs(mass(restored)-mass(s))/mass(s)
STEPControl_Controller.Init_s();reader=STEPControl_Reader();read_status=reader.ReadFile(str(STEP));transfer=reader.TransferRoots() if read_status==IFSelect_RetDone else 0
report['step_roundtrip']={'path':str(STEP),'sha256':hashlib.sha256(STEP.read_bytes()).hexdigest(),'read_status':str(read_status),'transferred_root_count':transfer}
if transfer:
    restored=reader.OneShape();report['step_roundtrip'].update(native(restored));report['step_roundtrip']['relative_volume_delta']=abs(mass(restored)-mass(s))/mass(s)
print(args.candidate,'readbacks completed',flush=True)
ends=np.array([[50.,0,0],[50.,-60.6,0]])
edge_matches=[]
for i,e in enumerate(shapes(solid,TopAbs_EDGE)):
    pts=np.array(curve_points(e,2));gap=min(np.linalg.norm(pts-ends),np.linalg.norm(pts-ends[::-1]))
    if gap<1e-7:edge_matches.append((i+1,e))
assert len(edge_matches)==1,len(edge_matches)
edge_index,e=edge_matches[0];owners=[]
for i,f in enumerate(shapes(solid,TopAbs_FACE)):
    if any(q.IsSame(e) for q in shapes(f,TopAbs_EDGE)):owners.append((i+1,f))
assert len(owners)==2
tangent=unit(ends[1]-ends[0]);e1=np.array([1.,0,0]);e2=np.array([0.,0,1.]);mid=ends.mean(axis=0)
target={'edge_index':edge_index,'endpoints':ends.tolist(),'physical_section_basis':[e1.tolist(),e2.tolist()],
  'stations':[],'adjacent_faces':[]}
for i,f in owners:
    n,p,uv=normal(f,mid);d=unit(np.cross(tangent,n));witness=[]
    for sign in [-1,1]:
        pp=p+sign*.25*d
        if state(pp-.01*n)=='IN' and state(pp+.01*n)=='OUT':witness.append(pp)
    target['adjacent_faces'].append({'face_index':i,'outward_normal':n.tolist(),'orientation':str(f.Orientation()),
      'normal_witness_verified':bool(witness),'witness_point':witness[0].tolist() if witness else None,
      'minus_normal_state':'IN' if witness else None,'plus_normal_state':'OUT' if witness else None})
dot=float(np.dot(*[np.array(q['outward_normal']) for q in target['adjacent_faces']]))
angle=math.degrees(math.acos(np.clip(dot,-1,1)));target.update(outward_normals_dot=dot,outward_normals_angle_deg=angle)
N=1440
for fraction in [.1,.25,.5,.75,.9]:
    p=ends[0]+fraction*(ends[1]-ends[0]);row={'fraction':fraction,'point':p.tolist(),'section':section(solid,p,tangent),'rings':[]}
    for r in [.5,.1,.01]:
        statuses=[state(p+r*(math.cos(2*math.pi*k/N)*e1+math.sin(2*math.pi*k/N)*e2)) for k in range(N)]
        counts=dict(collections.Counter(statuses));row['rings'].append({'radius_mm':r,'sample_count':N,'state_counts':counts,
          'material_angle_deg_sampled':360*counts.get('IN',0)/N,'on_angle_deg_sampled':360*counts.get('ON',0)/N,
          'air_angle_deg_sampled':360*counts.get('OUT',0)/N})
    target['stations'].append(row)
    print(args.candidate,'station',fraction,[q['material_angle_deg_sampled'] for q in row['rings']],flush=True)
target['convex_at_all_stations_and_radii']=all(q['material_angle_deg_sampled']<180 for row in target['stations'] for q in row['rings'])
target['about_90_degrees_at_all_stations_and_radii']=all(abs(q['material_angle_deg_sampled']-90)<=.5 for row in target['stations'] for q in row['rings'])
target['exact_interior_material_angle_deg']=180-angle if target['convex_at_all_stations_and_radii'] else 180+angle
target['quadrant_witnesses']=[{'point':[50+dx,yy,dz],'state':state([50+dx,yy,dz])} for yy in [-10,-30,-50] for dx,dz in [(-.2,.2),(.2,.2),(-.2,-.2),(.2,-.2)]]
report['target_A']=target

curved=[]
for i,f in enumerate(shapes(solid,TopAbs_FACE)):
    ad=BRepAdaptor_Surface(TopoDS.Face_s(f));u0,u1=ad.FirstUParameter(),ad.LastUParameter();v0,v1=ad.FirstVParameter(),ad.LastVParameter()
    pts=[]
    for fu in [.2,.5,.8]:
        for fv in [.2,.5,.8]:
            u=u0+fu*(u1-u0);v=v0+fv*(v1-v0)
            if BRepClass_FaceClassifier(TopoDS.Face_s(f),gp_Pnt2d(u,v),1e-8).State()!=TopAbs_IN:continue
            p,n,ks=curvatures(f,u,v)
            if 53.01<p[0]<99.99 and -61<p[1]<-45:pts.append((p,n,ks))
    if not pts or max(np.linalg.norm(pts[0][1]-q[1]) for q in pts)<.01:continue
    samples=[]
    for p,n,ks in pts:
        offsets=[{'offset_mm':eps,'minus_normal_state':state(p-eps*n),'plus_normal_state':state(p+eps*n)} for eps in [.01,.05,.25]]
        samples.append({'point':p.tolist(),'outward_normal':n.tolist(),'minus_normal_state':state(p-.01*n),
          'plus_normal_state':state(p+.01*n),'normal_curvatures_mm_inv':ks,
          'normal_offset_tests':offsets,
          'convex_material_curvature':min(ks)<-.001 and max(ks)<.001})
    curved.append({'face_index':i+1,'surface_type':str(ad.GetType()).split('.')[-1],
       'samples':samples,'all_normal_witnesses_verified':all(o['minus_normal_state']=='IN' and o['plus_normal_state']=='OUT' for q in samples for o in q['normal_offset_tests']),
       'all_samples_convex_material_curvature':all(q['convex_material_curvature'] for q in samples),
       'mean_z':float(np.mean([q['point'][2] for q in samples]))})
report['curved_faces_near_existing_band']=curved
verified_convex=[q for q in curved if q['all_normal_witnesses_verified'] and q['all_samples_convex_material_curvature']]
visible=max(curved,key=lambda q:q['mean_z']) if curved else None
report['visible_band']={'selection_method':'curved face near x53..100,y-61..-45 with verified outward normal and negative nonzero material curvature; upper mean-z picks visible side',
   'candidate_face_indices':[q['face_index'] for q in verified_convex],
   'face':visible,
   'passed':bool(visible and visible['all_normal_witnesses_verified'] and visible['all_samples_convex_material_curvature'])}
report['band_real_section_at_x75']=section(solid,[75.,0,0],[1.,0,0])
report['sha256_after']=hashlib.sha256(MODEL.read_bytes()).hexdigest();report['source_unchanged']=sha_before==report['sha256_after']
def native_pass(q):return q['brepcheck_valid'] and q['single_solid'] and q['signed_volume_mm3']>0 and q['infinite_point_state']=='TopAbs_OUT' and q['topology']['all_edges_two_owners_two_loop_uses'] and q['bop']['passed']
report['gates']={'native':native_pass(report['native']),'brep_roundtrip':native_pass(report['brep_roundtrip']),
 'step_roundtrip':bool(transfer) and native_pass(report['step_roundtrip']),
 'brep_roundtrip_volume_match':report['brep_roundtrip']['relative_volume_delta']<1e-8,
 'step_roundtrip_volume_match':bool(transfer) and report['step_roundtrip']['relative_volume_delta']<1e-8,
 'A_convex_physical_material_angle':target['convex_at_all_stations_and_radii'],
 'A_90_degree_physical_material_angle':target['about_90_degrees_at_all_stations_and_radii'],
 'A_outward_normals_verified':all(q['normal_witness_verified'] for q in target['adjacent_faces']),
 'actual_sections_completed':all(q['section']['done'] for q in target['stations']) and report['band_real_section_at_x75']['done'],
 'visible_band_convex_curvature_and_material_side':report['visible_band']['passed'],'model_unchanged':report['source_unchanged']}
report['automated_gates_passed']=all(report['gates'].values());report['human_appearance_status']='pending'
report['original_reference_hidden_material_status']='inferred reconstruction; not determined by this audit'
report['elapsed_seconds']=time.monotonic()-started
OUT.mkdir(parents=True,exist_ok=True);out=OUT/'new-geometry-audit.json';out.write_text(json.dumps(report,indent=2)+'\n')
# Preserve version evidence before a newer final candidate replaces the entry.
(OUT/f'new-geometry-audit-{args.candidate}.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'candidate':args.candidate,'sha256':sha_before,'gates':report['gates'],
  'native_topology':{k:v for k,v in report['native']['topology'].items() if k!='edge_rows'},
  'A_exact_angle':target['exact_interior_material_angle_deg'],
  'band_face':report['visible_band']['face']['face_index'] if report['visible_band']['face'] else None,
  'elapsed_seconds':report['elapsed_seconds']},indent=2))
