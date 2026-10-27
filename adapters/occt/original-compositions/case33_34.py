#!/usr/bin/env python3
"""Fresh OCP execution of the original case33/34 explicit compositions.

The numeric contract comes from the historical execution summaries, rather than
the later source-fit parameter files. No native face blend or rho API is claimed.
"""
import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "special"))
from geometry import face, sew, save, read, stats, shapes, xyz, shared_edges, edge_polyline
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepLProp import BRepLProp_SLProps
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.ChFi3d import ChFi3d_Rational
from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeSolid,
    BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeVertex)
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.Geom import Geom_BSplineSurface
from OCP.GeomAbs import GeomAbs_Plane
from OCP.TColgp import TColgp_Array2OfPnt
from OCP.TColStd import (TColStd_Array1OfReal, TColStd_Array1OfInteger,
    TColStd_Array2OfReal)
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_SHELL, TopAbs_REVERSED
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Pnt


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write(p, d):
    Path(p).write_text(json.dumps(d, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def spline(rows, weight):
    poles, weights = TColgp_Array2OfPnt(1, 2, 1, 3), TColStd_Array2OfReal(1, 2, 1, 3)
    for i, row in enumerate(rows, 1):
        for j, point in enumerate(row, 1):
            poles.SetValue(i, j, gp_Pnt(*point))
            weights.SetValue(i, j, weight if j == 2 else 1.)
    knots, um, vm = TColStd_Array1OfReal(1, 2), TColStd_Array1OfInteger(1, 2), TColStd_Array1OfInteger(1, 2)
    for i, value in enumerate((0., 1.), 1):
        knots.SetValue(i, value)
        um.SetValue(i, 2)
        vm.SetValue(i, 3)
    return Geom_BSplineSurface(poles, weights, knots, knots, um, vm, 1, 2, False, False)


def make33(p):
    w, h, d = p['width'], p['height'], p['depth']
    xl, xr = -w / 2, w / 2
    a0, a1, b0, b1 = (p[k] for k in ('a_left', 'a_right', 'b_left', 'b_right'))
    before = sew([face([(xl, 0, 0), (xr, 0, 0), (xr, 0, h), (xl, 0, h)]),
                  face([(xl, 0, 0), (xr, 0, 0), (xr, d, 0), (xl, d, 0)])])
    rows = [[(xl, 0, b1), (xl, 0, 0), (xl, a1, 0)],
            [(xr, 0, b0), (xr, 0, 0), (xr, a0, 0)]]
    s = spline(rows, math.sqrt(.5))
    wall = face([(xl, 0, b1), (xr, 0, b0), (xr, 0, h), (xl, 0, h)])
    wall.Reverse()  # Original script forces the wall normal toward +Y.
    floor = face([(xl, a1, 0), (xr, a0, 0), (xr, d, 0), (xl, d, 0)])
    result = sew([wall, BRepBuilderAPI_MakeFace(s, 1e-7).Face(), floor])
    return before, result, rows, math.sqrt(.5)


def make34_input(p):
    h, xb, xt, y = (p[k] for k in ('height', 'X_bottom', 'X_top', 'Y_width'))
    fs = [face([(0,0,0),(xb,0,0),(xt,0,h),(0,0,h)]),
          face([(0,0,0),(0,0,h),(0,y,h),(0,y,0)]),
          face([(0,y,0),(0,y,h),(xt,y,h),(xb,y,0)]),
          face([(xb,0,0),(xb,y,0),(xt,y,h),(xt,0,h)]),
          face([(0,0,0),(0,y,0),(xb,y,0),(xb,0,0)]),
          face([(0,0,h),(xt,0,h),(xt,y,h),(0,y,h)])]
    return BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(sew(fs))).Solid()


def make34(p, weight):
    h, xb, xt, y, db, dt = (p[k] for k in ('height','X_bottom','X_top','Y_width','d_bottom','d_top'))
    rows = [[(0, db, 0), (0, 0, 0), (db, 0, 0)],
            [(0, dt, h), (0, 0, h), (dt, 0, h)]]
    s = spline(rows, weight)
    blend = BRepBuilderAPI_MakeFace(s, 1e-7).Face()
    blend.Reverse()
    fs = [face([(db,0,0),(xb,0,0),(xt,0,h),(dt,0,h)]),
          face([(0,db,0),(0,dt,h),(0,y,h),(0,y,0)]),
          face([(0,y,0),(0,y,h),(xt,y,h),(xb,y,0)]),
          face([(xb,0,0),(xb,y,0),(xt,y,h),(xt,0,h)])]
    def cap(u, z, xx, dd):
        points = [(dd,0,z),(xx,0,z),(xx,y,z),(0,y,z),(0,dd,z)]
        wire = BRepBuilderAPI_MakeWire()
        wire.Add(BRepBuilderAPI_MakeEdge(s.UIso(u)).Edge())
        for a, b in zip(points, points[1:]):
            wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(*a), gp_Pnt(*b)).Edge())
        return BRepBuilderAPI_MakeFace(wire.Wire()).Face()
    bottom, top = cap(0.,0.,xb,db), cap(1.,h,xt,dt)
    bottom.Reverse()
    result = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(sew(fs + [bottom, top, blend]))).Solid()
    return result, rows


