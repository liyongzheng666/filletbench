"""Benchmark-only ctypes bridge to unmodified official SMLib C++ SM_API."""
import os
import ctypes as C
import math
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE_COMMIT = os.environ.get("FILLETBENCH_SDK_COMMIT", "unverified")


class Output(C.Structure):
    _fields_ = [("volume", C.c_double), ("area", C.c_double),
                ("centroid", C.c_double * 3), ("bbox", C.c_double * 6),
                ("operation_ms", C.c_double), ("configured_zone_tolerance", C.c_double), ("model_size_estimate", C.c_double), ("default_zone_tolerance", C.c_double),
                ("input_max_vertex_tol", C.c_double), ("input_max_edge_tol", C.c_double),
                ("result_max_vertex_tol", C.c_double), ("result_max_edge_tol", C.c_double),
                ("solids", C.c_long), ("voids", C.c_long), ("faces", C.c_long),
                ("edges", C.c_long), ("vertices", C.c_long),
                ("empty", C.c_int), ("manifold", C.c_int), ("valid", C.c_int),
                ("result_constructed", C.c_int), ("selected_edges_count", C.c_int), ("before_volume", C.c_double), ("before_area", C.c_double), ("input_a_valid", C.c_int), ("input_b_valid", C.c_int),
        ("input_a_manifold", C.c_int), ("input_b_manifold", C.c_int),
        ("input_a_valid_before_tolerance", C.c_int), ("input_b_valid_before_tolerance", C.c_int)]


class ShapeNode(C.Structure):
    _fields_ = [("kind",C.c_int),("left",C.c_int),("right",C.c_int),("operation",C.c_int),
        ("origin",C.c_double*3),("params",C.c_double*3),("scale",C.c_double*3),
        ("axis",C.c_double*3),("angle",C.c_double),("center",C.c_double*3),("translate",C.c_double*3)]

_lib=C.CDLL(os.environ["FILLETBENCH_SPECIAL_BRIDGE"])
_lib.smlib_advanced_run.argtypes=[C.POINTER(ShapeNode),C.c_int,C.c_int,C.c_int,C.c_double,C.c_int,
    C.POINTER(C.c_double),C.c_int,C.c_double,C.c_double,C.c_double,C.c_char_p,C.POINTER(C.c_int),C.POINTER(Output),C.c_char_p,C.c_int]
_lib.smlib_advanced_run.restype=C.c_int


def _shape(shape,nodes):
    kind=shape.get("kind","box"); n=ShapeNode();n.kind={"box":0,"sphere":1,"cylinder":2,"torus":3,"cone":4,"ellipsoid":5,"boolean":6}[kind]
    n.origin[:]=shape.get("origin",[0,0,0]); n.scale[:]=shape.get("radii",shape.get("scale",[1,1,1]))
    if kind=="box":n.params[:]=shape["size"]
    elif kind=="sphere":n.params[:]=[shape["radius"],0,0]
    elif kind=="cylinder":n.params[:]=[shape["radius"],shape["height"],0]
    elif kind=="torus":n.params[:]=[shape["major_radius"],shape["minor_radius"],0]
    elif kind=="cone":n.params[:]=[shape["radius1"],shape["radius2"],shape["height"]]
    elif kind=="boolean":
        n.left=_shape(shape["a"],nodes);n.right=_shape(shape["b"],nodes);n.operation={"union":0,"difference":1,"intersection":2}[shape["operation"]]
    tr=shape.get("transform",{});rot=tr.get("rotation",tr.get("rotate",{}));n.axis[:]=rot.get("axis",[0,0,1]);n.angle=rot.get("angle_deg",0)
    n.center[:]=rot.get("center",[0,0,0]);n.translate[:]=tr.get("translation",tr.get("translate",[0,0,0]));nodes.append(n);return len(nodes)-1


def _finite(value):
    return value if math.isfinite(value) else None


class KernelOperationError(RuntimeError):
    def __init__(self,message,operation_stage,details):
        super().__init__(message)
        self.operation_stage=operation_stage
        self.details=details


