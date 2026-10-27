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
#include <SmPointClass.h>
#include <SmRegion.h>
#include <typeinfo>
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
static void tol(SmBrep*p){SmTArray<SmFace*>fs;SmTArray<SmEdge*>es;SmTArray<SmVertex*>vs;p->GetFaces(fs);p->GetEdges(es);p->GetVertices(vs);p->SetTolerance(SmZoneTol3d(1e-7),FALSE,FALSE);for(long i=0;i<fs.GetSize();i++)fs[i]->SetTolerance(SmZoneTol3d(1e-7),FALSE,FALSE);for(long i=0;i<es.GetSize();i++)es[i]->SetTolerance(SmZoneTol3d(1e-7),FALSE,FALSE);for(long i=0;i<vs.GetSize();i++)vs[i]->SetTolerance(SmZoneTol3d(1e-7),FALSE,FALSE);}
static void stage_log(const std::string&o,const std::string&s){std::ofstream f(o+"/stage.log",std::ios::app);f<<s<<'\n';std::ofstream(o+"/stage.json")<<"{\"stage\":"<<quote(s)<<"}";std::cout<<s<<std::endl;}
static void classify(SmBrep*p,const std::string&path){
 std::ofstream f(path);f<<std::setprecision(17)<<"{\"native_point_tolerance_mm\":1e-6,\"meaning\":\"0=void/outside,1=material region,2=boundary,-1=error\",\"samples\":[";bool first=true;
 auto sample=[&](const char*group,const std::string&tag,double x,double y,double z,int expected){SmPointClassification pc;int state=-1;auto st=p->Point3DClassify(SmPoint3d(x,y,z),SmZoneTol3d(1e-6),TRUE,pc);if(st==SM_SUCCESS){auto type=pc.GetPointClass();if(type==SM_PC_REGION)state=static_cast<SmRegion*>(pc.GetObject())->IsVoid()?0:1;else if(type==SM_PC_FACE||type==SM_PC_EDGE||type==SM_PC_VERTEX)state=2;}if(!first)f<<',';first=false;f<<"{\"group\":"<<quote(group)<<",\"tag\":"<<quote(tag)<<",\"point\":["<<x<<','<<y<<','<<z<<"],\"source_expected\":"<<expected<<",\"state\":"<<state<<",\"status\":"<<st<<'}';};
 for(double x:{-34.,34.}){
  for(double z:{1.,8.,16.,24.,30.,31.})sample("hole_axis",x<0?"left":"right",x,0,z,0);
  for(int k=0;k<8;k++){double a=2*3.14159265358979323846*k/8;for(double z:{1.,16.,28.,30.})sample("hole_material_ring",x<0?"left":"right",x+4.8*std::cos(a),4.8*std::sin(a),z,1);}
  for(int k=0;k<8;k++){double a=2*3.14159265358979323846*k/8;for(double z:{1.,16.,28.,30.})sample("hole_interior",x<0?"left":"right",x+2.0*std::cos(a),2.0*std::sin(a),z,0);}
 }
 for(double x:{-15.,0.,15.})for(double y:{-5.,0.,5.})for(double z:{33.,36.,39.})sample("pad_witness","raised_pad",x,y,z,1);
 for(double x:{-50.,-40.,-20.,0.,20.,40.,50.})for(double y:{-22.,-10.,10.,22.})for(double z:{.5,1.})sample("untouched_bottom","base_bottom",x,y,z,1);
 for(double x:{-50.,-20.,0.,20.,50.})for(double y:{15.,22.})for(double z:{8.,20.,30.})sample("untouched_back","base_back",x,y,z,1);
 for(double x:{-50.,-20.,0.,20.,50.}){sample("target_corner_should_be_removed","front_top_near",x,-25,31,1);sample("target_corner_should_be_removed","front_top_deeper",x,-22,28,1);}
 f<<"]}";
}
static void surfaces(SmBrep*p,const std::string&path){SmTArray<SmFace*>fs;p->GetFaces(fs);std::ofstream f(path);f<<"{\"surfaces\":[";for(long i=0;i<fs.GetSize();i++){if(i)f<<',';f<<"{\"face_index_1based\":"<<i+1<<",\"rtti_name\":"<<quote(typeid(*fs[i]->GetSurface()).name())<<'}';}f<<"]}";}
int main(int argc,char**argv){
 if(argc!=3)return 2;double radius=std::stod(argv[1]);std::string out=argv[2],stage="initialize";
 try{
  stage_log(out,stage);SmApiCreateContext();SmBrep*p=nullptr;stage="create_base";stage_log(out,stage);ck(SmApiCreateBox(SmVector3d(-55,-26,0),110,52,32,p),"base box");tol(p);
  for(double x:{-34.,34.}){stage=x<0?"cut_left_through_hole":"cut_right_through_hole";stage_log(out,stage);SmBrep*tool=nullptr,*r=nullptr;ck(SmApiCreateCylinder(SmVector3d(x,0,-2),3.6,36,tool),"through hole cutter");tol(tool);ck(SmApiBooleanDifference(p,tool,r),"native through hole difference");if(!r)throw std::runtime_error("null difference");p=r;tol(p);}
  stage="union_raised_pad";stage_log(out,stage);SmBrep*pad=nullptr,*body=nullptr;ck(SmApiCreateBox(SmVector3d(-17.5,-6.5,32),35,13,8,pad),"raised pad box");tol(pad);ck(SmApiBooleanUnion(p,pad,body),"native pad union");if(!body)throw std::runtime_error("null pad union");p=body;tol(p);
  stage="save_full_input";stage_log(out,stage);save(p,out+"/input");stats(p,out+"/input-stats.json");geometry(p,out+"/input-edges.json");surfaces(p,out+"/input-surfaces.json");classify(p,out+"/input-pointstates.json");mesh(p,out+"/input-mesh.json");
  stage="select_world_fingerprint";stage_log(out,stage);SmTArray<SmEdge*>es,selected;p->GetEdges(es);long diagnostic_index=0;
  for(long i=0;i<es.GetSize();i++){auto e=es[i];if(!e->GetStartVertex()||!e->GetEndVertex())continue;auto a=e->GetStartVertex()->GetPoint(),b=e->GetEndVertex()->GetPoint();if(std::abs(a.y+26)<1e-6&&std::abs(b.y+26)<1e-6&&std::abs(a.z-32)<1e-6&&std::abs(b.z-32)<1e-6&&std::abs(std::min(a.x,b.x)+55)<1e-6&&std::abs(std::max(a.x,b.x)-55)<1e-6){selected.Add(e);diagnostic_index=i+1;}}
  if(selected.GetSize()!=1)throw std::runtime_error("world target edge not unique");
  std::ofstream req(out+"/request.json");req<<std::setprecision(17)<<"{\"number\":7,\"api\":\"SmApiFilletEdges\",\"native_default\":true,\"selected_fingerprint\":[[-55,-26,32],[55,-26,32]],\"diagnostic_edge_index\":"<<diagnostic_index<<",\"selected_count\":1,\"radius_mm\":"<<radius<<",\"xsect_type\":1,\"continuity\":1,\"thumbweight\":1,\"transfer_yes_no_flag_supplied\":false,\"input_method\":\"native primitives + two Boolean differences + pad Boolean union\"}";req.close();
  stage="native_default_fillet";stage_log(out,stage);auto start=std::chrono::steady_clock::now();auto st=SmApiFilletEdges(p,selected,radius,1,1,1.);double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();std::ofstream(out+"/operation.json")<<std::setprecision(17)<<"{\"api_status\":"<<st<<",\"operation_ms\":"<<ms<<"}";
  stage="save_raw_candidate";stage_log(out,stage);save(p,out+"/native");stats(p,out+"/native-stats.json");geometry(p,out+"/native-edges.json");surfaces(p,out+"/native-surfaces.json");
  if(st!=SM_SUCCESS){std::ofstream(out+"/status.json")<<"{\"stage\":\"native_operation_failed\",\"api_status\":"<<st<<",\"raw_candidate_saved\":true}";return 3;}
  stage="native_readback";stage_log(out,stage);auto*ctx=SmApiGetOrCreateContext();SmBrep*rb=new(*ctx)SmBrep();ck(rb->ReadFromFile(*ctx,(out+"/native.smb").c_str(),SM_ASCII,TRUE),"native readback");stats(rb,out+"/readback-stats.json");geometry(rb,out+"/readback-edges.json");classify(rb,out+"/readback-pointstates.json");surfaces(rb,out+"/readback-surfaces.json");stage="actual_result_mesh";stage_log(out,stage);mesh(rb,out+"/mesh.json");std::ofstream(out+"/status.json")<<"{\"stage\":\"native_returned_saved_readback\",\"source_transfer_option_equivalence_verified\":false}";return 0;
 }catch(const std::exception&e){std::ofstream(out+"/status.json")<<"{\"stage\":"<<quote(stage)<<",\"error\":"<<quote(e.what())<<"}";std::cerr<<stage<<": "<<e.what()<<'\n';return 1;}catch(...){std::ofstream(out+"/status.json")<<"{\"stage\":"<<quote(stage)<<",\"error\":\"unknown exception\"}";return 1;}
}
