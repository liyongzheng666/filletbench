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
#include <SmContext.h>
#include <SmLine.h>
#include <SmApiCurves.h>
#include <SmApiTrimmedSurfaces.h>
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
        bool pick=selector==4?(std::abs(a.y-29)<eps&&std::abs(b.y-29)<eps&&std::abs(a.z-12)<eps&&std::abs(b.z-12)<eps&&std::abs(std::abs(a.x-b.x)-70)<eps):selector==1?vertical:selector==2?std::abs(a.z-mx.z)<eps&&std::abs(b.z-mx.z)<eps:vertical&&std::abs(a.x-mn.x)<eps&&std::abs(a.y-mn.y)<eps;
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

static void native_evidence(SmBrep* p,const std::string& stem) {
 std::ofstream out(stem+"-native.json");out<<std::setprecision(17)<<"{";
 int v=-1,m=-1;SmStatus ws=SM_SUCCESS,rs=SM_SUCCESS;int rv=-1,rm=-1;
 try{v=p->AssertValid(nullptr,SM_LEVEL_2,SM_WALK);m=p->IsManifoldSolid();}catch(...){}
 try{ws=p->WriteToFile((stem+".smb").c_str(),SM_ASCII,TRUE,FALSE,0.0);
  if(ws==SM_SUCCESS){std::unique_ptr<SmBrep> q(new (*p->GetContext()) SmBrep());rs=q->ReadFromFile(*p->GetContext(),(stem+".smb").c_str(),SM_ASCII,FALSE);if(rs==SM_SUCCESS){rv=q->AssertValid(nullptr,SM_LEVEL_2,SM_WALK);rm=q->IsManifoldSolid();}}
 }catch(...){rs=SM_ERR_INVALID_INPUT;}
 out<<"\"native_valid\":"<<v<<",\"manifold\":"<<m<<",\"write_status\":"<<ws<<",\"read_status\":"<<rs<<",\"readback_valid\":"<<rv<<",\"readback_manifold\":"<<rm<<",\"edges\":[";
 SmTArray<SmEdge*> es;p->GetEdges(es);
 for(long i=0;i<es.GetSize();++i){if(i)out<<',';auto* e=es[i];out<<"{\"index\":"<<i<<",\"endpoints\":[";
  if(e->GetStartVertex()&&e->GetEndVertex()){auto a=e->GetStartVertex()->GetPoint(),b=e->GetEndVertex()->GetPoint();out<<'['<<a.x<<','<<a.y<<','<<a.z<<"],["<<b.x<<','<<b.y<<','<<b.z<<']';}out<<"]}";}
 out<<"]}";
}
static SmBrep* polygon_face(const std::vector<SmPoint3d>& points) {
 SmTArray<SmCurve*> curves;
 for(size_t i=0;i<points.size();++i){SmLine* l=nullptr;check(SmApiCreateLineSegment(points[i],points[(i+1)%points.size()],l),"aux segment");curves.Add(l);}
 SmBrep* p=nullptr;check(SmApiCreatePlanarFaces(curves,p),"aux planar face");return p;
}
extern "C" int smlib_caps_aux(const char* prefix,int kind,double dx,char* error,int cap) {
 try{SmApiCreateContext();std::vector<SmBrep*> faces;
  if(kind==0)faces.push_back(polygon_face({{29,29,15},{29,38,15},{29,38,41},{29,29,41}}));
  else if(kind==1)faces.push_back(polygon_face({{9,17,12},{16,37,12},{40,37,28},{33,17,28}}));
  else{double xs[]={24,24,27,27,24,24},ys[]={-3,8,15,24,31,43};for(int i=0;i<5;++i)faces.push_back(polygon_face({{dx+xs[i],ys[i],-3},{dx+xs[i+1],ys[i+1],-3},{dx+xs[i+1],ys[i+1],47},{dx+xs[i],ys[i],47}}));}
  SmBrep* result=faces[0];
  if(faces.size()>1){SmTArray<SmBrep*> all;for(auto* p:faces)all.Add(p);check(SmApiMergeBreps(all,SM_BO_MERGE,result),"merge five cap faces");}
  native_evidence(result,prefix);bool ok=true;std::ofstream mesh(std::string(prefix)+"-mesh.json");mesh<<mesh_json(result,false,ok);delete result;snprintf(error,cap,"%s",ok?"":"aux mesh failed");return ok?0:2;
 }catch(const std::exception& e){snprintf(error,cap,"%s",e.what());return 1;}catch(...){snprintf(error,cap,"unknown aux failure");return 3;}
}

