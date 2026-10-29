"""Explicit R8 cylindrical blend patches on the unchanged case36 supports.

These are constructed boundary controls, not a native face-face fillet call or
certification of Parasolid's general trim semantics. The output is only one
blend face; original walls remain exact input and separate auxiliary boundaries.
"""
from pathlib import Path
import argparse
import hashlib
from importlib.metadata import version
import importlib.util
import json
import math
import shutil
import sys

ROOT=Path(__file__).resolve().parents[3]
REQUESTS=ROOT/'data/case36-faceface/occt-requests.json'
PIN='7.9.3.1.1'
SOURCE_SHA='c88672f2fa73d5b40f13de10442dea5e432c6bd0b8f91db4412cd54fe6fbc5a1'

def read(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def relative(path):
    path=Path(path).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('Use repository-local artifact paths')
    return path.relative_to(ROOT).as_posix()
def geometry():
    spec=importlib.util.spec_from_file_location('case36_native_geometry',ROOT/'adapters/occt/original/geometry.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def support_geometry(source,g):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    faces=g.shapes(source,TopAbs_FACE);rows=[]
    if len(faces)!=2:raise ValueError('Expected original two finite support faces')
    vertical=horizontal=None
    for i,raw in enumerate(faces,1):
        face=TopoDS.Face_s(raw);ad=BRepAdaptor_Surface(face)
        if ad.GetType()!=GeomAbs_Plane:raise ValueError('Only the measured two-plane example is implemented')
        plane=ad.Plane();st=g.stats(face);n=g.xyz(plane.Axis().Direction());p=g.xyz(plane.Location());box=st['bbox_mm']
        row={'source_face_index_1based':i,'stats':st,'support_plane_normal':n,'support_plane_location':p,'x_interval_mm':[box[0],box[3]]}
        if abs(n[1])>1-1e-8 and abs(n[0])+abs(n[2])<1e-8:
            vertical=(face,row);row['role']='vertical_wall';row['plane_y_mm']=p[1]
        elif abs(n[2])>1-1e-8 and abs(n[0])+abs(n[1])<1e-8:
            horizontal=(face,row);row['role']='horizontal_wall';row['plane_z_mm']=p[2]
        else:raise ValueError('Unexpected plane frame')
        rows.append(row)
    if vertical is None or horizontal is None:raise ValueError('Both measured orthogonal support planes are required')
    gap=BRepExtrema_DistShapeShape(vertical[0],horizontal[0]);gap.Perform()
    return vertical,horizontal,{'faces':rows,'source_stats':g.stats(source),'finite_face_gap_mm':gap.Value()}

def boundaries(source,g):
    from OCP.TopAbs import TopAbs_FACE,TopAbs_EDGE
    from OCP.TopoDS import TopoDS
    return [{'id':f'original-wall-{i}-edge-{j}','target_kind':'auxiliary_guide','role':'original_finite_wall_boundary',
             'source_face_index_1based':i,'samples_mm':g.edge_record(source,TopoDS.Edge_s(edge))['polyline']}
            for i,face in enumerate(g.shapes(source,TopAbs_FACE),1)
            for j,edge in enumerate(g.shapes(face,TopAbs_EDGE),1)]

def mode_bounds(mode,vertical,horizontal,envelope):
    a,b=vertical['x_interval_mm'],horizontal['x_interval_mm']
    if mode=='short':
        bounds=[max(a[0],b[0]),min(a[1],b[1])]
        return bounds,bounds,'constant x bounds equal the intersection of measured wall x intervals'
    if mode=='long':
        bounds=[min(a[0],b[0]),max(a[1],b[1])]
        return bounds,bounds,'constant x bounds equal the envelope of measured wall x intervals; finite narrow-wall overhang remains visible'
    if mode=='no':
        return envelope,envelope,'finite working envelope only; no wall-based end trimming, and not an infinite or PDF-calibrated untrimmed result'
    if mode=='to_walls':
        return a,b,'explicit linear interpolation of cylinder UV end boundaries between the measured vertical and horizontal contact extents; not a general Parasolid trim law'
    raise ValueError('Unknown explicit mode')

def patch(radius,y0,z0,top,bottom):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge,BRepBuilderAPI_MakeWire,BRepBuilderAPI_MakeFace
    from OCP.BRepLib import BRepLib
    from OCP.GCE2d import GCE2d_MakeSegment
    from OCP.Geom import Geom_CylindricalSurface
    from OCP.gp import gp_Ax3,gp_Pnt,gp_Dir,gp_Pnt2d
    # S(theta,x) = (x, y0+R-R*cos(theta), z0+R-R*sin(theta)).
    surface=Geom_CylindricalSurface(gp_Ax3(gp_Pnt(0,y0+radius,z0+radius),gp_Dir(1,0,0),gp_Dir(0,-1,0)),radius)
    corners=[(0,top[0]),(math.pi/2,bottom[0]),(math.pi/2,bottom[1]),(0,top[1])]
    wire=BRepBuilderAPI_MakeWire()
    for a,b in zip(corners,corners[1:]+corners[:1]):
        curve=GCE2d_MakeSegment(gp_Pnt2d(*a),gp_Pnt2d(*b)).Value()
        maker=BRepBuilderAPI_MakeEdge(curve,surface)
        if not maker.IsDone():raise ValueError('UV boundary edge construction failed')
        wire.Add(maker.Edge())
    if not wire.IsDone():raise ValueError('UV boundary wire construction failed')
    maker=BRepBuilderAPI_MakeFace(surface,wire.Wire(),True)
    if not maker.IsDone():raise ValueError('Cylindrical patch construction failed')
    result=maker.Face()
    if not BRepLib.BuildCurves3d_s(result,1e-7):raise ValueError('3D boundary curve construction failed')
    return result,corners

def save_brep(shape,path):
    from OCP.BRepTools import BRepTools
    if not BRepTools.Write_s(shape,str(path)):raise ValueError('BREP write failed')

def step_roundtrip(shape,path,g):
    from OCP.STEPControl import STEPControl_Writer,STEPControl_Reader,STEPControl_AsIs
    from OCP.IFSelect import IFSelect_RetDone
    writer=STEPControl_Writer();transfer=writer.Transfer(shape,STEPControl_AsIs);written=writer.Write(str(path))
    report={'transfer':str(transfer),'write':str(written),'passed':False}
    if transfer==IFSelect_RetDone and written==IFSelect_RetDone:
        reader=STEPControl_Reader();status=reader.ReadFile(str(path));report['read']=str(status)
        if status==IFSelect_RetDone:
            reader.TransferRoots();inspection=g.inspect(reader.OneShape());report['readback']=inspection
            st=inspection['stats'];report['passed']=inspection['passed'] and st['faces']==1 and st['solids']==0
            report['relative_area_error']=abs(g.stats(shape)['area_mm2']-st['area_mm2'])/g.stats(shape)['area_mm2']
    return report

def actual_audit(result,vertical,horizontal,radius,y0,z0,g):
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.BRepLProp import BRepLProp_SLProps
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCP.TopAbs import TopAbs_EDGE,TopAbs_FACE
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Pnt
    faces=g.shapes(result,TopAbs_FACE)
    if len(faces)!=1:raise ValueError('Result must contain only the blend face')
    face=TopoDS.Face_s(faces[0]);ad=BRepAdaptor_Surface(face);surface=BRep_Tool.Surface_s(face)
    edge_rows=[{'native_edge_index_1based_diagnostic':i,**g.edge_record(result,TopoDS.Edge_s(e))} for i,e in enumerate(g.shapes(result,TopAbs_EDGE),1)]
    contacts=[];ends=[]
    for edge in edge_rows:
        points=edge['polyline']
        if all(abs(p[1]-y0)<1e-6 and abs(p[2]-(z0+radius))<1e-6 for p in points):support=vertical
        elif all(abs(p[2]-z0)<1e-6 and abs(p[1]-(y0+radius))<1e-6 for p in points):support=horizontal
        else:
            ends.append({'edge':edge,'x_range_mm':[min(p[0] for p in points),max(p[0] for p in points)],
                         'constant_x_end':max(p[0] for p in points)-min(p[0] for p in points)<1e-6})
            continue
        finite_face,wall=support;n=wall['support_plane_normal'];p0=wall['support_plane_location'];samples=[]
        for p in points:
            native_point=gp_Pnt(*p);project=GeomAPI_ProjectPointOnSurf(native_point,surface);u,v=project.LowerDistanceParameters()
            props=BRepLProp_SLProps(ad,u,v,2,1e-10);normal=g.xyz(props.Normal())
            cos=abs(sum(a*b for a,b in zip(normal,n)));angle=math.degrees(math.acos(max(-1,min(1,cos))))
            query=BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(native_point).Vertex(),finite_face);query.Perform()
            state=str(BRepClass_FaceClassifier(finite_face,native_point,1e-7).State()).split('.')[-1]
            samples.append({'point_mm':p,'finite_face_state':state,'within_original_finite_face':state in ['TopAbs_IN','TopAbs_ON'],
                            'g0_underlying_plane_error_mm':abs(sum(a*(b-c) for a,b,c in zip(n,p,p0))),
                            'g0_finite_face_distance_mm':query.Value(),'g1_tangent_plane_angle_deg':angle,
                            'actual_surface_projection_error_mm':project.LowerDistance()})
        contacts.append({'support_role':wall['role'],'source_face_index_1based':wall['source_face_index_1based'],
                         'edge':edge,'endpoints_mm':[points[0],points[-1]],'x_interval_mm':[min(p[0] for p in points),max(p[0] for p in points)],
                         'samples':samples,'all_samples_within_original_finite_face':all(s['within_original_finite_face'] for s in samples),
                         'max_g0_underlying_plane_error_mm':max(s['g0_underlying_plane_error_mm'] for s in samples),
                         'max_g0_finite_face_distance_mm':max(s['g0_finite_face_distance_mm'] for s in samples),
                         'max_g1_tangent_plane_angle_deg':max(s['g1_tangent_plane_angle_deg'] for s in samples)})
    curvature=[]
    for fu in [.1,.3,.5,.7,.9]:
        u=fu*math.pi/2
        # Use actual finite boundary x spans, interpolated only to choose interior samples.
        a=next(c for c in contacts if c['support_role']=='vertical_wall')['x_interval_mm'];b=next(c for c in contacts if c['support_role']=='horizontal_wall')['x_interval_mm']
        left=a[0]+fu*(b[0]-a[0]);right=a[1]+fu*(b[1]-a[1])
        for fv in [.1,.5,.9]:
            v=left+fv*(right-left);props=BRepLProp_SLProps(ad,u,v,2,1e-10);ks=[props.MinCurvature(),props.MaxCurvature()]
            curvature.append({'point_mm':g.xyz(props.Value()),'principal_curvatures_mm_inverse':ks,
                              'radius_from_principal_curvature_mm':1/max(abs(k) for k in ks),
                              'radial_distance_to_axis_mm':math.hypot(props.Value().Y()-(y0+radius),props.Value().Z()-(z0+radius))})
    return {'contacts':contacts,'ends':ends,'curvature_samples':curvature,
            'radius_range_mm':[min(s['radius_from_principal_curvature_mm'] for s in curvature),max(s['radius_from_principal_curvature_mm'] for s in curvature)],
            'both_underlying_support_planes_g0_g1_sampled_passed':len(contacts)==2 and all(c['max_g0_underlying_plane_error_mm']<1e-6 and c['max_g1_tangent_plane_angle_deg']<1e-4 for c in contacts),
            'both_original_finite_faces_contacted_over_full_track':len(contacts)==2 and all(c['all_samples_within_original_finite_face'] for c in contacts),
            'scope':'Sampled local contact and curvature checks. Infinite-plane G0/G1, finite-face attachment, CAD validity, trim semantics and human acceptance remain separate.'}

def run(mode,request,out,g,source_file,source_hash):
    source=g.read(source_file);vertical,horizontal,measurements=support_geometry(source,g)
    radius=float(request['radius_mm']);top,bottom,rule=mode_bounds(mode,vertical[1],horizontal[1],request['untrimmed_working_envelope_x_mm'])
    y0=vertical[1]['plane_y_mm'];z0=horizontal[1]['plane_z_mm']
    run_dir=out/mode;run_dir.mkdir(parents=True)
    shutil.copyfile(source_file,run_dir/'before.brep');write(run_dir/'before.mesh.json',g.mesh(source))
    wall_lines=boundaries(source,g);write(run_dir/'wall-boundaries.json',wall_lines)
    report={'schema':'case36.explicit-faceface-trim.v1','number':36,'mode':mode,'radius_mm':radius,
            'engine':'OCCT','engine_version':'7.9.3','binding_version':version('cadquery-ocp'),
            'source_brep':relative(source_file),'source_sha256':source_hash,'operation_input_sha256':sha(run_dir/'before.brep'),
            'request_file':relative(REQUESTS),'request_sha256':sha(REQUESTS),'adapter_sha256':sha(__file__),
            'method':'explicit_occ_composition','method_label':'显式端边界插值构造，尚非Parasolid一般语义认证' if mode=='to_walls' else '显式圆柱过渡面及端部边界控制',
            'native_face_face_call':False,'native_edge_fillet_call':False,'native_call_executed':False,'api_success':None,
            'construction_executed':False,'walls_modified':False,'result_kind':'single_blend_face','original_walls_added_to_result':False,
            'source_feature_certified':False,'source_feature_passed':False,'human_appearance_acceptance':False,
            'selected_source_faces':[vertical[1],horizontal[1]],'source_measurements':measurements,
            'parameters':{'radius_mm':radius,'cylinder_center_yz_mm':[y0+radius,z0+radius],'theta_range_rad':[0,math.pi/2],
                          'vertical_contact_x_mm':top,'horizontal_contact_x_mm':bottom,'end_boundary_law':rule,
                          'working_envelope_x_mm':request['untrimmed_working_envelope_x_mm'] if mode=='no' else None,
                          'work_envelope_is_pdf_dimension':False,'to_walls_general_law_certified':False},
            'outcome':'started','artifacts':{'before_brep':'before.brep','before_mesh':'before.mesh.json','original_wall_boundaries':'wall-boundaries.json'}}
    write(run_dir/'summary.json',report)
    try:
        result,uv=patch(radius,y0,z0,top,bottom);report['construction_executed']=True
        report['construction_apis']=['Geom_CylindricalSurface','GCE2d_MakeSegment','BRepBuilderAPI_MakeEdge(curve2d,surface)','BRepBuilderAPI_MakeWire','BRepBuilderAPI_MakeFace(surface,wire)','BRepLib.BuildCurves3d']
        report['parameters']['uv_boundary_corners_theta_x']=uv
        save_brep(result,run_dir/'result.brep');report['result_brep_sha256']=sha(run_dir/'result.brep')
        result=g.read(run_dir/'result.brep');report['result_inspection']=g.inspect(result)
        report['result_stats']=g.stats(result);write(run_dir/'result.mesh.json',g.mesh(result))
        report['step_roundtrip']=step_roundtrip(result,run_dir/'result.step',g)
        report['actual_geometry']=actual_audit(result,vertical,horizontal,radius,y0,z0,g)
        report['construction_checks']={'one_face_no_added_walls':report['result_stats']['faces']==1 and report['result_stats']['solids']==0 and report['result_stats']['shells']==0,
                                       'brep_and_bop':report['result_inspection']['passed'],'step_roundtrip':report['step_roundtrip']['passed'],
                                       'radius':all(abs(r-radius)<1e-6 for r in report['actual_geometry']['radius_range_mm']),
                                       'underlying_plane_g0_g1_sampled':report['actual_geometry']['both_underlying_support_planes_g0_g1_sampled_passed']}
        report['outcome']='explicit_candidate' if all(report['construction_checks'].values()) else 'explicit_geometry_failed'
        report['artifacts'].update(result_brep='result.brep',result_step='result.step',result_mesh='result.mesh.json')
        witnesses=[{'id':'actual-'+c['support_role']+'-contact','target_kind':'result_witness','label':'实际接触轨 / '+c['support_role'],'samples_mm':c['edge']['polyline']} for c in report['actual_geometry']['contacts']]
        write(run_dir/'contact-witnesses.json',witnesses);report['artifacts']['actual_contact_witnesses']='contact-witnesses.json'
    except Exception as error:
        report['outcome']='construction_exception';report['error']=type(error).__name__+': '+str(error)
    report['source_unchanged']=sha(source_file)==source_hash
    report['before_equals_exact_source_bytes']=sha(run_dir/'before.brep')==source_hash
    report['validation_boundary']='Only an explicit analytic cylindrical patch with the declared local boundary rule. Finite wall overhang is measured, not hidden; no general native face-face or Parasolid trim-mode acceptance.'
    write(run_dir/'summary.json',report)
    return {'mode':mode,'radius_mm':radius,'run_dir':relative(run_dir),'summary':relative(run_dir/'summary.json'),'summary_sha256':sha(run_dir/'summary.json'),
            'source_sha256':source_hash,'operation_input_sha256':sha(run_dir/'before.brep'),'outcome':report['outcome'],
            **{key:relative(run_dir/name) for key,name in [('before_brep','before.brep'),('before_mesh','before.mesh.json'),('result_brep','result.brep'),('result_step','result.step'),('result_mesh','result.mesh.json')] if (run_dir/name).exists()}}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('runs/case36-faceface/occt-composite'))
    parser.add_argument('--mode',choices=['short','long','no','to_walls'])
    args=parser.parse_args();out=args.output.resolve();relative(out)
    if out.exists() and any(out.iterdir()):parser.error('Refusing to overwrite existing evidence; use a fresh output')
    if version('cadquery-ocp')!=PIN:raise ValueError('Pinned cadquery-ocp required')
    request=read(REQUESTS);source_file=ROOT/request['source_brep'];source_hash=sha(source_file)
    if source_hash!=SOURCE_SHA or request['source_sha256']!=source_hash:raise ValueError('Exact original source identity mismatch')
    out.mkdir(parents=True,exist_ok=True);g=geometry();modes=[args.mode] if args.mode else request['modes'];rows=[]
    for mode in modes:
        rows.append(run(mode,request,out,g,source_file,source_hash))
        write(out/'index.json',{'schema':'case36.explicit-faceface-run-index.v1','engine':'OCCT','source_sha256':source_hash,
                               'method':'explicit_occ_composition','native_face_face_call':False,'radius_mm':request['radius_mm'],'rows':rows,
                               'source_unchanged':sha(source_file)==source_hash})
        print(json.dumps({'mode':mode,'outcome':rows[-1]['outcome'],'summary':rows[-1]['summary']}),flush=True)
    return 0 if all(row['outcome']=='explicit_candidate' for row in rows) else 1

if __name__=='__main__':sys.exit(main())
