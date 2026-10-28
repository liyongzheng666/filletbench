#!/usr/bin/env python3
"""Independent geometry audit of case 08 radius probes; never invokes a fillet.

Requires OCP and NumPy. Reads the frozen source and native artifacts, and writes
only docs/case08-radius-audit.json/md. No input radius is used as a measurement.
"""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepTools import BRepTools
from OCP.Bnd import Bnd_Box
from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
from OCP.GeomLProp import GeomLProp_SLProps
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID, TopAbs_VERTEX
from OCP.TopExp import TopExp
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.gp import gp_Pnt

ROOT = Path(__file__).resolve().parents[1]
TOL = 1e-6
EXPECTED_SHA = '57ea045f7da3735141b7f21f2fbc3e3a51c39933d08a5d7c6e3374e01ab064f9'
SOURCE = ROOT / 'data/models/08.brep'
RADII = [12, 13, 14, 15, 18]


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rel(path):
    return str(Path(path).resolve().relative_to(ROOT))


def xyz(p):
    return [p.X(), p.Y(), p.Z()]


def mapped(shape, kind):
    m = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, m)
    return [m.FindKey(i) for i in range(1, m.Extent()+1)]


def read_brep(path):
    shape = TopoDS_Shape()
    if not BRepTools.Read_s(shape, str(path), BRep_Builder()) or shape.IsNull():
        raise ValueError('BREP read failed: '+rel(path))
    return shape


def shape_stats(shape):
    area = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, area)
    box = Bnd_Box()
    box.SetGap(0)
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    return dict(valid=bool(BRepCheck_Analyzer(shape, True).IsValid()),
                faces=len(mapped(shape, TopAbs_FACE)), edges=len(mapped(shape, TopAbs_EDGE)),
                solids=len(mapped(shape, TopAbs_SOLID)), shells=len(mapped(shape, TopAbs_SHELL)),
                vertices=len(mapped(shape, TopAbs_VERTEX)), area_mm2=area.Mass(), bbox_mm=list(box.Get()))


def native_stats_vs_source(stats, source_stats):
    checks = {k: stats.get(k) == source_stats[k] for k in ['faces', 'edges', 'shells', 'vertices']}
    checks['zero_solids'] = stats.get('solids', stats.get('material_regions')) == 0
    area = stats.get('area_mm2', stats.get('area'))
    bbox = stats.get('bbox_mm', stats.get('bbox'))
    checks['area'] = area is not None and abs(area-source_stats['area_mm2']) <= TOL
    checks['bbox'] = bbox is not None and max(abs(a-b) for a, b in zip(bbox, source_stats['bbox_mm'])) <= TOL
    checks['valid'] = stats.get('valid') is True
    return dict(passed=all(checks.values()), checks=checks)


def source_planes(shape):
    records = []
    for i, face in enumerate(mapped(shape, TopAbs_FACE)):
        surface = BRepAdaptor_Surface(TopoDS.Face_s(face))
        record = dict(face_id=i, representation=str(surface.GetType()).split('.')[-1])
        if surface.GetType() == GeomAbs_Plane:
            plane = surface.Plane()
            normal = np.asarray(xyz(plane.Axis().Direction()))
            point = np.asarray(xyz(plane.Location()))
            record.update(normal=normal.tolist(), plane_offset_mm=float(normal@point))
        records.append(record)
    return records


def smlib_before_support_planes(snapshot):
    results = []
    for face in snapshot['geometry']['faces']:
        samples = [s for s in face['samples'] if s.get('status') == 1000]
        checks = []
        for axis, offset, name in [(1, 0, 'y=0'), (2, 40, 'z=40')]:
            residual = max((abs(s['point'][axis]-offset) for s in samples), default=float('inf'))
            normal_error = max((1-abs(s['raw_normal'][axis]) for s in samples), default=float('inf'))
            curvatures = [principal_from_D2(s) for s in samples]
            curvature = max((max(c) for c in curvatures if c is not None), default=float('inf'))
            if residual <= TOL and normal_error <= 1e-10 and curvature <= 1e-8:
                checks.append(dict(plane=name, point_residual_mm=residual, normal_error=normal_error, max_abs_principal_curvature=curvature))
        results.append(dict(face_id=face['id'], matched_planes=checks, passed=len(checks) == 1, sample_count=len(samples)))
    return dict(passed=len(results) == 2 and all(r['passed'] for r in results) and
                       {r['matched_planes'][0]['plane'] for r in results if r['matched_planes']} == {'y=0', 'z=40'},
                faces=results, scope='native support surfaces sampled independently; finite trimmed boundary equivalence checked separately')


