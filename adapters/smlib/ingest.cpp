// Explicit OCCT/NURBS exchange ingress. No automatic stitch, heal or thickening.
#include "smlib_common.h"
#include <SmBrepData.h>
#include <SmBSplineSurface.h>
#include <SmShell.h>
#include <SmRegion.h>
#include <SmAssertArray.h>
#include <NL_Geometry.h>
#include <map>

struct VertexData {int id;SmPoint3d p;double tol;};
struct CurveData {int id,a,z,degree;double first,last,tol;std::vector<gw_CPOINT> poles;std::vector<double> knots;};
struct UseData {int id,orient;};
struct LoopData {bool outer;int direction;std::vector<UseData> uses;};
struct FaceData {int id,orient,pu,pv,nu,nv;double u0,u1,v0,v1;std::vector<gw_CPOINT> poles;std::vector<double> ku,kv;std::vector<LoopData> loops;};
struct ShellData {bool isvoid,closed;std::vector<FaceData> faces;};
struct ComponentData {int id,solid;double tol;std::vector<VertexData> vs;std::vector<CurveData> es;std::vector<ShellData> shells;};
static void token(std::istream& in,const char* expected){std::string x;in>>x;if(x!=expected)throw std::runtime_error("token expected "+std::string(expected)+" got "+x);}
static std::vector<ComponentData> parse(const char* path){
 std::ifstream in(path);token(in,"SMX1");int nc;in>>nc;std::vector<ComponentData> out;
 for(int ci=0;ci<nc;++ci){ComponentData c;int nvs,nes,nsh;token(in,"COMP");in>>c.id>>c.solid>>c.tol>>nvs>>nes>>nsh;
  for(int i=0;i<nvs;++i){VertexData v;token(in,"V");in>>v.id>>v.p.x>>v.p.y>>v.p.z>>v.tol;c.vs.push_back(v);}
  for(int i=0;i<nes;++i){CurveData e;int np,nk;token(in,"E");in>>e.id>>e.a>>e.z>>e.first>>e.last>>e.tol>>e.degree>>np>>nk;e.poles.resize(np);e.knots.resize(nk);for(auto& p:e.poles)in>>p.x>>p.y>>p.z>>p.w;for(auto& v:e.knots)in>>v;c.es.push_back(e);}
  for(int j=0;j<nsh;++j){ShellData sh;int isv,cl,nf;token(in,"SH");in>>isv>>cl>>nf;sh.isvoid=isv;sh.closed=cl;
   for(int k=0;k<nf;++k){FaceData f;int nku,nkv,nl;token(in,"F");in>>f.id>>f.orient>>f.pu>>f.pv>>f.nu>>f.nv>>nku>>nkv>>f.u0>>f.u1>>f.v0>>f.v1>>nl;f.poles.resize(f.nu*f.nv);f.ku.resize(nku);f.kv.resize(nkv);for(auto& p:f.poles)in>>p.x>>p.y>>p.z>>p.w;for(auto& v:f.ku)in>>v;for(auto& v:f.kv)in>>v;
    for(int li=0;li<nl;++li){LoopData l;int outer,ne;token(in,"L");in>>outer>>l.direction>>ne;l.outer=outer;for(int ei=0;ei<ne;++ei){UseData u;in>>u.id>>u.orient;l.uses.push_back(u);}f.loops.push_back(l);}sh.faces.push_back(f);
   }c.shells.push_back(sh);
  }if(!in)throw std::runtime_error("truncated token stream");out.push_back(c);
 }return out;
}
static SmBSplineCurve* curve(const CurveData& e,const SmContext* context){return new (*context) SmBSplineCurve(3,e.poles.size()-1,e.knots.size()-1,e.degree,const_cast<gw_CPOINT*>(e.poles.data()),const_cast<double*>(e.knots.data()),context);}
static SmBSplineSurface* surface(const FaceData& f,const SmContext* context){std::vector<gw_CPOINT*> rows;for(int u=0;u<f.nu;++u)rows.push_back(const_cast<gw_CPOINT*>(f.poles.data())+u*f.nv);return new (*context) SmBSplineSurface(f.nu-1,f.nv-1,f.pu,f.pv,f.ku.size()-1,f.kv.size()-1,rows.data(),const_cast<double*>(f.ku.data()),const_cast<double*>(f.kv.data()));}
static void import_component(const ComponentData& c){
 SmBrepConstructor b;auto* context=SmApiGetOrCreateContext();SmBrep* body=b.StartBrep(*context);if(!body)throw std::runtime_error("StartBrep null");body->SetTolerance(SmZoneTol3d(c.tol),FALSE,FALSE);
 std::map<int,SmVertex*> vs;std::map<int,SmEdge*> es;std::map<int,SmFace*> fs;std::map<int,const CurveData*> edata;
 for(auto& v:c.vs){auto* p=b.StartVertex(v.p);if(!p)throw std::runtime_error("StartVertex null");p->SetTolerance(SmZoneTol3d(v.tol),FALSE,FALSE);vs[v.id]=p;check(b.EndVertex(),"EndVertex");}
 for(auto& e:c.es)edata[e.id]=&e;
 SmRegion* material=nullptr;
 for(size_t shi=0;shi<c.shells.size();++shi){auto& sh=c.shells[shi];bool reg=c.solid!=0;if(reg){auto* r=b.StartRegion(TRUE,sh.isvoid?material:body->GetInfiniteRegion());if(!r)throw std::runtime_error("StartRegion null");r->SetIsVoid(sh.isvoid?TRUE:FALSE);if(!sh.isvoid)material=r;}
  SmShell *outer=nullptr,*inner=nullptr;check(b.StartShell(outer,inner),"StartShell");
  for(auto& f:sh.faces){auto* face=b.StartFace(f.orient==1?SM_OT_SAME:SM_OT_OPPOSITE);if(!face)throw std::runtime_error("StartFace null");fs[f.id]=face;check(b.SetFaceSurface(surface(f,context),SmExtent2d(SmPoint2d(f.u0,f.v0),SmPoint2d(f.u1,f.v1))),"SetFaceSurface");
   for(auto& l:f.loops){auto lo=l.direction==1?SM_OT_SAME:SM_OT_OPPOSITE;if(!b.StartLoop(lo))throw std::runtime_error("StartLoop null");
    for(auto& u:l.uses){auto it=edata.find(u.id);if(it==edata.end())throw std::runtime_error("edge ID absent");auto& e=*it->second;auto* existing=es.count(e.id)?es[e.id]:nullptr;SmVertex *a=vs.at(e.a),*z=vs.at(e.z);
     auto* edge=b.StartEdge(u.orient==1?SM_OT_SAME:SM_OT_OPPOSITE,existing,a,z);if(!edge)throw std::runtime_error("StartEdge null");if(!existing){edge->SetTolerance(SmZoneTol3d(e.tol),FALSE,FALSE);check(b.SetEdgeCurve(curve(e,context),FALSE),"SetEdgeCurve");SmVertexNode n0,n1;n0.Set(e.first);n1.Set(e.last);check(b.SetLimits(n0,n1),"SetLimits");es[e.id]=edge;}check(b.EndEdge(),"EndEdge");
    }check(b.EndLoop(),"EndLoop");
   }check(b.EndFace(),"EndFace");
  }check(b.EndShell(FALSE),"EndShell without stitch");if(reg)check(b.EndRegion(),"EndRegion");
 }check(b.EndBrep(),"EndBrep");
 // Derive UV trim curves only; no geometric healing, stitch or orientation rewrite.
 event("create_missing_uv_trim_curves");SmTArray<SmFace*> actualfaces;body->GetFaces(actualfaces);for(long i=0;i<actualfaces.GetSize();++i){double a=0,z=0,c0=0,d0=0,e0=0,f0=0;check(actualfaces[i]->CreateUVTrimCurves(FALSE,nullptr,nullptr,a,z,c0,d0,e0,f0),"CreateUVTrimCurves without tolerance adjustment");}
 std::string prefix="component-"+std::to_string(c.id);event("native_save");check(body->WriteToFile((outdir+"/"+prefix+".smb").c_str(),SM_ASCII,TRUE,FALSE),"WriteToFile");write(prefix+"-stats.json",stats(body));
 SmAssertArray reports;bool av=body->AssertValid(&reports,SM_LEVEL_2,SM_WALK);std::ostringstream failures;failures<<"{\"valid\":"<<(av?"true":"false")<<",\"failed_reports\":[";bool first_report=true;for(long ri=0;ri<reports.GetSize();++ri){auto* report=reports[ri];if(report->m_bOK)continue;if(!first_report)failures<<',';first_report=false;failures<<"{\"name\":\""<<esc(report->m_pName?report->m_pName:"")<<"\",\"message\":\""<<esc(report->m_pMessage?report->m_pMessage:"")<<"\",\"owner_type\":\""<<esc(report->m_sOwnerTypeString?report->m_sOwnerTypeString:"")<<"\",\"test_index\":"<<report->m_lTestIndex<<",\"value\":"<<number(report->m_dValue)<<",\"distance\":"<<number(report->m_dDist3d)<<'}';}failures<<"]}";write(prefix+"-validity-details.json",failures.str());
 SmTArray<SmEdge*> actualedges;body->GetEdges(actualedges);std::ostringstream map;map<<"{\"component_id\":"<<c.id<<",\"edges\":[";bool first=true;for(auto& kv:es){long ix=-1;for(long k=0;k<actualedges.GetSize();++k)if(actualedges[k]==kv.second)ix=k+1;if(!first)map<<',';first=false;map<<"{\"source_id\":"<<kv.first<<",\"native_index\":"<<ix<<'}';}map<<"],\"faces\":[";first=true;for(auto& kv:fs){long ix=-1;for(long k=0;k<actualfaces.GetSize();++k)if(actualfaces[k]==kv.second)ix=k+1;if(!first)map<<',';first=false;map<<"{\"source_id\":"<<kv.first<<",\"native_index\":"<<ix<<'}';}map<<"],\"automatic_heal\":false,\"stitch\":false,\"thickening\":false}";write(prefix+"-topology-map.json",map.str());
 event("native_exact_geometry_samples");std::ostringstream samples;samples<<std::setprecision(17)<<"{\"edges\":[";first=true;
 for(auto& kv:es){if(!first)samples<<',';first=false;auto& ed=*edata.at(kv.first);samples<<"{\"source_id\":"<<kv.first<<",\"samples\":[";for(int j=0;j<=20;++j){double q=j/20.,t=ed.first+(ed.last-ed.first)*q;SmVector3d v[3];check(kv.second->GetCurve()->Evaluate(t,2,TRUE,v,FALSE),"exact imported edge sample");if(j)samples<<',';samples<<"{\"fraction\":"<<q<<",\"parameter\":"<<t<<",\"point\":"<<point(v[0])<<",\"d1\":"<<point(v[1])<<",\"d2\":"<<point(v[2])<<'}';}samples<<"]}";}samples<<"],\"faces\":[";first=true;
 for(auto& sh:c.shells)for(auto& f:sh.faces){if(!first)samples<<',';first=false;samples<<"{\"source_id\":"<<f.id<<",\"samples\":[";bool fp=true;for(int i=0;i<=4;++i)for(int j=0;j<=4;++j){SmPoint2d uv(f.u0+(f.u1-f.u0)*i/4.,f.v0+(f.v1-f.v0)*j/4.);SmVector3d v[9];check(fs.at(f.id)->GetSurface()->Evaluate(uv,2,2,TRUE,TRUE,TRUE,v,FALSE),"exact imported face sample");if(!fp)samples<<',';fp=false;samples<<"{\"uv\":["<<uv.x<<','<<uv.y<<"],\"point\":"<<point(v[0])<<",\"du\":"<<point(v[3])<<",\"dv\":"<<point(v[1])<<'}';}samples<<"]}";}samples<<"]}";write(prefix+"-samples.json",samples.str());
 double volume=0;int volume_status=SM_SUCCESS;if(body->IsManifoldSolid())volume_status=SmApiBrepComputeVolume(body,1e-8,volume);write(prefix+"-volume.json","{\"volume_mm3\":"+number(volume)+",\"status\":"+std::to_string(volume_status)+",\"zero_thickness_sheet\":"+(c.solid?"false":"true")+"}");
 event("native_mesh");detailed_mesh(body,prefix+"-mesh.json");
 event("native_readback");std::unique_ptr<SmBrep> rb(new (*context) SmBrep());check(rb->ReadFromFile(*context,(outdir+"/"+prefix+".smb").c_str(),SM_ASCII,FALSE),"ReadFromFile");write(prefix+"-readback-stats.json",stats(rb.get()));delete body;
}
int main(int argc,char** argv){if(argc!=3){std::cerr<<"usage ingest INPUT.tokens OUTDIR\n";return 2;}outdir=argv[2];try{event("parse_exchange");auto cs=parse(argv[1]);event("initialize");SmTol::SetModelSizeEstimate(.0005);SmApiCreateContext();for(auto& c:cs){event("construct_exact_NURBS_topology");import_component(c);}event("complete");return 0;}catch(const std::exception& e){write("error.json","{\"stage\":\""+esc(stage)+"\",\"error\":\""+esc(e.what())+"\"}");std::cerr<<stage<<": "<<e.what()<<std::endl;return 1;}}
