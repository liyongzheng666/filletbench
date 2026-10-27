#include "base-helpers.hpp"
#include <SmApiCurves.h>
#include <SmContext.h>
#include <SmSurface.h>
#include <filesystem>
namespace fs = std::filesystem;
static std::string path;
static void event(const std::string& s){std::cout<<s<<std::endl;}
static SmBrep* box(double x,double y,double z,double a,double b,double c){SmBrep* p=nullptr;check(SmApiCreateBox(SmVector3d(x,y,z),a,b,c,p),"box");set_input_tolerance(p,1e-7);return p;}
static SmBrep* cyl(double x,double y,double z,double r,double h){SmBrep* p=nullptr;check(SmApiCreateCylinder(SmVector3d(x,y,z),r,h,p),"cylinder");set_input_tolerance(p,1e-7);return p;}
static SmBrep* unite(SmBrep* a,SmBrep* b){SmBrep* p=nullptr;check(SmApiBooleanUnion(a,b,p),"native union");if(!p)throw std::runtime_error("null union");set_input_tolerance(p,1e-7);return p;}
static void point(std::ostream& o,const SmPoint3d& p){o<<'['<<p.x<<','<<p.y<<','<<p.z<<']';}
static std::string stats(SmBrep* p){
    SmTArray<SmFace*> fs;SmTArray<SmEdge*> es;SmTArray<SmVertex*> vs;p->GetFaces(fs);p->GetEdges(es);p->GetVertices(vs);
    SmPoint3d mn,mx;check(SmApiBrepBoundingBox(p,TRUE,mn,mx),"bounds");long solids=0,voids=0;check(SmApiBrepMaterialCensus(p,solids,voids),"census");
    double mass=0,area=0,volume=0;SmMassPropertyBehavior behavior(1);SmTArray<SmVector3d> moments;moments.SetSize(8);check(p->ComputePreciseProperties(1e-9,SmPoint3d(0,0,0),behavior,area,volume,mass,moments),"properties");
    std::ostringstream o;o<<std::setprecision(17)<<"{\"valid\":"<<(p->AssertValid(nullptr,SM_LEVEL_2,SM_WALK)?"true":"false")<<",\"manifold\":"<<(p->IsManifoldSolid()?"true":"false")<<",\"solids\":"<<solids<<",\"voids\":"<<voids<<",\"faces\":"<<fs.GetSize()<<",\"edges\":"<<es.GetSize()<<",\"vertices\":"<<vs.GetSize()<<",\"volume\":"<<volume<<",\"area\":"<<area<<",\"bbox\":[";point(o,mn);o<<',';point(o,mx);o<<"]}";return o.str();
}
static void save(SmBrep* p,const std::string& name){
    auto dest=path+"/"+name;check(p->WriteToFile((dest+".smb").c_str(),SM_ASCII,TRUE,FALSE,0),"native WriteToFile");
    std::ofstream(dest+"-stats.json")<<stats(p);bool ok=true;std::ofstream(dest+"-mesh.json")<<mesh_json(p,false,ok);
    SmTArray<SmEdge*> edges;p->GetEdges(edges);std::ofstream eout(dest+"-edges.json");eout<<std::setprecision(17)<<'[';
    for(long j=0;j<edges.GetSize();++j){if(j)eout<<',';auto* e=edges[j];auto interval=e->GetInterval();eout<<"{\"index\":"<<j+1<<",\"polyline\":[";
      for(int k=0;k<=128;++k){SmVector3d a;SmVector3d* pa=&a;SmVector3d* dn=nullptr;check(SmApiEvaluateCurve(e->GetCurve(),interval.GetMin()+(interval.GetMax()-interval.GetMin())*k/128.,pa,dn,dn),"edge eval");if(k)eout<<',';point(eout,a);}eout<<"]}";}
    eout<<']';
}
static SmTArray<SmEdge*> roots(SmBrep* p,const std::string& mode,bool allow_partial=false){
    SmTArray<SmEdge*> edges,selected;p->GetEdges(edges);
    for(long j=0;j<edges.GetSize();++j){auto* e=edges[j];if(e->IsSeam())continue;auto in=e->GetInterval();
      for(double xc:{3.,16.}){if((mode=="left"&&xc!=3)||(mode=="right"&&xc!=16))continue;bool match=true;
        for(int k=0;k<=16;++k){SmVector3d a;SmVector3d* pa=&a;SmVector3d* dn=nullptr;check(SmApiEvaluateCurve(e->GetCurve(),in.GetMin()+(in.GetMax()-in.GetMin())*k/16.,pa,dn,dn),"select sample");if(std::abs(a.z-18)>1e-5||std::abs(std::hypot(a.x-xc,a.y)-5.5)>1e-5){match=false;break;}}
        if(match){SmPoint3d mn,mx;check(SmApiEdgeBoundingBox(e,TRUE,mn,mx),"root bounds");if(allow_partial||(std::abs((mx.x-mn.x)-11)<1e-4&&std::abs((mx.y-mn.y)-11)<1e-4))selected.Add(e);}
      }
    }
    if((allow_partial&&selected.GetSize()==0)||(!allow_partial&&selected.GetSize()!=(mode=="both"?2:1)))throw std::runtime_error("root selector expected "+std::to_string(mode=="both"?2:1)+" found "+std::to_string(selected.GetSize()));return selected;
}
static SmBrep* boss(double xc){
    auto* p=cyl(xc,0,18,5.5,6.3);SmTArray<SmEdge*> edges,top;p->GetEdges(edges);
    for(long i=0;i<edges.GetSize();++i){SmPoint3d mn,mx;check(SmApiEdgeBoundingBox(edges[i],TRUE,mn,mx),"shoulder edge bounds");if(std::abs(mn.z-24.3)<1e-5&&std::abs(mx.z-24.3)<1e-5&&!edges[i]->IsSeam())top.Add(edges[i]);}
    if(top.GetSize()!=1)throw std::runtime_error("shoulder expected one top rim");check(SmApiFilletEdges(p,top,3.3,1,1,1.0),"existing shoulder fillet");if(!p->AssertValid(nullptr,SM_LEVEL_2,SM_WALK))throw std::runtime_error("invalid existing shoulder input");return p;
}
int main(int argc,char** argv){
 if(argc<4)return 3;path=argv[1];fs::create_directories(path);double radius=std::stod(argv[2]);std::string mode=argv[3];std::string stage="startup";
 try{SmTol::SetModelSizeEstimate(.0005);SmApiCreateContext();event("START native SMLib case23");
  stage="build_pad";auto* p=unite(box(0,-12,0,33.6,24,18),cyl(0,0,0,12,18));p=unite(p,box(33.6,-9.6,0,2.4,19.2,18));p=unite(p,cyl(33.6,-9.6,0,2.4,18));p=unite(p,cyl(33.6,9.6,0,2.4,18));
  stage="build_existing_shoulders";p=unite(p,boss(3));p=unite(p,boss(16));if(!p->AssertValid(nullptr,SM_LEVEL_2,SM_WALK))throw std::runtime_error("invalid input");save(p,"before");event("INPUT_VALID "+stats(p));
  if(radius<=0){std::ofstream(path+"/result.json")<<"{\"status\":\"input_only\",\"stats\":"<<stats(p)<<'}';return 0;}
  const auto start=std::chrono::steady_clock::now();stage="native_root_fillet";
  if(mode=="left-then-right"||mode=="right-then-left"){
    std::vector<std::string> order=mode=="left-then-right"?std::vector<std::string>{"left","right"}:std::vector<std::string>{"right","left"};
    int j=0;for(auto& side:order){stage="root_"+side;auto selected=roots(p,side,j>0);event("FILLET "+side+" count="+std::to_string(selected.GetSize()));check(SmApiFilletEdges(p,selected,radius,1,1,1.0),stage.c_str());save(p,"stage"+std::to_string(++j));}
  }else{auto selected=roots(p,mode);event("FILLET "+mode+" count="+std::to_string(selected.GetSize()));check(SmApiFilletEdges(p,selected,radius,1,1,1.0),"native roots");}
  auto elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();stage="native_output";save(p,"after");
  std::ofstream(path+"/result.json")<<std::setprecision(17)<<"{\"status\":\"returned_result\",\"radius\":"<<radius<<",\"mode\":\""<<mode<<"\",\"native_fillet_seconds_including_sequential_checkpoints\":"<<elapsed<<",\"stats\":"<<stats(p)<<'}';event("FILLET_RETURNED "+stats(p));
  stage="native_readback";auto* q=new (*SmApiGetOrCreateContext()) SmBrep();check(q->ReadFromFile(*SmApiGetOrCreateContext(),(path+"/after.smb").c_str(),SM_ASCII,FALSE),"readback");std::ofstream(path+"/readback.json")<<stats(q);event("READBACK_DONE");return 0;
 }catch(const std::exception& ex){std::ofstream(path+"/error.json")<<"{\"stage\":\""<<stage<<"\",\"error\":\""<<json_escape(ex.what())<<"\"}";std::cerr<<"FAILED "<<stage<<": "<<ex.what()<<std::endl;return 1;}
}