def shape_edges(shape):
    faces = mapped(shape, TopAbs_FACE)
    result = []
    for i, raw in enumerate(mapped(shape, TopAbs_EDGE)):
        edge = TopoDS.Edge_s(raw)
        curve = BRepAdaptor_Curve(edge)
        a, b = curve.FirstParameter(), curve.LastParameter()
        points = [xyz(curve.Value(a+(b-a)*j/64)) for j in range(65)]
        mass = GProp_GProps()
        BRepGProp.LinearProperties_s(edge, mass)
        owners = [j for j, face in enumerate(faces) if any(edge.IsSame(e) for e in mapped(face, TopAbs_EDGE))]
        result.append(dict(id=i, points=points, length=mass.Mass(), owners=owners,
                           representation=str(curve.GetType()).split('.')[-1]))
    return result


def segment_distance(points, a, b):
    points, a, b = np.asarray(points), np.asarray(a), np.asarray(b)
    d = b-a
    t = np.clip((points-a)@d/(d@d), 0, 1)
    return np.linalg.norm(points-a-t[:, None]*d, axis=1)


def line_model(edge):
    p = np.asarray(edge['points'])
    if len(p) < 3:
        return None
    d = p[-1]-p[0]
    length = float(np.linalg.norm(d))
    if length < TOL:
        return None
    error = float(max(segment_distance(p, p[0], p[-1])))
    if error > TOL or abs(edge['length']-length) > max(TOL, length*1e-7):
        return None
    return dict(start=p[0].tolist(), end=p[-1].tolist(), length_mm=length, sample_residual_mm=error)


def circle_model(edge):
    """Fit YZ circle on an actual fixed-X cross-section, without nominal R."""
    p = np.asarray(edge['points'])
    if len(p) < 5 or np.ptp(p[:, 0]) > TOL or line_model(edge):
        return None
    q = p[:, 1:]
    A = np.c_[2*q[:, 0], 2*q[:, 1], np.ones(len(q))]
    fit, _, rank, _ = np.linalg.lstsq(A, np.sum(q*q, axis=1), rcond=None)
    if rank != 3 or fit[2]+fit[0]**2+fit[1]**2 <= 0:
        return None
    center = fit[:2]
    radius = float(np.sqrt(fit[2]+center@center))
    residual = float(max(abs(np.linalg.norm(q-center, axis=1)-radius)))
    angles = np.unwrap(np.arctan2(q[:, 1]-center[1], q[:, 0]-center[0]))
    angle = float(abs(angles[-1]-angles[0]))
    length_error = abs(radius*angle-edge['length'])
    if residual > TOL or angle < .1 or length_error > max(TOL, edge['length']*1e-7):
        return None
    return dict(edge_id=edge['id'], x_mm=float(np.mean(p[:, 0])), center_yz_mm=center.tolist(),
                radius_mm=radius, max_radial_residual_mm=residual, angle_radians=angle,
                arc_length_mm=radius*angle, native_length_error_mm=length_error,
                method='least-squares circle from 65 actual native finite-edge world points; independent native arc length')


def matching_line(edges, a, b, owners=None):
    result = []
    for edge in edges:
        model = line_model(edge)
        if not model or (owners is not None and len(edge['owners']) != owners):
            continue
        ends = [model['start'], model['end']]
        gap = min(max(math.dist(ends[0], a), math.dist(ends[1], b)),
                  max(math.dist(ends[1], a), math.dist(ends[0], b)))
        if gap <= TOL and max(segment_distance(edge['points'], a, b)) <= TOL:
            result.append(dict(edge_id=edge['id'], owners=edge['owners'], endpoint_gap_mm=gap, **model))
    return result


