#!/usr/bin/env python3
"""Re-execute recorded case17-19 compositions on byte-identical source BREPs.

These are explicit compositions. They do not expose OCCT native automatic
cap_data or limit_topols, and are never ordinary-fillet feature certificates.
"""
from __future__ import annotations
import argparse, hashlib, json, math, sys, traceback
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'special'))
from geometry import read,children,compound,face,save,stats,shapes,edge_polyline,xyz
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common,BRepAlgoAPI_Cut,BRepAlgoAPI_Fuse,BRepAlgoAPI_Section
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox,BRepPrimAPI_MakePrism
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Plane,GeomAbs_Cylinder
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopAbs import TopAbs_COMPOUND,TopAbs_EDGE,TopAbs_FACE,TopAbs_VERTEX,TopAbs_SOLID
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Pnt,gp_Vec

PIN='7.9.3.1.1'
SOURCES={17:'49193e6a715814a24a5b6388eee77ff734a4f9502f9cc1e28a4626bc00e149f2',18:'6c5821a4f88f6e16a5cbfdf943524b3fdbce38ba959798fd8f4e848e8f87910d',19:'1efd818fdfa4c07d56e8c8b742cfc0249535e5a358bd700b0ff4c5ee527ab9f2'}
ORIGINAL_NAMES={17:'case17-capping/code/case17_capping.py',18:'case18-capping/code/case18_capping.py',19:'case19-trim/code/case19_trim.py'}
ORIGINAL_HASHES={17: '1ae78bd458062966327859c18f0ac8f96029a000c8f5d6e923ae820cb236d0e7', 18: '43201fa09b818fb8a792286ae9ef11b5f543c07f69f8380933beebd29ecdee4c', 19: '78f6ceaa5a4a236310fa1643a1184a2ead11e6b075e69e2bd8e5084a5d5813ee'}

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,d):Path(p).write_text(json.dumps(d,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
def unify(s):
 u=ShapeUpgrade_UnifySameDomain(s,True,True,False);u.Build();return u.Shape()
def boolean(cls,a,b):
 op=cls(a,b);op.Build()
 if not op.IsDone():raise ValueError(cls.__name__+' failed')
 return unify(op.Shape())
def common(a,b):return boolean(BRepAlgoAPI_Common,a,b)
def cut(a,b):return boolean(BRepAlgoAPI_Cut,a,b)
def fuse(a,b):return boolean(BRepAlgoAPI_Fuse,a,b)
def box(x,y,z,dx,dy,dz):return BRepPrimAPI_MakeBox(gp_Pnt(x,y,z),dx,dy,dz).Shape()
def extrude(s,v):return BRepPrimAPI_MakePrism(s,gp_Vec(*v)).Shape()
def edges(s):return [TopoDS.Edge_s(e) for e in shapes(s,TopAbs_EDGE)]
def faces(s):return [TopoDS.Face_s(f) for f in shapes(s,TopAbs_FACE)]
def bbox(s):return stats(s)['bbox_mm']
def mass(s,dim):
 g=GProp_GProps();getattr(BRepGProp,dim+'Properties_s')(s,g);return g.Mass(),xyz(g.CentreOfMass())
def volume(s):return mass(s,'Volume')[0]
def length(e):return mass(e,'Linear')[0]
def center(e):return mass(e,'Linear')[1]
def near(a,b,t=1e-6):return abs(a-b)<t
def one(items):
 if len(items)!=1:raise ValueError('Expected exactly one selected entity, got '+str(len(items)))
 return items[0]
def root(s,n,y,z):return one([e for e in edges(s) if near(length(e),n) and near(center(e)[1],y) and near(center(e)[2],z)])
def native(s,e,r):
 op=BRepFilletAPI_MakeFillet(s);op.Add(r,e);op.Build()
 if not op.IsDone():raise ValueError('BRepFilletAPI_MakeFillet rejected recorded radius')
 q=op.Shape();assert stats(q)['valid'];return q

def cap_audit(result,aux,kind,r):
    cylinders=[f for f in faces(result) if BRepAdaptor_Surface(f).GetType()==GeomAbs_Cylinder]
    caps=[]
    for f in faces(result):
        fs=BRepAdaptor_Surface(f)
        if fs.GetType()!=GeomAbs_Plane:continue
        p=fs.Plane();matches=[]
        for a in faces(aux):
            aps=BRepAdaptor_Surface(a)
            if aps.GetType()!=GeomAbs_Plane:continue
            q=aps.Plane()
            if abs(abs(p.Axis().Direction().Dot(q.Axis().Direction()))-1)<1e-7 and p.Distance(q.Location())<1e-7:matches.append(a)
        if not matches:continue
        shared=any(any(e.IsSame(ce) for ce in edges(c)) for c in cylinders for e in edges(f))
        if not shared:continue
        area=mass(f,'Surface')[0];overlap=sum(mass(common(f,a),'Surface')[0] for a in matches)
        caps.append({'area_mm2':area,'area_on_supplied_finite_cap_mm2':overlap,'bbox_mm':bbox(f)})
    return {'cap_faces':caps,'cap_boundary_present':bool(caps),'cap_within_supplied_finite_geometry':bool(caps) and all(abs(c['area_mm2']-c['area_on_supplied_finite_cap_mm2'])<1e-6 for c in caps),'sheet_fold_crossed_when_required':kind!='sheet' or r!=8 or len(caps)>=2}


def main():
 p=argparse.ArgumentParser();p.add_argument('--case',choices=['17','18','19','all'],default='all');p.add_argument('--output',type=Path,default=REPO/'runs/original-occ-compositions');p.add_argument('--historical-root',type=Path,help='Optional diagnostics root for independent historical BREP comparison');a=p.parse_args()
 if version('cadquery-ocp')!=PIN:raise ValueError('Pinned cadquery-ocp '+PIN+' required')
 for number in ([17,18,19] if a.case=='all' else [int(a.case)]):run_case(number,a.output,a.historical_root)

def run_case(number,outbase,historical):
 manifest_path=REPO/f'data/original-occ/cases/{number:02d}.json';manifest=json.loads(manifest_path.read_text());sourcefile=REPO/manifest['source_brep'];source=read(sourcefile);assert sha(sourcefile)==manifest['source_sha256']==SOURCES[number]
 original=children(source)[0] if source.ShapeType()==TopAbs_COMPOUND else source
 out=outbase/f'case{number:02d}';out.mkdir(parents=True,exist_ok=True)
 report=dict(schema_version=1,case_number=number,engine='OCCT',engine_version='7.9.3',binding_version=version('cadquery-ocp'),started_at=datetime.now(timezone.utc).isoformat(),source_brep=manifest['source_brep'],manifest=f'data/original-occ/cases/{number:02d}.json',manifest_sha256=sha(manifest_path),source_sha256=sha(sourcefile),source_sha256_verified=True,adapter='adapters/occt/original-compositions/case17_19.py',adapter_sha256=sha(__file__),geometry_helpers_sha256=sha(Path(__file__).resolve().parents[1]/'special/geometry.py'),original_recipe=ORIGINAL_NAMES[number],original_script_sha256=ORIGINAL_HASHES.get(number),original_runtime={'FreeCAD':'1.2.0-46770','OCCT':'7.8.1'},runtime_difference='Fresh port uses OCCT7.9.3/OCP; this is not a rerun in the original FreeCAD7.8.1 runtime.',method_kind='explicit_occ_composition',native_special_feature_api_used=False,source_feature_certified=False,parameter_values_from_pdf=False,trials=[])
 if historical:
  op=historical/ORIGINAL_NAMES[number]
  if op.is_file():report['original_script_sha256']=sha(op)
 write(out/'summary.json',report)
 def trial(tid,before,r,steps,build,selected=(),parameters=None,history=None,verify=None):
  d=out/tid;d.mkdir(exist_ok=True)
  variant=one([v for v in manifest['variants'] if v['id']==tid]);assert near(float(variant['radius_mm']),r)
  row=dict(schema_version=1,job_id=f'{number:02d}.original.{tid}',case_number=number,protocol_id=f'original-occ-composition-{number:02d}-{tid}-v1',method_kind='explicit_occ_composition',fresh_execution=True,source_sha256=sha(sourcefile),source_brep=report['source_brep'],adapter_sha256=report['adapter_sha256'],original_script_sha256=report['original_script_sha256'],engine='OCCT',engine_version='7.9.3',binding_version=report['binding_version'],radius_mm=r,parameters=parameters or {},processing_steps=steps,native_special_feature_api_used=False,source_feature_certified=False,selection=[{'samples_mm':edge_polyline(e,9),'recorded_predicate':'same world coordinates, edge length and support geometry as original recipe'} for e in selected],outcome='started',artifacts={'source_brep':'source.brep','source_mesh':'source.mesh.json','before_brep':'before.brep','before_mesh':'before.mesh.json'})
  row['method_kind']=variant['method']
  row['original_variant_id']=tid;row['original_variant_parameters']=variant['parameters'];row['original_script_provenance_status']=variant['script_provenance']['status']
  row['source']=save(source,d,'source');row['before']=save(before,d,'before',selected);row['input_stats']=row['before']['stats'];write(d/'summary.json',row)
  try:
   result,extra=build();row.update(extra);row['construction_executed']=True;row['native_call_executed']=True
   row['result']=save(result,d,'result');row['result_stats']=row['result']['stats'];row['valid']=row['result_stats']['valid'];row['artifacts'].update(result_brep='result.brep',result_mesh='result.mesh.json')
   removal=volume(cut(before,result));cyls=[f for f in faces(result) if BRepAdaptor_Surface(f).GetType()==GeomAbs_Cylinder]
   row['verify']={'brep_readback_valid':row['result']['readback_stats']['valid'],'single_solid':row['result_stats']['solids']==1,'input_removed_volume_mm3':removal,'input_preserved':abs(removal)<1e-6,'cylinder_radii_mm':[BRepAdaptor_Surface(f).Cylinder().Radius() for f in cyls],'requested_cylinder_present':len(cyls)==1 and near(BRepAdaptor_Surface(cyls[0]).Cylinder().Radius(),r),'mesh_ok':row['result']['mesh']['status']=='ok'}
   if verify:row['verify'].update(verify(result))
   references=variant.get('historical_results',[])
   if references:
    reference=references[0];old=historical/history if historical and history else REPO/reference['brep']
    if old.is_file():
     assert sha(old)==reference['sha256']
     h=read(old);ab=volume(cut(result,h));ba=volume(cut(h,result));row['historical_geometry_comparison']={'method':'symmetric Boolean difference against recorded original result BREP, independent of reconstruction','reference_brep':reference['brep'],'reference_sha256':sha(old),'fresh_minus_historical_mm3':ab,'historical_minus_fresh_mm3':ba,'volume_difference_mm3':stats(result)['volume_mm3']-stats(h)['volume_mm3'],'within_1e-5_mm3':max(abs(ab),abs(ba))<1e-5}
   row['outcome']='ok' if row['valid'] and all(v for k,v in row['verify'].items() if isinstance(v,bool)) else 'verification_failed'
  except Exception as e:row.update(outcome='exception',reason=type(e).__name__+': '+str(e),traceback=traceback.format_exc().replace(str(REPO),'<repo>'))
  write(d/'summary.json',row);report['trials'].append(row);write(out/'summary.json',report)
 if number==17:
  e=root(original,70,29,12);left=common(original,box(-1,-1,-1,30,40,43));right=common(original,box(29,-1,-1,42,40,43));le=root(left,29,29,12)
  cap=one([f for f in faces(original) if BRepAdaptor_Surface(f).GetType()==GeomAbs_Plane and near(bbox(f)[0],29) and near(bbox(f)[3],29) and bbox(f)[2]>12])
  for r in (8.,4.):
   def build(r=r):return fuse(native(left,le,r),right),{'partition_reassembly_symmetric_difference_mm3':[volume(cut(fuse(left,right),original)),volume(cut(original,fuse(left,right)))]}
   expected=29*r*r*(1-math.pi/4)
   trial(f'cap-r{r:g}',original,r,['Read unchanged original source and select its x=29 slot cap face','Partition unchanged body at existing cap support plane x=29','Native fillet only the 29mm left root segment','Fuse untouched right body and unify same-domain faces'],build,[e],{'cap_plane_x_mm':29,'fillet_interval_x_mm':[0,29],'sharp_interval_x_mm':[29,70]},f'case17-capping/runs/20261018T225625.665771-12265/cap-r{r:g}.brep',lambda result,expected=expected:{'analytic_added_volume_mm3':expected,'analytic_volume_error_mm3':abs(stats(result)['volume_mm3']-stats(original)['volume_mm3']-expected),'analytic_volume_passed':abs(stats(result)['volume_mm3']-stats(original)['volume_mm3']-expected)<1e-5})
 elif number==18:
  body1,plane,body2,sheet=children(source);plane_keeper=extrude(faces(plane)[0],(-100,0,0));b=bbox(sheet);profile=sorted({tuple(round(c,9) for c in xyz(BRep_Tool.Pnt_s(TopoDS.Vertex_s(v)))[:2]) for v in shapes(sheet,TopAbs_VERTEX) if near(BRep_Tool.Pnt_s(TopoDS.Vertex_s(v)).Z(),b[2])},key=lambda q:q[1]);assert len(profile)==6
  sheet_keeper=extrude(face([(97,profile[0][1],b[2])]+[(x,y,b[2]) for x,y in profile]+[(97,profile[-1][1],b[2])]),(0,0,b[5]-b[2]))
  for kind,body,aux,keeper,dx in [('plane',body1,plane,plane_keeper,0),('sheet',body2,sheet,sheet_keeper,98)]:
   e=root(body,70,29,12);left=common(body,box(dx-1,-1,-1,30,40,43));le=root(left,29,29,12)
   for r in (8.,4.):
    def build(r=r,body=body,left=left,le=le,keeper=keeper):
     rounded=native(left,le,r);added=cut(rounded,left);clipped=common(added,keeper);return fuse(body,clipped),{'untrimmed_added_volume_mm3':stats(added)['volume_mm3'],'clipped_addition_volume_mm3':stats(clipped)['volume_mm3']}
    trial(f'{kind}-r{r:g}',body,r,['Read unchanged original four-piece source; retain independent cap geometry','Extract left support with original x=29 split','Native fillet left root at recorded R','Subtract support to isolate added material','Intersect addition with exact supplied plane/sheet retaining region','Fuse clipped addition into unchanged body'],build,[e],{'kind':kind,'offset_x_mm':dx,'sheet_profile_world_xy_mm':profile if kind=='sheet' else None,'cap_input_part':2 if kind=='plane' else 4},f'case18-capping/runs/20261019T125124.653104-17057/{kind}-r{r:g}.brep',lambda result,aux=aux,kind=kind,r=r:cap_audit(result,aux,kind,r))
 elif number==19:
  e=root(original,62,32,20);fin=one([e for e in edges(original) if near(bbox(e)[0],29) and near(bbox(e)[3],29) and near(bbox(e)[2],20) and near(bbox(e)[5],20) and near(length(e),25)])
  limit=one([f for f in faces(original) if BRepAdaptor_Surface(f).GetType()==GeomAbs_Plane and near(bbox(f)[0],29) and near(bbox(f)[3],29) and near(bbox(f)[4],25) and near(bbox(f)[5],20)])
  support=fuse(box(0,0,0,62,42,20),box(0,32,20,62,10,25));missing=cut(support,original);mouths=[f for f in faces(missing) if BRepAdaptor_Surface(f).GetType()==GeomAbs_Plane and near(bbox(f)[2],20) and near(bbox(f)[5],20)];assert len(mouths)==3
  extensions=[extrude(f,(0,0,11)) for f in mouths];filleted=native(support,root(support,62,32,20),10.);boundary=one([e for e in edges(filleted) if near(length(e),62) and near(bbox(e)[2],20) and near(bbox(e)[5],20) and near(center(e)[1],22)])
  control=native(support,root(support,62,32,20),5.)
  control_boundary=one([e for e in edges(control) if near(length(e),62) and near(bbox(e)[2],20) and near(bbox(e)[5],20) and near(center(e)[1],27)])
  control_rows=[]
  for kind,entity in [('edge',fin),('face',limit)]:
   section=BRepAlgoAPI_Section(control_boundary,entity,False);section.Build();distance=BRepExtrema_DistShapeShape(control_boundary,entity);distance.Perform();count=len(shapes(section.Shape(),TopAbs_VERTEX));assert count==0 and near(distance.Value(),2)
   control_rows.append({'entity_kind':kind,'intersection_vertex_count':count,'finite_entity_distance_mm':distance.Value(),'trim_triggered':False})
  trial('r5-control',original,5.,['Read unchanged source and original selected root','Native original-body R5 fillet, without constructing a limit trim','Verify R5 boundary on declared support does not intersect either finite limit entity'],lambda:(native(original,e,5.),{}),[e],{'control':'no finite-entity intersection; no trim'},'case19-trim/runs/20261019T223401.873037-21129/ordinary-r5.brep')
  report['r5_limit_control']={'radius_mm':5,'boundary_y_mm':27,'finite_entity_y_max_mm':25,'actual_intersections':control_rows,'trim_refused':True}
  added=cut(filleted,support)
  for cutter in extensions:added=cut(added,cutter)
  intersections={}
  for kind,entity in [('edge',fin),('face',limit)]:
   sec=BRepAlgoAPI_Section(boundary,entity,False);sec.Build();pts=[xyz(BRep_Tool.Pnt_s(TopoDS.Vertex_s(v))) for v in shapes(sec.Shape(),TopAbs_VERTEX)];point=one(pts);assert all(near(x,y) for x,y in zip(point,[29,22,20]));intersections[kind]=point
  for tid,kind,side in [('edge-left','edge','left'),('face-left','face','left'),('direction-right','edge','right')]:
   x=intersections[kind][0];keeper=box(-1,-1,-1,x+1,50,50) if side=='left' else box(x,-1,-1,63-x,50,50)
   def build(keeper=keeper):return fuse(original,common(added,keeper)),{}
   trial(tid,original,10.,['Read unchanged source and select recorded root, finite x29 fin and finite slot face','Construct declared same-support unslotted operation support','Recover actual missing slot mouths and extend upward by 11mm','Native R10 support fillet; isolate addition and remove slot-mouth extensions','Compute real boundary/finite-entity intersection at [29,22,20]','Intersect added material with x29 retained region and fuse into unchanged source'],build,[e],{'entity_kind':kind,'retained_side':side,'intersection_point_mm':intersections[kind],'opening_extension_height_mm':11,'direction_right_is_counterexample':side=='right'},f'case19-trim/runs/20261019T223401.873037-21129/{tid}.brep')
 report['finished_at']=datetime.now(timezone.utc).isoformat();report['input_unchanged']=sha(sourcefile)==SOURCES[number];report['outcome']='ok' if report['trials'] and all(q['outcome']=='ok' for q in report['trials']) else 'partial_or_failed';write(out/'summary.json',report);print(f'case{number}: '+report['outcome']+' '+str(len(report['trials']))+' variants',flush=True)

if __name__=='__main__':main()
