"""Export finite source curves, support NURBS and original topology without repair.

Run inside a FreeCAD Python environment. Source/output paths are passed through
FILLETBENCH_SOURCE_BREP and FILLETBENCH_FIXTURE_JSON by the revision runner.
No machine-specific runtime or SDK paths are embedded in this exporter.
"""
from pathlib import Path
from collections import Counter, defaultdict
import hashlib
import json
import math
import os

import FreeCAD as App
import Part


REPO = Path(__file__).resolve().parents[2]
TOLERANCE = 1e-7


def xyz(point):
    return [float(point.x), float(point.y), float(point.z)]


def full_knots(knots, multiplicities):
    return [float(k) for k, count in zip(knots, multiplicities) for _ in range(count)]


def metrics(shape):
    bounds = shape.optimalBoundingBox(False, False)
    return dict(valid=shape.isValid(), shape_type=shape.ShapeType,
                faces=len(shape.Faces), edges=len(shape.Edges), vertices=len(shape.Vertexes),
                solids=len(shape.Solids), shells=len(shape.Shells), area=float(shape.Area),
                volume=float(sum(s.Volume for s in shape.Solids)),
                bbox=[bounds.XMin, bounds.YMin, bounds.ZMin, bounds.XMax, bounds.YMax, bounds.ZMax])


def components(shape):
    if shape.ShapeType in ("Solid", "Shell", "Face"):
        yield shape
    elif shape.ShapeType in ("Compound", "CompSolid"):
        for child in shape.childShapes():
            yield from components(child)
    else:
        raise ValueError("Unsupported source component: " + shape.ShapeType)


def finite_curve(edge):
    # Whole-shape toNurbs can expose a wrong angular range on finite arcs.
    curve = edge.Curve.toBSpline(edge.FirstParameter, edge.LastParameter)
    curve.setNotPeriodic()
    first, last = curve.FirstParameter, curve.LastParameter
    curve.segment(first, last)
    points = [curve.value(first + (last - first) * i / 32) for i in range(33)]
    original = [edge.valueAt(edge.FirstParameter + (edge.LastParameter - edge.FirstParameter) * i / 32)
                for i in range(33)]
    converted_edge = curve.toShape()
    errors = [edge.distToShape(Part.Vertex(p))[0] for p in points]
    errors += [converted_edge.distToShape(Part.Vertex(p))[0] for p in original]
    if max(errors) > TOLERANCE:
        raise ValueError("Finite source curve conversion changed geometry: " + str(max(errors)))
    knots = full_knots(curve.getKnots(), curve.getMultiplicities())
    poles = [xyz(p) for p in curve.getPoles()]
    if len(knots) != len(poles) + curve.Degree + 1:
        raise ValueError("Unclamped finite curve")
    return dict(degree=curve.Degree, knots=knots, poles=poles,
                weights=[float(w) for w in curve.getWeights()],
                source_evaluation_error_mm=max(errors),
                source_evaluation_error_method="bidirectional sampled distance to original finite curve",
                original_range=[edge.FirstParameter, edge.LastParameter],
                exported_range=[first, last], exported_endpoints=[xyz(points[0]), xyz(points[-1])],
                exported_polyline=[xyz(p) for p in points])