def profile_audit(result, rows, weight):
    fs = [TopoDS.Face_s(f) for f in shapes(result, TopAbs_FACE)
          if BRepAdaptor_Surface(TopoDS.Face_s(f)).GetType() != GeomAbs_Plane]
    assert len(fs) == 1
    surf = BRepAdaptor_Surface(fs[0])
    errors = []
    for i in range(11):
        u = i / 10
        for j in range(65):
            v = j / 64
            b = [(1-v)**2, 2*weight*v*(1-v), v*v]
            expected = [sum(b[k] * ((1-u)*rows[0][k][axis] + u*rows[1][k][axis])
                            for k in range(3))/sum(b) for axis in range(3)]
            errors.append(math.dist(xyz(surf.Value(u,v)), expected))
    return dict(method='715 readback surface samples versus independently evaluated rational Bernstein formula',
                sample_count=len(errors), maximum_position_residual_mm=max(errors), passed=max(errors)<1e-7)


def historical_audit(fresh, historical):
    """Trimmed-face sample distances in both directions, not just mass properties."""
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopLoc import TopLoc_Location
    maximum, count = 0., 0
    for a, b in ((fresh, historical), (historical, fresh)):
        BRepMesh_IncrementalMesh(a, .04, False, .15, False)
        for raw in shapes(a, TopAbs_FACE):
            loc = TopLoc_Location()
            triangulation = BRep_Tool.Triangulation_s(TopoDS.Face_s(raw), loc)
            if triangulation is None:
                continue
            indices = range(1, triangulation.NbNodes()+1, max(1, triangulation.NbNodes()//50))
            for i in indices:
                point = triangulation.Node(i).Transformed(loc.Transformation())
                check = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(point).Vertex(), b)
                if not check.IsDone():
                    raise ValueError('Historical nearest shape distance failed')
                maximum = max(maximum, check.Value())
                count += 1
    fresh_stats, old_stats = stats(fresh), stats(historical)
    return dict(method='bidirectional nearest trimmed-shape distances of up to about 50 native triangulation vertices per face',
        sample_count=count, maximum_sampled_distance_mm=maximum,
        historical_stats=old_stats,
        area_delta_mm2=fresh_stats['area_mm2']-old_stats['area_mm2'],
        volume_delta_mm3=fresh_stats['volume_mm3']-old_stats['volume_mm3'],
        sampled_geometry_agrees=maximum<1e-6,
        boundary='Finite sampling does not establish exact full-surface Hausdorff equivalence.')


def native_contact_audit(result, number, height):
    """Read the actual shared seam pcurves; distinguish solid end-cap seams."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    fs = [TopoDS.Face_s(f) for f in shapes(result, TopAbs_FACE)]
    generated = [f for f in fs if BRepAdaptor_Surface(f).GetType()!=GeomAbs_Plane]
    seams = []
    for e in shared_edges(result):
        owners = [f for f in fs if any(e.IsSame(t) for t in shapes(f,TopAbs_EDGE))]
        if not any(any(f.IsSame(g) for g in generated) for f in owners):
            continue
        points = edge_polyline(e,9)
        cap = number==34 and (all(abs(p[2])<1e-6 for p in points) or all(abs(p[2]-height)<1e-6 for p in points))
        curve = BRepAdaptor_Curve(e)
        gaps, angles = [], []
        for i in range(1,50):
            t = curve.FirstParameter()+(curve.LastParameter()-curve.FirstParameter())*i/50
            point, normals = curve.Value(t), []
            for f in owners:
                pc = BRep_Tool.CurveOnSurface_s(e,f,0.,0.)
                uv = pc.Value(t)
                surf = BRepAdaptor_Surface(f)
                gaps.append(surf.Value(uv.X(),uv.Y()).Distance(point))
                props = BRepLProp_SLProps(surf,uv.X(),uv.Y(),1,1e-10)
                normal = props.Normal()
                if f.Orientation()==TopAbs_REVERSED:
                    normal.Reverse()
                normals.append(normal)
            dot = normals[0].Dot(normals[1])
            if number==33:
                dot = abs(dot)  # Original open-shell control used unoriented G1.
            angles.append(math.degrees(math.acos(max(-1.,min(1.,dot)))))
        seams.append(dict(cap_C0_only=cap, samples_mm=points, sample_count=49,
            maximum_G0_mm=max(gaps), maximum_G1_degrees=max(angles),
            passed=max(gaps)<=1e-6 and (cap or max(angles)<=.1)))
    return dict(method='Actual readback shared-seam pcurves and surface normals; end-cap tangent continuity exempted',
        generated_nonplanar_face_count=len(generated), seams=seams,
        passed=len(generated)==1 and len(seams)==(2 if number==33 else 4) and all(q['passed'] for q in seams))


def run_native_controls(args, contract, report):
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    for number in (33,34):
        c = contract[str(number)]
        ctrl = c['native_control']
        tid = ctrl['variant_id']
        directory = args.out/f'case{number:02d}-{tid}'
        directory.mkdir(exist_ok=True)
        for filename in ('source.brep','source.mesh.json','before.brep','before.mesh.json','result.brep','result.mesh.json','summary.json'):
            (directory/filename).unlink(missing_ok=True)
        input_file = args.suite_root/ctrl['operation_input']['brep']
        result_file = args.suite_root/ctrl['historical_result']['brep']
        if sha(input_file)!=ctrl['operation_input']['sha256'] or sha(result_file)!=ctrl['historical_result']['sha256']:
            raise ValueError('Frozen native-control artifact SHA256 differs from contract')
        before = read(input_file)
        if number==33:
            before = TopoDS.Shell_s(shapes(before,TopAbs_SHELL)[0])
        selected_index = ctrl['operation_input']['selected_edges'][0]['index_1based']
        selected = TopoDS.Edge_s(shapes(before,TopAbs_EDGE)[selected_index-1])
        curve = BRepAdaptor_Curve(selected)
        selected_points = edge_polyline(selected,9)
        p = c['parameters']
        linked_script = ctrl['script_provenance']['linked_sources'][-1]
        row = dict(schema_version=1, case_number=number, variant=tid, original_variant_ids=[tid],
            engine=report['engine'],engine_version=report['engine_version'],binding_version=report['binding_version'],
            adapter_sha256=report['adapter_sha256'],parameter_contract_sha256=report['parameter_contract_sha256'],
            protocol_id=f'original-occ-{number:02d}-{tid}-v1',
            method_kind='native_variable_radius_fillet' if number==33 else 'native_circular_fillet_control',
            execution_status='fresh_native_control_executed',
            native_call_executed=False, native_operation_succeeded=False,
            source_brep=c['source_brep'],source_sha256=c['source_sha256'],
            operation_input_brep=ctrl['operation_input']['brep'], operation_input_sha256=ctrl['operation_input']['sha256'],
            original_result_sha256=ctrl['historical_result']['sha256'],
            original_summary_sha256=ctrl['original_summary_sha256'],
            original_script=linked_script['path'], original_script_sha256=linked_script['sha256'],
            original_script_version_status=ctrl['script_provenance']['status'],
            script_provenance=ctrl['script_provenance'],
            parameters=p, original_native_record=ctrl['native_record'], native_rho_parameter_used=False,
            source_feature_certified=False, symmetric_native_control_only=True,
            selection=dict(method='Exact original edge index on SHA-verified original operation input',
                index_1based=selected_index, samples_mm=selected_points,
                original_edge=ctrl['operation_input']['selected_edges'][0]),
            processing_steps=['Read immutable original operation-input BREP and verify SHA256',
                'Use original recorded edge index and unchanged two-end radius parameters',
                'Execute native BRepFilletAPI_MakeFillet with rational circular representation',
                'Write fresh native result BREP, read back, triangulate and check actual seam pcurves'],
            limitations=['This is the original symmetric/circular control, not the original asymmetric/rho feature.',
                'Original main-script version was not recorded in the historical summary; present linked source hash is retained.',
                'OCCT 7.9.3 rerun is compared with the 7.8.1 historical artifact; kernel identity is not asserted.',
                'Human appearance has not been reviewed.'],
            source=save(read(args.suite_root/c['source_brep']),directory,'source'),
            before=save(before,directory,'before',[selected]),
            artifacts=dict(source_brep='source.brep',source_mesh='source.mesh.json',before_brep='before.brep',before_mesh='before.mesh.json'))
        write(directory/'summary.json',row)
        try:
            fillet = BRepFilletAPI_MakeFillet(before,ChFi3d_Rational)
            if number==33:
                r1,r2 = ctrl['native_record']['radii']
                expected = ctrl['native_record']['radius_assignment']
                if abs(curve.Value(curve.FirstParameter()).X()-expected['start_x'])>1e-7 or abs(curve.Value(curve.LastParameter()).X()-expected['end_x'])>1e-7:
                    raise ValueError('Original selected edge orientation differs; refusing to silently reassign radii')
                fillet.Add(r1,r2,selected)
                row['native_call']='MakeFillet.Add(original_R_start,original_R_end,original_edge); Build()'
            else:
                fillet.Add(selected)
                contour = fillet.Contour(selected)
                first,last = BRep_Tool.Pnt_s(fillet.FirstVertex(contour)),BRep_Tool.Pnt_s(fillet.LastVertex(contour))
                rec = ctrl['native_record']
                if math.dist(xyz(first),rec['contour_first'])>1e-7 or math.dist(xyz(last),rec['contour_last'])>1e-7:
                    raise ValueError('Original contour orientation differs; refusing to silently reassign radii')
                r1,r2 = rec['radius_first'],rec['radius_last']
                fillet.SetRadius(r1,r2,contour,1)
                row['native_call']='MakeFillet.Add(original_edge); SetRadius(original_R_first,original_R_last,contour,1); Build()'
            row.update(native_call_executed=True, radius_first_mm=r1,radius_last_mm=r2,
                contour_count=fillet.NbContours(),representation='ChFi3d_Rational; circular representation only')
            write(directory/'summary.json',row)
            fillet.Build()
            row['native_operation_succeeded']=bool(fillet.IsDone())
            if not fillet.IsDone():
                raise RuntimeError('BRepFilletAPI_MakeFillet.IsDone() returned false')
            row['result']=save(fillet.Shape(),directory,'result')
            row['artifacts'].update(result_brep='result.brep',result_mesh='result.mesh.json')
            readback = read(directory/'result.brep')
            row['contact_validation']=native_contact_audit(readback,number,p.get('height'))
            row['historical_result_comparison']=historical_audit(readback,read(result_file))
            st=row['result']['readback_stats']
            row['verification_summary']=dict(valid=st['valid'],expected_topology=st['faces']==(3 if number==33 else 7) and st['solids']==(0 if number==33 else 1),
                result_mesh=row['result']['mesh']['status']=='ok',actual_pcurve_G0_G1=row['contact_validation']['passed'])
            row['outcome']='ok' if all(row['verification_summary'].values()) else 'verification_failed'
        except Exception as error:
            row.update(outcome='verification_failed' if row['native_operation_succeeded'] else ('native_rejected' if row['native_call_executed'] else 'precondition_failed'),reason=f'{type(error).__name__}: {error}')
        row['operation_input_unchanged']=sha(input_file)==ctrl['operation_input']['sha256']
        write(directory/'summary.json',row)
        report['trials'].append(row)
        report['original_variant_artifacts'][f'{number:02d}/{tid}']=[dict(run=f'case{number:02d}-{tid}/summary.json',
            before_mesh=f'case{number:02d}-{tid}/before.mesh.json',**({k:f'case{number:02d}-{tid}/{v}' for k,v in row['artifacts'].items() if k.startswith('result')}))]
        write(args.out/'case33_34-summary.json',report)
        print(number,tid,row['outcome'],row.get('reason',''),flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--suite-root', type=Path, default=ROOT, help='Repository containing the frozen original suite; defaults to this repository')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    contract = json.loads((HERE/'case33_34_parameters.json').read_text())
    binding = version('cadquery-ocp')
    if binding != '7.9.3.1.1':
        raise ValueError('Requires pinned cadquery-ocp 7.9.3.1.1')
    report = dict(schema_version=1, created_at=datetime.now(timezone.utc).isoformat(),
        engine='OCCT', engine_version='7.9.3', binding_version=binding,
        adapter_sha256=sha(__file__), parameter_contract_sha256=sha(HERE/'case33_34_parameters.json'),
        original_runtime='FreeCAD with OCCT 7.8.1', runtime_equivalence=False,
        method_kind='explicit_occ_composition', native_face_blend_executed=False,
        source_feature_certified=False, human_appearance_status='unreviewed', trials=[], original_variant_artifacts={})
    for n in (33,34):
        c = contract[str(n)]
        p = c['parameters']
        source_file = args.suite_root/c['source_brep']
        if sha(source_file) != c['source_sha256']:
            raise ValueError('Frozen source artifact SHA256 differs from contract')
        source = read(source_file)
        if n == 33:
            before, result, rows, w = make33(p)
            trials = [('asymmetric-ranges', result, rows, w, None)]
        else:
            before = make34_input(p)
            trials = []
            for tid, rho_type, rho, w in [('absolute-025','absolute',.25,1/3),
                                        ('absolute-050','absolute',.5,1.),
                                        ('absolute-075','absolute',.75,3.),
                                        ('relative-050','relative',.5,math.sqrt(.5))]:
                result, rows = make34(p,w)
                trials.append((tid,result,rows,w,dict(type=rho_type,value=rho)))
        for tid, result, rows, w, rho in trials:
            directory = args.out/f'case{n:02d}-{tid}'
            directory.mkdir(exist_ok=True)
            selected = shared_edges(before, lambda points: all(
                abs(q[1])<1e-7 and abs(q[2] if n==33 else q[0])<1e-7 for q in points))
            if len(selected) != 1:
                raise ValueError('Expected exactly one original common support seam')
            row = dict(schema_version=1, case_number=n, variant=tid,
                engine=report['engine'],engine_version=report['engine_version'],binding_version=report['binding_version'],
                adapter_sha256=report['adapter_sha256'],parameter_contract_sha256=report['parameter_contract_sha256'],
                protocol_id=f'original-occ-{n:02d}-{tid}-composition-v1',
                method_kind='explicit_occ_composition', execution_status='fresh_reconstruction_executed',
                construction_executed=True, native_call_executed=False,
                source_brep=c['source_brep'], source_sha256=c['source_sha256'],
                frozen_case_json_sha256=sha(args.suite_root/f'data/original-occ/cases/{n}.json'),
                original_script=c['original_script'], original_script_sha256=c['original_script_sha256'],
                original_script_version_status=c['script_provenance']['status'],
                script_provenance=c['script_provenance'],
                original_variant_ids=[key for key,values in c['original_variant_mapping'].items() if tid in values],
                original_summary_sha256=c['historical_summary_sha256'],
                original_input_sha256=c['historical_input_sha256'],
                original_result_sha256=c['historical_result_sha256'][tid],
                original_source_dimensions_known=False, parameters=p, rho=rho, rational_middle_weight=w,
                selection=dict(method='Unique two-face shared original sharp seam; geometry predicate',
                    predicate='y=z=0' if n==33 else 'x=y=0',
                    selected_edge_count=len(selected),
                    samples_mm=[edge_polyline(e,9) for e in selected],
                    role='Original operation target/reference; explicit composition does not call native edge filleting'),
                processing_steps=(['Create original perpendicular finite support sheets from recorded dimensions',
                    'Build degree 1 by degree 2 rational B-spline with independent linearly varying a/b offsets',
                    'Trim planar supports at recorded contact lines', 'Sew support/blend/support as an open three-face shell']
                    if n==33 else ['Create recorded six-planar-face convex closed input proxy',
                    'Build degree 1 by degree 2 rational conic surface with fixed recorded linear contact-distance law',
                    'Trim two support planes at identical contact lines for every rho',
                    'Create curved end-cap wires with the actual conic UIso edges',
                    'Sew seven faces and make one closed solid']),
                limitations=['Original inferred input dimensions are preserved, not promoted to original CAD truth.',
                    'OCP 7.9.3 execution replays the original explicit mathematical recipe, not the historical FreeCAD 7.8.1 runtime.',
                    'No native asymmetric face-blend API or native rho control was executed.',
                    'Human appearance review has not been repeated.'],
                source=save(source,directory,'source'), before=save(before,directory,'before',selected), result=save(result,directory,'result'),
                artifacts=dict(source_brep='source.brep',source_mesh='source.mesh.json',before_brep='before.brep',result_brep='result.brep',before_mesh='before.mesh.json',result_mesh='result.mesh.json'))
            readback = read(directory/'result.brep')
            row['profile_validation'] = profile_audit(readback,rows,w)
            row['valid'] = row['result']['readback_stats']['valid']
            row['expected_topology_passed'] = (row['result']['stats']['faces']==3 and row['result']['stats']['solids']==0) if n==33 else (row['result']['stats']['faces']==7 and row['result']['stats']['solids']==1 and 0<row['result']['stats']['volume_mm3']<row['before']['stats']['volume_mm3'])
            old_input = args.suite_root/c['historical_input']
            old_result = args.suite_root/c['historical_results'][tid]
            if sha(old_input) != c['historical_input_sha256'] or sha(old_result) != c['historical_result_sha256'][tid]:
                raise ValueError('Historical artifact SHA256 differs from frozen execution contract')
            row['historical_input_comparison'] = historical_audit(read(directory/'before.brep'), read(old_input))
            row['historical_result_comparison'] = historical_audit(readback,read(old_result))
            row['verification_summary'] = dict(valid=row['valid'], expected_topology=row['expected_topology_passed'],
                independent_rational_profile=row['profile_validation']['passed'],
                before_mesh=row['before']['mesh']['status']=='ok', result_mesh=row['result']['mesh']['status']=='ok',
                historical_input_sampled_agreement=row.get('historical_input_comparison',{}).get('sampled_geometry_agrees'),
                historical_result_sampled_agreement=row.get('historical_result_comparison',{}).get('sampled_geometry_agrees'))
            row['outcome']='ok' if all(q is not False for q in row['verification_summary'].values()) else 'verification_failed'
            write(directory/'summary.json',row)
            report['trials'].append(row)
            for original_id in row['original_variant_ids']:
                report['original_variant_artifacts'].setdefault(f'{n:02d}/{original_id}',[]).append(
                    dict(run=f'case{n:02d}-{tid}/summary.json', before_mesh=f'case{n:02d}-{tid}/before.mesh.json',
                         result_mesh=f'case{n:02d}-{tid}/result.mesh.json', result_brep=f'case{n:02d}-{tid}/result.brep'))
            write(args.out/'case33_34-summary.json',report)
            print(n,tid,row['outcome'],row['result']['stats'],flush=True)
    run_native_controls(args,contract,report)
    report['complete']=True
    report['fresh_composition_count']=5
    report['fresh_native_control_count']=2
    report['fresh_replay_count']=len(report['trials'])
    write(args.out/'case33_34-summary.json',report)


if __name__=='__main__':
    main()