def run_case(case):
    nodes=[]
    a=_shape(case["a"],nodes); b=_shape(case.get("b") or case["a"],nodes)
    c_nodes=(ShapeNode*len(nodes))(*nodes)
    result, err = Output(), C.create_string_buffer(16384)
    probes = case.get("probes", [])
    probe_coords = (C.c_double * (3 * len(probes)))(*[x for p in probes for x in p["point"]])
    states = (C.c_int * len(probes))()
    point_tolerance = case.get("point_tolerance", 1e-7)
    accuracy = case.get("measurement_accuracy", 1e-8)
    mesh_path = case.get("mesh_path")
    if mesh_path:
        mesh_path = str(Path(mesh_path).resolve())
        Path(mesh_path).parent.mkdir(parents=True, exist_ok=True)
    code = _lib.smlib_advanced_run(c_nodes, a, b,
        {"union": 0, "difference": 1, "intersection": 2,"fillet":3}[case["operation"]],
        case.get("fillet",{}).get("radius",0), {"all":0,"vertical":1,"top":2,"one_vertical":3,"root":4}[case.get("fillet",{}).get("selector","all")],
        probe_coords, len(probes), point_tolerance, accuracy, case.get("model_tolerance") or 0, (mesh_path or "").encode(), states, C.byref(result), err, len(err))
    errors = err.value.decode("utf-8", "replace").splitlines()
    if code:
        stage = "unknown"
        for candidate in ("initialization", "construct_inputs", "fillet_selection", "fillet", "boolean"):
            if f"stage={candidate}:" in err.value.decode("utf-8", "replace"):
                stage = candidate
        raise KernelOperationError(f"operation failed; result_constructed={bool(result.result_constructed)}; " + "; ".join(errors),
            stage, {"selected_edges_count":result.selected_edges_count,"before_volume":_finite(result.before_volume),
                    "before_area":_finite(result.before_area),
                    **{k:None if getattr(result,k)<0 else bool(getattr(result,k)) for k in ("input_a_valid","input_b_valid","input_a_manifold","input_b_manifold","input_a_valid_before_tolerance","input_b_valid_before_tolerance")},"mesh_path":mesh_path,"result_constructed":bool(result.result_constructed)})
    empty = bool(result.empty)
    centroid = [_finite(x) for x in result.centroid]
    bounds = [_finite(x) for x in result.bbox]
    valid = (None if result.valid < 0 or (not empty and result.manifold < 0)
             else bool(result.valid) and (empty or bool(result.manifold)))
    return {
        "input_a_valid": None if result.input_a_valid<0 else bool(result.input_a_valid),
        "input_b_valid": None if result.input_b_valid<0 else bool(result.input_b_valid),
        "input_a_manifold": None if result.input_a_manifold<0 else bool(result.input_a_manifold),
        "input_b_manifold": None if result.input_b_manifold<0 else bool(result.input_b_manifold),
        "input_a_valid_before_tolerance": None if result.input_a_valid_before_tolerance<0 else bool(result.input_a_valid_before_tolerance),
        "input_b_valid_before_tolerance": None if result.input_b_valid_before_tolerance<0 else bool(result.input_b_valid_before_tolerance),
        "before_volume": _finite(result.before_volume), "before_area": _finite(result.before_area),
        "selected_edges_count": result.selected_edges_count if case["operation"]=="fillet" else None,
        "mesh_path": mesh_path, "mesh_status": json.loads(Path(mesh_path).read_text())["mesh_status"] if mesh_path else "not_requested",
        "volume": _finite(result.volume), "area": _finite(result.area),
        "centroid": None if empty or None in centroid else centroid,
        "bbox": None if empty or None in bounds else [bounds[:3], bounds[3:]],
        "solid_count": None if result.solids < 0 else result.solids,
        "void_count": None if result.voids < 0 else result.voids,
        "face_count": result.faces, "edge_count": result.edges, "vertex_count": result.vertices,
        "native_valid": valid, "assert_valid": None if result.valid < 0 else bool(result.valid),
        "is_manifold": None if empty or result.manifold < 0 else bool(result.manifold),
        "empty": empty, "operation_ms": result.operation_ms,
        "result_constructed": bool(result.result_constructed), "measurement_errors": errors,
        "point_states": [{-1: "unknown", 0: "outside", 1: "inside", 2: "boundary"}[v] for v in states],
        "input_max_tolerance": max(result.input_max_vertex_tol, result.input_max_edge_tol),
        "result_max_tolerance": max(result.result_max_vertex_tol, result.result_max_edge_tol),
        "tolerances": {"requested_model_tolerance": case.get("model_tolerance"), "configured_zone_tolerance": result.configured_zone_tolerance, "model_size_estimate": result.model_size_estimate, "default_zone_tolerance": result.default_zone_tolerance,
            "input_max_vertex": result.input_max_vertex_tol, "input_max_edge": result.input_max_edge_tol,
            "result_max_vertex": result.result_max_vertex_tol, "result_max_edge": result.result_max_edge_tol,
            "point_classification": point_tolerance, "measurement_relative_accuracy": accuracy, "measurement_achieved_accuracy": None},
        "metadata": {"engine": "SMLib", "version": "10.0.0", "usd_brep_version": "1.0.0",
            "source": "https://github.com/NVIDIA-Omniverse/usd-brep", "commit": SOURCE_COMMIT,
            "binding": "custom ctypes C ABI to official SM_API; not official SmPyLib wheel",
            "properties": "official SmBrep::ComputePreciseProperties core integration at requested relative accuracy, no SM_API 1e-4 area/centroid clamp",
            "native_valid_check": "AssertValid(SM_LEVEL_2, SM_WALK) and IsManifoldSolid for nonempty",
            "empty_check": "no material/bounded void regions or faces/edges/vertices",
            "input_ownership": "fresh native primitives for each invocation; native boolean consumes inputs",
            "tolerance_configuration": "SM_USE_OLDTOL: public SmTol::SetModelSizeEstimate before context/primitives, then public SetTolerance(tol,FALSE,FALSE) on fresh input Brep/faces/edges/vertices before boolean; result tolerance never overwritten; reads effective edge/vertex tolerances; no solver edits; classification separate",
            "heal": False, "build": "portable consumer; SDK and compiler identity in binary-provenance.json"}}
