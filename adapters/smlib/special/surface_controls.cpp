#include <SmApiBrep.h>
#include <SmApiGeneral.h>
#include <SmApiPrimitives.h>
#include <SmApiQueries.h>
#include <SmApiCurves.h>
#include <SmFilletExecutive.h>
#include <SmSurface.h>
#include <SmBrep.h>
#include <SmContext.h>
#include <SmVertex.h>
#include <SmEdge.h>
#include <SmFace.h>
#include <SmCurve.h>
#include <SmLine.h>
#include <SmPoly.h>
#include <SmTol.h>
#include <chrono>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <memory>
#include <unordered_map>
#include <vector>
#include <cmath>
#include <string>

static const double H=24.0,XB=36.031828047407174,XT=19.155687980072315,Y=18.962451224311028;
static const double DB=16.857382645040378,DT=12.276845200098565;
static void ck(SmApiStatus st,const char* name){if(st!=SM_SUCCESS)throw std::runtime_error(std::string(name)+" status "+std::to_string(st));}
static std::string quote(const std::string&s){std::string q="\"";for(char c:s){if(c=='\n')q+="\\n";else{if(c=='"'||c=='\\')q+='\\';q+=c;}}return q+'"';}
static void pt(std::ostream&o,const SmVector3d&p){o<<'['<<p.x<<','<<p.y<<','<<p.z<<']';}
static void save(SmBrep*p,const std::string&base){ck(p->WriteToFile((base+".smb").c_str(),SM_ASCII,TRUE,FALSE,0.0),"native WriteToFile");}
static void stats(SmBrep*p,const std::string&path){
 std::ofstream f(path);f<<std::setprecision(17);SmTArray<SmFace*>fs;SmTArray<SmEdge*>es;SmTArray<SmVertex*>vs;p->GetFaces(fs);p->GetEdges(es);p->GetVertices(vs);
 const bool valid=p->AssertValid(nullptr,SM_LEVEL_2,SM_WALK);SmBoolean manifold=FALSE;auto mst=SmApiBrepIsManifoldSolid(p,manifold);long solids=-1,voids=-1;auto cst=SmApiBrepMaterialCensus(p,solids,voids);SmPoint3d mn,mx;auto bst=SmApiBrepBoundingBox(p,TRUE,mn,mx);
 double area=0;auto ast=SmApiBrepComputeArea(p,1e-8,area);double volume=0;auto vst=solids>0?SmApiBrepComputeVolume(p,1e-8,volume):SM_SUCCESS;f<<"{\"area_status\":"<<ast<<",\"area_mm2\":"<<area<<",\"valid_level2\":"<<(valid?"true":"false")<<",\"manifold\":"<<(manifold?"true":"false")<<",\"manifold_status\":"<<mst<<",\"census_status\":"<<cst<<",\"solids\":"<<solids<<",\"voids\":"<<voids<<",\"faces\":"<<fs.GetSize()<<",\"edges\":"<<es.GetSize()<<",\"vertices\":"<<vs.GetSize()<<",\"volume_status\":"<<vst<<",\"volume_mm3\":"<<volume<<",\"bbox_status\":"<<bst<<",\"bbox_min\":";pt(f,mn);f<<",\"bbox_max\":";pt(f,mx);f<<",\"vertex_points\":[";for(long i=0;i<vs.GetSize();i++){if(i)f<<',';pt(f,vs[i]->GetPoint());}f<<"]}";
}
static void geometry(SmBrep*p,const std::string&path){
 std::ofstream f(path);f<<std::setprecision(17)<<"{\"method\":\"native edge EvaluatePoint at actual parameter intervals\",\"edges\":[";SmTArray<SmEdge*>es;p->GetEdges(es);
 for(long i=0;i<es.GetSize();i++){
  if(i)f<<',';auto e=es[i];double a=0,b=0;auto st=SmApiEdgeParameterRange(e,a,b);f<<"{\"index_1based\":"<<i+1<<",\"range_status\":"<<st<<",\"a\":"<<a<<",\"b\":"<<b<<",\"points\":[";
  for(int j=0;j<=128;j++){if(j)f<<',';SmPoint3d point;auto q=e->GetCurve()->EvaluatePoint(a+(b-a)*j/128.0,point);if(q!=SM_SUCCESS)throw std::runtime_error("edge point failed");pt(f,point);}f<<"]}";
 }f<<"]}";
}
static void mesh(SmBrep*p,const std::string&path){
 // Work on a copy: visualization must not alter the operation input/result.
 std::unique_ptr<SmBrep> copy(new(*p->GetContext())SmBrep(*p));SmPolyBrep*m=nullptr;SmTessellationParams tp;SmTessellationReport tr;tp.dChordHeightTol=.008;tp.dCurveAngleTolDeg=10;tp.dSurfaceAngleTolDeg=10;ck(SmApiTessellate(copy.get(),m,tp,FALSE,nullptr,&tr),"mesh");std::unique_ptr<SmPolyBrep>own(m);SmTArray<SmPolyVertex*>vs;SmTArray<SmPolyFace*>fs;m->GetPolyVertices(vs);m->GetPolyFaces(fs);std::unordered_map<SmPolyVertex*,long>ids;
 std::ofstream f(path);f<<std::setprecision(17)<<"{\"positions\":[";for(long i=0;i<vs.GetSize();i++){ids[vs[i]]=i;if(i)f<<',';auto v=vs[i]->GetPoint();f<<v.x<<','<<v.y<<','<<v.z;}f<<"],\"indices\":[";bool first=true;for(long i=0;i<fs.GetSize();i++){auto loop=fs[i]->GetOuterPolyLoop();if(!loop)throw std::runtime_error("missing mesh loop");SmTArray<SmPolyEdge*>es;loop->GetPolyEdges(es);if(es.GetSize()!=3)throw std::runtime_error("nontriangle mesh");for(long j=0;j<3;j++){if(!first)f<<',';first=false;f<<ids.at(es[j]->GetStartPolyVertex());}}f<<"],\"method\":\"SmApiTessellate\",\"chord_height_mm\":0.008}";
}
static void set_tol(SmBrep*p){
 SmTArray<SmFace*>fs;SmTArray<SmEdge*>es;SmTArray<SmVertex*>vs;p->GetFaces(fs);p->GetEdges(es);p->GetVertices(vs);p->SetTolerance(SmZoneTol3d(1e-7),FALSE,FALSE);
 for(long i=0;i<fs.GetSize();i++)fs[i]->SetTolerance(SmZoneTol3d(1e-7),FALSE,FALSE);
 for(long i=0;i<es.GetSize();i++)es[i]->SetTolerance(SmZoneTol3d(1e-7),FALSE,FALSE);
 for(long i=0;i<vs.GetSize();i++)vs[i]->SetTolerance(SmZoneTol3d(1e-7),FALSE,FALSE);
}
static SmSurface* first_surface(SmBrep*p){SmTArray<SmFace*>f;p->GetFaces(f);if(f.GetSize()!=1)throw std::runtime_error("expected one finite plane face");return f[0]->GetSurface();}
static void support_details(SmSurface*p,const std::string&path){
 auto uv=p->GetNaturalUVDomain();SmVector3d normal;ck(p->EvaluateNormal(uv.GetMid(),TRUE,TRUE,normal),"surface normal");std::ofstream f(path);f<<std::setprecision(17)<<"{\"uv_domain\":["<<uv.GetUMin()<<','<<uv.GetUMax()<<','<<uv.GetVMin()<<','<<uv.GetVMax()<<"],\"normal\":";pt(f,normal);f<<",\"corners\":[";double us[2]={uv.GetUMin(),uv.GetUMax()},vs[2]={uv.GetVMin(),uv.GetVMax()};bool first=true;for(double u:us)for(double v:vs){SmVector3d val[1];ck(p->Evaluate(SmPoint2d(u,v),0,0,TRUE,TRUE,TRUE,val,FALSE),"support corner");if(!first)f<<',';first=false;pt(f,val[0]);}f<<"]}";
}
static void rail_normals(SmBrep*p,const std::string&path){
 SmTArray<SmFace*>fs;SmTArray<SmEdge*>es;p->GetFaces(fs);p->GetEdges(es);if(fs.GetSize()!=1)throw std::runtime_error("expected single fillet surface for rail normal test");auto*surface=fs[0]->GetSurface();std::ofstream f(path);f<<std::setprecision(17)<<"{\"method\":\"native readback edge -> actual surface closest UV -> EvaluateNormal; tangent plane angle ignores overall sheet normal sign\",\"rails\":[";bool first=true;
 for(long i=0;i<es.GetSize();i++){
  double a=0,b=0;ck(SmApiEdgeParameterRange(es[i],a,b),"rail range");double maxY=0,maxZ=0;for(int j=0;j<=8;j++){SmPoint3d q;ck(es[i]->GetCurve()->EvaluatePoint(a+(b-a)*j/8.,q),"rail classify point");maxY=std::max(maxY,std::abs(q.y));maxZ=std::max(maxZ,std::abs(q.z));}int axis=maxY<1e-7?1:maxZ<1e-7?2:-1;if(axis<0)continue;
  if(!first)f<<',';first=false;f<<"{\"edge_index_1based\":"<<i+1<<",\"support\":"<<quote(axis==1?"y=0":"z=0")<<",\"samples\":[";
  for(int j=0;j<=16;j++){if(j)f<<',';SmPoint3d q,closest;double distance=0;SmTArray<SmPoint2d>uvs;ck(es[i]->GetCurve()->EvaluatePoint(a+(b-a)*j/16.,q),"rail sample");ck(SmApiSurfaceClosestPoint(surface,q,closest,uvs,distance),"rail surface closest point");if(!uvs.GetSize())throw std::runtime_error("missing rail UV");SmVector3d n;ck(surface->EvaluateNormal(uvs[0],TRUE,TRUE,n),"rail normal");double len=std::sqrt(n.x*n.x+n.y*n.y+n.z*n.z);double cos=std::min(1.0,std::abs(axis==1?n.y:n.z)/len);double angle=std::acos(cos)*180/3.14159265358979323846;f<<"{\"point\":";pt(f,q);f<<",\"surface_point\":";pt(f,closest);f<<",\"surface_edge_gap_mm\":"<<distance<<",\"tangent_plane_angle_deg\":"<<angle<<",\"normal\":";pt(f,n);f<<'}';}f<<"]}";
 }f<<"]}";
}
int main(int argc,char**argv){
 if(argc!=7)return 2;int number=std::stoi(argv[1]),s1=std::stoi(argv[2]),s2=std::stoi(argv[3]),trim=std::stoi(argv[4]),base=std::stoi(argv[5]);std::string out=argv[6],stage="initialize";const double radius=8;
 try{
  SmApiCreateContext();SmBrep*left=nullptr,*right=nullptr;
  stage="construct_finite_planes";
  if(number==28){ck(SmApiCreatePlane(SmVector3d(-12,-14,0),24,28,left),"case28 vertical precursor");ck(SmApiRotate(left,SmVector3d(0,0,0),SmVector3d(1,0,0),90),"vertical rotation");ck(SmApiCreatePlane(SmVector3d(-12,-14,0),24,28,right),"case28 floor");}
  else if(number==36){ck(SmApiCreatePlane(SmVector3d(-7,5,0),14,20,left),"case36 vertical precursor");ck(SmApiRotate(left,SmVector3d(0,0,0),SmVector3d(1,0,0),90),"vertical rotation");ck(SmApiCreatePlane(SmVector3d(-12.5,5,0),25,18,right),"case36 floor");}
  else throw std::runtime_error("bad case number");
  set_tol(left);set_tol(right);stage="save_exact_input";
  save(left,out+"/input-left");save(right,out+"/input-right");stats(left,out+"/input-left-stats.json");stats(right,out+"/input-right-stats.json");geometry(left,out+"/input-left-edges.json");geometry(right,out+"/input-right-edges.json");mesh(left,out+"/input-left-mesh.json");mesh(right,out+"/input-right-mesh.json");support_details(first_surface(left),out+"/left-support.json");support_details(first_surface(right),out+"/right-support.json");
  std::ofstream request(out+"/request.json");request<<std::setprecision(17)<<"{\"number\":"<<number<<",\"api\":\"SmFilletExecutive::SurfaceSurfaceFillet\",\"signed_radius_left\":"<<s1*radius<<",\"signed_radius_right\":"<<s2*radius<<",\"R_mm\":8,\"cross_section_api_enum\":2,\"cross_section_meaning\":\"exact rational circular (not edge blend enum2)\",\"approximation_accuracy\":0.001,\"solver_contact_tolerance_mm\":1e-6,\"trim_enum\":"<<trim<<",\"base_trim\":"<<base<<",\"mirror\":false,\"complement\":false,\"original_finite_domains_preserved_before_call\":true,\"explicit_post_crop\":false}";request.close();
  stage="native_surface_surface_call";SmBrep*result=nullptr;SmFilletExecutive executive(*SmApiGetOrCreateContext());auto start=std::chrono::steady_clock::now();auto st=executive.SurfaceSurfaceFillet(*SmApiGetOrCreateContext(),first_surface(left),first_surface(right),s1*radius,s2*radius,1e-6,result,2,.001,static_cast<SmBoundaryTrimmingType>(trim),base,FALSE,FALSE);double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();std::ofstream(out+"/operation.json")<<std::setprecision(17)<<"{\"native_api_status\":"<<st<<",\"operation_ms\":"<<ms<<",\"nonnull_result\":"<<(result?"true":"false")<<"}";
  stage="save_returned_inputs";save(left,out+"/post-left");save(right,out+"/post-right");stats(left,out+"/post-left-stats.json");stats(right,out+"/post-right-stats.json");geometry(left,out+"/post-left-edges.json");geometry(right,out+"/post-right-edges.json");
  if(result){stage="save_raw_result";save(result,out+"/native");stats(result,out+"/native-stats.json");geometry(result,out+"/native-edges.json");}
  if(st!=SM_SUCCESS||!result){std::ofstream(out+"/status.json")<<"{\"stage\":\"native_operation_failed_or_empty\",\"native_api_status\":"<<st<<",\"nonnull_result\":"<<(result?"true":"false")<<"}";return 3;}
  stage="native_readback";auto*context=SmApiGetOrCreateContext();SmBrep*rb=new(*context)SmBrep();ck(rb->ReadFromFile(*context,(out+"/native.smb").c_str(),SM_ASCII,TRUE),"native readback");stats(rb,out+"/readback-stats.json");geometry(rb,out+"/readback-edges.json");stage="rail_normals";rail_normals(rb,out+"/rail-normal-check.json");stage="native_mesh";mesh(rb,out+"/mesh.json");std::ofstream(out+"/status.json")<<"{\"stage\":\"returned_saved_readback_and_mesh\",\"native_operation_executed\":true,\"explicit_post_crop\":false,\"source_mode_equivalence_not_inferred_from_enum\":true}";return 0;
 }catch(const std::exception&e){std::ofstream(out+"/status.json")<<"{\"stage\":"<<quote(stage)<<",\"error\":"<<quote(e.what())<<"}";std::cerr<<stage<<": "<<e.what()<<'\n';return 1;}catch(...){std::ofstream(out+"/status.json")<<"{\"stage\":"<<quote(stage)<<",\"error\":\"unknown exception\"}";return 1;}
}
