"""Call native OCCT surface/surface rolling-ball walking on exact case36 faces.

OCP 7.9 exposes the algorithms but lacks a constructible math_Vector argument.
This probe compiles an ordinary C++ caller against a user-selected OCCT SDK.
The caller reads the original BREP faces and uses their original finite domains.
No input extension, equal-width shell, sweep, or hand-built fillet is performed.
There is no Parasolid four-trim enum in the selected low-level OCCT API.
"""
from pathlib import Path
import argparse,datetime,hashlib,importlib.util,json,math,os,shutil,subprocess,sys
from importlib.metadata import version

ROOT=Path(__file__).resolve().parents[3]
SOURCE='data/original-occ/fixtures/c88672f2fa73d5b40f13de10442dea5e432c6bd0b8f91db4412cd54fe6fbc5a1.brep'
SHA='c88672f2fa73d5b40f13de10442dea5e432c6bd0b8f91db4412cd54fe6fbc5a1'
CPP=r'''
#include <BRep_Builder.hxx>
#include <BRepTools.hxx>
#include <BRep_Tool.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepTopAdaptor_TopolTool.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <BRepBlend_Walking.hxx>
#include <BRepBlend_Line.hxx>
#include <BRepBlend_AppFunc.hxx>
#include <BRepBlend_AppSurf.hxx>
#include <BlendFunc_ConstRad.hxx>
#include <BlendFunc_ConstRadInv.hxx>
#include <Blend_Point.hxx>
#include <ChFiDS_ElSpine.hxx>
#include <Geom_Line.hxx>
#include <Geom_BSplineSurface.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <STEPControl_Writer.hxx>
#include <Standard_Version.hxx>
#include <gp_Lin.hxx>
#include <gp_Circ.hxx>
#include <math_Vector.hxx>
#include <IntAna_QuadQuadGeo.hxx>
#include <fstream>
#include <iostream>
#include <iomanip>
#include <vector>
#include <cmath>
#include <string>

int main(int argc,char**argv) {
  const std::string source=argv[1], dest=argv[2];
  const int choice=std::stoi(argv[3]); const double radius=8.;
  std::ofstream out(dest+"/native.json");out<<std::setprecision(17)<<std::boolalpha;
  bool walked=false,approximated=false;
  try {
    TopoDS_Shape shape;BRep_Builder builder;
    if(!BRepTools::Read(shape,source.c_str(),builder))throw std::runtime_error("BREP read failed");
    std::vector<TopoDS_Face> faces;
    for(TopExp_Explorer it(shape,TopAbs_FACE);it.More();it.Next())faces.push_back(TopoDS::Face(it.Current()));
    if(faces.size()!=2)throw std::runtime_error("Expected exactly two original faces");
    Handle(BRepAdaptor_Surface) s1=new BRepAdaptor_Surface(faces[0],true),s2=new BRepAdaptor_Surface(faces[1],true);
    Handle(BRepTopAdaptor_TopolTool) d1=new BRepTopAdaptor_TopolTool(s1),d2=new BRepTopAdaptor_TopolTool(s2);
    Handle(ChFiDS_ElSpine) guide=new ChFiDS_ElSpine;
    // Compute the guide from the actual original supporting planes. It is not
    // a common edge or a replacement for either original finite face.
    const gp_Pln plane1=s1->Plane(),plane2=s2->Plane();
    IntAna_QuadQuadGeo intersection(plane1,plane2,1.e-12,1.e-7);
    if(!intersection.IsDone()||intersection.NbSolutions()!=1)throw std::runtime_error("Expected unique original plane intersection");
    gp_Lin axis=intersection.Line(1);if(axis.Direction().X()<0.)axis.Reverse();
    double first=1.e100,last=-1.e100;
    for(TopExp_Explorer it(shape,TopAbs_VERTEX);it.More();it.Next()){
      const double t=gp_Vec(axis.Location(),BRep_Tool::Pnt(TopoDS::Vertex(it.Current()))).Dot(gp_Vec(axis.Direction()));
      first=std::min(first,t);last=std::max(last,t);
    }
    const double middle=(first+last)/2.;
    guide->SetCurve(new Geom_Line(axis));guide->FirstParameter(first);guide->LastParameter(last);
    BlendFunc_ConstRad function(s1,s2,guide);function.Set(radius,choice);function.Set(BlendFunc_Rational);function.Set(middle);
    BlendFunc_ConstRadInv inverse(s1,s2,guide);inverse.Set(radius,choice);
    // Offset planes are an initial center guess only. Native walking receives
    // the unmodified original faces/domains and solves its own constraints.
    gp_Pln offset1=plane1,offset2=plane2;offset1.Translate(gp_Vec(plane1.Axis().Direction())*(-radius));offset2.Translate(gp_Vec(plane2.Axis().Direction())*radius);
    IntAna_QuadQuadGeo centers(offset1,offset2,1.e-12,1.e-7);
    if(!centers.IsDone()||centers.NbSolutions()!=1)throw std::runtime_error("Offset support center initialization failed");
    gp_Pnt center=centers.Line(1).Location();
    center.Translate(gp_Vec(axis.Direction())*(middle-gp_Vec(axis.Location(),center).Dot(gp_Vec(axis.Direction()))));
    GeomAPI_ProjectPointOnSurf p1(center,BRep_Tool::Surface(faces[0]));
    GeomAPI_ProjectPointOnSurf p2(center,BRep_Tool::Surface(faces[1]));
    double u1,v1,u2,v2;p1.LowerDistanceParameters(u1,v1);p2.LowerDistanceParameters(u2,v2);
    math_Vector seed(1,4),residual(1,4);seed(1)=u1;seed(2)=v1;seed(3)=u2;seed(4)=v2;
    bool evaluated=function.Value(seed,residual);double norm=0.;for(int i=1;i<=4;++i)norm+=residual(i)*residual(i);
    bool solution=function.IsSolution(seed,1.e-7);
    out<<"{\"engine_version\":\""<<OCC_VERSION_COMPLETE<<"\",\"choice\":"<<choice<<",\"radius_mm\":8,\"guide_parameter_range_from_original_vertex_projections\":["<<first<<","<<last<<"],\"seed_center_from_original_offset_planes\":["<<center.X()<<","<<center.Y()<<","<<center.Z()<<"],\"seed_value_called\":true,\"seed_evaluated\":"<<evaluated<<",\"seed_residual_norm\":"<<std::sqrt(norm)<<",\"seed_is_solution\":"<<solution;
    if(!evaluated || !solution || norm>1.e-10){out<<",\"native_walking_called\":false,\"status\":\"seed_quadrant_mismatch\"}";return 0;}
    gp_Circ circle;double start,end;function.Section(middle,u1,v1,u2,v2,start,end,circle);
    out<<",\"native_section_angle_rad\":"<<end-start<<",\"native_section_radius_mm\":"<<circle.Radius();
    BRepBlend_Walking walk(s1,s2,d1,d2,guide);
    walked=true;walk.Perform(function,inverse,middle,last,1.,1.e-7,1.e-7,seed,1.e-3,false);
    out<<",\"native_walking_called\":true,\"walking_done\":"<<walk.IsDone();
    if(!walk.IsDone()){out<<",\"status\":\"native_walking_not_done\"}";return 0;}
    bool completed=walk.Complete(function,inverse,first);Handle(BRepBlend_Line) line=walk.Line();
    out<<",\"walking_completed_backward\":"<<completed<<",\"line_point_count\":"<<line->NbPoints()<<",\"line\":[";
    for(int i=1;i<=line->NbPoints();++i){const Blend_Point& p=line->Point(i);const gp_Pnt a=p.PointOnS1(),b=p.PointOnS2();
      BRepClass_FaceClassifier ca(faces[0],a,1.e-6),cb(faces[1],b,1.e-6);
      if(i>1)out<<",";out<<"{\"guide_parameter\":"<<p.Parameter()<<",\"contact1\":["<<a.X()<<","<<a.Y()<<","<<a.Z()<<"],\"contact2\":["<<b.X()<<","<<b.Y()<<","<<b.Z()<<"],\"on_original_face1\":"<<(ca.State()==TopAbs_IN||ca.State()==TopAbs_ON)<<",\"on_original_face2\":"<<(cb.State()==TopAbs_IN||cb.State()==TopAbs_ON)<<"}";
    }
    out<<"]";out.flush();
    if(line->NbPoints()<2){out<<",\"status\":\"native_line_too_short\"}";return 0;}
    BRepBlend_AppSurf approx(3,8,1.e-7,1.e-7,8,true);approximated=true;approx.Perform(line,function,true);
    out<<",\"native_approximation_called\":true,\"approximation_done\":"<<approx.IsDone();
    if(!approx.IsDone()){out<<",\"status\":\"native_approximation_not_done\"}";return 0;}
    Handle(Geom_BSplineSurface) surface=new Geom_BSplineSurface(approx.SurfPoles(),approx.SurfWeights(),approx.SurfUKnots(),approx.SurfVKnots(),approx.SurfUMults(),approx.SurfVMults(),approx.UDegree(),approx.VDegree());
    TopoDS_Face result=BRepBuilderAPI_MakeFace(surface,1.e-7).Face();
    BRepTools::Write(result,(dest+"/result.brep").c_str());
    STEPControl_Writer writer;int transfer=writer.Transfer(result,STEPControl_AsIs);int write=writer.Write((dest+"/result.step").c_str());
    out<<",\"result_brep_valid\":"<<BRepCheck_Analyzer(result,true).IsValid()<<",\"step_transfer_status\":"<<transfer<<",\"step_write_status\":"<<write<<",\"surface_u_degree\":"<<surface->UDegree()<<",\"surface_v_degree\":"<<surface->VDegree()<<",\"status\":\"native_surface_candidate\"}";
  } catch(const Standard_Failure& error) {out<<",\"native_walking_called_at_exception\":"<<walked<<",\"native_approximation_called_at_exception\":"<<approximated<<",\"status\":\"native_exception\",\"error\":\""<<error.GetMessageString()<<"\"}";return 2;}
    catch(const std::exception& error) {out<<"{\"status\":\"caller_exception\",\"error\":\""<<error.what()<<"\"}";return 3;}
  return 0;
}
'''

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def relative(path):
    path=Path(path).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('Run output must be inside the repository')
    return path.relative_to(ROOT).as_posix()
