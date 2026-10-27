// Case35 native SMLib pilot. No SDK changes; zero-thickness orthogonal sheets.
#include <SmApiGeneral.h>
#include <SmApiPrimitives.h>
#include <SmApiBrep.h>
#include <SmApiQueries.h>
#include <SmBrep.h>
#include <SmFace.h>
#include <SmFaceuse.h>
#include <SmEdge.h>
#include <SmVertex.h>
#include <SmRegion.h>
#include <SmCurve.h>
#include <SmBSplineCurve.h>
#include <SmSurface.h>
#include <SmTol.h>
#include <SmPoly.h>
#include <fstream>
#include <sstream>
#include <iostream>
#include <iomanip>
#include <string>
#include <vector>
#include <array>
#include <unordered_map>
#include <memory>
#include <cmath>
#include <chrono>
#include <stdexcept>
#include <algorithm>
#include <typeinfo>

static std::string outdir,stage;
static void check(SmStatus s,const char* what){if(s!=SM_SUCCESS)throw std::runtime_error(std::string(what)+" status="+std::to_string(s));}
static void event(const char* s){stage=s;std::ofstream(outdir+"/stage.txt")<<s<<'\n';std::cout<<"STAGE "<<s<<std::endl;}
static void write(const std::string& name,const std::string& value){std::ofstream(outdir+"/"+name)<<value<<'\n';}
static std::string esc(const std::string& x){std::string o;for(char c:x){if(c=='"'||c=='\\')o+='\\';if(c=='\n')o+="\\n";else o+=c;}return o;}
template<class V>static std::string point(const V& p){std::ostringstream o;o<<std::setprecision(17)<<'['<<p.x<<','<<p.y<<','<<p.z<<']';return o.str();}
static std::string number(double v){if(!std::isfinite(v))return "null";std::ostringstream o;o<<std::setprecision(17)<<v;return o.str();}
static double dot(SmVector3d a,SmVector3d b){return a.x*b.x+a.y*b.y+a.z*b.z;}
static SmVector3d cross(SmVector3d a,SmVector3d b){return SmVector3d(a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x);}
static double length(SmVector3d a){return std::sqrt(dot(a,a));}
static double dist(SmVector3d a,SmVector3d b){return length(SmVector3d(a.x-b.x,a.y-b.y,a.z-b.z));}
static SmVector3d unit(SmVector3d a){double n=length(a);if(n<1e-15)throw std::runtime_error("zero normal");return SmVector3d(a.x/n,a.y/n,a.z/n);}
static SmVector3d surface_normal(SmFace* f,SmPoint2d uv){SmVector3d d[9];check(f->GetSurface()->Evaluate(uv,2,2,TRUE,TRUE,TRUE,d,FALSE),"normal derivatives");return unit(cross(d[3],d[1]));}

