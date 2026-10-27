#include <SmApiBrep.h>
#include <SmApiGeneral.h>
#include <SmApiPrimitives.h>
#include <SmApiQueries.h>
#include <SmApiCurves.h>
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
 double volume=0;auto vst=SmApiBrepComputeVolume(p,1e-8,volume);f<<"{\"valid_level2\":"<<(valid?"true":"false")<<",\"manifold\":"<<(manifold?"true":"false")<<",\"manifold_status\":"<<mst<<",\"census_status\":"<<cst<<",\"solids\":"<<solids<<",\"voids\":"<<voids<<",\"faces\":"<<fs.GetSize()<<",\"edges\":"<<es.GetSize()<<",\"vertices\":"<<vs.GetSize()<<",\"volume_status\":"<<vst<<",\"volume_mm3\":"<<volume<<",\"bbox_status\":"<<bst<<",\"bbox_min\":";pt(f,mn);f<<",\"bbox_max\":";pt(f,mx);f<<",\"vertex_points\":[";for(long i=0;i<vs.GetSize();i++){if(i)f<<',';pt(f,vs[i]->GetPoint());}f<<"]}";
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
int main(int argc,char**argv){
 if(argc!=3)return 2;std::string mode=argv[1],out=argv[2],stage="initialize";
 try{
  SmApiCreateContext();SmBrep*p=nullptr;
  stage="native_trapezoid_sweep";SmPoint3d pts[4]={SmPoint3d(0,0,0),SmPoint3d(XB,0,0),SmPoint3d(XT,0,H),SmPoint3d(0,0,H)};SmTArray<SmCurve*>profile;
  for(int i=0;i<4;i++){SmLine*line=nullptr;ck(SmApiCreateLineSegment(pts[i],pts[(i+1)%4],line),"native trapezoid line");profile.Add(line);}
  ck(SmApiCreateLinearSweep(profile,SmVector3d(0,1,0),Y,TRUE,p),"native capped sweep of exact trapezoid");
  for(long i=0;i<profile.GetSize();i++)delete profile[i];
  stage="input_evidence";save(p,out+"/input");stats(p,out+"/input-stats.json");geometry(p,out+"/input-edges.json");mesh(p,out+"/input-mesh.json");
  SmTArray<SmEdge*> es,selected;p->GetEdges(es);double startz=0,endz=0;long index=0;
  for(long i=0;i<es.GetSize();i++){auto e=es[i];if(!e->GetStartVertex()||!e->GetEndVertex())continue;auto a=e->GetStartVertex()->GetPoint(),b=e->GetEndVertex()->GetPoint();if(std::abs(a.x)<1e-7&&std::abs(a.y)<1e-7&&std::abs(b.x)<1e-7&&std::abs(b.y)<1e-7&&std::abs(std::abs(a.z-b.z)-H)<1e-6){selected.Add(e);startz=a.z;endz=b.z;index=i+1;}}
  if(selected.GetSize()!=1)throw std::runtime_error("target selector not unique");
  double sr=DB+(DT-DB)*startz/H,er=DB+(DT-DB)*endz/H;
  std::ofstream request(out+"/request.json");request<<std::setprecision(17)<<"{\"case\":34,\"mode\":"<<quote(mode)<<",\"height\":"<<H<<",\"X_bottom\":"<<XB<<",\"X_top\":"<<XT<<",\"Y_width\":"<<Y<<",\"target_index_diagnostic_only\":"<<index<<",\"selected_count\":1,\"target_start_z\":"<<startz<<",\"target_end_z\":"<<endz<<",\"radius_at_edge_start\":"<<sr<<",\"radius_at_edge_end\":"<<er<<",\"source_absolute_rho_parameter_used\":false,\"source_relative_rho_parameter_used\":false}";request.close();
  if(mode=="input-only"){std::ofstream(out+"/status.json")<<"{\"stage\":\"input_complete\",\"native_operation_executed\":false}";delete p;return 0;}
  stage="native_fillet";auto t0=std::chrono::steady_clock::now();SmApiStatus st;
  if(mode=="circular-r6")st=SmApiFilletEdges(p,selected,6.,1,1,1.);
  else if(mode=="variable-source-end-radii")st=SmApiVariableRadiusFillet(p,selected,sr,er,1,1);
  else throw std::runtime_error("unknown mode");
  double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-t0).count();std::ofstream(out+"/operation-status.json")<<std::setprecision(17)<<"{\"api_status\":"<<st<<",\"operation_ms\":"<<ms<<",\"source_rho_semantics_verified\":false}";
  // Preserve raw returned BRep even if API reports failure.
  stage="save_raw_returned_candidate";save(p,out+"/candidate");stats(p,out+"/candidate-stats.json");geometry(p,out+"/candidate-edges.json");
  if(st!=SM_SUCCESS){std::ofstream(out+"/status.json")<<"{\"stage\":\"operation_failed\",\"api_status\":"<<st<<",\"candidate_preserved\":true}";delete p;return 3;}
  stage="native_readback";const auto*ctx=SmApiGetOrCreateContext();SmBrep*rb=new(*ctx)SmBrep();ck(rb->ReadFromFile(*ctx,(out+"/candidate.smb").c_str(),SM_ASCII,TRUE),"readback");stats(rb,out+"/readback-stats.json");geometry(rb,out+"/readback-edges.json");
  stage="result_mesh";mesh(rb,out+"/result-mesh.json");std::ofstream(out+"/status.json")<<"{\"stage\":\"executed_and_readback_complete\",\"native_operation_executed\":true,\"source_rho_semantics_verified\":false}";delete rb;delete p;return 0;
 }catch(const std::exception&e){std::ofstream(out+"/status.json")<<"{\"stage\":"<<quote(stage)<<",\"error\":"<<quote(e.what())<<"}";std::cerr<<stage<<": "<<e.what()<<'\n';return 1;}catch(...){std::ofstream(out+"/status.json")<<"{\"stage\":"<<quote(stage)<<",\"error\":\"unknown exception\"}";return 1;}
}