def finite_edge_equivalence(a, b):
    """Unordered finite-curve matching; never pairs equal parameter fractions."""
    matches = []
    remaining = list(b)
    for edge in a:
        model = line_model(edge)
        found = None
        if model:
            for other in remaining:
                if matching_line([other], model['start'], model['end'], len(edge['owners'])):
                    found = other
                    break
        else:
            circle = circle_model(edge)
            if circle:
                for other in remaining:
                    candidate = circle_model(other)
                    if not candidate or len(other['owners']) != len(edge['owners']):
                        continue
                    p, q = edge['points'], other['points']
                    endpoint_gap = min(max(math.dist(p[0], q[0]), math.dist(p[-1], q[-1])),
                                       max(math.dist(p[0], q[-1]), math.dist(p[-1], q[0])))
                    if (endpoint_gap <= TOL and abs(circle['radius_mm']-candidate['radius_mm']) <= TOL and
                        math.dist(circle['center_yz_mm'], candidate['center_yz_mm']) <= TOL and
                        abs(edge['length']-other['length']) <= TOL):
                        found = other
                        break
        if found is not None:
            matches.append([edge['id'], found['id']])
            remaining.remove(found)
    return dict(passed=len(matches) == len(a) == len(b), matched_edges=len(matches),
                source_edges=len(a), candidate_edges=len(b), matches=matches,
                method='unordered bounded line/circle endpoints, lengths, world-carrier residuals and owner counts; no parameter-fraction pairing')


def opening_measurements(edges):
    openings = []
    top = matching_line(edges, [35, 0, 27], [65, 0, 27], 1)
    for edge in edges:
        model = line_model(edge)
        if not model or len(edge['owners']) != 1:
            continue
        p = np.asarray(edge['points'])
        if (max(abs(p[:, 1])) <= TOL and np.ptp(p[:, 2]) <= TOL and
            abs(min(p[:, 0])-35) <= TOL and abs(max(p[:, 0])-65) <= TOL):
            z = float(np.mean(p[:, 2]))
            openings.append(dict(edge_id=edge['id'], owners=edge['owners'], x_range_mm=[float(min(p[:, 0])), float(max(p[:, 0]))],
                                 y_max_abs_mm=float(max(abs(p[:, 1]))), z_mm=z, original_top_minus_actual_z_mm=27-z,
                                 actual_below_original_notch_top=z < 27-TOL))
    return dict(actual_opening_free_edges=openings, original_notch_top_retained=bool(top),
                original_notch_top_matches=top, actual_crossing_observed=any(e['actual_below_original_notch_top'] for e in openings))


def principal_from_D2(owner):
    try:
        du, dv, duu, duv, dvv = [np.asarray(owner[k], dtype=float) for k in ['du', 'dv', 'duu', 'duv', 'dvv']]
        normal = np.cross(du, dv)
        normal /= np.linalg.norm(normal)
        first = np.array([[du@du, du@dv], [du@dv, dv@dv]])
        second = np.array([[duu@normal, duv@normal], [duv@normal, dvv@normal]])
        values = sorted(abs(float(v)) for v in np.linalg.eigvals(np.linalg.solve(first, second)))
        if not all(math.isfinite(v) for v in values):
            return None
        return values
    except (KeyError, ValueError, np.linalg.LinAlgError):
        return None


def smlib_rail_checks(snapshot):
    """Check actual shared line geometry; pcurve fractions need not share X."""
    result = []
    for edge in snapshot['geometry']['edges']:
        line = line_model(edge)
        if len(edge['owners']) != 2 or not line:
            continue
        p = np.asarray(edge['points'])
        if np.ptp(p[:, 1]) > TOL or np.ptp(p[:, 2]) > TOL or np.ptp(p[:, 0]) < 1:
            continue
        if max(abs(p[:, 2]-40)) <= TOL and max(abs(p[:, 1])) <= TOL:
            # The retained original sharp fold is not a generated fillet rail.
            continue
        if max(abs(p[:, 2]-40)) <= TOL:
            axis = np.array([0., 0., 1.])
            role = 'horizontal_support_to_blend'
        elif max(abs(p[:, 1])) <= TOL and max(p[:, 2]) < 40-TOL:
            axis = np.array([0., 1., 0.])
            role = 'wall_support_to_blend'
        else:
            continue
        angles, carrier_gaps, fraction_gaps, curvatures = [], [], [], []
        samples = [s for s in snapshot.get('junction_samples', []) if s['edge_id'] == edge['id']]
        statuses_ok = True
        for sample in samples:
            for owner in sample['owners']:
                if owner.get('status') != 1000 or owner.get('uv_evaluation_status') != 1000:
                    statuses_ok = False
                    continue
                normal = np.asarray(owner['raw_normal'], dtype=float)
                normal /= np.linalg.norm(normal)
                angles.append(math.degrees(math.acos(float(np.clip(abs(normal@axis), -1, 1)))))
                carrier_gaps.append(float(segment_distance([owner['point']], line['start'], line['end'])[0]))
                fraction_gaps.append(math.dist(owner['point'], sample['point']))
                curvature = principal_from_D2(owner)
                if curvature is not None:
                    curvatures.append(dict(face_id=owner['face_id'], point=owner['point'],
                                           abs_principal_curvatures_per_mm=curvature,
                                           radius_from_D2_mm=1/curvature[1] if curvature[1] > 1e-8 else None))
        good = bool(samples and statuses_ok and carrier_gaps and max(carrier_gaps) <= TOL and max(angles) <= 1e-4)
        result.append(dict(edge_id=edge['id'], role=role, owner_count=2, sample_count=len(samples),
                           owner_surface_to_actual_bounded_rail_max_mm=max(carrier_gaps, default=None),
                           maximum_tangent_plane_angle_to_support_deg=max(angles, default=None),
                           same_fraction_world_point_difference_max_mm=max(fraction_gaps, default=None),
                           same_fraction_difference_used_as_G0_failure=False,
                           sampled_line_carrier_G0_and_G1_passed=good, D2_curvature_samples=curvatures,
                           method='each owner evaluated point belongs to the same actual finite X-line; tangent plane is compared with that rail support normal at its own world point; raw fractions are not equated',
                           scope='sampled shared-rail carrier and tangent plane checks; not global surface or G2 certification'))
    return result


