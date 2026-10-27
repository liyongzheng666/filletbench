"""Portable derivative geometry and readback checks; explicit construction only."""
import json
import hashlib
import math
from pathlib import Path
from OCP.BRep import BRep_Tool, BRep_Builder
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepLProp import BRepLProp_SLProps
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace, BRepBuilderAPI_Sewing
from OCP.Bnd import Bnd_Box
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_SOLID, TopAbs_SHELL, TopAbs_VERTEX, TopAbs_REVERSED
from OCP.TopExp import TopExp
from OCP.TopLoc import TopLoc_Location
from OCP.TopTools import TopTools_IndexedMapOfShape, TopTools_FormatVersion
from OCP.TopoDS import TopoDS, TopoDS_Shape, TopoDS_Iterator, TopoDS_Compound
from OCP.gp import gp_Pnt, gp_Vec
from OCP.GeomAbs import GeomAbs_Plane


def xyz(p):
    return [p.X(), p.Y(), p.Z()]


def shapes(shape, kind):
    m = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, m)
    return [m.FindKey(i) for i in range(1, m.Extent()+1)]


def children(shape):
    result, it = [], TopoDS_Iterator(shape)
    while it.More():
        result.append(it.Value())
        it.Next()
    return result


def compound(items):
    b, c = BRep_Builder(), TopoDS_Compound()
    b.MakeCompound(c)
    for item in items:
        b.Add(c, item)
    return c


def read(path):
    s = TopoDS_Shape()
    if not BRepTools.Read_s(s, str(path), BRep_Builder()):
        raise ValueError("BREP read failed")
    return s


def face(points):
    polygon = BRepBuilderAPI_MakePolygon()
    for p in points:
        polygon.Add(gp_Pnt(*p))
    polygon.Close()
    return BRepBuilderAPI_MakeFace(polygon.Wire()).Face()


def sew(faces):
    builder = BRepBuilderAPI_Sewing(1e-7)
    for f in faces:
        builder.Add(f)
    builder.Perform()
    return builder.SewedShape()


def stats(s):
    a, v, b = GProp_GProps(), GProp_GProps(), Bnd_Box()
    BRepGProp.SurfaceProperties_s(s, a)
    BRepGProp.VolumeProperties_s(s, v, OnlyClosed=True)
    BRepBndLib.AddOptimal_s(s, b, False, False)
    return dict(valid=BRepCheck_Analyzer(s, True).IsValid(),
        solids=len(shapes(s, TopAbs_SOLID)), shells=len(shapes(s, TopAbs_SHELL)),
        faces=len(shapes(s, TopAbs_FACE)), edges=len(shapes(s, TopAbs_EDGE)),
        area_mm2=a.Mass(), volume_mm3=v.Mass(), bbox_mm=list(b.Get()))


def edge_polyline(e, n=65):
    c = BRepAdaptor_Curve(TopoDS.Edge_s(e))
    a, b = c.FirstParameter(), c.LastParameter()
    return [xyz(c.Value(a+(b-a)*i/(n-1))) for i in range(n)]


def shared_edges(s, predicate=lambda points: True):
    result = []
    fs = shapes(s, TopAbs_FACE)
    for raw in shapes(s, TopAbs_EDGE):
        e = TopoDS.Edge_s(raw)
        owners = [f for f in fs if any(e.IsSame(t) for t in shapes(f, TopAbs_EDGE))]
        if len(owners) == 2 and predicate(edge_polyline(e, 9)):
            result.append(e)
    return result


def mesh(s, path, selected=()):
    m = dict(schema_version=1, vertices=[], triangles=[], face_ids=[], edges=[],
             selected_edges=[], status="ok", errors=[], metadata=dict(units="mm", source="OCCT native triangulation", linear_deflection_mm=.04))
    mesher = BRepMesh_IncrementalMesh(s, .04, False, .15, False)
    if not mesher.IsDone():
        m["errors"].append("Native mesher incomplete")
    for fi, raw in enumerate(shapes(s, TopAbs_FACE)):
        f, loc = TopoDS.Face_s(raw), TopLoc_Location()
        t = BRep_Tool.Triangulation_s(f, loc)
        if t is None or not t.NbTriangles():
            m["errors"].append(f"No triangles for face {fi}")
            continue
        offset = len(m["vertices"])
        m["vertices"].extend(xyz(t.Node(i).Transformed(loc.Transformation())) for i in range(1, t.NbNodes()+1))
        for i in range(1, t.NbTriangles()+1):
            a,b,c = t.Triangle(i).Get()
            if f.Orientation() == TopAbs_REVERSED:
                b,c = c,b
            m["triangles"].append([offset+a-1, offset+b-1, offset+c-1])
            m["face_ids"].append(fi)
    m["edges"] = [edge_polyline(e) for e in shapes(s, TopAbs_EDGE) if not BRep_Tool.Degenerated_s(TopoDS.Edge_s(e))]
    m["selected_edges"] = [edge_polyline(e) for e in selected]
    if m["errors"]:
        m["status"] = "error"
    Path(path).write_text(json.dumps(m, allow_nan=False))
    return {"status": m["status"], "triangles": len(m["triangles"]), "errors": m["errors"]}


def save(s, directory, name, selected=()):
    path = directory / (name+".brep")
    if not BRepTools.Write_s(s, str(path), False, False, TopTools_FormatVersion.TopTools_FormatVersion_VERSION_3):
        raise ValueError("BREP write failed")
    r = read(path)
    return {"stats": stats(s), "readback_stats": stats(r),
            "brep_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
            "mesh": mesh(r, directory/(name+".mesh.json"), selected)}


