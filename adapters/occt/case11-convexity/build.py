"""Isolated convex-shoulder reconstruction of Figure 73-29.

Physical Cartesian model; inferred dimensions, no affine geometry transform.
The local reference drawing is deliberately not bundled in run artifacts.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import shutil
from pathlib import Path
import sys
import time

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse, BRepAlgoAPI_Cut
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.BRepFeat import BRepFeat_SplitShape
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakePrism
from OCP.GC import GC_MakeArcOfCircle
from OCP.GeomAbs import GeomAbs_Plane
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.STEPControl import STEPControl_Writer, STEPControl_Reader, STEPControl_AsIs
from OCP.IFSelect import IFSelect_RetDone
from OCP.TopAbs import TopAbs_IN, TopAbs_SOLID, TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Pnt, gp_Vec

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'adapters/occt/original'))
import geometry as g
sys.path.insert(0, str(REPO / 'adapters/occt/special'))
import importlib.util
_spec = importlib.util.spec_from_file_location('special_geometry', REPO/'adapters/occt/special/geometry.py')
sg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sg)


PARAMETERS = dict(width=100., length=100., high_plane_z=0., step_depth=40.,
                  plate_thickness=3., shoulder_x=50., transition_end_y=-60.6,
                  transition_start_y=-45.5, tongue_end_x=33.5,
                  tongue_start_x=-21.5, tongue_y_front=-50., tongue_y_back=-34.,
                  tongue_depth=20.68, existing_transition_radius=10.597306561755333,
                  slot_end_x=33.5, slot_back_y=-50., slot_front_y=-60.6, outer_fold_depth=0.,
                  face_connected_wall=False, exact_tangent_arc=False, split_coplanar_tongue=False,
                  close_tongue_back_wedge=False)


def profile_wire(x, commands):
    wire = BRepBuilderAPI_MakeWire()
    point = lambda p: gp_Pnt(x, *p)
    for c in commands:
        if len(c)==2:
            wire.Add(BRepBuilderAPI_MakeEdge(point(c[0]), point(c[1])).Edge())
        else:
            wire.Add(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(point(c[0]), point(c[1]), point(c[2])).Value()).Edge())
    return wire.Wire()


def prism(x, width, commands):
    f = BRepBuilderAPI_MakeFace(profile_wire(x, commands)).Face()
    return BRepPrimAPI_MakePrism(f, gp_Vec(width,0,0)).Shape()


def union(shapes):
    shape = shapes[0]
    for piece in shapes[1:]:
        op = BRepAlgoAPI_Fuse(shape, piece)
        op.Build()
        if not op.IsDone(): raise RuntimeError('Fuse failed')
        shape=op.Shape()
    unifier=ShapeUpgrade_UnifySameDomain(shape, True, True, True)
    unifier.Build()
    return unifier.Shape()


def build():
    p=PARAMETERS; L=p['length']; H=p['step_depth']; t=p['plate_thickness']
    # A and C share the high plane. The original red shoulder remains x=50,z=0.
    high_left = BRepPrimAPI_MakeBox(gp_Pnt(0,-L,-t), 50,L,t).Shape()
    # A left-open slot reveals the short, thick tongue; its hidden connection
    # to A is inferred. It does not cut or shorten the target shoulder.
    slot = BRepPrimAPI_MakeBox(gp_Pnt(-1,p['slot_front_y'],-t-1),p['slot_end_x']+1,p['slot_back_y']-p['slot_front_y'],t+2).Shape()
    cut = BRepAlgoAPI_Cut(high_left,slot); cut.Build(); high_left=cut.Shape()
    high_front = BRepPrimAPI_MakeBox(gp_Pnt(50,-L,-t),50,L-60.6,t).Shape()
    # Existing narrow transition: low B, steep planar rise, tangent curved band
    # and high C. This is input geometry, not the requested target fillet.
    y_end=-60.6; r=p['existing_transition_radius']; old_y=-50.3; old_z=-.094/ .62*H
    slope=(-H-old_z)/(p['transition_start_y']-old_y)
    theta=math.atan(slope)
    # Descending z has an increasing section toward the front (negative y).
    theta=abs(theta)
    if p['exact_tangent_arc']:
        # Tangency from b to a circle centred at (y_end,-r).
        by,bz=p['transition_start_y']-y_end,-H+r
        theta=math.asin(r/math.hypot(by,bz))-math.atan2(bz,by)
    arc_y=y_end+r*math.sin(theta)
    arc_z=-r*(1-math.cos(theta))
    arc_mid=(y_end+r*math.sin(theta/2),-r*(1-math.cos(theta/2)))
    a=(0.,-H); b=(p['transition_start_y'],-H); q=(arc_y,arc_z); e=(y_end,0.)
    down=lambda v:(v[0],v[1]-t)
    panel=prism(50,50,[(a,b),(b,q),(q,arc_mid,e),(e,down(e)),
              (down(e),down(arc_mid),down(q)),(down(q),down(b)),(down(b),down(a)),(down(a),a)])
    # The material is LEFT and BELOW the shoulder, unlike the old concave root.
    wall_commands=[((0.,0.),a),(a,b),(b,q),(q,arc_mid,e),(e,(0.,0.))]
    if p['face_connected_wall']:
        # Include the whole panel end-cap thickness. A mere curve contact
        # would yield four face uses even when BRepCheck reports valid.
        wall_commands=[((0.,0.),down(a)),(down(a),down(b)),(down(b),down(q)),
                       (down(q),down(arc_mid),down(e)),(down(e),e),(e,(0.,0.))]
    wall=prism(47,3,wall_commands)
    tongue=BRepPrimAPI_MakeBox(gp_Pnt(-21.5,-50.,-p['tongue_depth']),55.,16.,p['tongue_depth']).Shape()
    pieces=[high_left,high_front,panel,wall,tongue]
    if p['close_tongue_back_wedge']:
        # A physical front-facing web behind the tongue, not a raster patch.
        # This inferred hidden wall closes the projected white triangle while
        # keeping the exposed tongue end and the fixed target separated.
        pieces.append(BRepPrimAPI_MakeBox(gp_Pnt(33.5,-34.5,-p['tongue_depth']),13.5,3.5,p['tongue_depth']).Shape())
    if p['outer_fold_depth']>0:
        depth=p['outer_fold_depth']
        front=BRepPrimAPI_MakeBox(gp_Pnt(0,-L,-depth),103,3,depth).Shape()
        right=prism(100,3,[(a,b),(b,q),(q,arc_mid,e),(e,(-L,0.)),
                          ((-L,0.),(-L,-depth)),((-L,-depth),(0.,-depth)),((0.,-depth),a)])
        pieces.extend([front,right])
    solid=union(pieces)
    if p['split_coplanar_tongue']:
        top_faces=[]
        for raw in g.shapes(solid,TopAbs_FACE):
            face=TopoDS.Face_s(raw);surface=BRepAdaptor_Surface(face)
            if surface.GetType()==GeomAbs_Plane and all(abs(BRep_Tool.Pnt_s(TopoDS.Vertex_s(v)).Z())<1e-7 for v in g.shapes(face,TopAbs_VERTEX)):
                top_faces.append(face)
        top=max(top_faces,key=lambda f:g.stats(f)['area_mm2'])
        seam=BRepBuilderAPI_MakeEdge(gp_Pnt(0,-34,0),gp_Pnt(33.5,-34,0)).Edge()
        split=BRepFeat_SplitShape(solid);split.Add(seam,top);split.Build()
        if not split.IsDone():raise RuntimeError('Coplanar source junction partition failed')
        solid=split.Shape()
    solids=g.shapes(solid,TopAbs_SOLID)
    if len(solids)!=1:raise RuntimeError('Expected exactly one solid')
    return solid, dict(arc_radius_mm=r, arc_tangent_yz=list(q), arc_end_yz=list(e),
                       low_plane_z=-H, high_plane_z=0.)


def step(shape, path):
    w=STEPControl_Writer(); transfer=w.Transfer(shape,STEPControl_AsIs)
    write=w.Write(str(path)); result=dict(transfer=str(transfer), write=str(write))
    if transfer==IFSelect_RetDone and write==IFSelect_RetDone:
        reader=STEPControl_Reader(); status=reader.ReadFile(str(path)); result['read']=str(status)
        if status==IFSelect_RetDone:
            reader.TransferRoots(); result['readback']=g.inspect(reader.OneShape())
            volume=g.stats(shape)['volume_mm3']
            result['relative_volume_error']=(abs(volume-result['readback']['stats']['volume_mm3'])/abs(volume)
                                             if abs(volume)>1e-12 else None)
    return result


def occupancy(shape):
    solid=TopoDS.Solid_s(g.shapes(shape,TopAbs_SOLID)[0]); rows=[]
    for y in (-12.,-30.,-48.):
        for dx,dz in [(-.25,-.25),(-.25,.25),(.25,-.25),(.25,.25)]:
            p=[50+dx,y,dz]; c=BRepClass3d_SolidClassifier(solid,gp_Pnt(*p),1e-7)
            rows.append(dict(point_mm=p, station_y_mm=y, dx=dx,dz=dz, material=c.State()==TopAbs_IN,state=str(c.State())))
    return dict(rows=rows, occupied_quadrants_by_station=[sum(r['material'] for r in rows if r['station_y_mm']==y) for y in (-12.,-30.,-48.)],
                classification='convex outer shoulder',material_quadrant='x<50,z<0',
                scope='Actual BREP solid classification at three interior target stations, four points each; independent of view and normals.')


def manifold_audit(shape):
    faces=g.shapes(shape,TopAbs_FACE);edges=g.shapes(shape,TopAbs_EDGE);rows=[]
    for i,edge in enumerate(edges,1):
        owners=[j for j,f in enumerate(faces,1) if any(edge.IsSame(q) for q in g.shapes(f,TopAbs_EDGE))]
        uses=0
        for face in faces:
            it=TopExp_Explorer(face,TopAbs_EDGE)
            while it.More():
                uses+=int(edge.IsSame(it.Current()));it.Next()
        rows.append(dict(edge_index_1based=i,face_owners_1based=owners,face_use_count=uses))
    faults=[r for r in rows if len(r['face_owners_1based'])!=2 or r['face_use_count']!=2]
    return dict(passed=not faults,edge_count=len(edges),all_edges_two_distinct_face_owners=not any(len(r['face_owners_1based'])!=2 for r in rows),
                all_edges_two_loop_uses=not any(r['face_use_count']!=2 for r in rows),faults=faults,rows=rows,
                method='Every unique edge checked for exactly two distinct face owners and exactly two edge occurrences over all face loops.')


def camera():
    # Only viewer projection; these vectors never transform BREP geometry.
    vectors=[[400.,216.],[-209.,424.],[-116.,-18.]]
    dot=lambda a,b:sum(x*y for x,y in zip(a,b))
    xy,xz,yz=dot(vectors[0],vectors[1]),dot(vectors[0],vectors[2]),dot(vectors[1],vectors[2])
    d=[math.sqrt(-xy*xz/yz),-math.sqrt(-xy*yz/xz),math.sqrt(-xz*yz/xy)]
    columns=[]
    for a,z in zip(vectors,d):
        v=a+[z]; norm=math.sqrt(dot(v,v)); columns.append([x/norm for x in v])
    return dict(screen_right=[v[0] for v in columns],screen_up=[v[1] for v in columns],toward_viewer=[v[2] for v in columns],
                model_transformed=False, kind='orthonormal projection inferred from drawing directions')


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--revision',choices=['candidate-v1','candidate-v2','candidate-v3','candidate-v4','candidate-v5','candidate-v6'],default='candidate-v6')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--source-brep',type=Path,help='Replay a registered exact input instead of reconstructing it')
    parser.add_argument('--expected-source-sha256',help='Required hash for exact-input replay')
    args=parser.parse_args()
    if bool(args.source_brep) != bool(args.expected_source_sha256):parser.error('Exact replay requires both --source-brep and --expected-source-sha256')
    if args.source_brep and args.revision!='candidate-v6':parser.error('Exact revision replay is defined only for candidate-v6')
    if args.revision=='candidate-v2':PARAMETERS.update(slot_end_x=47.,slot_back_y=-34.)
    if args.revision=='candidate-v3':PARAMETERS.update(slot_end_x=47.,slot_back_y=-34.,tongue_depth=33.35,outer_fold_depth=58.)
    if args.revision=='candidate-v4':PARAMETERS.update(slot_end_x=47.,slot_back_y=-34.,tongue_depth=33.35,outer_fold_depth=58.,face_connected_wall=True,exact_tangent_arc=True)
    if args.revision=='candidate-v5':PARAMETERS.update(slot_end_x=47.,slot_back_y=-34.,slot_front_y=-55.,tongue_depth=33.35,outer_fold_depth=58.,face_connected_wall=True,exact_tangent_arc=True,transition_start_y=-48.5,split_coplanar_tongue=True)
    if args.revision=='candidate-v6':PARAMETERS.update(slot_end_x=47.,slot_back_y=-34.,slot_front_y=-55.,tongue_depth=33.35,outer_fold_depth=58.,face_connected_wall=True,exact_tangent_arc=True,transition_start_y=-48.5,split_coplanar_tongue=True,close_tongue_back_wedge=True)
    out=(args.output or REPO/'runs/case11-convexity'/args.revision).resolve();out.mkdir(parents=True,exist_ok=True)
    if args.source_brep:
        source=args.source_brep.resolve()
        if source==out/'before.brep':raise ValueError('Exact source must remain outside the output artifacts')
        source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
        if source_hash!=args.expected_source_sha256:raise ValueError('Exact replay source hash mismatch')
        shape=g.read(source)
        transition={'method':'pre-existing geometry read from registered exact BREP; no reconstruction or repair'}
        input_creation={'method':'frozen_exact_revision_input','parametric_reconstruction_executed':False,
                        'source_brep':source.relative_to(REPO).as_posix() if source.is_relative_to(REPO) else 'external-exact-input',
                        'source_sha256':source_hash}
    else:
        shape, transition=build()
        input_creation={'method':'parametric_convex_reconstruction','parametric_reconstruction_executed':True}
    targets,selection=g.select(shape,[dict(samples_mm=[[50,0,0],[50,-60.6,0]],length_mm=60.6,required_support_adjacency_count=2)])
    if len(targets)!=1:raise RuntimeError(json.dumps(selection))
    before=sg.save(shape,out,'before',targets)
    if args.source_brep:
        before['kernel_reserialized_brep_sha256']=before['brep_sha256']
        shutil.copyfile(source,out/'before.brep')
        before['brep_sha256']=source_hash
        before['readback_stats']=sg.stats(g.read(out/'before.brep'))
    before['inspection']=g.inspect(shape);before['step']=step(shape,out/'before.step')
    before['manifold_audit']=manifold_audit(shape)
    if args.revision in ['candidate-v4','candidate-v5','candidate-v6'] and not before['manifold_audit']['passed']:
        raise RuntimeError('Before failed closed manifold edge-use gate')
    material=occupancy(shape)
    if material['occupied_quadrants_by_station']!=[1,1,1]:raise RuntimeError('Candidate is not convex at all stations')
    owners=[]
    for i in selection[0]['candidates'][0]['adjacent_faces_1based']:
        face=TopoDS.Face_s(g.shapes(shape,TopAbs_FACE)[i-1]); surf=BRepAdaptor_Surface(face)
        rec=dict(index_1based=i, surface_type=str(surf.GetType()), orientation=str(face.Orientation()))
        if surf.GetType()==GeomAbs_Plane:
            plane=surf.Plane();n=plane.Axis().Direction()
            if face.Orientation()==TopAbs_REVERSED:n.Reverse()
            rec.update(plane_location_mm=g.xyz(plane.Location()),outward_normal=g.xyz(n))
        owners.append(rec)
    attempts=[]
    for radius in (1.,3.,6.):
        path=out/('r'+str(int(radius)));path.mkdir(exist_ok=True)
        row=dict(radius_mm=radius,api='BRepFilletAPI_MakeFillet.Add(radius, original shoulder); Build()',
                 target_before_sha256=before['brep_sha256'],source_repair_fa_X_verified=False)
        start=time.monotonic();row['stage']='native_build';row['native_done']=False
        try:
            fillet=BRepFilletAPI_MakeFillet(shape);fillet.Add(radius,targets[0]);fillet.Build()
            row['native_done']=fillet.IsDone();row['contours']=fillet.NbContours()
            if fillet.IsDone():
                result=fillet.Shape();row['stage']='native_validation';row['inspection']=g.inspect(result)
                row['manifold_audit']=manifold_audit(result)
                row['artifacts']=sg.save(result,path,'result')
                row['stage']='step_export_readback'
                row['step']=step(result,path/'result.step')
                row['status']='native_candidate' if row['inspection']['passed'] and row['manifold_audit']['passed'] else 'native_invalid'
                row['stage']='complete'
            else:
                row.update(status='native_failed', faulty_contours=fillet.NbFaultyContours(), faulty_vertices=fillet.NbFaultyVertices())
        except Exception as exc:
            row.update(status='exception',error=type(exc).__name__+': '+str(exc))
        row['elapsed_seconds']=time.monotonic()-start
        (path/'attempt.json').write_text(json.dumps(row,indent=2));attempts.append(row)
    report=dict(schema='case11.convexity-candidate.v1', revision=args.revision,
        geometry_status='candidate pending independent shape review',
        shape_acceptance=False, reference_pdf_page=1296, reference_figure='73-29',
        parameters_mm=PARAMETERS, transition=transition, camera=camera(), before=before,input_creation=input_creation,
        target_selection=selection,target_adjacent_faces=owners,material_audit=material,attempts=attempts,
        assumptions=['All dimensions inferred; PDF gives no dimensional calibration.',
          'A and C are high at z=0; B is lower at z=-40. The red shoulder is a convex outer edge.',
          'A left-open slot, 3 mm plate thickness and hidden connection are reconstruction assumptions.',
          'The short tongue shares the high plane and extends downward; it stops before the shoulder.',
          'Existing steep/curved transition is inferred input geometry, separate from the target fillet.'],
        evidence_limits=['Native ordinary constant-radius fillets are not source repair_fa_X equivalence.',
          'Validity, STEP readback and native success do not establish likeness or human acceptance.',
          'Original reference images are local only and absent from generated/public assets.'])
    (out/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(output=str(out),before=before['stats'],material=material['occupied_quadrants_by_station'],
                          attempts=[{k:r.get(k) for k in ['radius_mm','status','native_done']} for r in attempts])))


if __name__=='__main__':main()