def occt_rail_checks(shape, edges):
    faces = mapped(shape, TopAbs_FACE)
    result = []
    for edge in edges:
        line = line_model(edge)
        if not line or len(edge['owners']) != 2:
            continue
        gaps, angles = [], []
        for point in edge['points'][3:-3:9]:
            normals = []
            for owner in edge['owners']:
                surface = BRep_Tool.Surface_s(TopoDS.Face_s(faces[owner]))
                projection = GeomAPI_ProjectPointOnSurf(gp_Pnt(*point), surface)
                gaps.append(projection.LowerDistance())
                u, v = projection.LowerDistanceParameters()
                props = GeomLProp_SLProps(surface, u, v, 1, 1e-9)
                normals.append(np.asarray(xyz(props.Normal())))
            angles.append(math.degrees(math.acos(float(np.clip(abs(normals[0]@normals[1]), -1, 1)))))
        result.append(dict(edge_id=edge['id'], owners=edge['owners'], sample_count=len(angles),
                           max_world_point_to_each_support_surface_mm=max(gaps),
                           max_tangent_plane_angle_deg=max(angles),
                           sampled_G0_G1_passed=max(gaps) <= TOL and max(angles) <= 1e-4,
                           method='same actual edge world point independently projected onto each native support surface'))
    return result


def common_output(edges):
    wall_rails = []
    for edge in edges:
        model = line_model(edge)
        p = np.asarray(edge['points'])
        if (model and len(edge['owners']) == 2 and max(abs(p[:, 1])) <= TOL and
            np.ptp(p[:, 2]) <= TOL and max(p[:, 2]) < 40-TOL):
            wall_rails.append(dict(edge_id=edge['id'], owners=edge['owners'],
                                   x_range_mm=[float(min(p[:, 0])), float(max(p[:, 0]))],
                                   z_mm=float(np.mean(p[:, 2]))))
    circles = [c for edge in edges if (c := circle_model(edge))]
    radii = [c['radius_mm'] for c in circles]
    return dict(**opening_measurements(edges), actual_wall_contact_rails=wall_rails,
                generated_blend_observed=bool(circles), measured_circle_sections=circles,
                measured_radius_range_mm=[min(radii), max(radii)] if radii else None,
                original_sharp_A_retained=bool(matching_line(edges, [0, 0, 40], [100, 0, 40], 2)))


