#!/usr/bin/env python3
"""Bounded, fresh ordinary constant/two-end-radius OCCT fillets. No FreeCAD."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import signal
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
PIN = "7.9.3.1.1"
BOUNDARY = ("Ordinary constant or explicitly bound linear two-end-radius edge fillet only. Neither API completion nor "
            "BREP validity certifies the source illustration's special feature, "
            "whole-shape equivalence, G2 continuity, or human appearance acceptance.")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, payload):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                                    allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def safe_error(error):
    return str(error).replace(str(ROOT), "<repo>").replace(str(Path(sys.executable).parent), "<python-bin>")


def repo_file(value):
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Input paths must be repository-relative without parent traversal")
    path = (ROOT / path).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Input path escapes the repository")
    return path


def initial(job_path, job):
    return {
        "schema_version": 1, "job_id": job["job_id"], "engine": "OCCT",
        "engine_version": "7.9.3", "binding_version": None,
        "adapter": "adapters/occt/run.py", "adapter_sha256": sha(__file__),
        "case_number": job.get("case_number", job.get("number")),
        "case_id": job.get("case_id"), "radius_mm": job.get("radius_mm"),
        "request_sha256": sha(job_path), "source_sha256": None,
        "source_fixture_sha256": None, "source_brep": job.get("source_brep"),
        "source_fixture_json": job.get("source_fixture_json"),
        "source_part_indices": job.get("source_part_indices"),
        "expected_input_kind": job.get("expected_input_kind"),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "outcome": "initializing", "reason": None, "api_success": False,
        "api": None, "parameters": {}, "request_parameters_verified": False,
        "native_call_executed": False, "api_result": {}, "valid": None,
        "solids": None, "input_stats": None, "result_stats": None,
        "selection": [], "metrics": {}, "artifacts": {},
        "scope": "ordinary_edge_fillet",
        "only_ordinary": True, "special_feature_certified": False,
        "validation_boundary": BOUNDARY,
        "pairing_eligibility": bool(job.get("runnable_by_selected_edge_runner")),
        "pairing_note": "Historical SMLib admission eligibility is a paired-track policy, not an OCCT capability verdict.",
        "environment": {"python": platform.python_version(), "platform": platform.system(),
                        "machine": platform.machine()},
    }


def worker(job_path, out):
    job = json.loads(job_path.read_text(encoding="utf-8"))
    summary = initial(job_path, job)
    start = perf_counter()

    def checkpoint(stage=None):
        if stage:
            summary["stage"] = stage
        summary["duration_seconds"] = perf_counter() - start
        write_json(out / "summary.json", summary)

    checkpoint("preflight")
    try:
        import OCP
        from OCP.BRep import BRep_Tool, BRep_Builder
        from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
        from OCP.BRepBndLib import BRepBndLib
        from OCP.BRepCheck import BRepCheck_Analyzer
        from OCP.BRepClass3d import BRepClass3d_SolidClassifier
        from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
        from OCP.BRepGProp import BRepGProp
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.BRepTools import BRepTools
        from OCP.Bnd import Bnd_Box
        from OCP.GeomAbs import GeomAbs_Line, GeomAbs_Circle, GeomAbs_Plane
        from OCP.GeomAPI import GeomAPI_ProjectPointOnCurve
        from OCP.GProp import GProp_GProps
        from OCP.TopAbs import (TopAbs_COMPOUND, TopAbs_SOLID, TopAbs_SHELL,
                                TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX,
                                TopAbs_REVERSED, TopAbs_IN, TopAbs_ON, TopAbs_OUT)
        from OCP.TopExp import TopExp
        from OCP.TopLoc import TopLoc_Location
        from OCP.TopTools import TopTools_IndexedMapOfShape
        from OCP.TopoDS import TopoDS, TopoDS_Shape, TopoDS_Iterator, TopoDS_Compound
        from OCP.gp import gp_Pnt
        summary["binding_version"] = version("cadquery-ocp")
        summary["ocp_version"] = OCP.__version__
        if summary["binding_version"] != PIN:
            raise RuntimeError(f"Pinned cadquery-ocp {PIN} required; found {summary['binding_version']}")

        def mapped(shape, kind):
            result = TopTools_IndexedMapOfShape()
            if not shape.IsNull():
                TopExp.MapShapes_s(shape, kind, result)
            return result

        def shapes(shape, kind):
            result = mapped(shape, kind)
            return [result.FindKey(i) for i in range(1, result.Extent() + 1)]

        def xyz(p):
            return [p.X(), p.Y(), p.Z()]

        def dist(a, b):
            return math.sqrt(sum((x-y)**2 for x, y in zip(a, b)))

        def segment_distance(point, ends):
            delta = [b-a for a, b in zip(*ends)]
            denominator = sum(d*d for d in delta)
            if denominator == 0:
                return dist(point, ends[0])
            t = max(0, min(1, sum((p-a)*d for p, a, d in zip(point, ends[0], delta))/denominator))
            return dist(point, [a+t*d for a, d in zip(ends[0], delta)])

        def stats(shape):
            surface, volume = GProp_GProps(), GProp_GProps()
            BRepGProp.SurfaceProperties_s(shape, surface, Eps=1e-8, SkipShared=False)
            BRepGProp.VolumeProperties_s(shape, volume, Eps=1e-8, OnlyClosed=True, SkipShared=False)
            box = Bnd_Box()
            box.SetGap(0)
            BRepBndLib.AddOptimal_s(shape, box, False, False)
            return {"valid": BRepCheck_Analyzer(shape, True).IsValid(),
                    "shape_type": str(shape.ShapeType()).split(".")[-1],
                    "solids": len(shapes(shape, TopAbs_SOLID)),
                    "shells": len(shapes(shape, TopAbs_SHELL)),
                    "faces": len(shapes(shape, TopAbs_FACE)),
                    "edges": len(shapes(shape, TopAbs_EDGE)),
                    "vertices": len(shapes(shape, TopAbs_VERTEX)),
                    "area_mm2": surface.Mass(), "volume_mm3": volume.Mass(),
                    "bbox_mm": list(box.Get()),
                    "volume_note": "Volume is meaningful only for closed solids."}

        def polyline(edge):
            curve = BRepAdaptor_Curve(edge)
            n = 2 if curve.GetType() == GeomAbs_Line else 65
            a, b = curve.FirstParameter(), curve.LastParameter()
            return [xyz(curve.Value(a + (b-a)*i/(n-1))) for i in range(n)]

        def mesh(shape, name, selected=()):
            box = summary["input_stats"]["bbox_mm"]
            diagonal = dist(box[:3], box[3:])
            linear = float(job.get("mesh_deflection_mm", max(0.03, diagonal*0.0008)))
            angular = float(job.get("mesh_angular_deflection_radians", 0.17))
            result = {"schema_version": 1, "vertices": [], "triangles": [],
                      "face_ids": [], "edges": [], "selected_edges": [],
                      "status": "ok", "errors": [],
                      "metadata": {"source": "OCCT native BRep triangulation", "units": "mm",
                                   "linear_deflection_mm": linear,
                                   "angular_deflection_radians": angular,
                                   "indices": "zero_based", "orientation_corrected": True}}
            mesher = BRepMesh_IncrementalMesh(shape, linear, False, angular, False)
            result["metadata"]["native_done"] = mesher.IsDone()
            result["metadata"]["native_status_flags"] = int(mesher.GetStatusFlags())
            if not mesher.IsDone():
                result["errors"].append("Native mesher did not complete")
            for face_id, raw in enumerate(shapes(shape, TopAbs_FACE)):
                face = TopoDS.Face_s(raw)
                location = TopLoc_Location()
                tri = BRep_Tool.Triangulation_s(face, location)
                if tri is None or not tri.NbTriangles():
                    result["errors"].append(f"Missing triangulation for face {face_id}")
                    continue
                offset = len(result["vertices"])
                transform = location.Transformation()
                result["vertices"].extend(xyz(tri.Node(i).Transformed(transform))
                                          for i in range(1, tri.NbNodes()+1))
                for i in range(1, tri.NbTriangles()+1):
                    a, b, c = tri.Triangle(i).Get()
                    if face.Orientation() == TopAbs_REVERSED:
                        b, c = c, b
                    result["triangles"].append([offset+a-1, offset+b-1, offset+c-1])
                    result["face_ids"].append(face_id)
            for raw in shapes(shape, TopAbs_EDGE):
                edge = TopoDS.Edge_s(raw)
                if not BRep_Tool.Degenerated_s(edge):
                    result["edges"].append(polyline(edge))
            result["selected_edges"] = [polyline(edge) for edge in selected]
            if result["errors"]:
                result["status"] = "error"
            write_json(out / f"{name}.mesh.json", result)
            summary["artifacts"][f"{name}_mesh"] = f"{name}.mesh.json"
            summary["metrics"][f"{name}_mesh"] = {"status": result["status"],
                "triangles": len(result["triangles"]), "errors": result["errors"]}

        def save_brep(shape, name):
            if not BRepTools.Write_s(shape, str(out / f"{name}.brep")):
                raise RuntimeError(f"Unable to write {name}.brep")
            summary["artifacts"][f"{name}_brep"] = f"{name}.brep"
            readback = TopoDS_Shape()
            ok = BRepTools.Read_s(readback, str(out / f"{name}.brep"), BRep_Builder())
            summary["metrics"][f"{name}_brep_readback"] = {
                "read": ok, "valid": bool(ok and BRepCheck_Analyzer(readback, True).IsValid()),
                "sha256": sha(out / f"{name}.brep")}

        source = repo_file(job["source_brep"])
        fixture = repo_file(job["source_fixture_json"])
        summary["source_sha256"], summary["source_fixture_sha256"] = sha(source), sha(fixture)
        if summary["source_sha256"] != job["source_sha256"]:
            raise ValueError("Source BREP SHA-256 mismatch")
        if summary["source_fixture_sha256"] != job["source_fixture_sha256"]:
            raise ValueError("Source fixture SHA-256 mismatch")
        if not job.get("runnable_by_selected_edge_runner", True):
            summary.update(outcome="blocked_by_pairing_policy", reason=job.get("blocked_reason") or
                           "Not admitted in the historical paired ordinary-request track")
            checkpoint("blocked")
            return 0
        if job.get("operation") != "native_edge_fillet":
            raise ValueError("Only native_edge_fillet is supported")
        radius = float(job["radius_mm"])
        if not math.isfinite(radius) or radius <= 0:
            raise ValueError("Radius must be finite and positive")
        variable_keys = {key for key in job if key.startswith("variable_")}
        known_variable = {"variable_start_mm", "variable_end_mm", "variable_physical_start",
                          "variable_physical_end", "variable_radius_orientation_rule"}
        required_variable = known_variable - {"variable_radius_orientation_rule"}
        variable = bool(variable_keys) or "variable" in job["job_id"]
        if variable and (variable_keys-known_variable or not required_variable.issubset(variable_keys)):
            summary.update(outcome="unsupported_parameters", reason="Incomplete or unhandled variable-radius request; constant-radius fallback is forbidden")
            checkpoint("parameter_rejected")
            return 0
        if variable:
            r_start, r_end = float(job["variable_start_mm"]), float(job["variable_end_mm"])
            physical_start, physical_end = job["variable_physical_start"], job["variable_physical_end"]
            if (not all(math.isfinite(r) and r>0 for r in (r_start,r_end)) or
                    any(len(p)!=3 or not all(math.isfinite(x) for x in p) for p in (physical_start,physical_end)) or
                    dist(physical_start,physical_end)<=1e-6):
                summary.update(outcome="unsupported_parameters", reason="Invalid variable radii or physical endpoints")
                checkpoint("parameter_rejected")
                return 0
            summary["parameters"] = {"radius_mode":"two_end_variable", "interpolation":"native_two_endpoint_default", **{key:job[key] for key in required_variable}}
            summary["api"] = "BRepFilletAPI_MakeFillet.Add(R1, R2, edge); Build()"
        else:
            summary["parameters"] = {"radius_mode":"constant", "radius_mm":radius}
            summary["api"] = "BRepFilletAPI_MakeFillet.Add(radius, edge); Build()"
        shape = TopoDS_Shape()
        if not BRepTools.Read_s(shape, str(source), BRep_Builder()) or shape.IsNull():
            raise ValueError("BREP read failed or returned a null shape")
        parts = []
        if shape.ShapeType() == TopAbs_COMPOUND:
            iterator = TopoDS_Iterator(shape)
            while iterator.More():
                parts.append(iterator.Value())
                iterator.Next()
        else:
            parts = [shape]
        indices = job["source_part_indices"]
        if not indices or any(type(i) is not int or not 0 <= i < len(parts) for i in indices):
            raise ValueError("Invalid 0-based source_part_indices")
        if len(indices) == 1:
            before = parts[indices[0]]
        else:
            before, builder = TopoDS_Compound(), BRep_Builder()
            builder.MakeCompound(before)
            for i in indices:
                builder.Add(before, parts[i])
        summary["input_stats"] = stats(before)
        expected = {"sheet": "shell"}.get(job["expected_input_kind"], job["expected_input_kind"])
        input_kind_ok = ((expected == "solid" and summary["input_stats"]["solids"] == 1) or
                         (expected == "shell" and summary["input_stats"]["solids"] == 0 and
                          summary["input_stats"]["shells"] >= 1))
        if not summary["input_stats"]["valid"] or not input_kind_ok:
            summary.update(outcome="input_rejected", reason="Input invalid or does not match expected solid/shell kind")
            save_brep(before, "before")
            mesh(before, "before")
            checkpoint("input_rejected")
            return 0
        checkpoint("selection")
        edge_map = mapped(before, TopAbs_EDGE)
        faces = shapes(before, TopAbs_FACE)
        adjacency = {}
        for face_i, face in enumerate(faces):
            for raw in shapes(face, TopAbs_EDGE):
                adjacency.setdefault(edge_map.FindIndex(raw), set()).add(face_i)
        selected = []
        for target in job["targets"]:
            tolerance = float(target.get("selector_tolerance_mm", 1e-6))
            coverage = float(target.get("coverage_tolerance_mm", 1e-5))
            samples = target.get("samples_mm", target.get("samples", []))
            endpoints = target.get("endpoints", [samples[0], samples[-1]])
            if len(samples) < 2 or len(endpoints) != 2:
                raise ValueError("Target requires at least two world samples and two endpoints")
            candidates = []
            for i in range(1, edge_map.Extent()+1):
                edge = TopoDS.Edge_s(edge_map.FindKey(i))
                if BRep_Tool.Degenerated_s(edge):
                    continue
                curve = BRepAdaptor_Curve(edge)
                first, last = curve.FirstParameter(), curve.LastParameter()
                ends = [xyz(curve.Value(first)), xyz(curve.Value(last))]
                gap = min(max(dist(ends[0], endpoints[0]), dist(ends[1], endpoints[1])),
                          max(dist(ends[0], endpoints[1]), dist(ends[1], endpoints[0])))
                if gap > coverage:
                    continue
                count = len(adjacency.get(i, set()))
                if count != target.get("required_support_adjacency_count", 2):
                    continue
                kind = (target.get("geometric_kind") or "").lower()
                native_samples = [xyz(curve.Value(first+(last-first)*k/64)) for k in range(65)]
                representation_residual = None
                # Source BREP sometimes represents exact lines/circles as rational
                # BSplines. Check their world geometry instead of rejecting by type.
                if kind == "line":
                    representation_residual = max(segment_distance(p, endpoints) for p in native_samples)
                    if representation_residual > tolerance:
                        continue
                if kind in ("circle", "circle_arc") and target.get("center"):
                    center, normal = target["center"], target.get("normal")
                    normal_length = math.sqrt(sum(n*n for n in normal)) if normal else 0
                    if normal_length == 0:
                        raise ValueError("Circle target requires a nonzero normal")
                    normal = [n/normal_length for n in normal]
                    representation_residual = max(max(abs(dist(p, center)-target["radius"]),
                        abs(sum((v-c)*n for v, c, n in zip(p, center, normal)))) for p in native_samples)
                    if representation_residual > tolerance:
                        continue
                elif kind in ("circle", "circle_arc") and curve.GetType() != GeomAbs_Circle:
                    # Without center/normal an analytic circle is required. Sample-only
                    # targets without an analytic kind are still matched by projection.
                    continue
                if curve.GetType() == GeomAbs_Circle and target.get("center"):
                    circle = curve.Circle()
                    if (dist(xyz(circle.Location()), target["center"]) > tolerance or
                            abs(circle.Radius()-target["radius"]) > tolerance):
                        continue
                prop = GProp_GProps()
                BRepGProp.LinearProperties_s(edge, prop)
                length = prop.Mass()
                expected_length = target.get("expected_length_mm")
                if expected_length is not None and not target.get("length_is_approximation", False):
                    if abs(length-expected_length) > max(coverage, expected_length*1e-8):
                        continue
                geometry = BRep_Tool.Curve_s(edge, first, last)
                residuals = []
                for point in samples:
                    projection = GeomAPI_ProjectPointOnCurve(gp_Pnt(*point), geometry, first, last)
                    # The projection API can omit endpoint minima; include both finite ends.
                    residuals.append(min([dist(point, ends[0]), dist(point, ends[1])] +
                        ([projection.LowerDistance()] if projection.NbPoints() else [])))
                if max(residuals) > tolerance:
                    continue
                candidates.append((edge, {"native_edge_index_1based_diagnostic": i,
                    "curve_type": str(curve.GetType()).split(".")[-1],
                    "length_mm": length, "endpoint_gap_mm": gap,
                    "max_sample_residual_mm": max(residuals), "sample_count": len(samples),
                    "max_native_to_target_geometry_residual_mm": representation_residual,
                    "native_to_target_geometry_sample_count": 65 if representation_residual is not None else 0,
                    "support_face_count": count, "endpoints_mm": ends}))
            record = {"target_id": target.get("target_id", target.get("id")),
                      "method": "unique finite native curve matched to world endpoints, all samples, exact length when supplied, and support adjacency",
                      "selector_tolerance_mm": tolerance, "coverage_tolerance_mm": coverage,
                      "candidate_count": len(candidates), "candidates": [x[1] for x in candidates],
                      "external_edge_indices_used": False,
                      "split_chain_implemented": False}
            summary["selection"].append(record)
            if len(candidates) != 1:
                summary.update(outcome="selection_rejected", reason=
                    f"Target {record['target_id']} resolved to {len(candidates)} complete native edges; no guess or split-chain fallback")
                save_brep(before, "before")
                mesh(before, "before", selected)
                checkpoint("selection_rejected")
                return 0
            edge = candidates[0][0]
            if not any(edge.IsSame(previous) for previous in selected):
                selected.append(edge)
        summary["selected_edge_count"] = len(selected)
        save_brep(before, "before")
        mesh(before, "before", selected)
        checkpoint("native_setup")
        fillet = BRepFilletAPI_MakeFillet(before)
        if variable:
            if len(selected)!=1 or BRepAdaptor_Curve(selected[0]).GetType()!=GeomAbs_Line:
                summary.update(outcome="unsupported_parameters",reason="Two-end law currently requires exactly one straight native edge")
                checkpoint("parameter_rejected")
                return 0
            curve=BRepAdaptor_Curve(selected[0])
            native_first=xyz(curve.Value(curve.FirstParameter()))
            native_last=xyz(curve.Value(curve.LastParameter()))
            tolerance=min(float(t.get("coverage_tolerance_mm",1e-5)) for t in job["targets"])
            forward=max(dist(native_first,physical_start),dist(native_last,physical_end))<=tolerance
            reverse=max(dist(native_first,physical_end),dist(native_last,physical_start))<=tolerance
            if forward==reverse:
                summary.update(outcome="unsupported_parameters",reason="Cannot uniquely bind variable physical endpoints to finite native parameter ends")
                checkpoint("parameter_rejected")
                return 0
            native_r1,native_r2=(r_start,r_end) if forward else (r_end,r_start)
            support_faces=[TopoDS.Face_s(face) for face in faces
                if any(selected[0].IsSame(e) for e in shapes(face,TopAbs_EDGE))]
            if len(support_faces)!=2 or any(BRepAdaptor_Surface(face).GetType()!=GeomAbs_Plane for face in support_faces):
                summary.update(outcome="unsupported_parameters",reason="Two-end measured law currently requires two planar supports")
                checkpoint("parameter_rejected")
                return 0
            planes=[BRepAdaptor_Surface(face).Plane() for face in support_faces]
            if abs(planes[0].Axis().Direction().Dot(planes[1].Axis().Direction()))>1e-7:
                summary.update(outcome="unsupported_parameters",reason="Two-end measured law currently requires orthogonal planar supports")
                checkpoint("parameter_rejected")
                return 0
            fillet.Add(native_r1,native_r2,selected[0])
            if fillet.NbContours()!=1 or fillet.NbEdges(1)!=1:
                summary.update(outcome="unsupported_parameters",reason="Automatic tangent contour extends beyond the single physically bound edge")
                checkpoint("parameter_rejected")
                return 0
            contour_first=xyz(BRep_Tool.Pnt_s(fillet.FirstVertex(1)))
            contour_last=xyz(BRep_Tool.Pnt_s(fillet.LastVertex(1)))
            if max(dist(contour_first,native_first),dist(contour_last,native_last))>tolerance:
                summary.update(outcome="unsupported_parameters",reason="Native contour orientation differs from the proven native parameter orientation")
                checkpoint("parameter_rejected")
                return 0
            summary["variable_radius_binding"]={"native_first_point_mm":native_first,
                "native_last_point_mm":native_last,"native_start_radius_mm":native_r1,
                "native_end_radius_mm":native_r2,"reversed_from_physical_endpoints":reverse,
                "contour_first_point_mm":contour_first,"contour_last_point_mm":contour_last,
                "contour_edge_count":1,"endpoint_gap_mm":max(dist(native_first,physical_end if reverse else physical_start),dist(native_last,physical_start if reverse else physical_end)),"verified":True}
        else:
            for edge in selected:
                fillet.Add(radius, edge)
            summary["request_parameters_verified"] = True
        summary["api_result"]["effective_parameters"]={"method":"Add(R1,R2,edge)" if variable else "Add(radius,edge)",
            **summary["parameters"],"continuity":"default_internal_C1","fillet_shape":"ChFi3d_Rational",
            "support_scope":"one straight native edge, two orthogonal planar supports; no source-special law" if variable else "ordinary selected-edge constant-radius contour; no source-special law"}
        contours = []
        for i in range(1, fillet.NbContours()+1):
            contours.append({"contour_index_1based": i, "edge_count": fillet.NbEdges(i),
                "native_edge_indices_1based_diagnostic": [edge_map.FindIndex(fillet.Edge(i, k))
                    for k in range(1, fillet.NbEdges(i)+1)], "length_mm": fillet.Length(i)})
        summary["api_result"]["contours"] = contours
        summary["native_call_executed"] = True
        checkpoint("native_build")
        fillet_start = perf_counter()
        fillet.Build()
        summary["metrics"]["fillet_seconds"] = perf_counter()-fillet_start
        summary["api_success"] = bool(fillet.IsDone())
        summary["api_result"].update(is_done=bool(fillet.IsDone()),
            faulty_contours=fillet.NbFaultyContours(), faulty_vertices=fillet.NbFaultyVertices())
        if not fillet.IsDone():
            summary.update(outcome="native_rejected", reason="BRepFilletAPI_MakeFillet.IsDone() is false")
            checkpoint("native_rejected")
            return 0
        result = fillet.Shape()
        if result.IsNull():
            summary.update(outcome="invalid_result", reason="Native API returned a null shape")
            checkpoint("invalid_result")
            return 0
        checkpoint("validation")
        summary["result_stats"] = stats(result)
        summary["valid"] = summary["result_stats"]["valid"]
        summary["solids"] = summary["result_stats"]["solids"]
        output_kind_ok = ((expected == "solid" and summary["solids"] == 1) or
                          (expected == "shell" and summary["solids"] == 0 and
                           summary["result_stats"]["shells"] >= 1))
        summary["metrics"]["expected_kind_preserved"] = output_kind_ok
        probes = []
        for probe in job.get("protected_probes", []):
            item = {"id": probe["id"], "point_mm": probe["point"]}
            for name, native in (("before", before), ("after", result)):
                solids = shapes(native, TopAbs_SOLID)
                states = [BRepClass3d_SolidClassifier(TopoDS.Solid_s(s), gp_Pnt(*probe["point"]), 1e-7).State() for s in solids]
                state = ("inside" if TopAbs_IN in states else "boundary" if TopAbs_ON in states
                         else "outside" if states and all(s == TopAbs_OUT for s in states) else "not_applicable")
                item[name] = state
                expected_state = probe.get(f"expected_{name}_state")
                item[f"{name}_passed"] = (state == ("inside" if expected_state else "outside")) if expected_state is not None and solids else None
            probes.append(item)
        summary["metrics"]["protected_probes"] = probes
        save_brep(result, "result")
        mesh(result, "result")
        if variable:
            # Read back the exported BREP. Measure both contact curves on the
            # two original support planes at fixed physical spine stations.
            measured=TopoDS_Shape()
            if not BRepTools.Read_s(measured,str(out/"result.brep"),BRep_Builder()):
                raise RuntimeError("Variable result BREP readback failed")
            result_faces=[TopoDS.Face_s(f) for f in shapes(measured,TopAbs_FACE)]
            contact_edges=[]
            spine_length=dist(physical_start,physical_end)
            direction=[(b-a)/spine_length for a,b in zip(physical_start,physical_end)]
            coordinate=lambda p:sum((x-a)*d for x,a,d in zip(p,physical_start,direction))/spine_length
            for raw in shapes(measured,TopAbs_EDGE):
                edge=TopoDS.Edge_s(raw)
                owners=[face for face in result_faces if any(edge.IsSame(e) for e in shapes(face,TopAbs_EDGE))]
                if len(owners)!=2 or not any(BRepAdaptor_Surface(face).GetType()!=GeomAbs_Plane for face in owners):
                    continue
                support=[face for face in owners if BRepAdaptor_Surface(face).GetType()==GeomAbs_Plane and
                    all(BRepAdaptor_Surface(face).Plane().Distance(gp_Pnt(*p))<=1e-6 for p in (physical_start,physical_end))]
                if len(support)!=1:
                    continue
                c=BRepAdaptor_Curve(edge);a,b=c.FirstParameter(),c.LastParameter()
                ca,cb=coordinate(xyz(c.Value(a))),coordinate(xyz(c.Value(b)))
                samples=[]
                for fraction in (0.,.1,.25,.5,.75,.9,1.):
                    lo,hi=a,b
                    for _ in range(64):
                        middle=(lo+hi)/2
                        value=coordinate(xyz(c.Value(middle)))
                        if (value<fraction)==(cb>ca):lo=middle
                        else:hi=middle
                    point=xyz(c.Value((lo+hi)/2));actual_fraction=coordinate(point)
                    foot=[a+actual_fraction*spine_length*d for a,d in zip(physical_start,direction)]
                    contact_radius=dist(point,foot)
                    expected_radius=r_start+(r_end-r_start)*fraction
                    samples.append({"physical_spine_fraction":fraction,"actual_spine_fraction":actual_fraction,
                        "contact_point_mm":point,"measured_contact_distance_mm":contact_radius,
                        "expected_linear_radius_mm":expected_radius,"radius_error_mm":abs(contact_radius-expected_radius)})
                contact_edges.append({"endpoint_spine_fractions":[ca,cb],"samples":samples,
                    "measured_radius_range_mm":[min(p['measured_contact_distance_mm'] for p in samples),max(p['measured_contact_distance_mm'] for p in samples)]})
            max_error=max((p['radius_error_mm'] for row in contact_edges for p in row['samples']),default=None)
            max_station_error=max((abs(p['actual_spine_fraction']-p['physical_spine_fraction']) for row in contact_edges for p in row['samples']),default=None)
            nonconstant=bool(contact_edges) and all(row['measured_radius_range_mm'][1]-row['measured_radius_range_mm'][0]>abs(r_end-r_start)*.9 for row in contact_edges)
            endpoint_error=max((p['radius_error_mm'] for row in contact_edges for p in row['samples'] if p['physical_spine_fraction'] in (0.,1.)),default=None)
            passed=len(contact_edges)==2 and endpoint_error is not None and endpoint_error<=1e-4 and max_station_error<=1e-6 and (nonconstant or abs(r_end-r_start)<=1e-6)
            summary["variable_radius_validation"]={"method":"Exported BREP readback; two actual blend/support contact curves, distance from original spine at seven fixed physical stations", "contact_curves":contact_edges,
                "maximum_radius_error_mm":max_error,"maximum_station_fraction_error":max_station_error,
                "maximum_endpoint_radius_error_mm":endpoint_error,
                "endpoint_radii_verified":len(contact_edges)==2 and endpoint_error is not None and endpoint_error<=1e-4,
                "nonconstant_radius_observed":nonconstant,"passed":passed,
                "full_linear_contact_law_passed":len(contact_edges)==2 and max_error is not None and max_error<=1e-4,
                "verification_scope":"Same two physical endpoint radii and nonconstant output only; interior linear reference differences are observations, not API failures",
                "boundary":"No full interpolation-law equivalence, source asymmetric range law, or rho certification"}
            summary["request_parameters_verified"]=passed
            summary["pairing_status"]="same_physical_two_endpoint_constraints_only" if passed else "two_endpoint_geometry_unverified"
            summary["full_variable_law_equivalence_verified"]=False
        summary.update(outcome="ok" if summary["valid"] and output_kind_ok else "invalid_result",
                       reason=None if summary["valid"] and output_kind_ok else "BREP invalid or expected input kind not preserved")
        if variable and summary["outcome"]=="ok" and not summary["request_parameters_verified"]:
            summary.update(outcome="parameter_validation_failed",reason="Physical endpoint radii and nonconstant output did not verify")
        checkpoint("complete")
        return 0
    except Exception as error:
        summary.update(outcome="dependency_error" if isinstance(error, ImportError) else "exception",
                       reason=f"{type(error).__name__}: {safe_error(error)}")
        checkpoint()
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    job_path, out = args.job.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.worker:
        return worker(job_path, out)
    if args.timeout <= 0 or not math.isfinite(args.timeout):
        parser.error("--timeout must be finite and positive")
    job = json.loads(job_path.read_text(encoding="utf-8"))
    for name in ("before.mesh.json", "result.mesh.json", "before.brep", "result.brep"):
        (out / name).unlink(missing_ok=True)
    # Never reuse an old summary if this execution fails before its first checkpoint.
    write_json(out / "summary.json", initial(job_path, job))
    start = perf_counter()
    command = [sys.executable, str(Path(__file__).resolve()), str(job_path),
               "--output", str(out), "--worker"]
    timed_out = False
    with (out / "stdout.log").open("w", encoding="utf-8") as stdout, \
            (out / "stderr.log").open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr,
                                   start_new_session=(os.name == "posix"), cwd=ROOT)
        try:
            process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait()
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    summary["process"] = {"returncode": process.returncode, "timeout_seconds": args.timeout,
                          "timed_out": timed_out, "wall_seconds": perf_counter()-start}
    if timed_out:
        summary.update(outcome="timeout", reason=f"Worker exceeded {args.timeout:g}s")
    elif process.returncode != 0:
        if process.returncode < 0 or summary["outcome"] == "initializing":
            summary["outcome"] = "crash"
        summary["reason"] = summary.get("reason") or f"Worker exited {process.returncode}"
    # Native diagnostics normally contain no paths; remove local paths if a wrapper adds one.
    for name in ("stdout.log", "stderr.log"):
        path = out / name
        path.write_text(safe_error(path.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_json(out / "summary.json", summary)
    print(json.dumps({"job_id": summary["job_id"], "outcome": summary["outcome"],
                      "api_success": summary["api_success"], "valid": summary["valid"],
                      "reason": summary["reason"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
