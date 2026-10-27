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
struct Selection {SmVector3d desired;std::vector<SmPoint3d> points;};
static Selection load_selection(const std::string&path){std::ifstream f(path);Selection s;long n=0;f>>s.desired.x>>s.desired.y>>s.desired.z>>n;if(!f||n<4)throw std::runtime_error("invalid world-face-selector file");for(long i=0;i<n;i++){SmPoint3d p;f>>p.x>>p.y>>p.z;s.points.push_back(p);}return s;}
static SmFace* select_face(SmBrep*p,const Selection&s,const std::string&path){
 SmTArray<SmFace*>faces;p->GetFaces(faces);SmFace*selected=nullptr;int matches=0;std::ofstream f(path);f<<std::setprecision(17)<<"{\"method\":\"all world samples within actual finite trimmed face; no face index supplied\",\"candidates\":[";
 for(long i=0;i<faces.GetSize();i++){double maximum=0;bool failed=false;for(const auto&q:s.points){SmPoint3d closest;double d=0;auto st=SmApiFaceClosestPoint(faces[i],q,closest,d);if(st!=SM_SUCCESS){failed=true;break;}maximum=std::max(maximum,d);}if(i)f<<',';f<<"{\"diagnostic_index\":"<<i+1<<",\"query_failed\":"<<(failed?"true":"false")<<",\"maximum_world_sample_distance_mm\":"<<maximum<<'}';if(!failed&&maximum<1e-6){selected=faces[i];matches++;}}
 f<<"],\"matches\":"<<matches;if(matches==1){auto dom=selected->GetSurface()->GetNaturalUVDomain();SmVector3d n;ck(selected->GetSurface()->EvaluateNormal(dom.GetMid(),TRUE,TRUE,n),"selected normal");SmPoint3d a,b;ck(SmApiFaceBoundingBox(selected,TRUE,a,b),"selected bbox");f<<",\"normal\":";pt(f,n);f<<",\"bbox_min\":";pt(f,a);f<<",\"bbox_max\":";pt(f,b);}f<<'}';f.close();if(matches!=1)throw std::runtime_error("finite world face selector is ambiguous or unmatched");return selected;
}
static double signed_radius(SmFace*f,const Selection&s,double r){auto d=f->GetSurface()->GetNaturalUVDomain();SmVector3d n;ck(f->GetSurface()->EvaluateNormal(d.GetMid(),TRUE,TRUE,n),"radius sense normal");double dot=n.x*s.desired.x+n.y*s.desired.y+n.z*s.desired.z;if(std::abs(dot)<.99)throw std::runtime_error("offset direction not parallel to selected support normal");return dot>0?r:-r;}
static void contact_check(SmBrep*result,SmFace*left,SmFace*right,const Selection&ls,const Selection&rs,const std::string&path){
 SmTArray<SmFace*>faces;SmTArray<SmEdge*>edges;result->GetFaces(faces);result->GetEdges(edges);std::ofstream f(path);f<<std::setprecision(17)<<"{\"geometry_scope\":\"actual result edge versus original finite faces and returned surface; tangent plane angle ignores overall sheet normal sign\",\"rails\":[";bool first=true;
 for(long i=0;i<edges.GetSize();i++){double a,b;ck(SmApiEdgeParameterRange(edges[i],a,b),"contact range");for(int side=0;side<2;side++){SmFace*support=side==0?left:right;const Selection&sel=side==0?ls:rs;auto dom=support->GetSurface()->GetNaturalUVDomain();SmVector3d normal;ck(support->GetSurface()->EvaluateNormal(dom.GetMid(),TRUE,TRUE,normal),"support normal");auto origin=sel.points[0];double plane_error=0;for(int j=0;j<=8;j++){SmPoint3d q;ck(edges[i]->GetCurve()->EvaluatePoint(a+(b-a)*j/8.,q),"classify contact edge");auto v=q-origin;plane_error=std::max(plane_error,std::abs(v.x*normal.x+v.y*normal.y+v.z*normal.z));}if(plane_error>1e-6)continue;
  if(!first)f<<',';first=false;f<<"{\"side\":"<<quote(side==0?"left":"right")<<",\"edge_index_diagnostic\":"<<i+1<<",\"plane_error_mm\":"<<plane_error<<",\"samples\":[";
  for(int j=0;j<=16;j++){if(j)f<<',';SmPoint3d q,closest_finite,closest;double finite_gap=0,gap=0;ck(edges[i]->GetCurve()->EvaluatePoint(a+(b-a)*j/16.,q),"contact actual point");auto finite_st=SmApiFaceClosestPoint(support,q,closest_finite,finite_gap);SmTArray<SmPoint2d>uvs;auto surf=faces[0]->GetSurface();auto st=SmApiSurfaceClosestPoint(surf,q,closest,uvs,gap);double angle=-1;if(st==SM_SUCCESS&&uvs.GetSize()){SmVector3d n;ck(surf->EvaluateNormal(uvs[0],TRUE,TRUE,n),"native contact normal");double len=std::sqrt(n.x*n.x+n.y*n.y+n.z*n.z);double dot=std::abs(n.x*normal.x+n.y*normal.y+n.z*normal.z)/len;angle=std::acos(std::min(1.0,dot))*180/3.14159265358979323846;}f<<"{\"point\":";pt(f,q);f<<",\"finite_face_status\":"<<finite_st<<",\"finite_face_gap_mm\":"<<finite_gap<<",\"result_surface_status\":"<<st<<",\"result_surface_edge_gap_mm\":"<<gap<<",\"tangent_plane_angle_deg\":"<<angle<<'}';}f<<"]}";
 }}f<<"]}";
}
int main(int argc,char**argv){
 if(argc!=8)return 2;std::string leftfile=argv[1],rightfile=argv[2],lt=argv[3],rt=argv[4],out=argv[6],stage="read_admitted_native_smb";double R=std::stod(argv[5]);int trim=std::stoi(argv[7]);
 try{
  SmApiCreateContext();auto*context=SmApiGetOrCreateContext();SmBrep*rawleft=new(*context)SmBrep();SmBrep*rawright=new(*context)SmBrep();ck(rawleft->ReadFromFile(*context,leftfile.c_str(),SM_ASCII,TRUE),"read admitted left SMB");ck(rawright->ReadFromFile(*context,rightfile.c_str(),SM_ASCII,TRUE),"read admitted right SMB");save(rawleft,out+"/source-object-left-before");save(rawright,out+"/source-object-right-before");
  Selection ls=load_selection(lt),rs=load_selection(rt);SmFace*original_left=select_face(rawleft,ls,out+"/source-selection-left.json");SmFace*original_right=select_face(rawright,rs,out+"/source-selection-right.json");
  stage="deep_copy_complete_components";SmBrep*left=new(*context)SmBrep(*rawleft);SmBrep*right=new(*context)SmBrep(*rawright);SmFace*l=select_face(left,ls,out+"/selection-left.json");SmFace*r=select_face(right,rs,out+"/selection-right.json");double lr=signed_radius(l,ls,R),rr=signed_radius(r,rs,R);save(left,out+"/input-left");save(right,out+"/input-right");stats(left,out+"/input-left-stats.json");stats(right,out+"/input-right-stats.json");geometry(left,out+"/input-left-edges.json");geometry(right,out+"/input-right-edges.json");mesh(left,out+"/input-left-mesh.json");mesh(right,out+"/input-right-mesh.json");support_details(l->GetSurface(),out+"/selected-left-surface.json");support_details(r->GetSurface(),out+"/selected-right-surface.json");
  std::ofstream req(out+"/request.json");req<<std::setprecision(17)<<"{\"api\":\"SmFilletExecutive::SurfaceSurfaceFillet\",\"left_smb\":"<<quote(leftfile)<<",\"right_smb\":"<<quote(rightfile)<<",\"radius_mm\":"<<R<<",\"signed_radius_left\":"<<lr<<",\"signed_radius_right\":"<<rr<<",\"xsection_api_enum\":2,\"xsection_meaning\":\"exact circular, not edge blend\",\"trim\":"<<trim<<",\"base_trim\":0,\"complete_components_deep_copied\":true,\"finite_face_selection_by_world_samples\":true,\"master_flag_supplied\":false,\"propagation_flag_supplied\":false,\"explicit_post_crop\":false}";req.close();
  stage="native_surface_pair_call";SmFilletExecutive exec(*context);SmBrep*result=nullptr;auto ts=std::chrono::steady_clock::now();auto st=exec.SurfaceSurfaceFillet(*context,l->GetSurface(),r->GetSurface(),lr,rr,1e-6,result,2,.001,static_cast<SmBoundaryTrimmingType>(trim),0,FALSE,FALSE);double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-ts).count();std::ofstream(out+"/operation.json")<<std::setprecision(17)<<"{\"status\":"<<st<<",\"nonnull_result\":"<<(result?"true":"false")<<",\"operation_ms\":"<<ms<<"}";
  stage="preserve_source_and_mutated_copies";save(rawleft,out+"/source-object-left-after");save(rawright,out+"/source-object-right-after");save(left,out+"/post-left");save(right,out+"/post-right");stats(left,out+"/post-left-stats.json");stats(right,out+"/post-right-stats.json");
  if(result){save(result,out+"/native");stats(result,out+"/native-stats.json");geometry(result,out+"/native-edges.json");}
  if(st!=SM_SUCCESS||!result){std::ofstream(out+"/status.json")<<"{\"stage\":\"native_failed_or_no_solution\",\"native_status\":"<<st<<",\"nonnull_result\":"<<(result?"true":"false")<<"}";return 3;}
  stage="readback_actual_geometry";SmBrep*rb=new(*context)SmBrep();ck(rb->ReadFromFile(*context,(out+"/native.smb").c_str(),SM_ASCII,TRUE),"native readback");stats(rb,out+"/readback-stats.json");geometry(rb,out+"/readback-edges.json");contact_check(rb,original_left,original_right,ls,rs,out+"/contact-check.json");mesh(rb,out+"/mesh.json");std::ofstream(out+"/status.json")<<"{\"stage\":\"native_returned_and_readback\",\"special_source_function_verified\":false}";return 0;
 }catch(const std::exception&e){std::ofstream(out+"/status.json")<<"{\"stage\":"<<quote(stage)<<",\"error\":"<<quote(e.what())<<"}";std::cerr<<stage<<": "<<e.what()<<'\n';return 1;}catch(...){std::ofstream(out+"/status.json")<<"{\"stage\":"<<quote(stage)<<",\"error\":\"unknown exception\"}";return 1;}
}