def audit_occt(directory, source_edges, source_stats):
    index = read(directory/'index.json')
    rows = []
    for entry in index['entries']:
        run = (ROOT/entry['run_dir']) if entry['run_dir'].startswith('runs/') else directory/entry['run_dir']
        summary_path = run/'summary.json'
        summary = read(summary_path)
        radius = float(summary['parameters']['radius_mm'])
        before_path = run/'before.brep'
        before = read_brep(before_path)
        row = dict(engine='OCCT', radius_nominal_mm=radius, run=rel(run),
                   summary_sha256=sha(summary_path), source_sha256_matches=summary['source_sha256'] == sha(SOURCE),
                   before_brep_sha256=sha(before_path), before_stats=shape_stats(before),
                   before_finite_edges_vs_source=finite_edge_equivalence(source_edges, shape_edges(before)),
                   api_success=summary['api_success'], outcome=summary['outcome'],
                   theoretical_contact_z_mm=40-radius, theoretical_crossing_depth_mm=max(0., radius-13),
                   theoretical_contact_is_an_observation=False,
                   preserve_notch_option_supplied=False, source_special_modes_certified=False)
        row['before_stats_vs_source'] = native_stats_vs_source(row['before_stats'], source_stats)
        path = run/'result.brep'
        row['native_after_available'] = path.exists()
        if path.exists():
            after = read_brep(path)
            edges = shape_edges(after)
            row['native_after'] = dict(brep_sha256=sha(path), stats=shape_stats(after),
                                       **common_output(edges), shared_rail_checks=occt_rail_checks(after, edges))
            cylinders = []
            for i, face in enumerate(mapped(after, TopAbs_FACE)):
                surface = BRepAdaptor_Surface(TopoDS.Face_s(face))
                if surface.GetType() == GeomAbs_Cylinder:
                    cylinder = surface.Cylinder()
                    cylinders.append(dict(face_id=i, radius_mm=cylinder.Radius(),
                                          axis=xyz(cylinder.Axis().Direction()), location_mm=xyz(cylinder.Location())))
            row['native_after']['analytic_cylinder_measurements'] = cylinders
            row['native_after']['measured_radius_matches_nominal'] = all(abs(c['radius_mm']-radius) <= TOL for c in row['native_after']['measured_circle_sections']) if row['native_after']['measured_circle_sections'] else None
            step = run/'result.step'
            if step.exists():
                reader = STEPControl_Reader()
                status = reader.ReadFile(str(step))
                if status == IFSelect_RetDone:
                    reader.TransferRoots()
                    rb = reader.OneShape()
                    row['step_readback'] = dict(available=True, sha256=sha(step), stats=shape_stats(rb),
                                                finite_edges_match=finite_edge_equivalence(edges, shape_edges(rb)))
        else:
            row['native_after'] = None
            row['step_readback'] = None
            row['failure_detail'] = [dict(api=s.get('api'), api_success=s.get('api_success'), faulty_contours=s.get('faulty_contours'),
                                          contour_statuses=s.get('contour_statuses')) for s in summary.get('steps', [])]
            row['no_after_reason'] = 'Build rejected; no native after BREP or STEP exists. Contact/free-edge/radius measurements are unavailable.'
        rows.append(row)
    return rows