def contact_audit(s):
    """Actual shared seam pcurves and first/second surface derivatives."""
    fs = [TopoDS.Face_s(f) for f in shapes(s, TopAbs_FACE)]
    seams = []
    for e in shared_edges(s):
        owners = [f for f in fs if any(e.IsSame(t) for t in shapes(f, TopAbs_EDGE))]
        curve = BRepAdaptor_Curve(e)
        gaps, angles, curvatures, fixed_contacts = [], [], [], []
        for k in range(1, 50):
            t = curve.FirstParameter()+(curve.LastParameter()-curve.FirstParameter())*k/50
            point, normals, ks = curve.Value(t), [], []
            fixed_contacts.append(min(max(abs(point.Y()),abs(point.Z()-13)),
                                      max(abs(point.Z()),abs(point.Y()-13))))
            for f in owners:
                pc = BRep_Tool.CurveOnSurface_s(e, f, 0., 0.)
                uv = pc.Value(t)
                surf = BRepAdaptor_Surface(f)
                gaps.append(surf.Value(uv.X(), uv.Y()).Distance(point))
                props = BRepLProp_SLProps(surf, uv.X(), uv.Y(), 2, 1e-10)
                normal = props.Normal()
                if f.Orientation() == TopAbs_REVERSED:
                    normal.Reverse()
                normals.append(normal)
                ks.append(max(abs(props.MinCurvature()), abs(props.MaxCurvature())))
            dot = max(-1., min(1., normals[0].Dot(normals[1])))
            angles.append(math.degrees(math.acos(dot)))
            curvatures.append(max(ks))
        seams.append(dict(sample_count=49, maximum_G0_mm=max(gaps),
            maximum_oriented_G1_degrees=max(angles),
            maximum_principal_curvature_at_contact_mm_inverse=max(curvatures),
            maximum_fixed_d13_contact_error_mm=max(fixed_contacts),
            G0_passed=max(gaps)<=1e-6, G1_passed=max(angles)<=.1,
            plane_support_G2_passed=max(curvatures)<=1e-6))
    return {"seams": seams, "method": "49 samples on each actual shared seam, readback pcurve positions, oriented normals and principal curvatures", "G0_G1_passed": bool(seams) and all(q["G0_passed"] and q["G1_passed"] for q in seams),
            "plane_support_G2_passed": len(seams)==2 and all(q["G0_passed"] and q["G1_passed"] and q["plane_support_G2_passed"] for q in seams)}


def g2_profile_audit(shape, alpha, d=13.):
    """Readback profile values and derivatives compared with Bernstein evaluation."""
    nonplanar = [TopoDS.Face_s(f) for f in shapes(shape,TopAbs_FACE)
                 if BRepAdaptor_Surface(TopoDS.Face_s(f)).GetType()!=GeomAbs_Plane]
    if len(nonplanar)!=1:
        raise ValueError("G2 proxy must have exactly one nonplanar face")
    surf=BRepAdaptor_Surface(nonplanar[0])
    geometry=surf.Bezier()
    h,q=alpha*d,d-2*alpha*d
    controls=[(0,d),(0,d-h)]+[(q*k/5,q*(1-k/5)) for k in range(6)]+[(d-h,0),(d,0)]
    profiles=[]
    for station in range(11):
        u=station/10
        points=[]; residuals=[]; speeds=[]; curvatures=[]
        for k in range(257):
            t=k/256
            p,du,dv,duu,dvv,duv=gp_Pnt(),gp_Vec(),gp_Vec(),gp_Vec(),gp_Vec(),gp_Vec()
            surf.D2(u,t,p,du,dv,duu,dvv,duv)
            actual=xyz(p)
            expected=[sum(math.comb(9,i)*t**i*(1-t)**(9-i)*controls[i][axis] for i in range(10)) for axis in range(2)]
            residuals.append(math.hypot(actual[1]-expected[0],actual[2]-expected[1]))
            speeds.append(dv.Magnitude())
            curvatures.append(dv.Crossed(dvv).Magnitude()/max(dv.Magnitude()**3,1e-30))
            points.append(actual)
        row=dict(x_mm=points[0][0],sample_count=257,
            maximum_Bernstein_position_residual_mm=max(residuals),
            fixed_contact_error_mm=max(abs(points[0][1]),abs(points[0][2]-d),abs(points[-1][1]-d),abs(points[-1][2])),
            minimum_derivative_speed=min(speeds),
            endpoint_curvatures_mm_inverse=[curvatures[0],curvatures[-1]],
            monotone_y_increasing_z_decreasing=all(b[1]>=a[1]-1e-9 and b[2]<=a[2]+1e-9 for a,b in zip(points,points[1:])),
            inside_contact_box=all(-1e-9<=p[1]<=d+1e-9 and -1e-9<=p[2]<=d+1e-9 for p in points))
        if station==5:row.update(profile_points_mm=points,profile_curvature_mm_inverse=curvatures)
        row['passed']=max(residuals)<=1e-6 and row['fixed_contact_error_mm']<=1e-6 and min(speeds)>1e-9 and max(curvatures[0],curvatures[-1])<=1e-6 and row['monotone_y_increasing_z_decreasing'] and row['inside_contact_box']
        profiles.append(row)
    return dict(method="Actual readback Bezier surface D2 at 11 width stations and 257 points per profile; separate Bernstein position evaluation",degrees=[geometry.UDegree(),geometry.VDegree()],profiles=profiles,passed=all(p['passed'] for p in profiles))