def finite_surface(face, original):
    support = face.Surface.copy()
    support.setUNotPeriodic()
    support.setVNotPeriodic()
    support.segment(*face.ParameterRange)
    domain = list(face.ParameterRange)
    original_domain = original.ParameterRange
    samples = []
    reverse = []
    for a in (.07, .3, .5, .7, .93):
        for b in (.07, .3, .5, .7, .93):
            u = domain[0] + (domain[1] - domain[0]) * a
            v = domain[2] + (domain[3] - domain[2]) * b
            point = support.value(u, v)
            old_uv = original.Surface.parameter(point)
            error = max((point - face.Surface.value(u, v)).Length,
                        (point - original.Surface.value(*old_uv)).Length)
            old_u = original_domain[0] + (original_domain[1] - original_domain[0]) * a
            old_v = original_domain[2] + (original_domain[3] - original_domain[2]) * b
            old_point = original.Surface.value(old_u, old_v)
            new_uv = support.parameter(old_point)
            reverse_error = (old_point - support.value(*new_uv)).Length
            if max(error, reverse_error) > TOLERANCE:
                raise ValueError("Support conversion changed source surface: " + str(max(error, reverse_error)))
            samples.append(dict(uv=[u, v], point=xyz(point), source_evaluation_error_mm=error))
            reverse.append(dict(original_uv=[old_u, old_v], exported_uv=list(new_uv),
                                source_evaluation_error_mm=reverse_error))
    data = dict(degree_u=support.UDegree, degree_v=support.VDegree,
                knots_u=full_knots(support.getUKnots(), support.getUMultiplicities()),
                knots_v=full_knots(support.getVKnots(), support.getVMultiplicities()),
                poles=[[xyz(p) for p in row] for row in support.getPoles()],
                weights=[[float(w) for w in row] for row in support.getWeights()],
                domain=domain, source_samples=samples, original_support_reverse_samples=reverse)
    return data, support


def export_component(source, identifier):
    converted = source.toNurbs()
    if (len(source.Faces), len(source.Edges), len(source.Vertexes)) != (
            len(converted.Faces), len(converted.Edges), len(converted.Vertexes)):
        raise ValueError("Support conversion changed topology; source faces cannot be discarded")
    edges = source.Edges
    vertices = source.Vertexes

    def edge_id(edge):
        return next(i + 1 for i, existing in enumerate(edges) if existing.isSame(edge))

    def vertex_id(point):
        distances = [(point - v.Point).Length for v in vertices]
        nearest = min(range(len(vertices)), key=lambda i: distances[i])
        if distances[nearest] > TOLERANCE:
            raise ValueError("Finite curve endpoint differs from original vertex")
        return nearest + 1

    edge_data = []
    for i, edge in enumerate(edges, 1):
        curve = finite_curve(edge)
        edge_data.append(dict(id=i, vertices=[vertex_id(App.Vector(*p)) for p in curve["exported_endpoints"]],
                              range=curve["exported_range"], curve=curve,
                              tolerance=float(getattr(edge, "Tolerance", TOLERANCE)),
                              source_polyline=curve["exported_polyline"], source_length=float(edge.Length),
                              source_curve_type=type(edge.Curve).__name__, source_orientation=edge.Orientation))
    shells = []
    face_number = 0
    source_shells = source.Shells if source.ShapeType == "Solid" else [source]
    for shell_number, shell in enumerate(source_shells):
        face_data = []
        for original in shell.Faces:
            face_number += 1
            # Verify face-index correspondence, then use only its support NURBS.
            support_face = converted.Faces[face_number - 1]
            if abs(original.Area - support_face.Area) > max(1e-6, original.Area * 1e-8):
                raise ValueError("Converted face correspondence failed")
            surface, support = finite_surface(support_face, original)
            loops = []
            for wire in original.Wires:
                uses, uv_points, gaps = [], [], []
                last_point = None
                first_point = None
                for edge in wire.OrderedEdges:
                    identifier_edge = edge_id(edge)
                    orientation = -1 if edge.Orientation == "Reversed" else 1
                    first, last = ((edge.FirstParameter, edge.LastParameter) if orientation == 1
                                   else (edge.LastParameter, edge.FirstParameter))
                    start_point = edge.valueAt(first)
                    if last_point is not None:
                        gaps.append((start_point - last_point).Length)
                    elif first_point is None:
                        first_point = start_point
                    for j in range(33):
                        point = edge.valueAt(first + (last - first) * j / 32)
                        uv = support.parameter(point)
                        if (point - support.value(*uv)).Length > TOLERANCE:
                            raise ValueError("Loop edge does not lie on exported support")
                        uv_points.append([float(x) for x in uv])
                    last_point = edge.valueAt(last)
                    uses.append(dict(id=identifier_edge, orientation=orientation))
                gaps.append((last_point - first_point).Length)
                if max(gaps) > TOLERANCE:
                    raise ValueError("Source coedge traversal is disconnected")
                area = sum(a[0] * b[1] - a[1] * b[0]
                           for a, b in zip(uv_points, uv_points[1:] + uv_points[:1])) / 2
                if not math.isfinite(area) or abs(area) < 1e-12:
                    raise ValueError("UV loop orientation is indeterminate")
                loops.append(dict(outer=wire.isSame(original.OuterWire), edges=uses,
                                  orientation=1 if area > 0 else -1,
                                  source_orientation=wire.Orientation, actual_UV_signed_area=area,
                                  actual_UV_points=uv_points, source_traversal_max_gap_mm=max(gaps)))
            loops.sort(key=lambda loop: not loop["outer"])
            if not loops or not loops[0]["outer"]:
                raise ValueError("Missing outer loop")
            face_data.append(dict(id=face_number, orientation=-1 if original.Orientation == "Reversed" else 1,
                                  surface=surface, loops=loops, source_area=float(original.Area),
                                  source_orientation=original.Orientation))
        shells.append(dict(is_void=shell_number > 0, closed=bool(shell.isClosed()), faces=face_data))
    face_uses = defaultdict(list)
    for shell in shells:
        for face in shell["faces"]:
            for loop in face["loops"]:
                for use in loop["edges"]:
                    face_uses[use["id"]].append(dict(face_id=face["id"], orientation=use["orientation"]))
    nonmanifold = [dict(edge_id=edge, uses=uses) for edge, uses in face_uses.items() if len(uses) != 2]
    topology_audit = dict(method="all preserved source face-loop coedge incidences",
                          edge_use_count_distribution=dict(Counter(len(uses) for uses in face_uses.values())),
                          every_edge_used_twice=not nonmanifold, nonmanifold_or_boundary_edges=nonmanifold)
    return dict(id=identifier, kind=source.ShapeType.lower(), tolerance=TOLERANCE,
                vertices=[dict(id=i + 1, point=xyz(v.Point), tolerance=float(getattr(v, "Tolerance", TOLERANCE)))
                          for i, v in enumerate(vertices)], edges=edge_data, shells=shells, source_stats=metrics(source),
                source_topology_audit=topology_audit,
                conversion_method="original finite Curve.toBSpline; converted support NURBS; original topology",
                loop_orientation_method="actual signed UV area of the ordered original coedge traversal")