static void tolerance(SmBrep* b){
 b->SetTolerance(SmZoneTol3d(1e-7),FALSE,FALSE);
 SmTArray<SmFace*> fs;SmTArray<SmEdge*> es;SmTArray<SmVertex*> vs;b->GetFaces(fs);b->GetEdges(es);b->GetVertices(vs);
 for(long i=0;i<fs.GetSize();++i)fs[i]->SetTolerance(SmZoneTol3d(1e-7),FALSE,FALSE);
 for(long i=0;i<es.GetSize();++i)es[i]->SetTolerance(SmZoneTol3d(1e-7),FALSE,FALSE);
 for(long i=0;i<vs.GetSize();++i)vs[i]->SetTolerance(SmZoneTol3d(1e-7),FALSE,FALSE);
}
static std::string stats(SmBrep* b){
 SmTArray<SmFace*> fs;SmTArray<SmEdge*> es;SmTArray<SmVertex*> vs;SmTArray<SmRegion*> rs;SmTArray<SmShell*> ss;
 b->GetFaces(fs);b->GetEdges(es);b->GetVertices(vs);b->GetRegions(rs);b->GetShells(ss);
 int material=0;for(long i=0;i<rs.GetSize();++i)if(!rs[i]->IsInfiniteRegion()&&!rs[i]->IsVoid())++material;
 SmPoint3d mn,mx;check(SmApiBrepBoundingBox(b,TRUE,mn,mx),"bounds");double area=0;check(SmApiBrepComputeArea(b,1e-8,area),"sheet area");
 double mt=0;for(long i=0;i<es.GetSize();++i)mt=std::max(mt,SmTol::GetZoneTol3d(es[i]).val);for(long i=0;i<vs.GetSize();++i)mt=std::max(mt,SmTol::GetZoneTol3d(vs[i]).val);
 bool valid=b->AssertValid(nullptr,SM_LEVEL_2,SM_WALK);std::ostringstream o;o<<std::setprecision(17)<<"{\"native_valid\":"<<(valid?"true":"false")<<",\"faces\":"<<fs.GetSize()<<",\"edges\":"<<es.GetSize()<<",\"vertices\":"<<vs.GetSize()<<",\"shells\":"<<ss.GetSize()<<",\"material_regions\":"<<material<<",\"manifold_solid\":"<<(b->IsManifoldSolid()?"true":"false")<<",\"area_mm2\":"<<area<<",\"bbox_min\":"<<point(mn)<<",\"bbox_max\":"<<point(mx)<<",\"maximum_edge_vertex_tolerance_mm\":"<<mt<<'}';return o.str();
}
static std::string mesh(SmBrep* b){
 SmPolyBrep* m=nullptr;SmTessellationParams p;SmTessellationReport report;p.dChordHeightTol=.005;p.dCurveAngleTolDeg=5;p.dSurfaceAngleTolDeg=5;
 check(SmApiTessellate(b,m,p,FALSE,nullptr,&report),"tessellate");std::unique_ptr<SmPolyBrep> owner(m);if(!m)throw std::runtime_error("null mesh");
 SmTArray<SmPolyVertex*> vs;SmTArray<SmPolyFace*> fs;m->GetPolyVertices(vs);m->GetPolyFaces(fs);std::unordered_map<SmPolyVertex*,long> ids;std::ostringstream o;o<<"{\"positions\":[";
 for(long i=0;i<vs.GetSize();++i){ids[vs[i]]=i;if(i)o<<',';o<<point(vs[i]->GetPoint());}o<<"],\"triangles\":[";bool first=true;
 for(long i=0;i<fs.GetSize();++i){auto* l=fs[i]->GetOuterPolyLoop();if(!l)throw std::runtime_error("no mesh loop");SmTArray<SmPolyEdge*> es;l->GetPolyEdges(es);if(es.GetSize()!=3)throw std::runtime_error("nontriangle");if(!first)o<<',';first=false;o<<'[';for(long j=0;j<3;++j){if(j)o<<',';o<<ids.at(es[j]->GetStartPolyVertex());}o<<']';}o<<"],\"method\":\"SmApiTessellate\",\"chord_mm\":0.005}";return o.str();
}
static void detailed_mesh(SmBrep* b,const std::string& name){
 SmTArray<SmFace*> fs;b->GetFaces(fs);std::ostringstream o;o<<"{\"camera\":[33,33],\"faces\":[";
 for(long i=0;i<fs.GetSize();++i){SmTArray<SmFace*> one;one.Add(fs[i]);std::unique_ptr<SmBrep> copy(new (*b->GetContext()) SmBrep());check(b->CopyFaces(one,copy.get(),nullptr,FALSE),"copy mesh face");if(i)o<<',';o<<"{\"face_index\":"<<i+1<<",\"surface_type\":\""<<esc(typeid(*fs[i]->GetSurface()).name())<<"\",\"mesh\":"<<mesh(copy.get())<<'}';}
 o<<"],\"edges\":[";SmTArray<SmEdge*> es;b->GetEdges(es);for(long i=0;i<es.GetSize();++i){if(i)o<<',';o<<'[';auto iv=es[i]->GetInterval();for(int j=0;j<=80;++j){SmVector3d p[1];check(es[i]->GetCurve()->Evaluate(iv.Evaluate(j/80.),0,TRUE,p,FALSE),"mesh edge");if(j)o<<',';o<<point(p[0]);}o<<']';}o<<"]}";write(name,o.str());
}
static SmBrep* input(){
 event("construct_two_planes");SmBrep *a=nullptr,*b=nullptr;check(SmApiCreatePlane(SmVector3d(-10,0,0),20,17,a),"floor plane");check(SmApiCreatePlane(SmVector3d(-10,-18,0),20,18,b),"wall plane");
 check(SmApiRotate(b,SmVector3d(0,0,0),SmVector3d(1,0,0),-90),"wall rotate");tolerance(a);tolerance(b);check(a->MergeBrep(*b),"MergeBrep copy");delete b;
 event("stitch_zero_thickness_shell");SmBoolean well=FALSE;ULONG count=0;double vg=0,eg=0;check(SmApiStitchIntoShell(a,well,1e-7,count,vg,eg),"StitchIntoShell");
 std::ostringstream st;st<<"{\"stitched_edges\":"<<count<<",\"max_vertex_gap\":"<<number(vg)<<",\"max_edge_gap\":"<<number(eg)<<",\"well_formed_input_mode\":false}";write("input-stitch.json",st.str());
 return a;
}
static std::string seams(SmBrep* b){
 SmTArray<SmEdge*> es;b->GetEdges(es);std::ostringstream o;o<<"{\"method\":\"actual shared-edge 3D sample -> each adjacent exact surface closest UV -> exact surface derivatives/principal curvature\",\"seams\":[";bool first=true;
 for(long i=0;i<es.GetSize();++i){SmTArray<SmFace*> fs;es[i]->GetFaces(fs);if(fs.GetSize()!=2)continue;if(!first)o<<',';first=false;auto iv=es[i]->GetInterval();o<<"{\"edge_index\":"<<i+1<<",\"samples\":[";
  for(int j=0;j<=10;++j){double q=j/10.;SmVector3d ep[1];check(es[i]->GetCurve()->Evaluate(iv.Evaluate(q),0,TRUE,ep,FALSE),"seam 3D");if(j)o<<',';o<<"{\"fraction\":"<<q<<",\"edge_point\":"<<point(ep[0])<<",\"faces\":[";SmVector3d normals[2];
   for(int k=0;k<2;++k){auto* surf=fs[k]->GetSurface();SmPoint3d cp;SmTArray<SmPoint2d> uvs;double distance=0;check(SmApiSurfaceClosestPoint(surf,SmPoint3d(ep[0].x,ep[0].y,ep[0].z),cp,uvs,distance),"seam surface closest");if(uvs.GetSize()<1)throw std::runtime_error("missing UV");auto uv=uvs[0];SmVector3d v[9];check(surf->Evaluate(uv,2,2,TRUE,TRUE,TRUE,v,FALSE),"surface derivatives");normals[k]=unit(cross(v[3],v[1]));double K,H,k1,k2;SmVector3d EFG,LMN,dir1,dir2;check(surf->EvaluateGeometric(uv,TRUE,TRUE,K,H,k1,k2,EFG,LMN,dir1,dir2),"surface curvatures");
    if(k)o<<',';o<<"{\"surface_type\":\""<<esc(typeid(*surf).name())<<"\",\"uv\":["<<number(uv.x)<<','<<number(uv.y)<<"],\"point\":"<<point(v[0])<<",\"G0_gap_mm\":"<<number(dist(v[0],ep[0]))<<",\"raw_surface_normal\":"<<point(normals[k])<<",\"principal_curvatures_mm_inverse\":["<<number(k1)<<','<<number(k2)<<"],\"derivatives\":{\"du\":"<<point(v[3])<<",\"dv\":"<<point(v[1])<<",\"duu\":"<<point(v[6])<<",\"duv\":"<<point(v[4])<<",\"dvv\":"<<point(v[2])<<"}}";
   }double c=std::clamp(dot(normals[0],normals[1]),-1.,1.);o<<"],\"raw_normal_angle_deg\":"<<number(std::acos(c)*180/M_PI)<<",\"unoriented_tangent_plane_angle_deg\":"<<number(std::acos(std::abs(c))*180/M_PI)<<'}';
  }o<<"]}";
 }o<<"]}";return o.str();
}
static void save(SmBrep* b,const std::string& prefix){
 event((prefix+"_native_save").c_str());check(b->WriteToFile((outdir+"/"+prefix+".smb").c_str(),SM_ASCII,TRUE,FALSE),"native WriteToFile");write(prefix+"-stats.json",stats(b));
 event((prefix+"_mesh").c_str());detailed_mesh(b,prefix+"-mesh.json");
 event((prefix+"_seam_sampling").c_str());write(prefix+"-seams.json",seams(b));
}
int main(int argc,char** argv){
 if(argc==4&&std::string(argv[1])=="--readback"){
  outdir=argv[3];try{event("independent_readback_started");SmTol::SetModelSizeEstimate(.0005);SmApiCreateContext();auto* context=SmApiGetOrCreateContext();std::unique_ptr<SmBrep> b(new (*context) SmBrep());check(b->ReadFromFile(*context,argv[2],SM_ASCII,FALSE),"independent native ReadFromFile");write("readback-stats.json",stats(b.get()));write("readback-seams.json",seams(b.get()));event("independent_readback_complete");return 0;}catch(const std::exception& e){write("error.json","{\"stage\":\""+esc(stage)+"\",\"error\":\""+esc(e.what())+"\"}");return 1;}
 }
 if(argc!=5){std::cerr<<"usage runner OUTPUTDIR RADIUS XSect THUMBWEIGHT\n";return 2;}outdir=argv[1];double radius=std::stod(argv[2]),thumb=std::stod(argv[4]);int xsect=std::stoi(argv[3]);int cont=xsect==2?2:1;auto begin=std::chrono::steady_clock::now();
 try{
  event("initialization");SmTol::SetModelSizeEstimate(.0005);SmApiCreateContext();std::unique_ptr<SmBrep> b(input());save(b.get(),"input");
  event("select_common_original_edge");SmTArray<SmEdge*> es,selected;b->GetEdges(es);std::ostringstream el;el<<"[";bool first=true;
  for(long i=0;i<es.GetSize();++i){auto* e=es[i];SmTArray<SmFace*> fs;e->GetFaces(fs);auto a=e->GetStartVertex()->GetPoint(),z=e->GetEndVertex()->GetPoint();if(fs.GetSize()==2&&std::abs(a.y)<1e-6&&std::abs(z.y)<1e-6&&std::abs(a.z)<1e-6&&std::abs(z.z)<1e-6&&std::abs(a.x-z.x)>19.999){selected.Add(e);if(!first)el<<',';first=false;el<<"{\"edge_index\":"<<i+1<<",\"start\":"<<point(a)<<",\"end\":"<<point(z)<<",\"adjacent_faces\":2}";}}
  el<<"]";write("selection.json",el.str());if(selected.GetSize()!=1)throw std::runtime_error("expected exactly one live shared sharp edge; found "+std::to_string(selected.GetSize()));
  std::ostringstream call;call<<"{\"api\":\"SmApiFilletEdges\",\"radius_mm\":"<<radius<<",\"xsect_type\":"<<xsect<<",\"continuity\":"<<cont<<",\"thumbweight\":"<<thumb<<",\"parasolid_softness_equivalence_claimed\":false,\"selected_edges\":1,\"source_dimensions\":{\"width\":20,\"height\":18,\"floor_depth\":17},\"target_fixed_contact_d_mm\":13,\"source_is_zero_thickness_sheet\":true}";write("call.json",call.str());
  event("native_fillet_call_started");auto op=std::chrono::steady_clock::now();auto st=SmApiFilletEdges(b.get(),selected,radius,xsect,cont,thumb);double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-op).count();std::ostringstream result;result<<"{\"status_code\":"<<st<<",\"native_call_returned\":true,\"operation_ms\":"<<number(ms)<<",\"requested_G2\":"<<(xsect==2?"true":"false")<<"}";write("native-return.json",result.str());
  event("native_fillet_call_returned");save(b.get(),"result");check(st,"native fillet");
  write("completed.json","{\"execution_complete\":true,\"native_status_success\":true,\"semantic_quality_independently_accepted\":false}");event("complete");return 0;
 }catch(const std::exception& e){std::string failed_stage=stage;write("error.json","{\"stage\":\""+esc(failed_stage)+"\",\"error\":\""+esc(e.what())+"\"}");std::cerr<<failed_stage<<": "<<e.what()<<std::endl;return 1;}catch(...){write("error.json","{\"stage\":\""+esc(stage)+"\",\"error\":\"unknown C++ exception\"}");return 1;}
}
