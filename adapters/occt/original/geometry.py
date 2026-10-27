"""Portable OCP helpers for the frozen, original manual-review series.

Native edges are resolved from physical finite curves. Recorded edge indices are
provenance only. A prepared input is never described as regenerated from base.
"""
from __future__ import annotations
import math
from pathlib import Path
from OCP.BRep import BRep_Tool, BRep_Builder
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_Sewing
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.BOPAlgo import BOPAlgo_ArgumentAnalyzer
from OCP.Bnd import Bnd_Box
from OCP.GeomAPI import GeomAPI_ProjectPointOnCurve
from OCP.GeomAbs import GeomAbs_Line, GeomAbs_Plane
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX, TopAbs_REVERSED
from OCP.TopExp import TopExp
from OCP.TopLoc import TopLoc_Location
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.TopoDS import TopoDS, TopoDS_Shape, TopoDS_Iterator
from OCP.gp import gp_Pnt


def xyz(p): return [p.X(), p.Y(), p.Z()]
def distance(a,b): return math.sqrt(sum((x-y)**2 for x,y in zip(a,b)))
def mapped(shape,kind):
    m=TopTools_IndexedMapOfShape()
    if not shape.IsNull(): TopExp.MapShapes_s(shape,kind,m)
    return m

def shapes(shape,kind):
    m=mapped(shape,kind)
    return [m.FindKey(i) for i in range(1,m.Extent()+1)]

def children(shape):
    if shape.ShapeType()!=TopAbs_COMPOUND: return [shape]
    it=TopoDS_Iterator(shape);out=[]
    while it.More():out.append(it.Value());it.Next()
    return out

def read(path):
    s=TopoDS_Shape()
    if not BRepTools.Read_s(s,str(path),BRep_Builder()) or s.IsNull():raise ValueError('BREP read failed')
    return s

def stats(s):
    if s.IsNull():return {'null':True,'valid':False}
    a,v=GProp_GProps(),GProp_GProps()
    BRepGProp.SurfaceProperties_s(s,a,Eps=1e-8,SkipShared=False)
    BRepGProp.VolumeProperties_s(s,v,Eps=1e-8,OnlyClosed=True,SkipShared=False)
    b=Bnd_Box();b.SetGap(0);BRepBndLib.AddOptimal_s(s,b,False,False)
    return {'null':False,'valid':bool(BRepCheck_Analyzer(s,True).IsValid()),
      'shape_type':str(s.ShapeType()).split('.')[-1],
      'faces':len(shapes(s,TopAbs_FACE)),'edges':len(shapes(s,TopAbs_EDGE)),
      'vertices':len(shapes(s,TopAbs_VERTEX)),'solids':len(shapes(s,TopAbs_SOLID)),
      'shells':len(shapes(s,TopAbs_SHELL)),'area_mm2':a.Mass(),'volume_mm3':v.Mass(),'bbox_mm':list(b.Get())}

def inspect(s):
    st=stats(s)
    if st.get('null'):return {'stats':st,'passed':False}
    check=BOPAlgo_ArgumentAnalyzer();check.SetShape1(s)
    for key in ['ArgumentTypeMode','SelfInterMode','SmallEdgeMode','RebuildFaceMode','ContinuityMode','CurveOnSurfaceMode']:
        setattr(check,key,True)
    check.StopOnFirstFaulty=False;check.Perform()
    faults=[]
    for item in check.GetCheckResult():
        faults.append({'status':str(item.GetCheckStatus()).split('.')[-1],
            'faulty_shape_count':item.GetFaultyShapes1().Size()})
    return {'stats':st,'bop_argument_check':{'modes':['argument_type','self_interference','small_edges','rebuild_face','continuity','curve_on_surface'],
      'has_faulty':check.HasFaulty(),'has_errors':check.HasErrors(),'faults':faults},
      'passed':bool(st['valid'] and st['faces'] and st['area_mm2']>1e-9 and not check.HasFaulty() and not check.HasErrors())}

def edge_record(s,e):
    c=BRepAdaptor_Curve(e);first,last=c.FirstParameter(),c.LastParameter()
    gp=GProp_GProps();BRepGProp.LinearProperties_s(e,gp)
    samples=[xyz(c.Value(first+(last-first)*i/31)) for i in range(32)]
    owners=[i+1 for i,f in enumerate(shapes(s,TopAbs_FACE)) if any(e.IsSame(x) for x in shapes(f,TopAbs_EDGE))]
    return {'start':samples[0],'end':samples[-1],'polyline':samples,'length':gp.Mass(),
      'curve_type':str(c.GetType()).split('.')[-1],'adjacent_faces_1based':owners}

