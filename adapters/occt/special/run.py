#!/usr/bin/env python3
"""Explicit derivative protocols; never counted as the paired ordinary jobs."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import version

ROOT = Path(__file__).resolve().parents[3]
PIN = "7.9.3.1.1"
CASES = (27, 28, 30, 35, 36)


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)+"\n")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def worker(number, out):
    from geometry import (read, children, compound, face, sew, save, stats,
                          shared_edges, shapes, contact_audit, xyz, edge_polyline,
                          TopAbs_EDGE, g2_profile_audit)
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Common
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.Geom import Geom_BezierSurface
    from OCP.GeomAbs import GeomAbs_C2, GeomAbs_BezierSurface, GeomAbs_BSplineSurface
    from OCP.TColgp import TColgp_Array2OfPnt
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Pnt
    binding = version("cadquery-ocp")
    if binding != PIN:
        raise ValueError("Pinned cadquery-ocp required")
    source_file = ROOT / f"data/models/{number:02d}.brep"
    source, source_hash = read(source_file), sha(source_file)
    parts = children(source)
    report = dict(schema_version=1, case_number=number, engine="OCCT", engine_version="7.9.3",
        binding_version=binding, source_brep=f"data/models/{number:02d}.brep", source_sha256=source_hash,
        adapter_sha256=sha(__file__), geometry_helpers_sha256=sha(Path(__file__).with_name("geometry.py")),
        created_at=datetime.now(timezone.utc).isoformat(), trials=[], special_feature_certified=False,
        scope="Explicit derivative/composition demonstrations; separate from unchanged 104 ordinary paired jobs",
        native_face_face_protocol_gap=True,
        gap="This driver does not encode native master-face, propagation, left/right-sense, four-mode trim or numeric softness laws through BRepFilletAPI_MakeFillet.")
    write(out/"summary.json", report)

    def trial(tid, before, radius, description, selected=None, composite=None, internal_c2=False, params=None):
        directory = out/tid
        directory.mkdir(exist_ok=True)
        for name in ("source.brep","before.brep","result.brep","source.mesh.json","before.mesh.json","result.mesh.json"):
            (directory/name).unlink(missing_ok=True)
        row = dict(schema_version=1, job_id=f"{number:02d}.special.{tid}", case_number=number,
            engine="OCCT", engine_version="7.9.3", binding_version=binding,
            protocol_id=f"occt-derived-{number:02d}-{tid}-v1", method_kind="explicit_occ_composition" if composite else "derived_input_native_edge_fillet",
            source_brep=f"data/models/{number:02d}.brep", source_sha256=source_hash,
            adapter_sha256=report["adapter_sha256"], description=description,
            radius_mm=radius, parameters=params or {}, source_feature_certified=False,
            source_part_indices=[2,3] if (number==27 and tid.startswith("boss")) or (number==30 and tid.startswith("multi")) else [0,1],
            comparison_protocol_matches_ordinary=False, outcome="started", api_success=False,
            native_call_executed=False, valid=None, result_stats=None, reason=None,
            artifacts={"source_mesh":"source.mesh.json", "before_mesh":"before.mesh.json", "before_brep":"before.brep"})
        request={key:row[key] for key in ("protocol_id","source_sha256","source_part_indices","radius_mm","parameters","method_kind","description","adapter_sha256")}
        request["geometry_helpers_sha256"]=report["geometry_helpers_sha256"]
        row["request_sha256"]=hashlib.sha256(json.dumps(request,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
        row["request_fingerprint_format"]="SHA256 of canonical sorted-key compact UTF-8 JSON of protocol, source, parts, radius, parameters, method, description and adapter/helper hashes"
        row["source"] = save(source, directory, "source")
        selected = selected if selected is not None else shared_edges(before, lambda ps:all(abs(p[1])<1e-6 and abs(p[2])<1e-6 for p in ps))
        row["before"] = save(before, directory, "before", selected)
        row["input_stats"] = row["before"]["stats"]
        row["selection"] = [{"method":"shared native edge with two distinct adjacent faces and world-space seam predicate", "samples_mm":edge_polyline(e,9)} for e in selected]
        write(directory/"summary.json",row)
        try:
            if composite:
                result, audit_extra = composite()
                row["construction_executed"] = True
                row.update(audit_extra)
                row["api_success"] = True
            else:
                if not selected:
                    raise ValueError("No eligible world-space shared edge")
                fillet = BRepFilletAPI_MakeFillet(before)
                if internal_c2:
                    fillet.SetContinuity(GeomAbs_C2, 1e-4)
                for e in selected:
                    fillet.Add(radius,e)
                row["api_result"] = {"contours":fillet.NbContours(), "internal_C2_requested":internal_c2, "softness_parameter_used":False}
                row["native_call_executed"] = True
                write(directory/"summary.json",row)
                fillet.Build()
                row["api_success"] = bool(fillet.IsDone())
                if not fillet.IsDone():
                    row.update(outcome="native_rejected",reason="BRepFilletAPI_MakeFillet.IsDone() is false")
                    write(directory/"summary.json",row)
                    report["trials"].append(row)
                    write(out/"summary.json",report)
                    return
                result=fillet.Shape()
            row["result"] = save(result,directory,"result")
            row["result_stats"] = row["result"]["stats"]
            row["valid"] = row["result_stats"]["valid"]
            row["artifacts"].update(result_mesh="result.mesh.json",result_brep="result.brep")
            if number==35:
                readback=read(directory/"result.brep")
                row["contact_validation"] = contact_audit(readback)
                if composite:
                    row["profile_validation"] = g2_profile_audit(readback,row["parameters"]["proxy_alpha"])
            row["outcome"] = "ok" if row["valid"] else "invalid_result"
        except Exception as error:
            row.update(outcome="exception",reason=f"{type(error).__name__}: {str(error).replace(str(ROOT),'<repo>')}")
        write(directory/"summary.json",row)
        report["trials"].append(row)
        write(out/"summary.json",report)

    if number in (27,30):
        groups = [("walls",parts[:2])] if number==27 else [("single-row",parts[:2]),("multi-row",parts[2:4])]
        for label, items in groups:
            op=sew([f for item in items for f in shapes(item,TopAbs_FACE)])
            for r in (4.,8.):
                trial(f"{label}-r{r:g}",op,r,"Sew original finite support faces, preserving partition edges; no thickness or extension. No master/propagation protocol is claimed.")
        if number==27:
            boss,floor=parts[2:4]
            skin=[f for f in shapes(boss,TopAbs_FACE) if not all(abs(p[2])<1e-7 for e in shapes(f,TopAbs_EDGE) for p in edge_polyline(e,2))]
            cut=BRepAlgoAPI_Cut(floor,boss)
            if not cut.IsDone():raise ValueError("Floor footprint cut failed")
            op=sew(skin+shapes(cut.Shape(),TopAbs_FACE))
            for r in (2.,4.):
                trial(f"boss-skin-r{r:g}",op,r,"Explicit derivative: remove boss bottom cap and floor footprint; sew an open skin and fillet four root edges. Original boss solid is not preserved or scored.",selected=shared_edges(op,lambda ps:all(abs(p[2])<1e-6 for p in ps)))
    elif number==28:
        a,b=parts[:2]
        for ys,zs in ((1,1),(1,-1),(-1,1),(-1,-1)):
            va=BRepAlgoAPI_Common(a,BRepPrimAPI_MakeBox(gp_Pnt(-15,-1,0 if zs>0 else -14),30,2,14).Shape()).Shape()
            hb=BRepAlgoAPI_Common(b,BRepPrimAPI_MakeBox(gp_Pnt(-15,0 if ys>0 else -14,-1),30,14,2).Shape()).Shape()
            op=sew(shapes(va,TopAbs_FACE)+shapes(hb,TopAbs_FACE))
            trial(f"quadrant-y{ys:+d}-z{zs:+d}-r4",op,4.,"Explicit finite-domain clipping to one geometric quadrant, followed by sewing and ordinary edge fillet. Four geometric quadrant derivatives are not native left/right-sense calls.",params={"y_sign":ys,"z_sign":zs})
    elif number==36:
        op=sew([face([(-7,0,0),(7,0,0),(7,0,25),(-7,0,25)]),face([(-7,0,0),(7,0,0),(7,23,0),(-7,23,0)])])
        for r in (4.,8.):
            trial(f"extended-common-band-r{r:g}",op,r,"Explicit derivative: extend both original support planes to their theoretical line and crop the floor to the common 14mm band. Finite domains changed; original four trim modes remain a protocol gap.")
    elif number==35:
        op=sew([f for part in parts[:2] for f in shapes(part,TopAbs_FACE)])
        for c2 in (False,True):
            trial("internal-c2-r13" if c2 else "native-circle-r13",op,13.,"Original finite walls sewn without extension. Native circular R13 control; internal C2 is separately requested and does not assert G2-to-support.",internal_c2=c2)
        for label,alpha in (("0p1",.03),("1p0",.30),("10p0",.49)):
            def build(alpha=alpha):
                d,w,H,D=13.,20.,18.,17.
                h,q=alpha*d,d-2*alpha*d
                yz=[(0,d),(0,d-h)]+[(q*k/5,q*(1-k/5)) for k in range(6)]+[(d-h,0),(d,0)]
                poles=TColgp_Array2OfPnt(1,2,1,10)
                for i,x in enumerate((-w/2,w/2),1):
                    for j,(y,z) in enumerate(yz,1):poles.SetValue(i,j,gp_Pnt(x,y,z))
                surface=Geom_BezierSurface(poles)
                blend=BRepBuilderAPI_MakeFace(surface,1e-7).Face()
                wall=face([(-10,0,d),(-10,0,H),(10,0,H),(10,0,d)])
                floor=face([(-10,d,0),(10,d,0),(10,D,0),(-10,D,0)])
                result=sew([wall,blend,floor])
                # Audit actual readback surface separately below; retain analytic
                # controls only as an independently evaluable construction contract.
                profile=[xyz(surface.Value(.5,k/256)) for k in range(257)]
                return result,{"g2_proxy":{"degree":9,"alpha":alpha,"contact_distance_mm":d,
                    "control_points_yz":yz,"profile_257_points":profile,
                    "minimum_profile_step_mm":min(math.dist(a,b) for a,b in zip(profile,profile[1:])),
                    "sampled_monotone_y_increasing_z_decreasing":all(b[1]>=a[1]-1e-9 and b[2]<=a[2]+1e-9 for a,b in zip(profile,profile[1:])),
                    "numeric_softness_law_verified":False}}
            trial(f"g2-proxy-label-{label}",op,None,"Explicit degree-9 Bezier G2 sheet at fixed wall/floor contact distance d=13. Source softness labels are illustrative labels; alpha mapping is a local proxy, not a native softness API or numeric equivalence.",composite=build,params={"proxy_alpha":alpha,"source_softness_label":label})
    report["source_unchanged"] = sha(source_file)==source_hash
    report["complete"] = True
    write(out/"summary.json",report)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--case",type=int,choices=CASES)
    p.add_argument("--output",type=Path,default=Path("runs/fresh-occt-special"))
    p.add_argument("--timeout",type=float,default=120)
    p.add_argument("--worker",action="store_true",help=argparse.SUPPRESS)
    a=p.parse_args()
    if a.worker:
        a.output.mkdir(parents=True,exist_ok=True)
        worker(a.case,a.output.resolve())
        return
    a.output.mkdir(parents=True,exist_ok=True)
    records=[]
    for n in (a.case,) if a.case else CASES:
        destination=a.output if a.case else a.output/f"case{n:02d}"
        destination.mkdir(parents=True,exist_ok=True)
        process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),"--case",str(n),"--output",str(destination.resolve()),"--worker"],cwd=ROOT,start_new_session=(os.name=="posix"),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        timeout=False
        try:stdout,stderr=process.communicate(timeout=a.timeout)
        except subprocess.TimeoutExpired:
            timeout=True
            if os.name=="posix":os.killpg(process.pid,signal.SIGKILL)
            else:process.kill()
            stdout,stderr=process.communicate()
        (destination/"stdout.log").write_text(stdout.replace(str(ROOT),"<repo>"))
        (destination/"stderr.log").write_text(stderr.replace(str(ROOT),"<repo>"))
        status=dict(case_number=n,returncode=process.returncode,timed_out=timeout,summary=f"case{n:02d}/summary.json" if not a.case else "summary.json")
        records.append(status)
        print(json.dumps(status),flush=True)
    write(a.output/"process-index.json",dict(schema_version=1,records=records))


if __name__=="__main__":main()
