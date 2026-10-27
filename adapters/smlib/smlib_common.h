// Snapshot of tested native query/mesh helpers; not an importer or geometry repair.
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
 SmPoint3d mn,mx;check(SmApiBrepBoundingBox(b,TRUE,mn,mx),"bounds");double area=0;
 // Integrate actual trimmed faces directly: the wrapper clamps relative tolerance.
 for(long i=0;i<fs.GetSize();++i){SmExtent3d box;check(fs[i]->CalculateTightBoundingBox(box),"face bounds");auto a=box.GetMin(),z=box.GetMax();double estimate=2*((z.x-a.x)*(z.y-a.y)+(z.x-a.x)*(z.z-a.z)+(z.y-a.y)*(z.z-a.z));double fa=0,fv=0;SmTArray<SmVector3d> moments;check(fs[i]->ComputePreciseProperties(SM_OT_SAME,1e-9,box.GetMid(),std::max(estimate,1e-12),0.,fa,fv,moments),"trimmed face precise area");area+=std::abs(fa);}
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
