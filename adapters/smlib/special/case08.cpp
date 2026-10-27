#include <SmApiBrep.h>
#include <SmApiGeneral.h>
#include <SmApiPrimitives.h>
#include <SmApiQueries.h>
#include <SmBrep.h>
#include <SmVector3d.h>
#include <SmPointClass.h>
#include <SmRegion.h>
#include <SmVertex.h>
#include <SmEdge.h>
#include <SmFace.h>
#include <SmTol.h>
#include <chrono>
#include <memory>
#include <stdexcept>
#include <string>
#include <cstdio>
#include <limits>
#include <algorithm>
#include <SmPoly.h>
#include <SmCurve.h>
#include <cmath>
#include <fstream>
#include <sstream>
#include <iomanip>
#include <unordered_map>
#include <vector>

struct Output {
    double volume, area, centroid[3], bbox[6], operation_ms;
    double configured_zone_tolerance, model_size_estimate, default_zone_tolerance, input_max_vertex_tol, input_max_edge_tol, result_max_vertex_tol, result_max_edge_tol;
    long solids, voids, faces, edges, vertices;
    int empty, manifold, valid, result_constructed, selected_edges_count;
    double before_volume,before_area;
    int input_a_valid,input_b_valid,input_a_manifold,input_b_manifold,input_a_valid_before_tolerance,input_b_valid_before_tolerance;
};
static void check(SmApiStatus s, const char* f) {
    if (s != SM_SUCCESS) throw std::runtime_error(std::string(f) + " status " + std::to_string(s));
}
struct ShapeNode {
    int kind, left, right, operation;
    double origin[3], params[3], scale[3], axis[3], angle, center[3], translate[3];
};
static void set_input_tolerance(SmBrep* p, double tolerance);
static void make_shape(const ShapeNode* nodes, int idx, SmBrep*& p, double tol, int depth=0, int* valid_before_tolerance=nullptr) {
    if(depth>6)throw std::runtime_error("composite depth exceeded");
    const auto& n=nodes[idx];SmVector3d origin(n.origin[0],n.origin[1],n.origin[2]);
    if(n.kind==0)check(SmApiCreateBox(origin,n.params[0],n.params[1],n.params[2],p),"create box");
    else if(n.kind==1)check(SmApiCreateSphere(origin,n.params[0],p),"create sphere");
    else if(n.kind==2)check(SmApiCreateCylinder(origin,n.params[0],n.params[1],p),"create cylinder");
    else if(n.kind==3)check(SmApiCreateTorus(origin,n.params[0],n.params[1],p),"create torus");
    else if(n.kind==4)check(SmApiCreateCone(origin,n.params[0],n.params[1],n.params[2],p),"create cone");
    else if(n.kind==5){
        check(SmApiCreateSphere(SmVector3d(0,0,0),1,p),"ellipsoid seed sphere");
        check(SmApiScale(p,SmVector3d(n.scale[0],n.scale[1],n.scale[2])),"ellipsoid scale");
        check(SmApiTranslate(p,origin),"ellipsoid origin");
    }else if(n.kind==6){
        SmBrep* a=nullptr;SmBrep* b=nullptr;make_shape(nodes,n.left,a,tol,depth+1);make_shape(nodes,n.right,b,tol,depth+1);
        SmApiStatus st=n.operation==0?SmApiBooleanUnion(a,b,p):n.operation==1?SmApiBooleanDifference(a,b,p):SmApiBooleanIntersection(a,b,p);
        check(st,"input composite boolean");if(!p)throw std::runtime_error("null composite");
    }else throw std::runtime_error("unsupported shape kind");
    if(n.angle!=0)check(SmApiRotate(p,SmVector3d(n.center[0],n.center[1],n.center[2]),SmVector3d(n.axis[0],n.axis[1],n.axis[2]),n.angle),"rotate input");
    if(n.translate[0]||n.translate[1]||n.translate[2])check(SmApiTranslate(p,SmVector3d(n.translate[0],n.translate[1],n.translate[2])),"translate input");
    if(valid_before_tolerance){try{*valid_before_tolerance=p->AssertValid(nullptr,SM_LEVEL_2,SM_WALK);}catch(...){*valid_before_tolerance=-1;}}
    set_input_tolerance(p,tol);
}
static void select_edges(SmBrep* p,int selector,SmTArray<SmEdge*>& selected) {
    SmTArray<SmEdge*> edges;p->GetEdges(edges);SmPoint3d mn,mx;check(SmApiBrepBoundingBox(p,TRUE,mn,mx),"fillet bounds");
    const double eps=1e-6;
    for(long i=0;i<edges.GetSize();++i){auto* e=edges[i];if(e->IsSeam()||e->IsTangentEdge(1e-5))continue;
        if(selector==0){selected.Add(e);continue;}
        if(!e->GetStartVertex()||!e->GetEndVertex())continue;
        auto a=e->GetStartVertex()->GetPoint(),b=e->GetEndVertex()->GetPoint();
        bool vertical=std::abs(a.x-b.x)<eps&&std::abs(a.y-b.y)<eps&&std::abs(a.z-b.z)>eps;
        bool pick=selector==1?vertical:selector==2?std::abs(a.z-mx.z)<eps&&std::abs(b.z-mx.z)<eps:vertical&&std::abs(a.x-mn.x)<eps&&std::abs(a.y-mn.y)<eps;
        if(pick)selected.Add(e);
    }
    if(!selected.GetSize())throw std::runtime_error("no edges matched geometric fillet selector");
}
static void set_input_tolerance(SmBrep* p, double tolerance) {
    if(tolerance<=0) return;
    SmTArray<SmFace*> fs;SmTArray<SmEdge*> es;SmTArray<SmVertex*> vs;
    p->GetFaces(fs);p->GetEdges(es);p->GetVertices(vs);
    p->SetTolerance(SmZoneTol3d(tolerance),FALSE,FALSE);
    for(long i=0;i<fs.GetSize();++i)fs[i]->SetTolerance(SmZoneTol3d(tolerance),FALSE,FALSE);
    for(long i=0;i<es.GetSize();++i)es[i]->SetTolerance(SmZoneTol3d(tolerance),FALSE,FALSE);
    for(long i=0;i<vs.GetSize();++i)vs[i]->SetTolerance(SmZoneTol3d(tolerance),FALSE,FALSE);
}
static void tolerances(SmBrep* p, double& vt, double& et) {
    SmTArray<SmVertex*> vs; SmTArray<SmEdge*> es;
    p->GetVertices(vs); p->GetEdges(es);
    vt = 0; et = 0;
    for (long i = 0; i < vs.GetSize(); ++i) vt = std::max(vt, SmTol::GetZoneTol3d(vs[i]).val);
    for (long i = 0; i < es.GetSize(); ++i) et = std::max(et, SmTol::GetZoneTol3d(es[i]).val);
}