extern "C" int smlib_advanced_run(const ShapeNode* nodes, int a_idx, int b_idx, int op, double fillet_radius, int selector,
    const double* probes, int nprobes, double point_tol, double accuracy, double model_tol, const char* mesh_path, int* states, Output* out, char* error, int cap) {
    std::string errors, mesh_a, mesh_b;
    bool mesh_ok=true;
    const bool export_mesh=mesh_path && mesh_path[0];
    const char* stage="initialization";
    auto write_mesh=[&](const std::string& result,const char* status){if(export_mesh){std::ofstream mf(mesh_path);mf<<"{\"a\":"<<(mesh_a.empty()?"null":mesh_a)<<",\"b\":"<<(mesh_b.empty()?"null":mesh_b)<<",\"result\":"<<result<<",\"mesh_status\":\""<<status<<"\",\"stage\":\""<<stage<<"\",\"chord_height\":0.001,\"angle_degrees\":10}";}};
    auto diagnose = [&](const char* stage, auto fn) {
        try { fn(); }
        catch (const std::exception& e) { errors += std::string(stage) + ": " + e.what() + "\n"; }
        catch (...) { errors += std::string(stage) + ": unknown C++ exception\n"; }
    };
    try {
        const double nan = std::numeric_limits<double>::quiet_NaN();
        out->volume = out->area = out->before_volume = out->before_area = nan;
        for (double& v : out->centroid) v = nan;
        for (double& v : out->bbox) v = nan;
        out->solids = out->voids = -1;
        out->empty = out->manifold = out->valid = -1;
        out->input_a_valid=out->input_b_valid=out->input_a_manifold=out->input_b_manifold=out->input_a_valid_before_tolerance=out->input_b_valid_before_tolerance=-1;
        for (int i=0; i<nprobes; ++i) states[i] = -1;
        out->default_zone_tolerance = SmTol::GetZoneTol3d().val;
        if(model_tol>0) {
            if(model_tol==1e-7) SmTol::SetModelSizeEstimate(0.0005);
            else if(model_tol==1e-5) SmTol::SetModelSizeEstimate(50);
            else throw std::runtime_error("supported model_tolerance: null, 1e-7, 1e-5");
        }
        out->configured_zone_tolerance=SmTol::GetZoneTol3d().val;
        out->model_size_estimate=SmTol::GetModelSizeEstimate();
        SmApiCreateContext();
        SmBrep *pa = nullptr, *pb = nullptr, *r = nullptr;
        stage="construct_inputs";make_shape(nodes,a_idx,pa,model_tol,0,&out->input_a_valid_before_tolerance); if(op!=3)make_shape(nodes,b_idx,pb,model_tol,0,&out->input_b_valid_before_tolerance);
        set_input_tolerance(pa,model_tol);if(pb)set_input_tolerance(pb,model_tol);
        diagnose("input A validity",[&]{out->input_a_valid=pa->AssertValid(nullptr,SM_LEVEL_2,SM_WALK);out->input_a_manifold=pa->IsManifoldSolid();});
        if(pb)diagnose("input B validity",[&]{out->input_b_valid=pb->AssertValid(nullptr,SM_LEVEL_2,SM_WALK);out->input_b_manifold=pb->IsManifoldSolid();});
        if(export_mesh)native_evidence(pa,std::string(mesh_path)+"-input");
        double bvt=0, bet=0;
        diagnose("input tolerances", [&]{
            tolerances(pa, out->input_max_vertex_tol, out->input_max_edge_tol);
            if(pb)tolerances(pb, bvt, bet);
            out->input_max_vertex_tol = std::max(out->input_max_vertex_tol,bvt);
            out->input_max_edge_tol = std::max(out->input_max_edge_tol,bet);
        });

        if(export_mesh){
            // Mesh official deep copies only: keep operand caches/tolerances untouched.
            std::unique_ptr<SmBrep> copy_a(new (*pa->GetContext()) SmBrep(*pa));
            std::unique_ptr<SmBrep> copy_b(pb?new (*pb->GetContext()) SmBrep(*pb):nullptr);
            mesh_a=mesh_json(copy_a.get(),false,mesh_ok);
            mesh_b=mesh_json(copy_b.get(),!pb,mesh_ok);
            write_mesh("{\"positions\":[],\"indices\":[],\"empty\":false,\"status\":\"pending\"}","pending");
        }
        diagnose("before properties",[&]{
            double mass=0,area=0,volume=0;SmMassPropertyBehavior behavior(1.0);SmTArray<SmVector3d> moments;moments.SetSize(8);
            check(pa->ComputePreciseProperties(accuracy,SmPoint3d(0,0,0),behavior,area,volume,mass,moments),"before properties");out->before_volume=volume;out->before_area=area;
        });
        stage=op==3?"fillet":"boolean";
        auto start=std::chrono::steady_clock::now();
        SmApiStatus status;
        if(op==0) status=SmApiBooleanUnion(pa,pb,r);
        else if(op==1) status=SmApiBooleanDifference(pa,pb,r);
        else if(op==2) status=SmApiBooleanIntersection(pa,pb,r);
        else if(op==3){stage="fillet_selection";SmTArray<SmEdge*> selected;select_edges(pa,selector,selected);out->selected_edges_count=selected.GetSize();stage="fillet";status=SmApiFilletEdges(pa,selected,fillet_radius,1,1,1.0);r=pa;}
        else throw std::runtime_error("invalid operation");
        out->operation_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
        out->result_constructed = r != nullptr;
        if(export_mesh&&r){native_evidence(r,std::string(mesh_path)+"-result");std::ofstream st(std::string(mesh_path)+"-api.json");st<<"{\"native_api_status\":"<<status<<",\"radius\":"<<fillet_radius<<",\"selected_edges\":"<<out->selected_edges_count<<"}";}
        check(status,stage);
        if(!r) throw std::runtime_error("boolean succeeded but returned null");
        std::unique_ptr<SmBrep> owner(r);
        SmTArray<SmFace*> faces; SmTArray<SmEdge*> edges; SmTArray<SmVertex*> vertices;
        r->GetFaces(faces); r->GetEdges(edges); r->GetVertices(vertices);
        out->faces=faces.GetSize(); out->edges=edges.GetSize(); out->vertices=vertices.GetSize();
        diagnose("material census", [&]{ check(SmApiBrepMaterialCensus(r,out->solids,out->voids),"material census"); });
        out->empty = out->solids==0 && out->voids==0 && out->faces==0 && out->edges==0 && out->vertices==0;
        diagnose("native validity", [&]{out->valid=r->AssertValid(nullptr,SM_LEVEL_2,SM_WALK);});
        diagnose("result tolerances", [&]{tolerances(r,out->result_max_vertex_tol,out->result_max_edge_tol);});
        for(int i=0; i<nprobes; ++i) {
            if(out->empty) { states[i]=0; continue; }
            diagnose(("point " + std::to_string(i)).c_str(), [&]{
                SmPointClassification pc;
                check(r->Point3DClassify(SmPoint3d(probes[3*i],probes[3*i+1],probes[3*i+2]),SmZoneTol3d(point_tol),TRUE,pc),"point classification");
                if(pc.GetPointClass()==SM_PC_REGION) states[i]=static_cast<SmRegion*>(pc.GetObject())->IsVoid()?0:1;
                else if(pc.GetPointClass()==SM_PC_FACE || pc.GetPointClass()==SM_PC_EDGE || pc.GetPointClass()==SM_PC_VERTEX) states[i]=2;
                else throw std::runtime_error("unclassified probe");
            });
        }
        if(out->empty) { out->volume=0; out->area=0; out->manifold=0; }
        else {
            diagnose("manifold", [&]{SmBoolean manifold=FALSE; check(SmApiBrepIsManifoldSolid(r,manifold),"manifold");out->manifold=manifold;});
            diagnose("mass properties", [&]{
                // Public core API allows accuracy tighter than the SM_API area/centroid 1e-4 clamp.
                // This is the same integration entry point called by SmApiBrepComputeVolume.
                if(!r->IsManifoldSolid()) throw std::runtime_error("requires manifold solid");
                double mass=0, area=0, volume=0;
                SmPoint3d origin(0,0,0);
                SmMassPropertyBehavior behavior(1.0);
                SmTArray<SmVector3d> moments; moments.SetSize(8);
                check(r->ComputePreciseProperties(accuracy,origin,behavior,area,volume,mass,moments),"core ComputePreciseProperties");
                out->volume=volume; out->area=area;
                if(mass<=0) throw std::runtime_error("non-positive mass");
                SmPoint3d centroid=origin+(moments[4]/mass);
                for(int i=0;i<3;++i)out->centroid[i]=centroid[i];
            });
            diagnose("bounds", [&]{
                SmPoint3d mn,mx;check(SmApiBrepBoundingBox(r,TRUE,mn,mx),"bounds");
                for(int i=0;i<3;++i){out->bbox[i]=mn[i];out->bbox[i+3]=mx[i];}
            });
        }
        if(export_mesh){
            std::string mesh_result=mesh_json(r,out->empty,mesh_ok);
            write_mesh(mesh_result,mesh_ok?"ok":"error");
        }
        snprintf(error,cap,"%s",errors.c_str()); return 0;
    } catch(const std::exception& e) {write_mesh("{\"positions\":[],\"indices\":[],\"empty\":false,\"status\":\"error\",\"error\":\""+json_escape(e.what())+"\"}","error");snprintf(error,cap,"%s stage=%s: %s",errors.c_str(),stage,e.what()); return 1;}
    catch(...) {snprintf(error,cap,"%sunknown C++ exception",errors.c_str()); return 2;}
}