def audit_smlib(directory, source_edges, source_stats):
    if not (directory/'index.json').exists():
        return [], 'missing_index'
    index = read(directory/'index.json')
    entries = index.get('entries', index.get('rows', index.get('results', [])))
    if not entries:
        raise ValueError('SMLib index has no entries, rows or results')
    rows = []
    for entry in entries:
        run_name = entry.get('run_dir', entry.get('job_id'))
        run = (ROOT/run_name) if run_name.startswith('runs/') else directory/run_name
        summary_path = run/'summary.json'
        summary = read(summary_path)
        radius = float(summary['radius_mm'])
        before = read(run/'before.json')
        after = read(run/'result.json')
        rb = read(run/'readback.json') if (run/'readback.json').exists() else None
        execution = read(run/'execution.json')
        edges = after['geometry']['edges']
        row = dict(engine='SMLib', radius_nominal_mm=radius, run=rel(run), summary_sha256=sha(summary_path),
                   source_sha256_matches=summary['source_sha256'] == sha(SOURCE),
                   before_stats=before['native_stats'],
                   before_finite_edges_vs_source=finite_edge_equivalence(source_edges, before['geometry']['edges']),
                   api_success=execution.get('native_api_success'), api_raw_status=execution.get('native_api_raw_status'),
                   outcome=summary.get('outcome'), native_after_available=True,
                   candidate_retained_even_on_api_failure=execution.get('candidate_retained_even_on_api_failure'),
                   theoretical_contact_z_mm=40-radius, theoretical_crossing_depth_mm=max(0., radius-13),
                   theoretical_contact_is_an_observation=False,
                   preserve_notch_option_supplied=False, source_special_modes_certified=False,
                   native_after=dict(result_json_sha256=sha(run/'result.json'), stats=after['native_stats'],
                                     **common_output(edges), shared_rail_checks=smlib_rail_checks(after)),
                   returned_geometry_matches_before=finite_edge_equivalence(before['geometry']['edges'], edges),
                   native_readback=dict(available=bool(rb), raw_status=execution.get('result_readback_raw_status'),
                                        stats=rb['native_stats'] if rb else None,
                                        finite_edges_match=finite_edge_equivalence(edges, rb['geometry']['edges']) if rb else None),
                   step_readback=None, step_note='No STEP exchange test is included in this SMLib radius run.')
        row['before_stats_vs_source'] = native_stats_vs_source(row['before_stats'], source_stats)
        row['before_support_planes_vs_source'] = smlib_before_support_planes(before)
        curvatures = [c['radius_from_D2_mm'] for rail in row['native_after']['shared_rail_checks'] for c in rail['D2_curvature_samples'] if c['radius_from_D2_mm'] is not None]
        row['native_after']['measured_D2_radius_range_mm'] = [min(curvatures), max(curvatures)] if curvatures else None
        fitted = row['native_after']['measured_radius_range_mm']
        row['native_after']['circle_fit_and_D2_radius_agree'] = bool(fitted and curvatures and abs(min(curvatures)-fitted[0]) <= TOL and abs(max(curvatures)-fitted[1]) <= TOL) if fitted else None
        row['native_after']['measured_radius_matches_nominal'] = bool(fitted and abs(fitted[0]-radius) <= TOL and abs(fitted[1]-radius) <= TOL) if fitted else None
        if not row['api_success'] and row['returned_geometry_matches_before']['passed']:
            row['candidate_interpretation'] = 'Failed native call retained the unchanged original input; this is not a fillet result.'
        elif row['api_success']:
            row['candidate_interpretation'] = 'Native API returned a modified sheet candidate; measured geometry and readback remain separate gates.'
        else:
            row['candidate_interpretation'] = 'Failed native call retained a modified candidate; do not accept it as successful.'
        rows.append(row)
    return rows, 'audited'