static std::string json_escape(const std::string& s) {
    std::string out;
    for(char c:s) { if(c=='"'||c=='\\')out+='\\'; if(c=='\n'){out+="\\n";continue;} out+=c; }
    return out;
}
static std::string mesh_json(SmBrep* shape, bool empty, bool& success) {
    if(empty) return "{\"positions\":[],\"indices\":[],\"empty\":true,\"status\":\"ok\"}";
    try {
        SmPolyBrep* mesh=nullptr; SmTessellationParams params; SmTessellationReport report;
        params.dChordHeightTol=1e-3;params.dCurveAngleTolDeg=10;params.dSurfaceAngleTolDeg=10;
        check(SmApiTessellate(shape,mesh,params,FALSE,nullptr,&report),"SmApiTessellate");
        std::unique_ptr<SmPolyBrep> owner(mesh);
        if(!mesh)throw std::runtime_error("nonempty native model returned null tessellation");
        SmTArray<SmPolyVertex*> vs;SmTArray<SmPolyFace*> fs;
        mesh->GetPolyVertices(vs);mesh->GetPolyFaces(fs);
        if(!vs.GetSize()||!fs.GetSize())throw std::runtime_error("nonempty native model returned empty tessellation");
        std::unordered_map<SmPolyVertex*,long> ids;
        std::ostringstream out;out<<std::setprecision(17)<<"{\"positions\":[";
        for(long i=0;i<vs.GetSize();++i){ids[vs[i]]=i;const auto& pt=vs[i]->GetPoint();if(i)out<<',';out<<pt.x<<','<<pt.y<<','<<pt.z;}
        out<<"],\"indices\":[";bool first=true;
        for(long i=0;i<fs.GetSize();++i){
            auto* loop=fs[i]->GetOuterPolyLoop();if(!loop)throw std::runtime_error("mesh face without outer loop");
            SmTArray<SmPolyEdge*> es;loop->GetPolyEdges(es);
            if(es.GetSize()!=3)throw std::runtime_error("tessellation returned non-triangle face");
            for(long j=0;j<3;++j){if(!first)out<<',';first=false;out<<ids.at(es[j]->GetStartPolyVertex());}
        }
        out<<"],\"empty\":false,\"status\":\"ok\",\"method\":\"SmApiTessellate\"}";
        return out.str();
    }catch(const std::exception& e){success=false;return "{\"positions\":[],\"indices\":[],\"empty\":false,\"status\":\"error\",\"error\":\""+json_escape(e.what())+"\"}";}
}

