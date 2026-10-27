#!/usr/bin/env python3
"""Export existing special-protocol SMLib evidence without running a kernel.

Only JSON geometry and sanitized JSON measurements are exported. Source images,
PDFs, SDK binaries and private paths are never copied into the public tree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path


MEDIA_KEYS = {"image", "comparison", "before_image", "after_image", "focus",
              "image_sha256", "source_crop", "source_pdf", "reference_image"}
STATUS_LABELS = {
    "controlled_subchecks": "受控几何子判据通过",
    "candidate_unverified": "已有候选，特殊功能未证",
    "geometry_failed": "实际几何检查失败",
    "native_api_failed_with_candidate": "API失败，保留已有候选证据",
    "empty_or_failed": "API失败或无结果",
}


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sanitize(obj):
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items() if k not in MEDIA_KEYS}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    if not isinstance(obj, str):
        return obj
    # A complete path may contain spaces, so handle it before command fragments.
    if re.match(r"^/(?:Users|private|tmp|var|opt|Applications|Library)/", obj):
        return "history:" + Path(obj).name
    return re.sub(r"/(?:Users|private|tmp|var|opt|Applications|Library)/[^\s\"'<>;,\)\]]+",
                  lambda m: "history:" + Path(m.group(0)).name, obj)


def polylines(obj):
    if not obj:
        return []
    if isinstance(obj, dict):
        geom = obj.get("geometry", obj)
        items = geom.get("edge_samples", geom.get("edges", []))
    else:
        items = obj
    out = []
    if not isinstance(items, list):
        return out
    for edge in items:
        pts = edge.get("points", edge.get("samples", edge.get("polyline", []))) if isinstance(edge, dict) else edge
        if isinstance(pts, list) and len(pts) >= 2 and isinstance(pts[0], list):
            if all(len(p) >= 3 and all(isinstance(x, (int, float)) for x in p[:3]) for p in pts):
                out.append([p[:3] for p in pts])
    return out


def triples(items):
    if not items:
        return []
    return items if isinstance(items[0], list) else [items[i:i+3] for i in range(0, len(items), 3)]


def mesh_data(obj, edges=None):
    """Normalize native tessellation formats; never invent face membership."""
    if "faces" in obj and isinstance(obj["faces"], list):
        chunks = []
        for f in obj["faces"]:
            if isinstance(f, dict) and isinstance(f.get("mesh"), dict):
                chunk = mesh_data(f["mesh"])
                chunk["face_ids"] = [f.get("face_index")] * len(chunk["triangles"])
                chunks.append(chunk)
        out = combine(chunks)
    else:
        verts = triples(obj.get("vertices", obj.get("positions", [])))
        tris = triples(obj.get("triangles", obj.get("indices", [])))
        face_ids = obj.get("face_ids", obj.get("triangle_face_ids", []))
        out = {"vertices": verts, "triangles": tris,
               "face_ids": face_ids if len(face_ids) == len(tris) else [], "edges": []}
    out["edges"] = polylines(edges) or polylines(obj)
    return out


def combine(chunks):
    out = {"vertices": [], "triangles": [], "face_ids": [], "edges": []}
    complete_faces = all(len(c["face_ids"]) == len(c["triangles"]) for c in chunks)
    for c in chunks:
        offset = len(out["vertices"])
        out["vertices"].extend(c["vertices"])
        out["triangles"].extend([[i + offset for i in t] for t in c["triangles"]])
        if complete_faces:
            out["face_ids"].extend(c["face_ids"])
        out["edges"].extend(c["edges"])
    return out


class Exporter:
    def __init__(self, source_root, output, fresh_runs=None):
        self.source_root = source_root
        self.full = source_root / "outputs/manual-review/smlib-full"
        self.pilot = source_root / "outputs/manual-review/smlib-pilot"
        self.output = output
        self.fresh_runs = fresh_runs
        self.output.mkdir(parents=True, exist_ok=True)
        self.manifest = {}

    def source(self, path):
        path = Path(path)
        if not path.is_file():
            return None
        # Stable source identifiers retain case/run context but reveal no home path.
        try:
            key = "fresh:" + path.relative_to(self.fresh_runs).as_posix() if self.fresh_runs and path.is_relative_to(self.fresh_runs) else "history:" + path.relative_to(self.source_root).as_posix()
        except ValueError:
            key = "history:" + path.name
        self.manifest[key] = {"sha256": sha(path), "bytes": path.stat().st_size}
        return key

    def write(self, relative, obj):
        path = self.output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sanitize(obj), ensure_ascii=False, separators=(",", ":")) + "\n")
        return "data/supplemental/" + relative

    def json_copy(self, path, relative):
        if not Path(path).is_file():
            return None
        self.source(path)
        return self.write(relative, read(path))

    def mesh(self, path, relative, edges=None, field=None):
        if not path or not Path(path).is_file():
            return None
        self.source(path)
        obj = read(path)
        if field:
            obj = obj.get(field, {})
        edge_data = None
        if edges and Path(edges).is_file():
            self.source(edges)
            edge_data = read(edges)
        out = mesh_data(obj, edge_data)
        if not out["vertices"] or not out["triangles"]:
            return None
        return self.write(relative, out)

    def pair_input(self, directory, relative):
        chunks = []
        for side in ["left", "right"]:
            p = directory / f"input-{side}-mesh.json"
            if p.is_file():
                self.source(p)
                ep = directory / f"input-{side}-edges.json"
                ed = read(ep) if ep.is_file() else None
                self.source(ep)
                chunks.append(mesh_data(read(p), ed))
        return self.write(relative, combine(chunks)) if chunks else None

    def pilot_trial(self, number, variant):
        base = self.pilot / f"case{number:02d}"
        summary = base / ("notch-crossing/summary.json" if number == 8 else "summary.json")
        group = read(summary)
        key = variant["id"]
        selector = {
            "pilot-r14-crossing": "r14-crossing", "pilot-r12": "r12-control",
            "pilot-r13-contact": "r13-contact", "pilot-r18-crossing": "r18-crossing",
            "pilot-body-r8": "body", "pilot-plane-r8": "plane", "pilot-sheet-r8": "sheet",
            "pilot-r2p5": "both-r2p5", "pilot-r2": "both-r2",
            "pilot-native-controls": "circular-r6", "pilot-smlib-thumb1": "blend-g2-t1p0",
            "pilot-smlib-thumb01": "blend-g2-t0p1", "pilot-smlib-thumb10": "blend-g2-t10p0",
            "pilot-smlib-circle-r13": "circle-r13",
        }[key]
        trial = next(t for t in group["trials"] if t.get("id", t.get("mode", t.get("kind"))) == selector)
        if number == 23:
            directory = Path(group["run_dir"]) / selector
        else:
            directory = Path(trial.get("run_dir", trial.get("directory")))
        return summary, group, trial, directory

    def export_variant(self, row, variant):
        n = row["number"]
        vid = variant["id"]
        rel = f"case{n:02d}/{vid}"
        m = variant.get("metrics", {})
        pilot = vid.startswith("pilot-")
        extra = {}
        targets = []
        if pilot:
            summary_path, group, trial, directory = self.pilot_trial(n, variant)
            metrics = {"trial": trial, "report_metrics": m}
            self.json_copy(summary_path, f"case{n:02d}/source-summary.json")
            radius = trial.get("radius_mm", trial.get("call", {}).get("radius_mm", group.get("radius_mm")))
            if n == 8:
                radius = trial["radius_mm"]
                inspection = Path(trial["inspection"])
                mesh = self.mesh(Path(str(inspection) + ".mesh.json"), rel + "/result.json", inspection)
                before = self.mesh(directory / "input.json.mesh.json", rel + "/before.json", directory / "input.json")
                request = trial.get("call", {})
                self.json_copy(inspection, rel + "/native-inspection.json")
            elif n in [17, 18]:
                raw_mesh = directory / "ordinary-r8-mesh.json"
                mesh = self.mesh(raw_mesh, rel + "/result.json", field="result")
                before = self.mesh(raw_mesh, rel + "/before.json", field="a")
                request = trial.get("case", {}).get("fillet", {})
                cap = self.mesh(directory / "specified-cap-mesh.json", rel + "/specified-cap.json")
                if cap:
                    extra["constraints"] = [{"role": "specified_cap", "mesh": cap, "applied_to_native_call": False}]
            elif n == 23:
                mesh = self.mesh(directory / "after-mesh.json", rel + "/result.json", directory / "after-edges.json")
                before = self.mesh(directory / "before-mesh.json", rel + "/before.json", directory / "before-edges.json")
                request = read(directory / "request.json")
            elif n == 34:
                radius = 6
                mesh = self.mesh(directory / "result-mesh.json", rel + "/result.json", directory / "candidate-edges.json")
                before = self.mesh(directory / "input-mesh.json", rel + "/before.json", directory / "input-edges.json")
                request = read(directory / "request.json")
                vt = next(t for t in group["trials"] if t["mode"] == "variable-source-end-radii")
                vd = Path(vt["directory"])
                vm = self.mesh(vd / "result-mesh.json", rel + "/variable-result.json", vd / "candidate-edges.json")
                extra["additional_results"] = [{"label": "原生变半径控制；未传rho", "mesh": vm,
                                                 "request": read(vd / "request.json"), "source_trial": vt}]
            else:
                radius = trial["call"]["radius_mm"]
                mesh = self.mesh(directory / "result-mesh.json", rel + "/result.json")
                before = self.mesh(directory / "input-mesh.json", rel + "/before.json")
                request = trial["call"]
                if key_is_thumb10(vid):
                    diag = self.pilot / "case35/high10-self-intersection-diagnostic"
                    extra["self_intersection"] = {
                        "diagnostic": self.json_copy(diag / "diagnostic.json", rel + "/self-intersection.json"),
                        "actual_native_edge_samples": self.json_copy(diag / "actual-edge-4097.json", rel + "/actual-edge-4097.json"),
                        "quality": self.json_copy(self.pilot / "case35/shape-quality-supplement.json", rel + "/shape-quality.json"),
                    }
        else:
            directory = Path(m["directory"])
            metrics = m
            request = m.get("native_request", m.get("request", {}))
            radius = m.get("radius_mm", request.get("radius_mm", request.get("R_mm")))
            summary_path = next((self.full / x["href"] for x in variant["links"] if x["href"].endswith("summary.json")), None)
            if summary_path:
                self.json_copy(summary_path, f"case{n:02d}/source-summary.json")
            mesh = self.mesh(directory / "mesh.json", rel + "/result.json", directory / "native-edges.json")
            if (directory / "input-mesh.json").is_file():
                before = self.mesh(directory / "input-mesh.json", rel + "/before.json", directory / "input-edges.json")
            else:
                before = self.pair_input(directory, rel + "/before.json")
                extra["before_display"] = "两个真实输入对象的网格并列；仅合并显示缓冲区，未做布尔或缝合。"
            targets = [{"samples_mm": t["samples_mm"], "kind": "face_samples",
                        "label": t.get("part_label", "源有限面采样")}
                       for t in m.get("selection_world_samples", [])]
            if not targets and request.get("selected_fingerprint"):
                targets = [{"samples_mm": request["selected_fingerprint"], "kind": "edge_endpoints",
                            "label": "本协议实际目标棱端点"}]
        if not targets:
            # Native selection record is protocol-specific; do not borrow ordinary targets.
            select = directory / "selection.json"
            if select.is_file():
                extra["selection"] = self.json_copy(select, rel + "/selection.json")
                selection = read(select)
                if isinstance(selection, list):
                    targets = [{"samples_mm": [s["start"], s["end"]], "kind": "edge_endpoints",
                                "label": "本协议原生实际选中棱端点"}
                               for s in selection if isinstance(s, dict) and "start" in s and "end" in s]
            if n == 8:
                p = directory / "input.json"
                self.source(p)
                targets = [{"samples_mm": pts, "kind": "native_edge_samples", "label": "原生实际共用根棱"}
                           for pts in polylines(read(p))
                           if all(abs(q[1]) < 1e-6 and abs(q[2] - 40) < 1e-6 for q in pts)
                           and max(q[0] for q in pts) - min(q[0] for q in pts) > 99.99]
            elif n in [17, 18]:
                p = directory / "ordinary-r8-mesh.json-input-native.json"
                self.source(p)
                for edge in read(p).get("edges", []):
                    pts = edge.get("endpoints", [])
                    if len(pts) == 2 and all(abs(q[1]-29) < 1e-6 and abs(q[2]-12) < 1e-6 for q in pts) and abs(abs(pts[0][0]-pts[1][0])-70) < 1e-6:
                        targets.append({"samples_mm": pts, "kind": "native_edge_endpoints", "label": "原生root选择器实际棱端点"})
            elif n == 23:
                p = directory / "before-edges.json"
                self.source(p)
                for pts in polylines(read(p)):
                    if any(all(abs(q[2]-18) < 1e-5 and abs(math.hypot(q[0]-xc, q[1])-5.5) < 1e-5 for q in pts) for xc in [3, 16]):
                        targets.append({"samples_mm": pts, "kind": "native_edge_samples", "label": "原生实际输入根部圆棱"})
            elif n == 34:
                p = directory / "input-edges.json"
                self.source(p)
                targets = [{"samples_mm": e["points"], "kind": "native_edge_samples", "label": "本协议原生已选中目标棱"}
                           for e in read(p).get("edges", []) if e.get("index_1based") == request.get("target_index_diagnostic_only")]
            elif n in [28, 36]:
                for side in ["left", "right"]:
                    p = directory / (side + "-support.json")
                    self.source(p)
                    if p.is_file():
                        targets.append({"samples_mm": read(p).get("corners", []), "kind": "native_finite_surface_corners",
                                        "label": "原生" + ("左" if side == "left" else "右") + "有限输入面角点"})
        artifacts = []
        for name in ["request.json", "call.json", "operation.json", "operation-status.json", "native-return.json",
                     "result.json", "error.json", "process.json", "contact-check.json", "rail-normal-check.json"]:
            p = directory / name
            if p.is_file():
                url = self.json_copy(p, rel + "/evidence-" + name)
                artifacts.append({"label": name, "href": url})
        # Preserve native model hashes even though only JSON geometry is published.
        native_models = []
        for p in sorted(directory.glob("*.smb")):
            native_models.append({"source": self.source(p), "sha256": sha(p), "published": False})
        summary = self.write(rel + "/summary.json", {
            "schema": "filletbench.special-evidence.v1", "historical_snapshot": True,
            "case_number": n, "variant_id": vid, "metrics": metrics, "request": request,
            "report_category": variant["category"], "gates": variant.get("gates", {}),
            "native_model_hashes": native_models, "artifacts": artifacts,
            "source_feature_passed": False, "pdf_or_image_exported": False,
        })
        note = reason(n, variant)
        if not mesh:
            note += " 未找到该次调用的非空结果网格；保留请求与失败证据。"
        smlib = {"status": variant["category"], "label": STATUS_LABELS.get(variant["category"], variant["category"]),
                 "reason": note, "mesh": mesh, "mesh_status": "available" if mesh else "missing",
                 "before_mesh": before, "summary": summary, "version": "10.0.0",
                 "method": request.get("api", "SmApiFilletEdges"), "api_status": variant.get("api"),
                 "request": request, "metrics": metrics, "artifacts": artifacts,
                 "source_feature_passed": False, "historical_snapshot": True,
                 "reproduce": {"status": "historical_snapshot", "exact_reproducible": False,
                               "reason": "本条保留既有运行快照；公开portable consumer可独立重跑同一请求，新的产物与历史SHA分开记录。",
                               "fresh_run_supported": True,
                               "command": f"python3 adapters/smlib/special/run.py --job {n:02d}/{vid}",
                               "dependencies": ["C++17 compiler", "SMLIB_ROOT", "SMLIB_LIBRARY"],
                               "request": request},
                 **extra}
        fresh_directory = self.fresh_runs / f"{n:02d}" / vid if self.fresh_runs else None
        if fresh_directory and (fresh_directory / "summary.json").is_file():
            fresh_summary = read(fresh_directory / "summary.json")
            if fresh_summary.get("job_id") != f"{n:02d}/{vid}":
                raise ValueError("fresh replay identity does not match historical variant")
            def fresh_mesh(name, old_url):
                p = fresh_directory / name
                if not p.is_file():
                    return None, False
                self.source(p)
                obj = read(p)
                old = self.output.parent.parent / old_url if old_url else None
                if old and old.is_file() and read(old) == obj:
                    return old_url, True
                return self.write(rel + "/fresh-" + name, obj), False
            fresh_result, reused_result = fresh_mesh("display-result.json", mesh)
            fresh_before, reused_before = fresh_mesh("display-input.json", before)
            execution = fresh_summary.get("execution", {})
            fresh_extra = []
            for additional in fresh_summary.get("additional_runs", []):
                directory_name = additional["directory"]
                p = fresh_directory / directory_name / "display-result.json"
                if p.is_file():
                    self.source(p)
                    fresh_extra.append({"label": additional["label"], "mesh": self.write(rel + "/fresh-additional-result.json", read(p)),
                                        "execution": additional["execution"]})
            smlib["fresh_replay"] = {
                "tested": fresh_summary.get("freshly_executed", False), "historical_snapshot": False,
                "outcome": fresh_summary.get("outcome"), "execution": execution,
                "mesh": fresh_result, "before_mesh": fresh_before,
                "display_result_reuses_identical_historical_mesh_data": reused_result,
                "display_input_reuses_identical_historical_mesh_data": reused_before,
                "summary": self.json_copy(fresh_directory / "summary.json", rel + "/fresh-summary.json"),
                "binary_provenance": self.json_copy(fresh_directory / "binary-provenance.json", rel + "/fresh-binary-provenance.json"),
                "additional_results": fresh_extra,
                "scope": "本次重新执行同一consumer协议；API返回、结果可用性和网格数组比较不认证完整特殊功能。",
            }
            smlib["reproduce"].update(fresh_tested=fresh_summary.get("freshly_executed", False),
                                      verification="data/supplemental/replay-verification.json")
        return sanitize({"id": vid, "label": variant["label"], "radius_mm": radius,
                         "role": variant.get("role"), "note": note, "input_mesh": before, "targets": targets,
                         "pairing": "unmatched_special_protocol", "historical_snapshot": True,
                         "occt": {"status": "not_run", "label": "本特殊协议未配对运行",
                                  "reason": "尚无已核对同输入、同半径和同特殊参数的OCCT结果；普通轨结果不能替代本协议。",
                                  "mesh": None}, "smlib": smlib})

    def run(self):
        report_path = self.full / "report-data.json"
        report = read(report_path)
        self.source(report_path)
        cases = {}
        for row in report["rows"]:
            selected = [v for v in row["variants"] if v["id"].startswith(("special-", "pilot-"))]
            if selected:
                cases[f"{row['number']:02d}"] = [self.export_variant(row, v) for v in selected]
        total = sum(len(v) for v in cases.values())
        assert total == 51, f"Expected all 51 non-ordinary views, got {total}"
        doc = {"schema": "filletbench.supplemental.v1", "cases": cases,
               "scope": "37个受控特殊协议 + 14个先导历史结果；不认证源高级功能或跨内核等价。",
               "historical_snapshot": True, "original_report_sha256": sha(report_path),
               "counts": {"variants": total, "special": 37, "pilot": 14,
                          "result_meshes": sum(bool(v['smlib']['mesh']) for vs in cases.values() for v in vs),
                          "input_meshes": sum(bool(v['input_mesh']) for vs in cases.values() for v in vs)},
               "media_policy": "Only sanitized JSON geometry and measurements. No PDFs, screenshots or generated images.",
               "sources": self.manifest}
        self.write("index.json", doc)
        print(json.dumps(doc["counts"], ensure_ascii=False))


def key_is_thumb10(vid):
    return vid == "pilot-smlib-thumb10"


def reason(number, variant):
    vid = variant["id"]
    if number == 8:
        return {"pilot-r12": "R12距缺口1mm，未越过；零厚片体，无缺口保留参数。",
                "pilot-r13-contact": "R13临界接触时API失败；候选只是该次实际存留数据，不算成功圆角。",
                "pilot-r14-crossing": "真实R14结果越过原缺口上缘1mm；仍是零厚片体，未测试缺口保留模式。",
                "pilot-r18-crossing": "真实R18结果越过原缺口上缘5mm；仍是零厚片体，未测试缺口保留模式。"}[vid]
    if number in [17, 18]:
        return "普通R8原生基线；指定cap边界未传入原生调用，不能认证封口功能。"
    if number == 23:
        return "R2.5虽返回成功码，实际是开放残片，非合格实体圆角。" if vid == "pilot-r2p5" else "R2原生调用失败；无成功圆角结果，不认证overlap策略。"
    if number == 34:
        return "展示真实R6圆弧与原生变半径控制；rho参数未传入，不能认证conic rho功能。"
    if number == 35:
        if key_is_thumb10(vid):
            return "thumbweight=10的真实边界自交，整体越界约35.1mm；接头G2检查通过不能覆盖此缺陷。"
        return "SMLib原生截面/continuity/thumbweight控制；接头子检查不等于整体形状验收，也不等价于Parasolid softness。"
    if number == 7:
        return "原生默认edge fillet；未提供transfer yes/no高级开关。" + (" 实际几何子检查失败。" if variant["category"] == "geometry_failed" else "仅受控几何子检查通过。")
    if number in [27, 30]:
        return "真实有限面pair调用，保留原始输入；未传master/propagation策略，仅返回独立blend片面，不是完整缝合体。"
    if number == 28:
        return "原生SurfaceSurfaceFillet左右有符号半径受控对照；未认证完整源sense策略，结果为独立blend片面。"
    if number == 36:
        return "原生trim/base_trim枚举受控对照；无调用者后裁剪，不推断其与源trim策略完全等价。"
    return variant.get("metrics", {}).get("description", "特殊协议历史证据；源功能仍待认证。")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-root", type=Path, required=True, help="Private historical workspace root (read-only)")
    ap.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "web/data/supplemental")
    ap.add_argument("--fresh-runs", type=Path, help="Optional fresh special replay root containing CASE/variant/summary.json")
    args = ap.parse_args()
    Exporter(args.source_root.resolve(), args.output.resolve(), args.fresh_runs.resolve() if args.fresh_runs else None).run()


if __name__ == "__main__":
    main()
