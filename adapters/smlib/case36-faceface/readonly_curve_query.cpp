#include <SmApiGeneral.h>
#include <SmApiQueries.h>
#include <SmBrep.h>
#include <SmContext.h>
#include <SmEdge.h>
#include <SmCurve.h>
#include <fstream>
#include <iomanip>
#include <cmath>
#include <stdexcept>
static void check(long code){if(code!=SM_SUCCESS)throw std::runtime_error("native read/query failed");}
int main(int argc,char**argv){
 if(argc!=3)return 2;
 SmApiCreateContext();auto*ctx=SmApiGetOrCreateContext();auto*b=new(*ctx)SmBrep();
 check(b->ReadFromFile(*ctx,argv[1],SM_ASCII,FALSE));
 SmTArray<SmEdge*>edges;b->GetEdges(edges);std::ofstream f(argv[2]);f<<std::setprecision(17);
 f<<"{\"query_only\":true,\"fillet_called\":false,\"samples_per_end\":8193,\"edges\":[";bool first=true;
 for(long k=0;k<edges.GetSize();k++){
  auto*e=edges[k];double a,b;check(SmApiEdgeParameterRange(e,a,b));double my=0,mz=0;
  for(int j=0;j<=2;j++){SmPoint3d p;check(e->GetCurve()->EvaluatePoint(a+(b-a)*j/2.,p));my=std::max(my,std::abs(p.y));mz=std::max(mz,std::abs(p.z));}
  if(my<1e-6||mz<1e-6)continue;
  if(!first)f<<',';first=false;f<<"{\"edge_id\":"<<k<<",\"points\":[";
  for(int j=0;j<=8192;j++){SmPoint3d p;check(e->GetCurve()->EvaluatePoint(a+(b-a)*j/8192.,p));if(j)f<<',';f<<'['<<p.x<<','<<p.y<<','<<p.z<<']';}
  f<<"]}";
 }
 f<<"]}";return 0;
}