#include <SmApiCurves.h>
#include <SmApiTrimmedSurfaces.h>
#include <SmApiSurfaces.h>
#include <SmLine.h>
#include <SmSurface.h>
#include <SmContext.h>
static void ck(SmStatus s,const char* name){if(s!=SM_SUCCESS)throw std::runtime_error(std::string(name)+" status "+std::to_string(s));}
static SmBrep* face(const std::vector<SmPoint3d>& pts){SmTArray<SmCurve*> curves;for(size_t i=0;i<pts.size();++i){SmLine* ln=nullptr;check(SmApiCreateLineSegment(pts[i],pts[(i+1)%pts.size()],ln),"line");curves.Add(ln);}SmBrep* r=nullptr;check(SmApiCreatePlanarFaces(curves,r),"planar face");return r;}
static void vecj(std::ostream&o,const SmPoint3d&p){o<<'['<<p.x<<','<<p.y<<','<<p.z<<']';}
static void snapshot(SmBrep* p,const std::string& path){
 std::ofstream f(path);f<<std::setprecision(17);SmTArray<SmFace*> fs;SmTArray<SmEdge*> es;SmTArray<SmVertex*> vs;p->GetFaces(fs);p->GetEdges(es);p->GetVertices(vs);long so=-1,vo=-1;auto mc=SmApiBrepMaterialCensus(p,so,vo);int valid=p->AssertValid(nullptr,SM_LEVEL_2,SM_WALK);SmPoint3d mn,mx;check(SmApiBrepBoundingBox(p,TRUE,mn,mx),"bounds");
 f<<"{\"valid\":"<<valid<<",\"faces\":"<<fs.GetSize()<<",\"edges\":"<<es.GetSize()<<",\"vertices\":"<<vs.GetSize()<<",\"solids\":"<<so<<",\"voids\":"<<vo<<",\"material_census_status\":"<<mc<<",\"manifold_solid\":"<<p->IsManifoldSolid()<<",\"bbox\":["<<mn.x<<','<<mn.y<<','<<mn.z<<','<<mx.x<<','<<mx.y<<','<<mx.z<<"],\"surfaces\":[";
 for(long i=0;i<fs.GetSize();++i){if(i)f<<',';auto* s=fs[i]->GetSurface();SmPoint3d ip;auto is=fs[i]->CalculateAnInternalPoint(ip);f<<"{\"face\":"<<i+1<<",\"type\":\""<<s->GetTypeString()<<"\",\"sheet\":"<<fs[i]->IsSheet()<<",\"internal_point_status\":"<<is<<",\"internal_point\":";vecj(f,ip);double area=-1;SmPoint3d centroid;auto area_status=SmApiFaceComputeCentroid(fs[i],1e-4,area,centroid);f<<",\"area_status\":"<<area_status<<",\"area\":"<<area<<",\"samples\":[";auto domain=fs[i]->GetUVDomain();bool firstSample=true;for(int iu=0;iu<=10;++iu)for(int iv=0;iv<=16;++iv){SmPoint2d uv(domain.GetUMin()+(domain.GetUMax()-domain.GetUMin())*iu/10.,domain.GetVMin()+(domain.GetVMax()-domain.GetVMin())*iv/16.);int classification=0;auto cs=SmApiFaceClassifyUV(fs[i],uv,classification);if(cs!=SM_SUCCESS||classification==SM_PC_UNKNOWN)continue;SmPoint3d qp;auto ev=s->EvaluatePoint(uv,qp);if(ev!=SM_SUCCESS)continue;if(!firstSample)f<<',';firstSample=false;vecj(f,qp);}f<<"]}";}f<<"],\"edge_samples\":[";
 for(long i=0;i<es.GetSize();++i){if(i)f<<',';SmTArray<SmFace*> owners;es[i]->GetFaces(owners);auto iv=es[i]->GetInterval();f<<"{\"edge\":"<<i+1<<",\"owner_count\":"<<owners.GetSize()<<",\"samples\":[";
 for(int j=0;j<33;++j){if(j)f<<',';SmPoint3d pt;ck(es[i]->GetCurve()->EvaluatePoint(iv.Evaluate(j/32.),pt),"edge sample");vecj(f,pt);}f<<']';
 if(owners.GetSize()==2){f<<",\"join_samples\":[";for(int j=1;j<10;++j){if(j>1)f<<',';SmPoint3d pt;ck(es[i]->GetCurve()->EvaluatePoint(iv.Evaluate(j/10.),pt),"join sample");f<<"{\"point\":";vecj(f,pt);f<<",\"owners\":[";for(int k=0;k<2;++k){if(k)f<<',';SmPoint3d qp;SmTArray<SmPoint2d> uvs;double dist=-1;auto st=SmApiSurfaceClosestPoint(owners[k]->GetSurface(),pt,qp,uvs,dist);f<<"{\"surface\":\""<<owners[k]->GetSurface()->GetTypeString()<<"\",\"closest_status\":"<<st<<",\"distance\":"<<dist;
 if(st==SM_SUCCESS&&uvs.GetSize()){SmVector3d nr;auto ns=owners[k]->GetSurface()->EvaluateNormal(uvs[0],TRUE,TRUE,nr);f<<",\"normal_status\":"<<ns<<",\"normal\":";vecj(f,nr);}f<<'}';}f<<"]}";}f<<']';}f<<'}';}
 f<<"]}";
 bool ok=true;auto m=mesh_json(p,false,ok);std::ofstream(path+".mesh.json")<<m;
}
int main(int argc,char**argv){std::string dir=argv[1];double radius=argc>2?std::stod(argv[2]):12;const char* stage="init";std::ofstream rec(dir+"/run.json");rec<<std::setprecision(17);try{
 std::cout<<"INIT"<<std::endl;SmApiCreateContext();stage="build input";
 SmBrep* p=face({{0,0,40},{100,0,40},{100,34,40},{0,34,40}});SmBrep* b=face({{0,0,40},{0,0,0},{35,0,0},{35,0,27},{65,0,27},{65,0,0},{100,0,0},{100,0,40}});ck(p->MergeBrep(*b),"MergeBrep");SmBoolean mode=FALSE;ULONG stitched=0;double vg=-1,eg=-1;check(SmApiStitchIntoShell(p,mode,1e-7,stitched,vg,eg),"StitchIntoShell");std::cout<<"STITCHED "<<stitched<<" gaps "<<vg<<" "<<eg<<std::endl;
 snapshot(p,dir+"/input.json");ck(p->WriteToFile((dir+"/input.smb").c_str()),"write input");
 SmTArray<SmEdge*> es,sel;p->GetEdges(es);for(long i=0;i<es.GetSize();++i){SmTArray<SmFace*> fs;es[i]->GetFaces(fs);if(fs.GetSize()==2&&es[i]->GetStartVertex()&&es[i]->GetEndVertex()){auto a=es[i]->GetStartVertex()->GetPoint(),b=es[i]->GetEndVertex()->GetPoint();if(std::abs(a.y)<1e-7&&std::abs(b.y)<1e-7&&std::abs(a.z-40)<1e-7&&std::abs(b.z-40)<1e-7&&std::abs(std::abs(a.x-b.x)-100)<1e-7)sel.Add(es[i]);}}
 if(sel.GetSize()!=1)throw std::runtime_error("Expected one actual shared root edge, got "+std::to_string(sel.GetSize()));
 stage="native fillet";std::cout<<"CALL SmApiFilletEdges R="<<radius<<" selected="<<sel.GetSize()<<std::endl;auto start=std::chrono::steady_clock::now();auto st=SmApiFilletEdges(p,sel,radius,1,1,1.0);auto ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();std::cout<<"RETURN "<<st<<" milliseconds "<<ms<<std::endl;
 std::ofstream(dir+"/call-returned.json")<<"{\"call_status\":"<<st<<",\"SM_SUCCESS\":"<<SM_SUCCESS<<",\"radius_mm\":"<<radius<<",\"elapsed_ms\":"<<ms<<",\"selected_edges\":1}";stage="save result";auto ws=p->WriteToFile((dir+"/result.smb").c_str());snapshot(p,dir+"/result.json");std::cout<<"READBACK_BEGIN"<<std::endl;SmBrep* back = new (*p->GetContext()) SmBrep();auto rs=back->ReadFromFile(*p->GetContext(),(dir+"/result.smb").c_str());std::cout<<"READBACK_RETURN "<<rs<<std::endl;int bv=rs==SM_SUCCESS?back->AssertValid(nullptr,SM_LEVEL_2,SM_WALK):-1;if(rs==SM_SUCCESS)snapshot(back,dir+"/readback.json");rec<<"{\"status\":\"returned\",\"radius_mm\":"<<radius<<",\"call_status\":"<<st<<",\"SM_SUCCESS\":"<<SM_SUCCESS<<",\"selected_edges\":1,\"elapsed_ms\":"<<ms<<",\"write_status\":"<<ws<<",\"read_status\":"<<rs<<",\"readback_valid\":"<<bv<<",\"preserve_notch_option_supplied\":false}";return 0;
 }catch(const std::exception&e){rec<<"{\"status\":\"exception\",\"stage\":\""<<stage<<"\",\"error\":\""<<json_escape(e.what())<<"\"}";std::cerr<<stage<<": "<<e.what()<<std::endl;return 1;}}
