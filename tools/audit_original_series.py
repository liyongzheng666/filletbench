#!/usr/bin/env python3
"""Read-only audit of original OCC source, target, parameter and run bindings.

Run with the pinned OCP Python and --source-root pointing to the private review
workspace. Only docs/original-series-audit.{json,md} are written. No modelling
adapter is imported, no fillet is rebuilt, and no private file is modified.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.BRepTools import BRepTools
from OCP.BOPAlgo import BOPAlgo_ArgumentAnalyzer
from OCP.GProp import GProp_GProps
from OCP.STEPControl import STEPControl_Controller, STEPControl_Reader
from OCP.Interface import Interface_Static
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID, TopAbs_VERTEX
from OCP.TopExp import TopExp
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.gp import gp_Pnt

from audit_original_smlib_column import case11_revision_checks, repository_file

REPO = Path(__file__).resolve().parents[1]
TOL = 1e-5
MACHINE = re.compile(r'/(?:Users|home|private|tmp|opt|Applications|Volumes)/')
MEDIA = re.compile(r'^\S+\.(?:pdf|png|jpe?g|gif|webp|svg)(?:[?#]\S*)?$', re.I)


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def distance(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def xyz(p):
    return [p.X(), p.Y(), p.Z()]


def shapes(shape, kind):
    result = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, result)
    return [result.FindKey(i) for i in range(1, result.Extent() + 1)]


def brep(path):
    shape = TopoDS_Shape()
    if not BRepTools.Read_s(shape, str(path), BRep_Builder()) or shape.IsNull():
        raise ValueError('BREP could not be read')
    return shape


def mass(shape, name):
    properties = GProp_GProps()
    getattr(BRepGProp, name + 'Properties_s')(shape, properties)
    return properties.Mass()


def stats(shape):
    return dict(valid=bool(BRepCheck_Analyzer(shape, True).IsValid()),
                faces=len(shapes(shape, TopAbs_FACE)), edges=len(shapes(shape, TopAbs_EDGE)),
                vertices=len(shapes(shape, TopAbs_VERTEX)), shells=len(shapes(shape, TopAbs_SHELL)),
                solids=len(shapes(shape, TopAbs_SOLID)), area_mm2=mass(shape, 'Surface'))


def point_distance(point, shape):
    check = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*point)).Vertex(), shape)
    check.Perform()
    if not check.IsDone():
        raise ValueError('Finite point-to-shape distance failed')
    return check.Value()


def samples(target):
    for key in ('samples_mm', 'polyline_mm', 'polyline', 'points', 'endpoints', 'vertices'):
        pts = target.get(key)
        if pts and isinstance(pts[0], (list, tuple)) and len(pts[0]) == 3:
            return pts
    return [target[k] for k in ('start', 'midpoint', 'end') if k in target]


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


class Audit:
    def __init__(self, source_root, repo):
        self.root, self.repo = source_root.resolve(), repo.resolve()
        self.review = self.root / 'outputs/manual-review'
        self.issues, self.notes, self.case_rows, self.native_rows, self.composition_rows = [], [], [], [], []
        self._geometry, self._targets = {}, {}
        self.g2_rows = []

    def require(self, condition, code, **context):
        if not condition:
            self.issues.append(dict(code=code, **context))
        return bool(condition)

    def resolve_source(self, value):
        if not isinstance(value, str):
            return None
        value = value.removeprefix('history:')
        path = Path(value)
        candidates = [path] if path.is_absolute() else [self.root / path, self.review / path, self.repo / path]
        return next((p for p in candidates if p.is_file()), None)

    def geometry(self, path):
        digest = sha(path)
        if digest not in self._geometry:
            shape = brep(path)
            faces, edges = shapes(shape, TopAbs_FACE), shapes(shape, TopAbs_EDGE)
            records = []
            for i, raw in enumerate(edges, 1):
                edge = TopoDS.Edge_s(raw)
                if BRep_Tool.Degenerated_s(edge):
                    continue
                curve = BRepAdaptor_Curve(edge)
                owners = [j for j, face in enumerate(faces, 1)
                          if any(edge.IsSame(e) for e in shapes(face, TopAbs_EDGE))]
                records.append(dict(index=i, edge=edge, length_mm=mass(edge, 'Linear'), owners=owners,
                                    ends=[xyz(curve.Value(curve.FirstParameter())), xyz(curve.Value(curve.LastParameter()))]))
            self._geometry[digest] = shape, stats(shape), records
        return digest, self._geometry[digest]

    def target(self, path, target, require_adjacency=False):
        digest, (_, _, edges) = self.geometry(path)
        key = digest, json.dumps(target, sort_keys=True), require_adjacency
        if key in self._targets:
            return self._targets[key]
        pts = samples(target)
        closed_circle = len(pts) == 1 and target.get('curve', target.get('curve_type')) in ('Circle', 'GeomAbs_Circle') and target.get('center') and target.get('length')
        if len(pts) < 2 and not closed_circle:
            return dict(status='no_finite_world_samples', matching_edge_indices=[])
        expected = target.get('length', target.get('length_mm'))
        owners = target.get('required_support_adjacency_count')
        if owners is None and require_adjacency:
            owners = len(target.get('adjacent_faces_1based', target.get('adjacent_faces', [1, 2])))
        matches = []
        for record in edges:
            a, b = record['ends']
            gap = min(max(distance(a, pts[0]), distance(b, pts[-1])),
                      max(distance(a, pts[-1]), distance(b, pts[0])))
            if gap > TOL or (expected is not None and abs(record['length_mm'] - expected) > max(TOL, abs(expected) * 1e-7)):
                continue
            if owners is not None and len(record['owners']) != owners:
                continue
            if closed_circle:
                curve = BRepAdaptor_Curve(record['edge'])
                if not str(curve.GetType()).endswith('GeomAbs_Circle') or distance(xyz(curve.Circle().Location()), target['center']) > TOL:
                    continue
                if abs(record['length_mm'] - 2*math.pi*curve.Circle().Radius()) > TOL:
                    continue
            residual = max(point_distance(p, record['edge']) for p in pts)
            if residual <= TOL:
                matches.append(dict(index_1based=record['index'], adjacent_faces_1based=record['owners'],
                                    length_mm=record['length_mm'], endpoint_residual_mm=gap,
                                    max_finite_sample_residual_mm=residual))
        claimed = target.get('index_1based')
        result = dict(status='matched' if matches else 'not_on_this_finite_input', sample_count=len(pts),
                      matching_edge_indices=[m['index_1based'] for m in matches], matches=matches,
                      claimed_index_1based=claimed,
                      claimed_index_matches=(claimed in [m['index_1based'] for m in matches]) if claimed else None)
        self._targets[key] = result
        return result

    def frozen(self):
        source_path = self.review / 'review-state.json'
        self.initial_review_hash = sha(source_path)
        raw = read(source_path)
        index = read(self.repo / 'data/original-occ/index.json')
        manifest = read(self.repo / 'data/original-occ/manifest.json')
        self.index, self.raw_cases, self.cases = index, {c['number']: c for c in raw['items']}, {}
        expected = list(range(1, 29)) + list(range(30, 37))
        self.require([c['number'] for c in index['cases']] == expected, 'original_case_numbers_changed')
        self.require(index['source_review_state_sha256'] == self.initial_review_hash == manifest['source_review_state']['sha256'], 'review_source_hash_changed')
        self.require(sha(self.root / 'work/occ-coverage-audit.json') == manifest['source_coverage_audit']['sha256'], 'source_coverage_audit_hash_changed')
        self.require(index['model_groups'] == 34 and index['explanation_only'] == [32], 'model_explanation_counts_changed')
        for entry in index['cases']:
            n = entry['number']; case_path = self.repo / entry['path']; case = read(case_path)
            self.cases[n] = case; raw_case = self.raw_cases[n]
            self.require(sha(case_path) == entry['sha256'], 'frozen_case_json_hash_mismatch', number=n)
            self.require(case['human_status'] == raw_case.get('status'), 'human_status_changed', number=n)
            if not case['has_model']:
                self.require(n == 32 and not case['source_brep'] and not case['variants'], 'explanation_page_has_geometry', number=n)
                self.case_rows.append(dict(number=n, has_model=False)); continue
            origin = self.resolve_source(raw_case['files']['brep'])
            actual = sha(origin) if origin else None
            self.require(actual == case['source_sha256'] == entry['source_sha256'] == sha(self.repo / case['source_brep']), 'current_base_bytes_mismatch', number=n)
            self.require(raw_case.get('snapshot', {}).get('brep_sha256') == actual == case['recorded_source_sha256'], 'current_snapshot_hash_mismatch', number=n)
            base = self.repo / case['source_brep']; _, (_, st, _) = self.geometry(base)
            base_checks = [self.target(base, t) for t in case['base_targets']]
            for ti, check in enumerate(base_checks):
                self.require(bool(check['matching_edge_indices']), 'base_target_not_on_original_base', number=n, target=ti)
                self.require(check.get('claimed_index_matches') is not False, 'base_target_index_is_not_global_on_base', number=n, target=ti, check=check)
            raw_variants = {v['id']: v for v in raw_case.get('variants', [])}
            if raw_variants:
                self.require(set(raw_variants) == {v['id'] for v in case['variants']}, 'review_variant_set_changed', number=n)
            else:
                original_summary = self.resolve_source(raw_case.get('test_spec', {}).get('batch_execution', {}).get('summary_file'))
                if original_summary:
                    plans = read(original_summary).get('plan', {}).get('parts', [])
                    expected_radii = [(pi, radius) for pi, plan in enumerate(plans, 1) for radius in plan.get('radii', [])]
                    actual_radii = [(v['parameters'].get('part_number'), v['radius_mm']) for v in case['variants']]
                    self.require(actual_radii == expected_radii, 'original_planned_parts_radii_or_order_changed', number=n)
            op_rows = []
            for variant in case['variants']:
                vid = variant['id']
                self.require(variant['base_sha256'] == actual and variant['base_brep'] == case['source_brep'], 'variant_base_replaced_by_prepared_input', number=n, variant=vid)
                if vid in raw_variants:
                    raw_v = raw_variants[vid]
                    self.require(raw_v.get('demo', {}).get('radius') == variant['radius_mm'], 'original_display_radius_changed', number=n, variant=vid)
                    self.require(raw_v.get('parameter_summary') == variant['parameters'].get('summary') and raw_v.get('demo', {}).get('radius_text') == variant['parameters'].get('radius_text'), 'original_parameter_description_changed', number=n, variant=vid)
                for op in variant['operation_inputs']:
                    op_path = self.repo / op['brep']
                    self.require(sha(op_path) == op['sha256'] == op['selection_sha256'], 'frozen_operation_hash_mismatch', number=n, variant=vid)
                    checks = [self.target(op_path, t) for t in op['selected_edges']]
                    for ti, check in enumerate(checks):
                        self.require(bool(check['matching_edge_indices']), 'operation_target_not_on_frozen_input', number=n, variant=vid, target=ti)
                        self.require(check.get('claimed_index_matches') is not False, 'operation_target_index_mismatch', number=n, variant=vid, target=ti, check=check)
                    op_rows.append(dict(variant_id=vid, sha256=op['sha256'], same_bytes_as_base=op['sha256'] == actual, targets=checks))
            self.case_rows.append(dict(number=n, has_model=True, source_sha256=actual, original_base_stats=st,
                                       base_targets=base_checks, operation_inputs=op_rows))
        for artifact in manifest['artifacts']:
            self.require(sha(self.repo / artifact['path']) == artifact['sha256'], 'manifest_fixture_hash_mismatch', path=artifact['path'])
            for value in artifact['original_paths']:
                source = self.resolve_source(value)
                self.require(source is not None and sha(source) == artifact['sha256'], 'original_fixture_origin_drifted', fixture=artifact['path'], origin=value)
        for doc in manifest['history_documents']:
            self.require(sha(self.repo / doc['path']) == doc['sanitized_sha256'], 'sanitized_history_hash_mismatch', path=doc['path'])
            source = self.resolve_source(doc['original_path'])
            self.require(source is not None and sha(source) == doc['original_sha256'], 'original_history_document_drifted', path=doc['path'])
        self.manifest = manifest

    def native(self):
        requests_path = self.repo / 'adapters/occt/original/requests.json'
        requests = read(requests_path); index = read(self.repo / 'runs/original-occ-native/index.json')
        indexed = {x['job_id']: x for x in index['entries']}; self.jobs = requests['jobs']
        self.require(requests['source_review_state_sha256'] == self.initial_review_hash, 'native_requests_from_other_review_state')
        self.require(index['request_sha256'] == sha(requests_path), 'native_index_request_hash_stale')
        self.require(set(indexed) == {j['job_id'] for j in self.jobs}, 'native_index_job_set_mismatch')
        for job in self.jobs:
            jid = job['job_id']; n = job['case_number']; path = self.repo / 'runs/original-occ-native' / jid / 'summary.json'
            if not self.require(path.is_file(), 'native_summary_missing', job_id=jid): continue
            summary = read(path); entry = indexed.get(jid, {})
            self.require(entry.get('summary_sha256') == sha(path), 'native_index_summary_hash_stale', job_id=jid)
            self.require(summary['request_sha256'] == hashlib.sha256(json.dumps(job, sort_keys=True, ensure_ascii=False).encode()).hexdigest(), 'native_actual_request_hash_changed', job_id=jid)
            self.require(summary['adapter_sha256'] == sha(self.repo / 'adapters/occt/original/run.py') and summary['geometry_helper_sha256'] == sha(self.repo / 'adapters/occt/original/geometry.py'), 'native_executed_code_differs_from_frozen_adapter', job_id=jid)
            self.require(summary['parameters'] == job['parameters'], 'native_requested_parameters_changed', job_id=jid)
            frozen_variant = next((v for v in self.cases[n]['variants'] if v['id'] in job['original_variant_ids']), None)
            if frozen_variant and frozen_variant.get('radius_mm') is not None:
                self.require(job['parameters'].get('radius_mm') == frozen_variant['radius_mm'], 'native_radius_differs_from_original_review_variant', job_id=jid)
            original_record = job.get('historical', {}).get('record', {})
            original_radius = original_record.get('radius_mm', original_record.get('radius'))
            if original_radius is not None and job['parameters']['radius_mode'] == 'constant':
                self.require(original_radius == job['parameters']['radius_mm'], 'native_radius_differs_from_original_attempt', job_id=jid)
            self.require(summary['source_sha256'] == job['source_sha256'] == self.cases[n]['source_sha256'] == sha(self.repo / job['source_brep']), 'native_source_not_current_original', job_id=jid)
            self.require(summary['original_case_number'] == n and summary['original_variant_id'] == job['original_variant_id'], 'native_case_variant_binding_changed', job_id=jid)
            self.require(summary.get('special_feature_certified') is False and summary.get('human_appearance_acceptance') == 'pending', 'native_control_promoted_to_special_or_human_pass', job_id=jid)
            self.require(summary.get('process', {}).get('returncode') == 0 and summary.get('outcome') in {
                'native_and_step_passed', 'native_rejected', 'step_roundtrip_failed', 'native_quality_failed',
                'selection_rejected', 'input_rejected', 'geometry_failed'}, 'native_run_did_not_finish', job_id=jid)
            before = path.parent / 'before.brep'
            self.require(before.is_file() and sha(before) == summary.get('operation_input_sha256'), 'native_actual_before_not_hash_bound', job_id=jid)
            checks = [self.target(before, t, True) for t in job['targets']]
            for ti, check in enumerate(checks):
                self.require(len(check['matching_edge_indices']) == 1, 'native_original_target_not_unique_on_actual_before', job_id=jid, target=ti, check=check)
            if summary.get('native_call_executed'):
                effective = summary.get('effective_parameters', {})
                self.require(all(effective.get(k) == v for k, v in job['parameters'].items()), 'native_effective_parameters_changed', job_id=jid)
            if job['source_revision'] == 'source_revision_mismatch':
                self.require(job['track'] == 'historical_batch_native' and summary['preprocess']['execution_mode'] == 'frozen_prepared_input_replay', 'obsolete_operation_is_current_default', job_id=jid)
            for step in summary.get('steps', []):
                if job['parameters']['radius_mode'] != 'two_end_variable': continue
                binding = step.get('radius_binding', {}); parameters = job['parameters']
                pairs = [(binding.get('contour_first_mm'), binding.get('contour_first_radius_mm')),
                         (binding.get('contour_last_mm'), binding.get('contour_last_radius_mm'))]
                for point_key, radius_key in [('physical_start_mm', 'start_radius_mm'), ('physical_end_mm', 'end_radius_mm')]:
                    found = [r for p, r in pairs if p and distance(p, parameters[point_key]) < TOL]
                    self.require(len(found) == 1 and found[0] == parameters[radius_key], 'native_physical_endpoint_radius_swapped', job_id=jid)
            if summary.get('api_success'):
                self.require((path.parent / 'result.brep').is_file() and 'step_roundtrip' in summary, 'native_candidate_or_step_gate_dropped', job_id=jid)
                settings = summary.get('step_settings', {})
                expected_settings = {'write.surfacecurve.mode': 1, 'write.precision.mode': 0, 'read.surfacecurve.mode': 0}
                self.require(settings.get('controller_initialized') is True and settings.get('effective') == expected_settings and
                             settings.get('set_succeeded') == {k: True for k in expected_settings}, 'native_step_settings_not_actually_applied', job_id=jid)
            if summary['outcome'] == 'native_and_step_passed':
                self.require(summary['native']['passed'] and summary['step_roundtrip']['passed'], 'native_combined_pass_contradicts_gates', job_id=jid)
            self.native_rows.append(dict(job_id=jid, number=n, variant_ids=job['original_variant_ids'], track=job['track'],
                                         execution_mode=summary['preprocess']['execution_mode'],
                                         base_evidence='read frozen current base BREP; apply declared preparation or replay frozen prepared BREP',
                                         outcome=summary['outcome'], parameters=summary['parameters'],
                                         api_success=summary['api_success'], native_passed=summary.get('native', {}).get('passed'),
                                         step_passed=summary.get('step_roundtrip', {}).get('passed'),
                                         actual_before_sha256=summary.get('operation_input_sha256'), original_target_checks=checks,
                                         summary=path.relative_to(self.repo).as_posix(), summary_sha256=sha(path)))
        self.native_index = index

    def compositions(self):
        index = read(self.repo / 'runs/original-occ-compositions/index.json'); self.composition_index = index
        for row in index['rows']:
            n, vid = row['number'], row['variant_id']
            self.require(row['source_sha256'] == self.cases[n]['source_sha256'], 'composition_source_not_current_original', number=n, variant=vid)
            self.require(row.get('source_feature_certified') is False and row.get('native_special_feature_api_used') is False, 'composition_promoted_to_native_special_pass', number=n, variant=vid)
            variants = {v['id']: v for v in self.cases[n]['variants']}
            self.require(vid in variants, 'composition_variant_not_in_original_review', number=n, variant=vid)
            exrows = []
            for execution in row['executions']:
                path = self.repo / execution['summary']; summary = read(path)
                self.require(sha(path) == execution['summary_sha256'], 'composition_summary_hash_stale', number=n, variant=vid)
                self.require(execution['parameters'] == summary['parameters'], 'composition_effective_parameters_changed', number=n, variant=vid)
                if summary.get('source_sha256'):
                    self.require(summary['source_sha256'] == self.cases[n]['source_sha256'], 'composition_summary_source_changed', number=n, variant=vid)
                if n in (33, 34):
                    self.require(summary['parameters'] == variants[vid]['parameters']['construction'], 'original_two_range_or_rho_dimensions_changed', number=n, variant=vid)
                before = path.parent / execution['artifacts']['before_brep']
                result_name = execution['artifacts'].get('result_brep')
                result = path.parent / result_name if result_name else None
                self.require(before.is_file() and result is not None and result.is_file(), 'composition_candidate_dropped', number=n, variant=vid)
                before_sha, (_, before_stats, _) = self.geometry(before)
                result_sha, (_, result_stats, _) = self.geometry(result)
                recorded_result_sha = summary.get('result', {}).get('brep_sha256')
                self.require(recorded_result_sha == result_sha, 'composition_result_hash_mismatch', number=n, variant=vid)
                selection = summary.get('selection', [])
                if isinstance(selection, dict):
                    points = selection.get('samples_mm', [])
                    selection = [selection] if points and len(points[0]) == 3 and isinstance(points[0][0], (float, int)) else [{'samples_mm': p} for p in points]
                checks = [self.target(before, target) for target in selection]
                for ti, check in enumerate(checks):
                    self.require(bool(check['matching_edge_indices']), 'composition_target_not_on_actual_before', number=n, variant=vid, target=ti)
                exrows.append(dict(summary=execution['summary'], summary_sha256=sha(path), outcome=summary.get('outcome'),
                                   before_sha256=before_sha, result_sha256=result_sha, before_stats=before_stats,
                                   result_stats=result_stats, original_target_checks=checks,
                                   step_roundtrip='not independently rerun in this composition audit'))
            self.composition_rows.append(dict(number=n, variant_id=vid, method=row['method'], executions=exrows))

    def specific_contracts(self):
        result = {}
        case24 = self.cases[24]
        targets = case24['base_targets']
        vectors = [[p[-1][i] - p[0][i] for i in range(3)] for p in [samples(t) for t in targets[:2]]]
        cosine = abs(sum(a * b for a, b in zip(*vectors))) / math.prod(math.sqrt(sum(x * x for x in v)) for v in vectors)
        angle = math.degrees(math.acos(min(1, cosine)))
        self.require(30 < angle < 50, 'case24_parallel_old_source_substituted')
        result['case24'] = dict(source_sha256=case24['source_sha256'], independent_root_angle_deg=angle,
                                current_oblique_source=True, historical_batch_track_is_separate=True)
        case36 = self.cases[36]; _, (shape, st, _) = self.geometry(self.repo / case36['source_brep'])
        fs = shapes(shape, TopAbs_FACE); dist = BRepExtrema_DistShapeShape(fs[0], fs[1]); dist.Perform()
        gap = dist.Value()
        self.require(st['faces'] == 2 and st['shells'] == 0 and gap > TOL and not case36['base_targets'], 'case36_prepared_shell_replaced_original_disjoint_faces')
        result['case36'] = dict(original_faces=st['faces'], original_shells=st['shells'], independent_finite_face_gap_mm=gap,
                                base_has_shared_target_edge=False, prepared_operation_is_extended_overlap_band=True)
        native22 = read(self.repo / 'runs/original-occ-native/22.part01-r6/summary.json')
        historical22 = next(v for v in self.cases[22]['variants'] if v['id'] == 'part01-r6')
        historical = historical22['source_spec'].get('attempt') or {}
        step = self.repo / 'runs/original-occ-native/22.part01-r6/result.step'
        STEPControl_Controller.Init_s(); Interface_Static.SetIVal_s('read.surfacecurve.mode', 0)
        reader = STEPControl_Reader(); reader.ReadFile(str(step)); reader.TransferRoots(); restored = reader.OneShape()
        check = BOPAlgo_ArgumentAnalyzer(); check.SetShape1(restored)
        for key in ('ArgumentTypeMode', 'SelfInterMode', 'SmallEdgeMode', 'RebuildFaceMode', 'ContinuityMode', 'CurveOnSurfaceMode'):
            setattr(check, key, True)
        check.StopOnFirstFaulty = False; check.Perform()
        faults = [str(v.GetCheckStatus()).split('.')[-1] for v in check.GetCheckResult()]
        self.require(native22['parameters']['radius_mm'] == 6 and native22['native']['passed'] and not native22['step_roundtrip']['passed'], 'case22_radius_or_gate_regression')
        self.require('BOPAlgo_InvalidCurveOnSurface' in faults, 'case22_independent_step_failure_not_reproduced')
        historical_step_failed = historical.get('status') == 'failed' and 'roundtrip_step' in historical.get('traceback', '') and 'BOPAlgo_InvalidCurveOnSurface' in historical.get('error', '')
        self.require(historical_step_failed and historical.get('checks', {}).get('native_check_passed') is True,
                     'case22_old_step_failure_dropped')
        result['case22'] = dict(radius_mm=6, native_passed=native22['native']['passed'], historical_status=historical.get('status'),
                                historical_step_passed=False if historical_step_failed else None, fresh_step_passed=False,
                                independent_step_brepcheck_valid=bool(BRepCheck_Analyzer(restored, True).IsValid()), independent_step_bop_faults=faults)
        result['case31'] = dict(current_source_sha256=self.cases[31]['source_sha256'],
                                body_operation_sha256=self.cases[31]['variants'][0]['operation_inputs'][0]['sha256'],
                                blade_input_only=True, display_aliases_share_actual_runs=True)
        special = {}
        for n, folder in [(33, 'case33-asymmetric-ranges'), (34, 'case34-absolute-025'), (34, 'case34-absolute-050'), (34, 'case34-absolute-075'), (34, 'case34-relative-050')]:
            path = self.repo / 'runs/original-occ-compositions' / folder / 'summary.json'; summary = read(path)
            shape = brep(path.parent / summary['artifacts']['result_brep']); p = summary['parameters']; points = []
            weight = summary['rational_middle_weight']
            for ti in range(9):
                t = ti / 8
                if n == 33:
                    xx = -p['width'] / 2 + t * p['width']
                    aa = p['a_right'] * (1-t) + p['a_left'] * t
                    bb = p['b_right'] * (1-t) + p['b_left'] * t
                    poles = [[xx, 0, bb], [xx, 0, 0], [xx, aa, 0]]
                else:
                    zz = t * p['height']; dd = p['d_bottom'] * (1-t) + p['d_top'] * t
                    poles = [[0, dd, zz], [0, 0, zz], [dd, 0, zz]]
                for vi in range(17):
                    v = vi / 16; coeffs = [(1-v)**2, 2*weight*v*(1-v), v*v]
                    points.append([sum(coeffs[k]*poles[k][axis] for k in range(3))/sum(coeffs) for axis in range(3)])
            residual = max(point_distance(point, shape) for point in points)
            self.require(residual < TOL, 'special_recipe_sample_residual_failed', number=n, execution=folder, residual_mm=residual)
            if n == 33:
                self.require(p['a_right'] > p['a_left'] and p['b_right'] < p['b_left'], 'case33_independent_offsets_replaced_with_radius')
            else:
                rho = summary['rho']; expected_weight = rho['value'] / (1-rho['value']) if rho['type'] == 'absolute' else math.sqrt(.5)
                self.require(abs(weight-expected_weight) < 1e-12, 'case34_rho_weight_changed', execution=folder)
            special[folder] = dict(rho=summary.get('rho'), rational_middle_weight=weight, independent_profile_sample_count=len(points),
                                    max_point_to_finite_result_residual_mm=residual, native_special_api_used=False)
        result['independent_two_range_and_rho_samples'] = special
        return result

    def g2_proxies(self):
        """Bind the original illustrative proxies without certifying softness."""
        case = self.cases[35]
        process = read(self.repo / 'runs/original-occ-g2/process-index.json')
        umbrella = read(self.repo / 'runs/original-occ-g2/summary.json')
        self.require(umbrella.get('source_unchanged') is True and umbrella.get('complete') is True and
                     all(r['returncode'] == 0 and not r['timed_out'] for r in process['records']), 'original_g2_proxy_process_not_complete')
        for variant in case['variants']:
            if not variant['id'].startswith('proxy-s'): continue
            token = variant['id'].removeprefix('proxy-s')
            path = self.repo / 'runs/original-occ-g2' / ('g2-proxy-label-' + token) / 'summary.json'
            if not self.require(path.is_file(), 'original_g2_proxy_fresh_run_missing', variant=variant['id']): continue
            summary = read(path); original = variant['parameters']['trial']; proxy = summary['g2_proxy']
            self.require(summary['source_sha256'] == case['source_sha256'] == sha(self.repo / summary['source_brep']), 'original_g2_proxy_base_changed', variant=variant['id'])
            self.require(proxy['alpha'] == original['handle_fraction_alpha'] and proxy['degree'] == original['degree'] and proxy['control_points_yz'] == original['control_points_yz'], 'original_g2_proxy_recipe_changed', variant=variant['id'])
            self.require(summary['source_feature_certified'] is False and proxy['numeric_softness_law_verified'] is False, 'g2_proxy_promoted_to_softness_certificate', variant=variant['id'])
            before = path.parent / summary['artifacts']['before_brep']; result = path.parent / summary['artifacts']['result_brep']
            checks = [self.target(before, t, True) for t in summary['selection']]
            self.require(all(len(c['matching_edge_indices']) == 1 for c in checks), 'g2_proxy_original_target_not_unique', variant=variant['id'])
            shape = brep(result); poles = original['control_points_yz']; degree = original['degree']; points = []
            width = variant['parameters']['construction']['width']
            for x in (-width/2, 0., width/2):
                for vi in range(65):
                    v = vi/64; coeffs = [math.comb(degree,i)*(1-v)**(degree-i)*v**i for i in range(degree+1)]
                    points.append([x] + [sum(c*p[axis] for c,p in zip(coeffs,poles)) for axis in (0,1)])
            residual = max(point_distance(point, shape) for point in points)
            self.require(residual < TOL, 'g2_proxy_independent_profile_residual_failed', variant=variant['id'], residual_mm=residual)
            self.g2_rows.append(dict(number=35, variant_id=variant['id'], method='explicit_occ_composition',
                                     summary=path.relative_to(self.repo).as_posix(), summary_sha256=sha(path), outcome=summary['outcome'],
                                     alpha=proxy['alpha'], source_softness_label=original['source_softness_label'], degree=degree,
                                     independent_sample_count=len(points), max_point_to_finite_result_residual_mm=residual,
                                     original_target_checks=checks, numeric_softness_law_verified=False))

    def published(self):
        path = self.repo / 'web/data/original-occ/catalog.json'
        if not self.require(path.is_file(), 'original_viewer_catalog_missing'): return {}
        catalog = read(path); fresh = 0; bindings = {}
        for row in self.native_rows:
            if row['track'] == 'historical_batch_native': continue
            for variant_id in row['variant_ids']:
                bindings.setdefault((row['number'], variant_id), set()).add(row['summary_sha256'])
        for row in self.composition_rows:
            bindings.setdefault((row['number'], row['variant_id']), set()).update(e['summary_sha256'] for e in row['executions'])
        for row in self.g2_rows:
            bindings.setdefault((row['number'], row['variant_id']), set()).add(row['summary_sha256'])
        extension_file=self.repo/'data/case08-radius/protocol.json'
        if extension_file.exists() and (self.repo/'runs/case08-radius/occt/index.json').exists():
            extension=read(extension_file)
            self.require(extension['base_sha256']==self.cases[8]['source_sha256'],'case08_extension_source_changed')
            for row in read(self.repo/'runs/case08-radius/occt/index.json')['rows']:
                self.require(row['variant_id'] in extension['variant_ids'] and row['radius_mm'] in extension['radii_mm'],'case08_extension_undeclared_radius')
                self.require(sha(self.repo/row['summary'])==row['summary_sha256'],'case08_extension_raw_summary_stale')
                bindings.setdefault((8,row['variant_id']),set()).add(row['summary_sha256'])
        self.require(catalog['source_review_state_sha256'] == self.initial_review_hash, 'published_original_review_source_changed')
        revisions = []
        input_admission_protocols = []
        for entry in catalog['cases']:
            n = entry['number']; case = read(self.repo / 'web' / entry['data'])
            contract = None
            admission = None
            if case.get('input_protocol'):
                from audit_case36_input import case36_input_checks
                checks, admission = case36_input_checks(case, self.repo)
                for name, passed in checks.items():
                    self.require(passed, 'published_' + name, number=n)
                if all(checks.values()):
                    for row in admission['variants']:
                        bindings[(n, row['id'])] = {row['summary_sha256']}
                    input_admission_protocols.append(dict(number=n, protocol=case['input_protocol'], source_sha256=case['source_sha256'], native_call_executed=False, variants=len(admission['variants'])))
            if case.get('revision'):
                checks, registered = case11_revision_checks(case, self.repo)
                checks['revision_catalog_case_number'] = n == 11 and case.get('number') == n
                for name, passed in checks.items():
                    self.require(passed, 'published_' + name, number=n)
                if all(checks.values()):
                    contract = registered
                    base = self.repo / contract['source_brep']
                    finite_targets = [self.target(base, target, True) for target in contract['target_world']]
                    self.require(all(len(check['matching_edge_indices']) == 1 for check in finite_targets),
                                 'published_revision_target_not_unique_on_registered_source', number=n)
                    declared = contract.get('occt_runs', [])
                    self.require(len(declared) == len({r.get('variant_id') for r in declared}) and
                                 {r.get('variant_id') for r in declared} == {v['id'] for v in case['variants']},
                                 'published_revision_execution_registry_incomplete', number=n)
                    for row in declared:
                        raw = repository_file(self.repo, row.get('summary'))
                        if not self.require(raw is not None and sha(raw) == row.get('summary_sha256'),
                                            'published_revision_raw_summary_hash_mismatch', number=n, variant=row.get('variant_id')):
                            continue
                        summary = read(raw)
                        variant = next((v for v in case['variants'] if v['id'] == row['variant_id']), {})
                        self.require(summary.get('target_before_sha256') == contract['source_sha256'],
                                     'published_revision_actual_input_source_mismatch', number=n, variant=row['variant_id'])
                        self.require(summary.get('radius_mm') == variant.get('radius_mm') and
                                     summary.get('source_repair_fa_X_verified') is False,
                                     'published_revision_actual_parameters_or_feature_claim_changed', number=n, variant=row['variant_id'])
                        bindings[(n, row['variant_id'])] = {row['summary_sha256']}
                    revisions.append(dict(number=n, id=contract['id'], source_sha256=contract['source_sha256'],
                                          previous_source_sha256=contract['previous_source_sha256'],
                                          geometry_audit=contract['geometry_audit'], target_checks=finite_targets))
            if contract is None:
                self.require(case['source_sha256'] == self.cases[n]['source_sha256'], 'published_base_not_original', number=n)
            if not case['has_model']: continue
            if contract is None:
                self.require(case['source_case_sha256'] == sha(self.repo / f'data/original-occ/cases/{n:02d}.json'), 'published_frozen_case_stale', number=n)
            for variant in case['variants']:
                occt = variant.get('occt', {})
                self.require(variant['base_sha256'] == case['source_sha256'] and variant['base_mesh'] == case['base_mesh'], 'published_variant_base_replaced', number=n, variant=variant['id'])
                if variant['id'] == 'blade-input' and n == 31: continue
                self.require(occt.get('evidence_kind') == 'fresh_run' and occt.get('summary'), 'published_computation_variant_without_fresh_summary', number=n, variant=variant['id'])
                self.require(occt.get('source_feature_passed') is False, 'published_special_acceptance_promoted', number=n, variant=variant['id'])
                if contract:
                    self.require(occt.get('source_sha256') == occt.get('operation_input_sha256') == contract['source_sha256'],
                                 'published_revision_execution_source_mismatch', number=n, variant=variant['id'])
                self.require(occt.get('raw_summary_sha256') in bindings.get((n, variant['id']), set()), 'published_summary_not_bound_to_actual_original_execution', number=n, variant=variant['id'])
                if occt.get('evidence_kind') == 'fresh_run': fresh += 1
                for key in ('base_mesh', 'operation_mesh'):
                    if variant.get(key): self.require((self.repo / 'web' / variant[key]).is_file(), 'published_mesh_missing', number=n, variant=variant['id'], kind=key)
            if n == 36:
                if admission:
                    self.require(all(v['base_mesh'] == v['operation_mesh'] for v in case['variants']), 'published_case36_original_input_changed')
                else:
                    self.require(all(v['base_mesh'] != v['operation_mesh'] for v in case['variants']), 'published_case36_extended_input_is_base')
        return dict(computation_variants_with_fresh_summary=fresh, catalog_sha256=sha(path), registered_public_revisions=revisions,
                    registered_input_admission_protocols=input_admission_protocols,
                    frozen_originals_independently_preserved=True)

    def public_scan(self):
        inventory = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=self.repo,
                                   check=True, capture_output=True).stdout.decode().split('\0')
        public_files = set(inventory)
        paths = list((self.repo / 'data/original-occ').rglob('*.json'))
        paths += list((self.repo / 'runs/original-occ-native').rglob('*.json'))
        paths += list((self.repo / 'runs/original-occ-compositions').rglob('*.json'))
        web = self.repo / 'web/data/original-occ'
        if web.is_dir(): paths += list(web.rglob('*.json'))
        paths = [p for p in paths if p.relative_to(self.repo).as_posix() in public_files]
        for path in paths:
            text = path.read_text()
            self.require(not MACHINE.search(text), 'public_machine_path_retained', path=path.relative_to(self.repo).as_posix())
            self.require(not any(MEDIA.search(value.strip()) for value in strings(read(path))), 'public_reference_artwork_link_retained', path=path.relative_to(self.repo).as_posix())
        for folder in ('data/original-occ', 'runs/original-occ-native', 'runs/original-occ-compositions', 'web/data/original-occ'):
            for path in (self.repo / folder).rglob('*'):
                self.require(not (path.is_file() and path.relative_to(self.repo).as_posix() in public_files and path.suffix.lower() in {'.pdf', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'}),
                             'public_artwork_file_retained', path=path.relative_to(self.repo).as_posix())
        return dict(scope='git tracked and nonignored files only; private ignored attempt history remains local', json_files_checked=len(paths), machine_paths_found=any(i['code'] == 'public_machine_path_retained' for i in self.issues),
                    artwork_found=any('artwork' in i['code'] for i in self.issues))

    def run(self):
        self.frozen(); self.native(); self.compositions(); self.g2_proxies(); specifics = self.specific_contracts(); published = self.published(); scan = self.public_scan()
        self.require(sha(self.review / 'review-state.json') == self.initial_review_hash, 'source_review_state_modified_during_audit')
        computable = [(n, v['id']) for n, case in self.cases.items() for v in case['variants'] if v['method'] != 'input_only_preserved']
        bound = {(r['number'], v) for r in self.native_rows if r['track'] != 'historical_batch_native' for v in r['variant_ids']}
        bound.update((r['number'], r['variant_id']) for r in self.composition_rows)
        bound.update((r['number'], r['variant_id']) for r in self.g2_rows)
        unbound = sorted(set(computable) - bound)
        self.require(not unbound, 'original_computation_variants_without_fresh_execution', variants=unbound)
        outcomes = Counter(r['outcome'] for r in self.native_rows)
        attempts = self.composition_index['execution_attempts']
        report = dict(schema='filletbench.original-series-independent-audit.v1', created_at=datetime.now(timezone.utc).isoformat(),
                      passed=not self.issues, review_state_sha256=self.initial_review_hash,
                      auditor_sha256=sha(Path(__file__)),
                      audited_indexes={str(p): sha(self.repo / p) for p in ('data/original-occ/index.json', 'data/original-occ/manifest.json', 'runs/original-occ-native/index.json', 'runs/original-occ-compositions/index.json')},
                      scope='Independent byte, finite geometry, parameter and execution correspondence audit; no fillet builds and no new human appearance acceptance.',
                      counts=dict(case_records=len(self.cases), model_groups=sum(c['has_model'] for c in self.cases.values()),
                                  display_variants=sum(len(c['variants']) for c in self.cases.values()), computation_variants=len(computable),
                                  fresh_bound_computation_variants=len(set(computable) & bound), native_requests=len(self.native_rows),
                                  native_outcomes=dict(outcomes), native_execution_modes=dict(Counter(r['execution_mode'] for r in self.native_rows)),
                                  composition_review_variants=len(self.composition_rows), unique_bound_composition_executions=len({e['summary'] for r in self.composition_rows for e in r['executions']}),
                                  composition_attempts=len(attempts), composition_attempt_outcomes=dict(Counter(a['outcome'] for a in attempts)),
                                  fresh_original_g2_proxy_executions=len(self.g2_rows),
                                  frozen_brep_artifacts=len(self.manifest['artifacts']), frozen_history_documents=len(self.manifest['history_documents'])),
                      special_contracts=specifics, published=published, public_scan=scan,
                      limitations=['Current base fidelity is established against the current review-state snapshot and original BREP bytes; original vendor dimensions and appearance are not certified.',
                                   'Reading a frozen base BREP and preparing its subshapes is not reconstruction of that base from parameters.',
                                   'Historical source revisions remain separately marked replay tracks; their results do not become current-source defaults.',
                                   'Independent finite edge matching uses endpoint, length, all recorded samples and native face ownership; a sampled check is not global curve equivalence.',
                                   'Explicit construction execution is separate from native special-feature support. Native API completion, native BRep/BOP validity, STEP roundtrip, continuity and appearance remain independent.',
                                   'Composition STEP gates were not newly executed by this auditor. Historical STEP failures are preserved as historical evidence.'],
                      issues=self.issues, cases=self.case_rows, native_runs=self.native_rows, composition_runs=self.composition_rows, g2_proxy_runs=self.g2_rows)
        output = self.repo / 'docs/original-series-audit.json'; output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        c = report['counts']; lines = ['# 原版 OCC 系列独立审计', '',
            f"审计结果：{'通过' if report['passed'] else '发现问题'}。源 review-state SHA-256：`{self.initial_review_hash}`。", '',
            f"核对 {c['case_records']} 条原记录、{c['model_groups']} 个模型、{c['display_variants']} 个展示变体；{c['computation_variants']} 个计算变体中 {c['fresh_bound_computation_variants']} 个绑定实际新执行，31 的 blade-input 仅保留输入，32 仅说明。", '',
            f"原生对照 {c['native_requests']} 次：" + '，'.join(f'{k} {v}' for k,v in outcomes.items()) + '。', '',
            f"组合/专用展示变体 {c['composition_review_variants']} 个，绑定 {c['unique_bound_composition_executions']} 次独立执行；全部尝试 {c['composition_attempts']} 次。展示别名与组合比较不能按新的独立执行计数。", '',
            '## 核对结果', '',
            '- 每个 current base 与当前源文件、snapshot 和冻结 BREP 的字节哈希一致；冻结准备输入与 base 保留独立哈希。',
            '- 实际 before.brep 上独立匹配有限选边：端点、长度、全部原始世界坐标采样与邻面归属；不依赖适配器的边选择函数。',
            '- 24 使用当前斜向两根边，独立夹角 %.6f°；旧 batch 结果保留在独立的 historical track。' % specifics['case24']['independent_root_angle_deg'],
            '- 31 当前 packet 与 A 主体操作输入分开，clean 展示别名共享同一次实际计算，B 叶片输入不冒充重算结果。',
            '- 33 的 a/b 两条独立反向偏距和 34 的 absolute/relative rho 分别通过独立数学剖面点到有限结果的距离核对；原生圆角仅作对照。',
            '- 35 三档 degree9 代理保留原始控制点和 α，独立采样验证有限结果；数字 softness 映射与完整 G2/外观验收未由本次采样证明。',
            '- 22 R6 原生 BREP 通过而 STEP 失败；独立重读新 STEP 仍出现 BOPAlgo_InvalidCurveOnSurface，旧失败记录继续保留。',
            '- 36 原 base 是两个不相交有限面，面间最短距离 %.6f mm；延伸/裁公共带后共边圆角输入单独展示。' % gap_value(specifics),
            '- 冻结源数据、运行记录与原版网页数据进行了机器绝对路径和参考图像/PDF 扫描；结果见 JSON 的 public_scan 与 issues。', '',
            '## 验证边界', '',
            '读取冻结 BREP、提取子体、缝合或构造操作输入，不等于从参数重建整个 base。组合配方执行不等于原生特殊 API；BREP、STEP、G0/G1/G2 和人工外观验收互不替代。此次不对原始厂商尺寸、全局曲面等价或外观作新验收，也未重新运行所有圆角。', '',
            '完整逐项证据见 [original-series-audit.json](original-series-audit.json)。']
        if self.issues:
            lines += ['', '## 待处理问题', '', *['- ' + json.dumps(i,ensure_ascii=False) for i in self.issues]]
        (self.repo / 'docs/original-series-audit.md').write_text('\n'.join(lines)+'\n')
        print(json.dumps(dict(passed=report['passed'], counts=c, issue_count=len(self.issues), issues=self.issues), ensure_ascii=False, indent=2))
        return 0 if report['passed'] else 1


def gap_value(specifics):
    return specifics['case36']['independent_finite_face_gap_mm']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--repo', type=Path, default=REPO)
    args = parser.parse_args()
    return Audit(args.source_root, args.repo).run()


if __name__ == '__main__':
    raise SystemExit(main())