def select(s,targets,allow_trimmed=False):
    selected=[];records=[];edges=shapes(s,TopAbs_EDGE)
    for ti,target in enumerate(targets):
        samples=target.get('samples_mm',target.get('polyline',[]))
        if len(samples)<2:raise ValueError('Target requires finite physical samples')
        tol=float(target.get('tolerance_mm',1e-5));p0,p1=samples[0],samples[-1]
        expected=target.get('length',target.get('length_mm'));candidates=[]
        required=target.get('required_support_adjacency_count',len(target.get('adjacent_faces_1based',[1,2])))
        delta=[b-a for a,b in zip(p0,p1)];den=sum(x*x for x in delta)
        for ei,raw in enumerate(edges,1):
            e=TopoDS.Edge_s(raw)
            if BRep_Tool.Degenerated_s(e):continue
            c=BRepAdaptor_Curve(e);a,b=c.FirstParameter(),c.LastParameter();ends=[xyz(c.Value(a)),xyz(c.Value(b))]
            row=edge_record(s,e)
            if len(row['adjacent_faces_1based'])!=required:continue
            if allow_trimmed:
                if c.GetType()!=GeomAbs_Line or den<=0:continue
                fractions=[sum((x-y)*d for x,y,d in zip(p,p0,delta))/den for p in row['polyline']]
                residual=max(distance(p,[y+t*d for y,d in zip(p0,delta)]) for p,t in zip(row['polyline'],fractions))
                if residual>tol or min(fractions)<-tol or max(fractions)>1+tol:continue
                if row['length']<tol:continue
                supports=target.get('support_planes',[])
                actual=[plane_signature(TopoDS.Face_s(shapes(s,TopAbs_FACE)[i-1])) for i in row['adjacent_faces_1based']]
                if supports and not all(any(same_plane(a,z) for a in actual) for z in supports):continue
                gap=None
            else:
                gap=min(max(distance(ends[0],p0),distance(ends[1],p1)),max(distance(ends[1],p0),distance(ends[0],p1)))
                if gap>tol:continue
                if expected is not None and abs(row['length']-expected)>max(tol,float(expected)*1e-7):continue
                geom=BRep_Tool.Curve_s(e,a,b);res=[]
                for p in samples:
                    projection=GeomAPI_ProjectPointOnCurve(gp_Pnt(*p),geom,a,b)
                    res.append(min([distance(p,ends[0]),distance(p,ends[1])]+([projection.LowerDistance()] if projection.NbPoints() else [])))
                residual=max(res)
                if residual>tol:continue
            candidates.append((e,{'native_edge_index_1based_diagnostic':ei,'endpoint_gap_mm':gap,'max_sample_residual_mm':residual,**row}))
        record={'target_index':ti,'target':target,'candidate_count':len(candidates),'candidates':[r for _,r in candidates],
           'method':'unique remaining line on both original support planes within original finite root' if allow_trimmed else 'unique finite native curve by world endpoints, all projected samples, length and adjacency',
           'external_edge_indices_used':False}
        records.append(record)
        if len(candidates)!=1:return [],records
        if any(candidates[0][0].IsSame(e) for e in selected):raise ValueError('Duplicate physical edge target')
        selected.append(candidates[0][0])
    return selected,records

def plane_signature(face):
    a=BRepAdaptor_Surface(face)
    if a.GetType()!=GeomAbs_Plane:return None
    p=a.Plane();n=xyz(p.Axis().Direction());q=xyz(p.Location())
    for x in n:
        if abs(x)>1e-10:
            if x<0:n=[-v for v in n]
            break
    return n+[sum(x*y for x,y in zip(n,q))]

def same_plane(a,b):return bool(a and b and all(abs(x-y)<1e-6 for x,y in zip(a,b)))

def sew(parts,tolerance=1e-6):
    builder=BRepBuilderAPI_Sewing(tolerance)
    for part in parts:
        for face in shapes(part,TopAbs_FACE):builder.Add(face)
    builder.Perform();s=builder.SewedShape()
    if len(shapes(s,TopAbs_SHELL))!=1:raise ValueError('Recipe did not produce one shell')
    return shapes(s,TopAbs_SHELL)[0]

def polygon_face(points):
    p=BRepBuilderAPI_MakePolygon()
    for pt in points:p.Add(gp_Pnt(*pt))
    p.Close();return BRepBuilderAPI_MakeFace(p.Wire()).Face()