def export(source_path, output_path):
    source_path, output_path = Path(source_path).resolve(), Path(output_path).resolve()
    if not source_path.is_relative_to(REPO) or not output_path.is_relative_to(REPO):
        raise ValueError("Source and output must stay within repository")
    if output_path.exists():
        raise ValueError("Refusing to overwrite existing fixture")
    shape = Part.Shape()
    shape.read(str(source_path))
    stats = metrics(shape)
    if not stats["valid"]:
        raise ValueError("Invalid source BREP; no repair allowed")
    record = dict(schema_version=1, case_number=11,
                  exchange_kind="exact_NURBS_and_topology_custom_bridge_no_USD",
                  source_brep=str(source_path.relative_to(REPO)),
                  source_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(), source_stats=stats,
                  source_faces_preserved=True, healing=False, stitching=False,
                  exporter_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  conversion_runtime=dict(FreeCAD=App.Version(), OCCT=getattr(Part, "OCC_VERSION", "unavailable")),
                  components=[export_component(c, "case11-component-" + str(i + 1))
                              for i, c in enumerate(components(shape))],
                  publication=dict(tier="exploratory_reconstruction", dimensions_inferred=True,
                                   not_original_vendor_CAD=True, reference_images_included=False))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(dict(status="exported", source_sha256=record["source_sha256"],
                          output=str(output_path.relative_to(REPO)), components=len(record["components"]))))
    return record


if __name__ == "__main__" or (os.environ.get("FILLETBENCH_SOURCE_BREP") and
                              os.environ.get("FILLETBENCH_FIXTURE_JSON")):
    export(os.environ["FILLETBENCH_SOURCE_BREP"], os.environ["FILLETBENCH_FIXTURE_JSON"])