def binding_boundary(shape,g):
    """Retain an actually attempted Python-argument conversion boundary."""
    from OCP import BRepAdaptor,BlendFunc,ChFiDS,Geom,gp,TColStd,math as ocp_math
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    faces=g.shapes(shape,TopAbs_FACE)
    s1=BRepAdaptor.BRepAdaptor_Surface(TopoDS.Face_s(faces[0]),True)
    s2=BRepAdaptor.BRepAdaptor_Surface(TopoDS.Face_s(faces[1]),True)
    guide=ChFiDS.ChFiDS_ElSpine();guide.SetCurve(Geom.Geom_Line(gp.gp_Lin(gp.gp_Pnt(),gp.gp_Dir(1,0,0))))
    function=BlendFunc.BlendFunc_ConstRad(s1,s2,guide);function.Set(8.,4);function.Set(0.)
    values=TColStd.TColStd_Array1OfReal(1,4);residual=TColStd.TColStd_Array1OfReal(1,4)
    record={'binding_version':version('cadquery-ocp'),'math_Vector_exported':hasattr(ocp_math,'math_Vector'),
            'attempted_method':'BlendFunc_ConstRad.Value(TColStd_Array1OfReal,TColStd_Array1OfReal)',
            'native_walking_called':False,'scope':'Python adapter argument availability, not a native OCCT face-face capability failure.'}
    try:
        function.Value(values,residual);record['status']='argument_conversion_available'
    except TypeError as error:
        record.update(status='python_argument_type_unavailable',error_type='TypeError',raw_error=str(error),
                      required_argument='math_VectorBase<double>',fallback='Separate compiled C++ OCCT caller, with its own runtime version and provenance.')
    return record