def preprocess(base,request):
    recipe=request.get('preprocess',{});kind=recipe.get('type','none')
    parts=children(base);labels=request.get('source_labels',[])
    if labels and len(labels)!=len(parts):raise ValueError('Source label / compound child count mismatch')
    mapping=dict(zip(labels,parts))
    if kind=='none':
        label=request.get('part_label');return mapping[label] if label in mapping else base
    if kind=='shell':return shapes(base,TopAbs_SHELL)[0]
    if kind=='sew_parts':return sew([mapping[x] for x in recipe['source_labels']])
    n=request['case_number'];group=recipe.get('operation_group')
    if kind=='portable_prepare_d':
        chosen=[mapping[x] for x in recipe['source_labels']]
        if group.startswith('walls-'):return sew(chosen)
        if n==27 and group=='boss-floor-skin':
            from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
            boss,floor=chosen
            keep=[f for f in shapes(boss,TopAbs_FACE) if not all(abs(BRep_Tool.Pnt_s(TopoDS.Vertex_s(v)).Z())<1e-7 for v in shapes(f,TopAbs_VERTEX))]
            cut=BRepAlgoAPI_Cut(floor,boss);cut.Build()
            if not cut.IsDone():raise ValueError('Floor footprint cut failed')
            return sew(keep+shapes(cut.Shape(),TopAbs_FACE))
        if n==28:
            from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
            from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
            boxes=[BRepPrimAPI_MakeBox(gp_Pnt(-15,-1,0),30,2,14).Shape(),BRepPrimAPI_MakeBox(gp_Pnt(-15,0,-1),30,14,2).Shape()]
            clips=[]
            for part,box in zip(chosen,boxes):
                op=BRepAlgoAPI_Common(part,box);op.Build()
                if not op.IsDone():raise ValueError('Quadrant clipping failed')
                clips.append(op.Shape())
            return sew(clips)
        if n==36:return sew([polygon_face([(-7,0,0),(7,0,0),(7,0,25),(-7,0,25)]),polygon_face([(-7,0,0),(7,0,0),(7,23,0),(-7,23,0)])])
    raise ValueError('Portable recipe is not implemented: '+str(recipe))

def equivalent(a,b):
    sa,sb=stats(a),stats(b)
    tests={k:sa[k]==sb[k] for k in ['faces','edges','solids','shells','vertices']}
    tests.update({k:abs(sa[k]-sb[k])<=max(1e-5,abs(sb[k])*1e-7) for k in ['area_mm2','volume_mm3']})
    tests['bbox_mm']=all(abs(x-y)<=1e-5 for x,y in zip(sa['bbox_mm'],sb['bbox_mm']))
    def lengths(s):return sorted(edge_record(s,TopoDS.Edge_s(e))['length'] for e in shapes(s,TopAbs_EDGE))
    aa,bb=lengths(a),lengths(b);tests['all_edge_lengths']=len(aa)==len(bb) and all(abs(x-y)<=max(1e-5,abs(y)*1e-7) for x,y in zip(aa,bb))
    return {'checks':tests,'passed':all(tests.values()),'method':'Native topology counts, area, volume, optimal bbox and all edge lengths; finite target geometry verified separately'}

def mesh(s,selected=()):
    result={'schema_version':1,'vertices':[],'triangles':[],'face_ids':[],'edges':[],'selected_edges':[],
      'status':'ok','errors':[],'metadata':{'source':'fresh OCCT BRep triangulation','units':'mm','linear_deflection_mm':0.08,'angular_deflection_radians':0.17,'indices':'zero_based','orientation_corrected':True}}
    mesher=BRepMesh_IncrementalMesh(s,0.08,False,0.17,False)
    result['metadata']['native_done']=mesher.IsDone();result['metadata']['native_status_flags']=int(mesher.GetStatusFlags())
    for fi,raw in enumerate(shapes(s,TopAbs_FACE)):
        f=TopoDS.Face_s(raw);loc=TopLoc_Location();tri=BRep_Tool.Triangulation_s(f,loc)
        if tri is None or tri.NbTriangles()==0:result['errors'].append('Missing face '+str(fi));continue
        offset=len(result['vertices']);transform=loc.Transformation()
        result['vertices'].extend(xyz(tri.Node(i).Transformed(transform)) for i in range(1,tri.NbNodes()+1))
        for i in range(1,tri.NbTriangles()+1):
            a,b,c=tri.Triangle(i).Get()
            if f.Orientation()==TopAbs_REVERSED:b,c=c,b
            result['triangles'].append([offset+a-1,offset+b-1,offset+c-1]);result['face_ids'].append(fi)
    def poly(e):
        c=BRepAdaptor_Curve(e);n=2 if c.GetType()==GeomAbs_Line else 97;a,b=c.FirstParameter(),c.LastParameter()
        return [xyz(c.Value(a+(b-a)*i/(n-1))) for i in range(n)]
    result['edges']=[poly(TopoDS.Edge_s(e)) for e in shapes(s,TopAbs_EDGE) if not BRep_Tool.Degenerated_s(TopoDS.Edge_s(e))]
    result['selected_edges']=[poly(e) for e in selected]
    if result['errors'] or not mesher.IsDone():result['status']='error'
    return result
