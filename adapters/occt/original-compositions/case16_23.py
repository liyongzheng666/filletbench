#!/usr/bin/env python3
"""Re-execute recorded original compositions, without substituting ordinary jobs.

Input BREP bytes must match the original source hashes. The recipes preserve the
original chosen demonstration parameters; no source-feature certification is
implied. Use cadquery-ocp 7.9.3.1.1. All paths are CLI inputs or repository relative.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import sys
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "special"))
import geometry as g
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Common, BRepAlgoAPI_Fuse
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeVertex
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeRevol
from OCP.GC import GC_MakeArcOfCircle
from OCP.GeomAbs import GeomAbs_Torus, GeomAbs_Cylinder, GeomAbs_Plane
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Pnt, gp_Dir, gp_Ax1

SOURCES = {
    16: ("73-34_combine_limits-1305.brep", "6bc86bc6493cac781d0ecba194e4de4a1eda367e1bfee96fc0ad513fc33e3fdc", "case16-limits", "case16_limits.py"),
    20: ("73-39_patch-1309.brep", "3905f4d7c2bc1e1fa05b54088fee54d1e9be55a999dab71eb488773950a2b7bd", "case20-patch", "case20_patch.py"),
    21: ("73-40_under_topol-1310.brep", "cfe248e5375706097e823041f28ae9b4935597cd2966b62b42ba4a293f6748fe", "case21-unders", "case21_unders.py"),
    23: ("73-42_43_overlap-1316.brep", "3f3ec1986be71db79acd9d751ea62a37f53e907e9bf4e53deea118f99db774b1", "case23-overlap", "case23_overlap.py"),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def unary(s):
    cs = g.children(s)
    return cs[0] if len(cs) == 1 else s


def clean(s):
    # Exact counterpart to the recorded FreeCAD removeSplitter calls.
    u = ShapeUpgrade_UnifySameDomain(s, True, True, False)
    u.Build()
    return u.Shape()


def operation(cls, a, b, refine=False):
    op = cls(a, b)
    op.Build()
    if not op.IsDone():
        raise RuntimeError(cls.__name__ + " failed")
    return clean(op.Shape()) if refine else op.Shape()


def cut(a, b, refine=False): return operation(BRepAlgoAPI_Cut, a, b, refine)
def common(a, b, refine=False): return operation(BRepAlgoAPI_Common, a, b, refine)
def fuse(a, b, refine=False): return operation(BRepAlgoAPI_Fuse, a, b, refine)
def box(x, y, z, origin=(0, 0, 0)): return BRepPrimAPI_MakeBox(gp_Pnt(*origin), x, y, z).Shape()


def fillet(shape, radius, selected):
    op = BRepFilletAPI_MakeFillet(shape)
    for e in selected:
        op.Add(radius, TopoDS.Edge_s(e))
    op.Build()
    if not op.IsDone():
        raise RuntimeError("BRepFilletAPI_MakeFillet failed at exact recorded radius")
    s = op.Shape()
    if not g.stats(s)["valid"]:
        raise RuntimeError("Exact recorded fillet returned invalid geometry")
    return s


def edges(shape): return g.shapes(shape, TopAbs_EDGE)
def selected(shape, indices): return [edges(shape)[i - 1] for i in indices]
def point_distance(shape, p):
    d = BRepExtrema_DistShapeShape(shape, BRepBuilderAPI_MakeVertex(gp_Pnt(*p)).Shape())
    d.Perform()
    if not d.IsDone(): raise RuntimeError("distance query failed")
    return d.Value()


def delta(a, b):
    return {"a_minus_b_mm3": volume(cut(a, b)), "b_minus_a_mm3": volume(cut(b, a))}


def volume(s):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    properties = GProp_GProps()
    BRepGProp.VolumeProperties_s(s, properties, OnlyClosed=True)
    return properties.Mass()


def compare_sampled(a, b):
    # Surface points from native tessellation would include interior vertices;
    # edge sampling independently compares every trim curve in both directions.
    result = []
    for source, target in [(a, b), (b, a)]:
        distances = [point_distance(target, p) for e in edges(source) for p in g.edge_polyline(e, 17)]
        result.append(max(distances, default=0.))
    sa, sb = g.stats(a), g.stats(b)
    return dict(method="17 exact curve samples per edge in both directions, distance to the other BREP; area and volume separately",
                maximum_trim_samples_to_shape_mm=result, area_difference_mm2=abs(sa["area_mm2"] - sb["area_mm2"]),
                volume_difference_mm3=abs(sa["volume_mm3"] - sb["volume_mm3"]),
                geometry_equivalent_at_sample_tolerance=max(result) < 1e-5 and abs(sa["volume_mm3"] - sb["volume_mm3"]) < 1e-5)


class Run:
    def __init__(self, number, args):
        self.number, self.args = number, args
        filename, expected, dirname, scriptname = SOURCES[number]
        self.out = args.out / ("case%02d" % number)
        self.out.mkdir(parents=True, exist_ok=True)
        corpus = json.loads((ROOT / "data/original-occ/cases" / ("%02d.json" % number)).read_text())
        sourcefile = args.source_root / filename if args.source_root else ROOT / corpus["source_brep"]
        if sha(sourcefile) != expected:
            raise ValueError("Original source SHA mismatch: " + filename)
        self.source = unary(g.read(sourcefile))
        original_script = args.original_root / dirname / "code" / scriptname if args.original_root else None
        self.history = {v["id"]: dict(brep=str(ROOT/v["historical_results"][0]["brep"])) for v in corpus["variants"] if v.get("historical_results")}
        script_provenance = next((v["script_provenance"] for v in corpus["variants"] if v.get("script_provenance")), {})
        if args.original_root:
            s = json.loads((args.original_root / dirname / "summary.json").read_text())
            self.history.update({q["id"]: q for q in s.get("cases", []) + s.get("smoothing_attempts", []) + s.get("native_controls", [])})
        self.report = dict(schema_version=1, case_number=number, created_at=datetime.now(timezone.utc).isoformat(),
            source_filename=filename, source_sha256=expected, adapter_sha256=sha(__file__),
            geometry_helper_sha256=sha(HERE.parent / "special" / "geometry.py"),
            original_script_filename=scriptname, original_script_sha256=sha(original_script) if original_script else next((h["expected_sha256"] for h in script_provenance.get("recorded_hashes", []) if h.get("found")),None),
            original_script_provenance=script_provenance,
            original_runtime={"FreeCAD": "1.2.0 local debug", "OCCT": "7.8.1"},
            runtime={"binding": "cadquery-ocp", "binding_version": version("cadquery-ocp"), "OCCT": "7.9.3"},
            dependency_gap="Ported FreeCAD Part operations to OCP; exact input bytes, parameters and recipe preserved; kernel 7.8.1 to 7.9.3 differs.",
            source_feature_certified=False, native_special_feature_api_used=False,
            provenance_kind="fresh_recipe_execution", trials=[])
        write(self.out / "summary.json", self.report)

    def trial(self, tid, recipe, parameters, build, selected_edges=(), control=False, before_shape=None):
        out = self.out / tid
        out.mkdir(exist_ok=True)
        # Each requested execution has its own output root; a failed build must
        # never be represented by a leftover successful result.
        if any(out.iterdir()): raise ValueError("Nonempty trial output; choose a fresh --out")
        row = dict(id=tid, method_kind="ordinary_native_control" if control else "explicit_occ_composition",
                   provenance_kind="fresh_recipe_execution", source_feature_certified=False,
                   native_special_feature_api_used=False, parameters=parameters, processing_steps=recipe,
                   outcome="started", api_success=False,
                   artifacts={"before_brep":"before.brep", "before_mesh":"before.mesh.json"})
        self.report["trials"].append(row)
        before = self.source if before_shape is None else before_shape
        row["before"] = g.save(before, out, "before", selected_edges)
        row["selection"] = [{"polyline_mm":g.edge_polyline(e,17),"index_1based":next((i for i,x in enumerate(edges(before),1) if e.IsSame(x)),None)} for e in selected_edges]
        try:
            shape, audit = build(out)
            row["api_success"] = True
            row["result"] = g.save(shape, out, "result")
            row["artifacts"].update(result_brep="result.brep", result_mesh="result.mesh.json")
            row["verification"] = audit
            row["verification"]["valid_and_single_solid"] = row["result"]["stats"]["valid"] and row["result"]["stats"]["solids"] == 1
            hist = self.history.get(tid)
            if hist and hist.get("brep"):
                hp = Path(hist["brep"])
                if not hp.exists():
                    # Rebase recorded machine paths to an explicitly provided
                    # artifact directory, preserving only the final run path.
                    hp = self.args.original_root / SOURCES[self.number][2] / "runs" / hp.parent.name / hp.name
                if hp.exists():
                    row["historical_comparison"] = compare_sampled(shape, unary(g.read(hp)))
                    row["historical_comparison"].update(reference_sha256=sha(hp), reference_filename=hp.name)
                else: row["historical_comparison"] = {"status":"unavailable", "historical_snapshot_not_fresh":True}
            row["outcome"] = "success" if row["verification"]["valid_and_single_solid"] and row["result"]["mesh"]["status"] == "ok" else "geometry_verification_failed"
        except Exception as e:
            row.update(outcome="failed", error_type=type(e).__name__, error=str(e), traceback=traceback.format_exc().replace(str(ROOT),"<repo>"))
        write(out / "summary.json", row)
        write(self.out / "summary.json", self.report)
        return row


def case16(run):
    s, r, a, b, c, length = run.source, 6., 6., 14., 3., 35.
    axes = {}
    for e in edges(s):
        ps = g.edge_polyline(e, 2)
        if any(math.dist(p, [35, 0, 35]) < 1e-7 for p in ps):
            other = next(p for p in ps if math.dist(p, [35, 0, 35]) > 1e-7)
            axis = max(range(3), key=lambda j: abs(other[j] - [35, 0, 35][j]))
            axes["xyz"[axis]] = e
    assert set(axes) == set("xyz")
    tools = {axis: cut(s, fillet(s, r, [e])) for axis, e in axes.items()}
    for tid, edge_stop in [("vertex_only", None), ("case1", b), ("case2", c)]:
        stops = {"x": a, "y": a, "z": a if edge_stop is None else max(a, edge_stop)}
        def build(out, stops=stops):
            current = s
            for axis in "xyz":
                stop, q = stops[axis], 1.
                clip = box(length-stop+q,length+2*q,length+2*q,(-q,-q,-q)) if axis=="x" else box(length+2*q,length-stop+q,length+2*q,(-q,stop,-q)) if axis=="y" else box(length+2*q,length+2*q,length-stop+q,(-q,-q,-q))
                tool = common(tools[axis], clip)
                g.save(tool, out, "removal-"+axis)
                current = cut(current, tool)
            result = clean(current)
            analytic = length**3-r*r*(1-math.pi/4)*sum(length-t for t in stops.values())
            error = abs(g.stats(result)["volume_mm3"]-analytic)
            if error > 1e-5: raise ValueError("Analytic stopped-cylinder volume disagrees")
            return result, dict(analytic_volume_mm3=analytic, analytic_volume_error_mm3=error,
                original_vertex_distance_mm=point_distance(result,[35,0,35]),
                original_vertical_edge_distances_mm={str(t):point_distance(result,[35,0,35-t]) for t in [1,3,5,9,13,16,20,30]})
        run.trial(tid, ["Native R6 single-edge fillet on each of the three selected cube edges", "Subtract each native result from source to construct removal tools", "Intersect each tool with the recorded stop half box", "Sequentially subtract the three clipped tools from the same source and unify same-domain faces"],
            dict(radius_mm=r, cube_edge_mm=length, vertex=[35,0,35], vertex_stop_A_mm=a, edge_stop_requested_mm=edge_stop, effective_stops_mm=stops), build, list(axes.values()))


def case20(run):
    s = run.source
    side_edges, full_edges = selected(s,[7,10]), selected(s,[7,10,16,17,18,19,20])
    side, full = fillet(s,1.,side_edges), fillet(s,1.,full_edges)
    no = clean(cut(s, clean(cut(s,side))))
    bridge = clean(cut(no,full))
    yes = clean(cut(no,bridge))
    for tid, result, reference in [("patch-no",no,side),("patch-yes",yes,full)]:
        def build(out, result=result, reference=reference):
            g.save(side,out,"fresh-native-side-reference")
            g.save(full,out,"fresh-native-full-front-reference")
            g.save(bridge,out,"proposed-bridge-removal")
            return result, dict(versus_fresh_native_reference=delta(result,reference),
                bridge_volume_mm3=g.stats(bridge)["volume_mm3"], independent_patch_algorithm=False,
                original_limit_entities_recovered=False,
                limits="Original demonstration borrows the full-front native R1 surfaces; it does not execute a native patch option.")
        run.trial(tid,["Fresh native R1 fillets on side edges [7,10] and full-front chain [7,10,16,17,18,19,20]", "No = source minus side-removal tool", "Bridge = No minus full-front reference", "Yes = No minus bridge"],
            dict(radius_mm=1., side_edges_1based=[7,10],full_front_edges_1based=[7,10,16,17,18,19,20],patch=tid=="patch-yes"),build,side_edges)
    for r in [1.,2.]:
        def control(out,r=r):
            return fillet(s,r,full_edges),dict(exact_recorded_edge_chain=True,native_patch_switch_used=False)
        run.trial("native-full-front-chain-r"+str(int(r)),["Native fillet on the exact recorded full-front chain"],
            dict(radius_mm=r,full_front_edges_1based=[7,10,16,17,18,19,20]),control,full_edges,control=True)


def case21(run):
    s=run.source
    roots=[e for e in edges(s) if all(abs(p[2]-30)<1e-7 and (abs(p[0])<1e-7 or abs(p[0]-32)<1e-7) for p in g.edge_polyline(e,3)) and abs(math.dist(*g.edge_polyline(e,2))-42)<1e-7]
    assert len(roots)==2
    def features(result,r):
        caps=[]; torus=0; vertical=0
        for f in g.shapes(result,TopAbs_FACE):
            surface=BRepAdaptor_Surface(TopoDS.Face_s(f)); st=g.stats(f);bb=st["bbox_mm"]
            if surface.GetType()==GeomAbs_Plane and abs(bb[1]-18)<1e-6 and abs(bb[4]-18)<1e-6 and bb[5]>30-r-1e-6:
                caps.append(st["area_mm2"])
            if surface.GetType()==GeomAbs_Torus: torus+=1
            if surface.GetType()==GeomAbs_Cylinder and abs(surface.Cylinder().Radius()-r)<1e-6 and abs(surface.Cylinder().Axis().Direction().Z())>.99:vertical+=1
        return dict(stop_cap_areas_mm2=caps,nose_torus_count=torus,front_vertical_extra_count=vertical)
    for r in [4.,2.]:
        native=fillet(s,r,roots)
        run.trial("native-free-r"+str(int(r)),["Native free-propagating fillet on both original flat-top side edges"],
            dict(radius_mm=r,topology_filter_supplied=False),lambda out,native=native,r=r:(native,features(native,r)),roots,control=True)
        removed=clean(cut(s,native))
        tools=[clean(common(removed,box(17,62,32,(-1,-1,-1)))),clean(common(removed,box(17,62,32,(16,-1,-1))))]
        modes=["both-stop","right-stop-left-continue"] if r==4. else ["right-stop-left-continue"]
        for mode in modes:
            tid=mode+"-r"+str(int(r))
            def build(out,r=r,native=native,tools=tools,mode=mode):
                g.save(native,out,"fresh-native-free-reference")
                current=s;keep=box(34,43,32,(-1,18,-1))
                for side,tool in zip(["left","right"],tools):
                    chosen=clean(common(tool,keep)) if mode=="both-stop" or side=="right" else tool
                    g.save(chosen,out,side+"-removal")
                    current=cut(current,chosen)
                result=clean(current); audit=features(result,r)
                expected=2 if mode=="both-stop" else 1
                if len(audit["stop_cap_areas_mm2"])!=expected or any(abs(x-r*r*(1-math.pi/4))>1e-6 for x in audit["stop_cap_areas_mm2"]):raise ValueError("Actual stop caps do not match recorded analytic caps")
                audit.update(expected_stop_cap_count=expected, rear_region_vs_fresh_native=delta(common(result,keep),common(native,keep)),input_added_material_mm3=volume(cut(result,s)))
                return result,audit
            run.trial(tid,["Fresh native free-propagating fillet on the two flat-top side edges", "Source minus native result gives removal tools; split at x16 into left/right", "Declared side association explicitly clips chosen tools at tangent topology y18", "Subtract selected tools from the same source and unify"],
                dict(radius_mm=r,mode=mode,limit_y_mm=18.,side_associations="declared keys, not native unders encoding",front_vertical_extra_is_source_uncertain=True),build,roots)


def ring(x,r):
    a,z=5.5,18.;p,q,t=gp_Pnt(a,0,z),gp_Pnt(a+r,0,z),gp_Pnt(a,0,z+r)
    middle=gp_Pnt(a+r-r/math.sqrt(2),0,z+r-r/math.sqrt(2))
    wire=BRepBuilderAPI_MakeWire()
    wire.Add(BRepBuilderAPI_MakeEdge(p,q).Edge())
    wire.Add(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(q,middle,t).Value()).Edge())
    wire.Add(BRepBuilderAPI_MakeEdge(t,p).Edge())
    face=BRepBuilderAPI_MakeFace(wire.Wire()).Face()
    shape=BRepPrimAPI_MakeRevol(face,gp_Ax1(gp_Pnt(0,0,0),gp_Dir(0,0,1)),2*math.pi,True).Shape()
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf,gp_Vec
    tr=gp_Trsf();tr.SetTranslation(gp_Vec(x,0,0))
    return BRepBuilderAPI_Transform(shape,tr,True).Shape()


def case23(run):
    s=run.source
    for r in [2.,2.5]:
        tid="notch-r"+str(r).replace(".0","").replace(".","p")
        left,right=ring(3,r),ring(16,r)
        result=clean(fuse(fuse(s,left),right))
        seam=[]
        for e in edges(result):
            owners=[TopoDS.Face_s(f) for f in g.shapes(result,TopAbs_FACE) if any(e.IsSame(x) for x in edges(f))]
            if len(owners)!=2:continue
            ss=[BRepAdaptor_Surface(f) for f in owners]
            if all(t.GetType()==GeomAbs_Torus and abs(t.Torus().MinorRadius()-r)<1e-6 and abs(t.Torus().MajorRadius()-5.5-r)<1e-6 for t in ss) and abs(ss[0].Torus().Location().X()-ss[1].Torus().Location().X())>1:seam.append(e)
        def build(out,left=left,right=right,result=result,r=r):
            g.save(left,out,"left-root-addition");g.save(right,out,"right-root-addition")
            overlap=common(left,right,True)
            g.save(overlap,out,"actual-overlap-diagnostic")
            return result,dict(actual_overlap_mm3=g.stats(overlap)["volume_mm3"],added_volume_mm3=g.stats(result)["volume_mm3"]-g.stats(s)["volume_mm3"],
                footprint_overlap_width_mm=2*(5.5+r)-13,midline_notch_height_mm=18+r-math.sqrt(r*r-(r-1)**2),
                midline_expected_normal_jump_degrees=2*math.degrees(math.asin((r-1)/r)),actual_intersection_seam_count=len(seam))
        run.trial(tid,["Revolve exact quarter-circle root-addition profile around each recorded boss axis", "Fuse both additions to the original capsule and unify", "Measure actual common of additions independently"],dict(root_radius_mm=r,boss_radius_mm=5.5,centers_x_mm=[3.,16.],plate_top_mm=18.),build,selected(s,[17,18]))
        for smooth_r in [.25,.5,1.]:
            sid=tid+"-secondary-r"+str(smooth_r).replace(".","p")
            def smooth(out,result=result,seam=seam,smooth_r=smooth_r,r=r):
                if not seam:raise RuntimeError("No actual root intersection seam")
                smoothed=fillet(result,smooth_r,seam)
                return smoothed,dict(root_radius_mm=r,secondary_radius_mm=smooth_r,selected_actual_intersection_seam_count=len(seam),continuity_status="not independently certified")
            run.trial(sid,["Rebuild exact original overlapping root-addition union", "Native secondary fillet on actual intersection seams at the recorded radius"],dict(root_radius_mm=r,secondary_radius_mm=smooth_r),smooth,seam,before_shape=result)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cases",nargs="+",type=int,default=[16,20,21,23],choices=SOURCES)
    p.add_argument("--source-root",type=Path,help="Optional exact original input BREP directory; default frozen repository corpus")
    p.add_argument("--original-root",type=Path,help="Original diagnostics directory, only for script hashes and historical comparisons")
    p.add_argument("--out",type=Path,required=True,help="Fresh output root; never reuse a completed run")
    args=p.parse_args()
    if version("cadquery-ocp")!="7.9.3.1.1":raise RuntimeError("cadquery-ocp 7.9.3.1.1 required")
    for number in args.cases:
        run=Run(number,args)
        try:globals()["case"+str(number)](run)
        except Exception as e:run.report.update(outcome="failed",error=str(e),traceback=traceback.format_exc())
        run.report["finished_at"]=datetime.now(timezone.utc).isoformat()
        run.report["outcome"]="complete" if run.report["trials"] and all(q["outcome"]=="success" for q in run.report["trials"]) else "partial_or_failed"
        write(run.out/"summary.json",run.report)
        print(json.dumps(dict(case=number,outcome=run.report["outcome"],trials=[(q["id"],q["outcome"]) for q in run.report["trials"]])),flush=True)


if __name__=="__main__":main()