def independent_quality(before,result,step_path,g):
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCP.TopAbs import TopAbs_FACE,TopAbs_IN,TopAbs_ON
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Pnt,gp_Pnt2d,gp_Vec
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    face=TopoDS.Face_s(g.shapes(result,TopAbs_FACE)[0]);surface=BRep_Tool.Surface_s(face)
    supports=[TopoDS.Face_s(f) for f in g.shapes(before,TopAbs_FACE)];rails=[]
    for i,base in enumerate(supports):
        axis=BRepAdaptor_Surface(base).Plane().Axis().Direction();normal=[axis.X(),axis.Y(),axis.Z()]
        for x in [-7.,-5.,-3.,0.,3.,5.,7.]:
            point=gp_Pnt(x,0.,8.) if i==0 else gp_Pnt(x,8.,0.)
            proj=GeomAPI_ProjectPointOnSurf(point,surface);u,v=proj.LowerDistanceParameters()
            p=gp_Pnt();du=gp_Vec();dv=gp_Vec();surface.D1(u,v,p,du,dv);n=du.Crossed(dv);length=n.Magnitude()
            cosine=min(1.,max(0.,abs((n.X()*normal[0]+n.Y()*normal[1]+n.Z()*normal[2])/length)))
            rails.append({'support_index':i+1,'requested_point_mm':g.xyz(point),'actual_point_mm':g.xyz(p),
                          'projection_distance_mm':proj.LowerDistance(),'unoriented_tangent_plane_error_deg':math.degrees(math.acos(cosine)),
                          'inside_or_on_original_face':BRepClass_FaceClassifier(base,point,1.e-7).State() in [TopAbs_IN,TopAbs_ON],
                          'inside_or_on_result_face':BRepClass_FaceClassifier(face,gp_Pnt2d(u,v),1.e-7).State() in [TopAbs_IN,TopAbs_ON]})
    u0,u1,v0,v1=surface.Bounds();midu=(u0+u1)/2;midv=(v0+v1)/2
    along_u=abs(surface.Value(u1,midv).X()-surface.Value(u0,midv).X())
    along_v=abs(surface.Value(midu,v1).X()-surface.Value(midu,v0).X())
    section_u=along_u<along_v;curvatures=[]
    for along in [.1,.3,.5,.7,.9]:
        for cross in [.1,.2,.3,.4,.5,.6,.7,.8,.9]:
            u=u0+(u1-u0)*(cross if section_u else along);v=v0+(v1-v0)*(along if section_u else cross)
            p=gp_Pnt();du=gp_Vec();dv=gp_Vec();duu=gp_Vec();dvv=gp_Vec();duv=gp_Vec();surface.D2(u,v,p,du,dv,duu,dvv,duv)
            d,dd=(du,duu) if section_u else (dv,dvv);k=d.Crossed(dd).Magnitude()/d.Magnitude()**3
            curvatures.append({'point_mm':g.xyz(p),'radius_from_native_surface_d2_mm':1/k,
                               'distance_to_inferred_circle_center_mm':math.hypot(p.Y()-8.,p.Z()-8.)})
    reader=STEPControl_Reader();status=reader.ReadFile(str(step_path));step={'read_status':str(status),'passed':False}
    if status==IFSelect_RetDone:
        reader.TransferRoots();step['inspection']=g.inspect(reader.OneShape());step['passed']=step['inspection']['passed']
    gates={'all_rails_on_original_finite_faces':all(r['inside_or_on_original_face'] for r in rails),
           'all_rails_on_native_result_boundary':all(r['inside_or_on_result_face'] for r in rails),
           'contact_g0_samples_passed':max(r['projection_distance_mm'] for r in rails)<1.e-6,
           'unoriented_contact_g1_samples_passed':max(r['unoriented_tangent_plane_error_deg'] for r in rails)<1.e-4,
           'R8_d2_samples_passed':max(abs(r['radius_from_native_surface_d2_mm']-8.) for r in curvatures)<1.e-5,
           'R8_circle_position_samples_passed':max(abs(r['distance_to_inferred_circle_center_mm']-8.) for r in curvatures)<1.e-5,
           'step_readback_passed':step['passed']}
    return {'independent_reader_binding_version':version('cadquery-ocp'),'contact_rail_samples':rails,'curvature_samples':curvatures,
            'step_readback':step,'gates':gates,'sampled_gates_passed':all(gates.values()),
            'scope':'Actual exported native BREP/STEP; sampled contact geometry and unoriented tangent planes only. No topological wall attachment, four-trim semantics or human appearance acceptance.'}
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--include-dir',type=Path,default=os.environ.get('OCCT_INCLUDE_DIR') or os.environ.get('OCC_INCLUDE_DIR'));ap.add_argument('--library-dir',type=Path,default=os.environ.get('OCCT_LIBRARY_DIR') or os.environ.get('OCC_LIBRARY_DIR'))
    ap.add_argument('--output',type=Path);ap.add_argument('--cxx',default=os.environ.get('CXX','clang++'));ap.add_argument('--probe-quadrants',action='store_true',help='Optional diagnostics; default benchmarks only the known positive-quadrant 90-degree branch (choice4)');args=ap.parse_args()
    out=(args.output or ROOT/'runs/case36-faceface'/('native-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))).resolve();relative(out)
    if out.exists() and any(out.iterdir()):ap.error('Choose a fresh output directory')
    out.mkdir(parents=True,exist_ok=True);source=ROOT/SOURCE
    if sha(source)!=SHA:raise ValueError('Original input hash mismatch')
    shutil.copyfile(source,out/'before.brep');cpp=out/'native-worker.cpp';cpp.write_text(CPP);binary=out/'native-worker'
    if sha(out/'before.brep')!=SHA:raise ValueError('Before artifact does not preserve the exact input bytes')
    missing=[]
    if not args.include_dir or not (args.include_dir/'BRepBlend_Walking.hxx').is_file():missing.append('matching OCCT headers (OCCT_INCLUDE_DIR or --include-dir)')
    if not args.library_dir or not any(args.library_dir.glob('libTKFillet.*')):missing.append('matching OCCT libraries (OCCT_LIBRARY_DIR or --library-dir)')
    if not shutil.which(args.cxx):missing.append('C++17 compiler (CXX or --cxx)')
    if missing:
        record={'schema':'case36.native-faceface-probe.v1','status':'dependency_missing','missing_dependencies':missing,
                'source_sha256':SHA,'operation_input_sha256':sha(out/'before.brep'),'before_brep':relative(out/'before.brep'),
                'native_call_executed':False,'four_trim_controls_supported':False,'rows':[],
                'reason':'Configure a matching installed OCCT SDK. No native face-face algorithm was called; this is not a kernel failure.'}
        write(out/'summary.json',record);write(out/'index.json',record);print(json.dumps(record));return 2
    sys.path.insert(0,str(ROOT/'adapters/occt/original'));import geometry as g
    spec=importlib.util.spec_from_file_location('special_geometry',ROOT/'adapters/occt/special/geometry.py');sg=importlib.util.module_from_spec(spec);spec.loader.exec_module(sg)
    shape=g.read(source);sg.mesh(shape,out/'before.mesh.json');write(out/'binding-boundary.json',binding_boundary(shape,g))
    step_libraries=['TKDESTEP'] if any(args.library_dir.glob('libTKDESTEP.*')) else ['TKSTEP','TKSTEPBase','TKSTEPAttr']
    libraries=['TKFillet','TKTopAlgo','TKBRep','TKGeomAlgo','TKGeomBase','TKG3d','TKG2d','TKMath','TKernel','TKShHealing',*step_libraries,'TKXSBase']
    command=[args.cxx,'-std=c++17','-O1','-I'+str(args.include_dir),str(cpp),'-L'+str(args.library_dir),'-Wl,-rpath,'+str(args.library_dir),*['-l'+n for n in libraries],'-o',str(binary)]
    build=subprocess.run(command,capture_output=True,text=True);(out/'compile.stdout.log').write_text(build.stdout);(out/'compile.stderr.log').write_text(build.stderr)
    if build.returncode:write(out/'index.json',{'status':'cpp_compile_failed','return_code':build.returncode,'worker_source_sha256':sha(cpp)});print('C++ compile failed:',relative(out));return 2
    rows=[]
    for choice in (range(1,9) if args.probe_quadrants else [4]):
        run=out/f'choice-{choice}';run.mkdir()
        try:
            proc=subprocess.run([str(binary),str(source),str(run),str(choice)],capture_output=True,text=True,timeout=30)
            (run/'stdout.log').write_text(proc.stdout);(run/'stderr.log').write_text(proc.stderr)
            try:native=json.loads((run/'native.json').read_text())
            except Exception as error:native={'status':'native_record_unavailable','error':str(error)}
            native['process_returncode']=proc.returncode
        except subprocess.TimeoutExpired:native={'status':'native_timeout','timeout_seconds':30}
        result=run/'result.brep'
        if result.exists():
            body=g.read(result);native['result_inspection_ocp']=g.inspect(body);native['mesh_export']=sg.mesh(body,run/'result.mesh.json');native['result_brep_sha256']=sha(result)
            native['independent_quality']=independent_quality(shape,body,run/'result.step',g)
        native.update(source_brep=SOURCE,source_sha256=SHA,operation_input_sha256=SHA,requested_radius_mm=8.,
                      method='native_surface_surface_rolling_ball_walking_and_approximation',
                      native_call_executed=native.get('native_walking_called') is True,
                      api_success=bool(native.get('walking_done') and native.get('approximation_done')) if native.get('native_walking_called') else None,
                      source_finite_domains_preserved=True,input_surface_extension=False,input_common_edge_constructed=False,
                      guide={'kind':'IntAna_QuadQuadGeo intersection of original supporting planes','range_source':'original vertex projections onto guide','parameter_range':native.get('guide_parameter_range_from_original_vertex_projections'),'is_existing_input_edge':False,
                             'center_initialization':'projection of original-plane signed-offset intersection; no input-face modification'},
                      returned_entity_kind='separate_blend_face' if result.exists() else None,
                      original_trim_modes_native_parameter_available=False,four_trim_controls_supported=False,source_feature_passed=False,human_appearance_passed=False,
                      reference_quarter_section_branch=abs(native.get('native_section_angle_rad',0)-math.pi/2)<1.e-6)
        write(run/'summary.json',native)
        rows.append({'id':f'native-r8-choice-{choice}','choice':choice,'status':native['status'],'run_dir':relative(run),'summary':relative(run/'summary.json'),'summary_sha256':sha(run/'summary.json'),'raw_summary_sha256':sha(run/'summary.json'),
                     'source_sha256':SHA,'operation_input_sha256':SHA,'before_brep':relative(out/'before.brep'),'before_mesh':relative(out/'before.mesh.json'),
                     'engine_version':native.get('engine_version'),'method':native['method'],'native_call_executed':native['native_call_executed'],'api_success':native['api_success'],
                     'four_trim_controls_supported':False,
                     'reference_quarter_section_branch':native['reference_quarter_section_branch'],
                     'result_brep':relative(result) if result.exists() else None,'result_step':relative(run/'result.step') if (run/'result.step').exists() else None,
                     'result_mesh':relative(run/'result.mesh.json') if (run/'result.mesh.json').exists() else None})
    selected=[dict(r,id='native-r8') for r in rows if r['reference_quarter_section_branch'] and r['api_success']]
    if len(selected)>1:raise ValueError('Multiple quarter-section candidates; inspect instead of selecting ambiguously')
    baseline=[dict(r,id='native-r8') for r in rows if r['choice']==4]
    library=next(args.library_dir.glob('libTKFillet.*')).resolve()
    index={'schema':'case36.native-faceface-probe.v1','source_brep':SOURCE,'source_sha256':SHA,'operation_input_sha256':SHA,'radius_mm':8,
           'before_brep':relative(out/'before.brep'),'before_mesh':relative(out/'before.mesh.json'),'worker_source_sha256':sha(cpp),'worker_binary_sha256':sha(binary),
           'rows':baseline,'diagnostic_rows':rows,'selected_candidate':selected[0] if selected else None,
           'python_binding_boundary':{'path':relative(out/'binding-boundary.json'),'sha256':sha(out/'binding-boundary.json')},
           'native_library':{'name':library.name,'sha256':sha(library)},
           'native_call_executed':any(r['native_call_executed'] for r in baseline),'four_trim_controls_supported':False,
           'source_unchanged':sha(source)==SHA,'input_finite_domain_changed':False,
           'scope':'Actual native surface/surface rolling-ball walking with original finite face domains; no native four-trim enum and no source-feature acceptance.'}
    write(out/'index.json',index);print(json.dumps({'output':relative(out),'outcomes':[(r['choice'],r['status']) for r in rows]}));return 0

if __name__=='__main__':sys.exit(main())
