#!/usr/bin/env python3
"""Replay five radii on the original case 08 shell and inspect native evidence.

Run with the pinned OCP environment used by adapters/occt/original/run.py.
The original adapter and fixtures are read only. Existing run directories are
never overwritten; --measure-only inspects an already completed sweep.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REQUEST = ROOT / 'adapters/occt/original/requests.json'
RUNNER = ROOT / 'adapters/occt/original/run.py'
VARIANTS = [(12, 'local-demo'), (13, 'r13-contact'), (14, 'r14-crossing'),
            (15, 'r15-crossing'), (18, 'r18-crossing')]
EXPECTED_SOURCE = '57ea045f7da3735141b7f21f2fbc3e3a51c39933d08a5d7c6e3374e01ab064f9'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    temp.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def requests():
    original = json.loads(SOURCE_REQUEST.read_text())
    base = next(j for j in original['jobs'] if j['job_id'] == '08.local-demo')
    assert base['source_sha256'] == EXPECTED_SOURCE
    assert base['preprocess'] == {'type': 'shell'}
    assert base['targets'][0]['start'] == [0.0, 0.0, 40.0]
    assert base['targets'][0]['end'] == [100.0, 0.0, 40.0]
    jobs = []
    for radius, variant in VARIANTS:
        job = copy.deepcopy(base)
        job['parameters']['radius_mm'] = float(radius)
        job['job_id'] = '08.' + variant
        job['original_variant_id'] = variant
        job['original_variant_ids'] = [variant]
        # A normalized equality gate ensures geometry, selection, preprocessing,
        # error thresholds and algorithm settings remain the frozen original.
        normalized = copy.deepcopy(job)
        for key in ['job_id', 'original_variant_id', 'original_variant_ids', 'parameters']:
            normalized[key] = base[key]
        assert normalized == base
        assert set(job['parameters']) == set(base['parameters'])
        assert job['parameters']['radius_mode'] == base['parameters']['radius_mode']
        jobs.append(job)
    result = {k: copy.deepcopy(v) for k, v in original.items()
              if k not in ['jobs', 'case_count', 'missing_fixtures']}
    result.update(suite='case08_radius_sweep_original_occ_native',
                  source_request_file=relative(SOURCE_REQUEST),
                  source_request_sha256=sha(SOURCE_REQUEST), source_job_id=base['job_id'],
                  changed_fields=['job_id', 'original_variant_id', 'original_variant_ids',
                                  'parameters.radius_mm'], case_count=1, jobs=jobs)
    return result


def compact_edge(g, shape, edge):
    record = g.edge_record(shape, edge)
    return {key: record[key] for key in
            ['start', 'end', 'length', 'curve_type', 'adjacent_faces_1based']}


def shape_measurements(g, shape):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE
    from OCP.TopoDS import TopoDS
    faces = []
    for index, raw in enumerate(g.shapes(shape, TopAbs_FACE), 1):
        face = TopoDS.Face_s(raw)
        adaptor = BRepAdaptor_Surface(face)
        row = {'face_index_1based': index, 'surface_type': str(adaptor.GetType()).split('.')[-1],
               'plane_signature': g.plane_signature(face),
               'boundary_edges': [compact_edge(g, shape, TopoDS.Edge_s(e))
                                  for e in g.shapes(face, TopAbs_EDGE)]}
        if adaptor.GetType() == GeomAbs_Cylinder:
            cylinder = adaptor.Cylinder()
            row['cylinder'] = {'radius_mm': cylinder.Radius(),
                               'axis_origin_mm': g.xyz(cylinder.Location()),
                               'axis_direction': g.xyz(cylinder.Axis().Direction())}
        faces.append(row)
    return {'stats': g.stats(shape), 'faces': faces}


def notch_measurements(g, before, candidate):
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopoDS import TopoDS
    edges = [compact_edge(g, before, TopoDS.Edge_s(e)) for e in g.shapes(before, TopAbs_EDGE)]
    # Locate the interior horizontal edge directly from the original BREP.
    roofs = [e for e in edges if e['curve_type'] == 'GeomAbs_Line'
             and max(abs(e['start'][1]), abs(e['end'][1])) < 1e-8
             and abs(e['start'][2] - e['end'][2]) < 1e-8
             and 0 < e['start'][2] < 40 and e['length'] < 100]
    assert len(roofs) == 1
    roof = roofs[0]
    x0, x1 = sorted([roof['start'][0], roof['end'][0]])
    notch_z = roof['start'][2]
    notch_edges = [e for e in edges if
                   all(abs(p[1]) < 1e-8 and x0 - 1e-8 <= p[0] <= x1 + 1e-8
                       and p[2] <= notch_z + 1e-8 for p in [e['start'], e['end']])]
    result = {'source': 'Measured original before.brep finite edges',
              'notch_x_interval_mm': [x0, x1], 'notch_roof_z_mm': notch_z,
              'original_notch_boundary_edges': notch_edges,
              'result_measurement_available': candidate is not None}
    if candidate is None:
        result['result_note'] = 'Build produced no accepted result; actual notch trimming cannot be measured.'
        return result
    output = [compact_edge(g, candidate, TopoDS.Edge_s(e)) for e in g.shapes(candidate, TopAbs_EDGE)]
    same = []
    for old in notch_edges:
        matches = [e for e in output if min(
            max(g.distance(e['start'], old['start']), g.distance(e['end'], old['end'])),
            max(g.distance(e['end'], old['start']), g.distance(e['start'], old['end']))) < 1e-7
                   and abs(e['length'] - old['length']) < 1e-7]
        same.append({'before_edge': old, 'matching_result_edges': matches,
                     'unchanged_finite_curve': len(matches) == 1})
    measure = shape_measurements(g, candidate)
    wall_contact = []
    for face in measure['faces']:
        if 'cylinder' not in face:
            continue
        for edge in face['boundary_edges']:
            if edge['curve_type'] == 'GeomAbs_Line' and all(abs(p[1]) < 1e-7
                    for p in [edge['start'], edge['end']]):
                wall_contact.append(edge)
    result.update(notch_boundary_comparison=same,
                  all_three_notch_edges_unchanged=len(same) == 3 and all(e['unchanged_finite_curve'] for e in same),
                  measured_cylinder_wall_contact_edges=wall_contact)
    if wall_contact:
        result['measured_wall_contact_z_mm'] = min(p[2] for e in wall_contact for p in [e['start'], e['end']])
        result['measured_clearance_above_notch_mm'] = result['measured_wall_contact_z_mm'] - notch_z
    return result


def native_diagnostics(g, job, before, summary, out):
    from OCP.BRep import BRep_Tool
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    from OCP.BRepTools import BRepTools
    from OCP.ChFi3d import ChFi3d_Rational
    from OCP.GeomAdaptor import GeomAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.TopoDS import TopoDS
    from OCP.TopAbs import TopAbs_EDGE
    # Reconstruct from source rather than relying on the runner's mesh output.
    source = ROOT / job['source_brep']
    assert sha(source) == job['source_sha256']
    fresh = g.preprocess(g.read(source), job)
    equivalence = g.equivalent(fresh, before)
    assert equivalence['passed']
    selected, selection = g.select(fresh, job['targets'])
    assert len(selected) == 1
    assert digest(selection) == digest(summary['selection'])
    radius = float(job['parameters']['radius_mm'])
    builder = BRepFilletAPI_MakeFillet(fresh, ChFi3d_Rational)
    builder.Add(radius, selected[0])
    builder.Build()
    contours = []
    for ci in range(1, builder.NbContours() + 1):
        surfaces = []
        for si in range(1, builder.NbComputedSurfaces(ci) + 1):
            surface = builder.ComputedSurface(ci, si)
            adaptor = GeomAdaptor_Surface(surface)
            record = {'surface_index_1based': si,
                      'surface_type': str(adaptor.GetType()).split('.')[-1],
                      'boundary': 'Untrimmed intermediate support; not an accepted result face.'}
            if adaptor.GetType() == GeomAbs_Cylinder:
                cylinder = adaptor.Cylinder()
                record['cylinder'] = {'radius_mm': cylinder.Radius(),
                                      'axis_origin_mm': g.xyz(cylinder.Location()),
                                      'axis_direction': g.xyz(cylinder.Axis().Direction())}
            surfaces.append(record)
        contours.append({'contour_index_1based': ci, 'edge_count': builder.NbEdges(ci),
                         'length_mm': builder.Length(ci),
                         'first_vertex_mm': g.xyz(BRep_Tool.Pnt_s(builder.FirstVertex(ci))),
                         'last_vertex_mm': g.xyz(BRep_Tool.Pnt_s(builder.LastVertex(ci))),
                         'edges': [compact_edge(g, fresh, builder.Edge(ci, ei))
                                   for ei in range(1, builder.NbEdges(ci) + 1)],
                         'computed_surfaces': surfaces})
    fault_contours = [{'fault_index_1based': i, 'contour_index_1based': builder.FaultyContour(i),
                       'stripe_status': str(builder.StripeStatus(builder.FaultyContour(i))).split('.')[-1]}
                      for i in range(1, builder.NbFaultyContours() + 1)]
    fault_vertices = [{'fault_index_1based': i,
                       'point_mm': g.xyz(BRep_Tool.Pnt_s(builder.FaultyVertex(i)))}
                      for i in range(1, builder.NbFaultyVertices() + 1)]
    native = {'api': 'BRepFilletAPI_MakeFillet(before, ChFi3d_Rational); Add(radius, original_edge); Build()',
              'settings': {'fillet_shape': 'ChFi3d_Rational', 'continuity': 'default_internal_C1',
                           'radius_mode': 'constant', 'radius_mm': radius,
                           'tolerance_overrides': [], 'additional_algorithm_options': []},
              'isDone': bool(builder.IsDone()), 'hasResult': bool(builder.HasResult()),
              'faultyContourCount': builder.NbFaultyContours(),
              'faultyVertexCount': builder.NbFaultyVertices(),
              'faultContours': fault_contours, 'faultVertices': fault_vertices, 'contours': contours,
              'precise_failure_point_available': bool(fault_vertices),
              'failure_location_note': ('Native fault vertices are the only point locations reported here. '
                  'Contour endpoints identify the selected contour and are not failure points. '
                  'ChFiDS_Error supplies no more specific cause.')}
    assert native['isDone'] == summary['api_success']
    partial = None
    if not native['isDone'] and native['hasResult']:
        partial = builder.BadShape()
        if not partial.IsNull():
            path = out / 'diagnostic-partial-result.brep'
            assert BRepTools.Write_s(partial, str(path))
            write(out / 'diagnostic-partial-result.mesh.json', g.mesh(partial))
            native['partial_candidate'] = {'brep': path.name, 'sha256': sha(path), 'inspection': g.inspect(partial)}
    native['candidate_retained'] = native['isDone'] or bool(partial is not None and not partial.IsNull())
    result_path = out / 'result.brep'
    candidate = g.read(result_path) if result_path.is_file() and summary['api_success'] else None
    notch = notch_measurements(g, before, candidate)
    return {'schema_version': 1, 'job_id': job['job_id'], 'source_sha256': job['source_sha256'],
            'source_request_sha256': sha(SOURCE_REQUEST), 'request_sha256': digest(job),
            'before_brep_sha256': sha(out / 'before.brep'), 'selection_sha256': digest(selection),
            'independent_source_preprocess_vs_saved_before': equivalence,
            'raw': {'native': native, 'step': {
                'export_attempted': 'step_settings' in summary,
                'settings': summary.get('step_settings'),
                'roundtrip': summary.get('step_roundtrip'),
                'boundary': 'STEP settings and readback gates are separate from native Build completion.'}},
            'before_measurement': shape_measurements(g, before),
            'result_measurement': shape_measurements(g, candidate) if candidate is not None else None,
            'notch_measurement': notch,
            'theoretical_reference': {'label': 'Ideal right-angle construction reference; not an OCC result.',
                'formula': 'contactZ = 40 - R', 'contact_z_mm': 40.0 - radius,
                'source_notch_roof_z_mm': notch['notch_roof_z_mm'],
                'signed_clearance_above_notch_mm': 40.0 - radius - notch['notch_roof_z_mm']}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requests', type=Path, default=ROOT / 'data/case08-radius/occ-requests.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'runs/case08-radius/occt')
    parser.add_argument('--measure-only', action='store_true')
    args = parser.parse_args()
    request_path, output = args.requests.resolve(), args.output.resolve()
    relative(request_path)
    relative(output)
    expected = requests()
    if request_path.exists():
        if json.loads(request_path.read_text()) != expected:
            parser.error('Existing request differs from the strictly cloned original case 08 sweep')
    else:
        write(request_path, expected)
    adapter_paths = [RUNNER, RUNNER.with_name('geometry.py'), ROOT / 'adapters/occt/run.py', SOURCE_REQUEST]
    adapter_hashes = {relative(p): sha(p) for p in adapter_paths}
    if not args.measure_only:
        if any(output.glob('*/summary.json')):
            parser.error('Existing run evidence is preserved; choose a new --output or use --measure-only')
        subprocess.run([sys.executable, str(RUNNER), '--requests', str(request_path),
                        '--output', str(output)], cwd=ROOT, check=True)
    sys.path.insert(0, str(RUNNER.parent))
    import geometry as g
    index_path = output / 'index.json'
    index = json.loads(index_path.read_text())
    rows, audits = [], []
    for job in expected['jobs']:
        out = output / job['job_id']
        summary_path = out / 'summary.json'
        summary = json.loads(summary_path.read_text())
        assert summary['request_sha256'] == digest(job)
        assert summary['adapter_sha256'] == adapter_hashes[relative(RUNNER)]
        assert summary['effective_parameters']['radius_mm'] == job['parameters']['radius_mm']
        before = g.read(out / 'before.brep')
        audit = native_diagnostics(g, job, before, summary, out)
        audit_path = out / 'native-diagnostics.json'
        write(audit_path, audit)
        audits.append(audit)
        row = next(copy.deepcopy(r) for r in index['rows'] if r['job_id'] == job['job_id'])
        row.update(number=8, variant_id=job['original_variant_id'], radius_mm=job['parameters']['radius_mm'],
                   summary=relative(summary_path), run_dir=relative(out), request_file=relative(request_path),
                   source_brep=job['source_brep'], source_sha256=job['source_sha256'],
                   source_request_file=relative(SOURCE_REQUEST), source_job_id='08.local-demo',
                   effective_parameters=summary['effective_parameters'],
                   operation_input_sha256=summary['operation_input_sha256'],
                   native_diagnostics=relative(audit_path),
                   precise_failure_point_available=audit['raw']['native']['precise_failure_point_available'])
        rows.append(row)
    assert adapter_hashes == {relative(p): sha(p) for p in adapter_paths}
    before_hashes = sorted(set(a['before_brep_sha256'] for a in audits))
    selected_hashes = sorted(set(a['selection_sha256'] for a in audits))
    assert len(before_hashes) == len(selected_hashes) == 1
    index.update(suite='case08_radius_sweep_original_occ_native', rows=rows, entries=rows,
                 counts=dict(Counter(r['outcome'] for r in rows)), request_file=relative(request_path),
                 source_sha256=EXPECTED_SOURCE, source_job_id='08.local-demo',
                 adapter_hashes_unchanged=adapter_hashes,
                 measured_same_input={'passed': True, 'before_brep_sha256': before_hashes[0],
                                      'selected_curve_record_sha256': selected_hashes[0], 'job_count': len(rows)},
                 measured_at=datetime.now(timezone.utc).isoformat())
    write(index_path, index)
    print(json.dumps({'counts': index['counts'], 'same_input': index['measured_same_input'],
                      'index': relative(index_path)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