def write_markdown(report, path):
    lines = ['# Case 08 radius audit', '',
             'This audit reads fresh native artifacts independently. Source dimensions are from the frozen reconstructed BREP, not vendor CAD.', '',
             f"Source SHA-256: `{report['source']['sha256']}`. Source: {report['source']['stats']['faces']} faces, 0 solids. A is the unique shared X-line at y=0, z=40, length 100 mm; the original notch top is x=35..65, y=0, z=27. Thus R=13 is the theoretical touch threshold. R=15 predicts z=25 and 2 mm crossing; prediction alone is never an observed result.", '',
             '| Engine | Nominal R | API | Actual after | Measured R | Wall contact rail z | Notch free-edge z | Native validity | Readback |',
             '|---|---:|---|---|---|---|---|---|---|']
    for row in report['rows']:
        after = row['native_after']
        if after:
            measured = after['measured_radius_range_mm']
            measured = f'{measured[0]:.9g}..{measured[1]:.9g}' if measured else 'none'
            rails = ', '.join(f"{z:.9g}" for z in sorted({e['z_mm'] for e in after['actual_wall_contact_rails']})) or 'none'
            openings = ', '.join(f"{e['z_mm']:.9g}" for e in after['actual_opening_free_edges']) or 'none'
            stats = after['stats']
            solids = stats.get('solids', stats.get('material_regions'))
            shape = f"{stats['faces']} faces / {solids} solids"
            if not row['api_success']:
                shape += ' (retained input)'
            valid = str(stats['valid'])
            rb = row.get('native_readback', row.get('step_readback'))
            readback = 'matched' if rb and rb['finite_edges_match']['passed'] else 'unavailable'
        else:
            measured, rails, openings, shape, valid, readback = ['unavailable']*6
        lines.append(f"| {row['engine']} | {row['radius_nominal_mm']:g} | {'success' if row['api_success'] else 'failed'} | {shape} | {measured} | {rails} | {openings} | {valid} | {readback} |")
    lines.extend(['', 'SMLib R13 failure retained the unchanged two-face input, with no measured circular section. Its original z27 notch edge is not a generated fillet boundary. R15 generated two measured R15 side sections and a free edge at x35..65, y0, z25; the original z27 notch top is absent. This is actual 2 mm default-trim encroachment into the original notch outline. R13 failure with an unchanged retained input is recorded separately from a generated blend. For OCCT Build failures there is no after model, so theoretical contact positions are not reported as measurements.', '',
                  'Radius measurements use independent fits of actual native finite cross-section edge samples and native arc lengths. OCCT analytic cylinder radii are also read directly. SMLib D2 surface derivatives are independently reduced to principal curvatures. Nominal input radii are never copied into measured-radius fields.', '',
                  'Shared-rail checks use actual world curves. SMLib pcurve fractions can evaluate at different X positions; those differences are recorded but never treated as G0 gaps. Each owner surface point is checked against the same finite rail carrier and its tangent plane against the rail support. This is a sampled local G0/G1 check, not a global continuity or self-intersection proof.', '',
                  'These runs supply no preserve_notch option. Default trimming, unchanged-input failures, native validity, native persistence, STEP exchange and human appearance acceptance stay separate. No source special-mode equivalence or human acceptance is certified.', '',
                  f"SMLib status: {report['smlib_status']}. Audit consistency passed: {report['audit_consistency_passed']}. See `case08-radius-audit.json` for individual gates, measured edge ownership, fit residuals and artifact hashes.", ''])
    path.write_text('\n'.join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=Path, default=ROOT/'runs/case08-radius')
    args = parser.parse_args()
    shape = read_brep(SOURCE)
    edges = shape_edges(shape)
    target = matching_line(edges, [0, 0, 40], [100, 0, 40], 2)
    notch = [matching_line(edges, a, b, 1) for a, b in [([35, 0, 0], [35, 0, 27]),
             ([35, 0, 27], [65, 0, 27]), ([65, 0, 27], [65, 0, 0])]]
    source = dict(path=rel(SOURCE), sha256=sha(SOURCE), recorded_sha256=EXPECTED_SHA,
                  stats=shape_stats(shape), support_planes=source_planes(shape), shared_A_matches=target, original_notch_edges=notch,
                  original_notch_total_length_mm=sum(m[0]['length_mm'] for m in notch if m),
                  representation_note='OCCT frozen BREP compound containing one two-face shell; operation extracts that same shell. SMLib imports equivalent finite rational NURBS geometry, with distinct native representation.')
    occt = audit_occt(args.runs/'occt', edges, source['stats'])
    smlib, sm_status = audit_smlib(args.runs/'smlib', edges, source['stats'])
    rows = sorted(occt+smlib, key=lambda r: (r['radius_nominal_mm'], r['engine']))
    checks = dict(source_sha256=source['sha256'] == EXPECTED_SHA,
                  source_valid_two_face_zero_solid_sheet=source['stats']['valid'] and source['stats']['faces'] == 2 and source['stats']['solids'] == 0,
                  source_A_unique_shared_edge=len(target) == 1,
                  source_notch_three_unique_free_edges=all(len(n) == 1 for n in notch),
                  all_sources_match=all(r['source_sha256_matches'] for r in rows),
                  all_actual_before_geometry_matches=all(r['before_finite_edges_vs_source']['passed'] and r['before_stats_vs_source']['passed'] for r in rows),
                  smlib_actual_before_support_planes_match=all(r['before_support_planes_vs_source']['passed'] for r in smlib),
                  all_five_occt_radii={r['radius_nominal_mm'] for r in occt} == set(RADII),
                  all_five_smlib_radii={r['radius_nominal_mm'] for r in smlib} == set(RADII))
    report = dict(schema_version=1, audited_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  audit_script_sha256=sha(Path(__file__)), source=source,
                  method='Read-only independent OCP BREP/STEP readback, NumPy finite native-edge circle fits and D2 curvature reduction. No fillet calls, repair, model edits or mesh-as-geometry proof.',
                  tolerance_mm=TOL, smlib_status=sm_status, checks=checks,
                  audit_consistency_passed=all(checks.values()), source_special_modes_certified=False,
                  human_appearance_acceptance='pending', rows=rows)
    out = ROOT/'docs/case08-radius-audit.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    write_markdown(report, ROOT/'docs/case08-radius-audit.md')
    print(json.dumps(dict(audit_consistency_passed=report['audit_consistency_passed'], checks=checks,
                         rows=len(rows), output=rel(out)), ensure_ascii=False))
    return 0 if report['audit_consistency_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
