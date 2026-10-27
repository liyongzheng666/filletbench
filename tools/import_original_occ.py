#!/usr/bin/env python3
"""Freeze the original OCC review series without executing geometry.

Only BREP geometry and sanitized JSON are distributed. The private source tree
is read-only. Content hashes always describe the original bytes, while JSON
snapshots explicitly identify themselves as sanitized derivatives.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

SCHEMA = 'filletbench.original-occ.v1'
EXPECTED_REVIEW_SHA256 = 'c4e90452d792e28b1b5a0c5a5237ba7043a235c98abffde445b2dbe70c0f8fa5'
OMIT = object()
MEDIA = re.compile(r'\.(?:png|jpe?g|gif|webp|pdf|svg)(?:[?#].*)?$', re.I)
ABS = re.compile(r'/(?:Users|home|private|tmp|opt|Applications|Volumes)/[^\s\"\'<>;,\)\]\}]+')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from dicts(v)


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)


class Freezer:
    def __init__(self, root, repo, expected_review_sha256=EXPECTED_REVIEW_SHA256):
        self.root, self.repo = root.resolve(), repo.resolve()
        self.review = self.root / 'outputs/manual-review'
        self.dest = self.repo / 'data/original-occ'
        self.artifacts = {}
        self.documents = {}
        self.missing = set()
        self.expected_review_sha256 = expected_review_sha256
        cache = self.dest / 'selection-samples.json'
        self.sample_cache = json.loads(cache.read_text()).get('edges', {}) if cache.is_file() else {}

    def relative(self, path):
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            # External source code remains provenance, never a machine path.
            parts = path.parts
            for anchor in ('scenarios', 'site-packages'):
                if anchor in parts:
                    return 'external/' + '/'.join(parts[parts.index(anchor):])
            return 'external/' + path.name

    def resolve(self, value):
        if not isinstance(value, str) or value.startswith(('history:', 'http:', 'https:')):
            return None
        p = Path(value)
        candidates = [p] if p.is_absolute() else [self.review / p, self.root / p, self.repo / p]
        return next((x.resolve() for x in candidates if x.is_file()), None)

    def fixture(self, value):
        p = value if isinstance(value, Path) else self.resolve(value)
        if not p or not p.is_file() or p.suffix.lower() != '.brep':
            return None
        digest = sha(p)
        out = self.dest / 'fixtures' / (digest + '.brep')
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists():
            shutil.copyfile(p, out)
        rec = self.artifacts.setdefault(digest, {'path': out.relative_to(self.repo).as_posix(), 'sha256': digest, 'bytes': p.stat().st_size, 'original_paths': []})
        origin = 'history:' + self.relative(p)
        if origin not in rec['original_paths']:
            rec['original_paths'].append(origin)
        return {'brep': rec['path'], 'sha256': digest, 'original_path': origin}

    def sanitize(self, obj):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                # Raster/PDF display assets and their hashes are outside this corpus.
                if any(t in k.lower() for t in ('image', 'comparison', 'render', 'screenshot')):
                    continue
                clean = self.sanitize(v)
                if clean is not OMIT:
                    key = self.sanitize(k)
                    if key is not OMIT:
                        out[key] = clean
            return out
        if isinstance(obj, list):
            vals = [self.sanitize(v) for v in obj]
            return [v for v in vals if v is not OMIT]
        if not isinstance(obj, str):
            return obj
        if MEDIA.search(obj.strip()):
            return OMIT
        if obj.endswith('.brep'):
            fix = self.fixture(obj)
            if fix:
                return fix['brep']
        if obj.startswith('/'):
            return 'history:' + self.relative(Path(obj))
        if obj.startswith(('diagnostics/', '../', 'annotations/', 'local-refinement/')):
            p = self.resolve(obj)
            return 'history:' + (self.relative(p) if p else 'outputs/manual-review/' + obj)
        return ABS.sub(lambda m: 'history:' + self.relative(Path(m.group(0))), obj)

    def linked_json(self, obj):
        found = {}
        for s in strings(obj):
            if s.endswith('.json') and not s.endswith('-mesh.json'):
                p = self.resolve(s)
                if p:
                    try:
                        found[p] = json.loads(p.read_text())
                    except (ValueError, UnicodeError):
                        pass
        return found

    def archive_document(self, path, data):
        digest = sha(path)
        out = self.dest / 'history' / (digest + '.json')
        value = {'schema': 'filletbench.sanitized-history.v1', 'original_path': 'history:' + self.relative(path), 'original_sha256': digest, 'sanitized': True, 'record': self.sanitize(data)}
        out.parent.mkdir(parents=True, exist_ok=True)
        # Historical topology maps can be large. Keep the complete data in
        # compact JSON and avoid embedding those maps in the browser catalog.
        out.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n')
        rec = {'path': out.relative_to(self.repo).as_posix(), 'original_sha256': digest, 'original_path': value['original_path'], 'sanitized_sha256': sha(out)}
        self.documents[digest] = rec
        return rec

    def edge(self, e):
        if not isinstance(e, dict):
            return {'index_1based': e, 'samples_mm': [], 'selection_evidence': 'index only in historical record'}
        clean = self.sanitize(e)
        samples = e.get('samples_mm') or e.get('polyline') or e.get('points') or e.get('vertices') or e.get('endpoints')
        if not samples:
            samples = [e[k] for k in ('start', 'midpoint', 'end') if k in e]
        return {**clean, 'index_1based': e.get('index_1based', e.get('index', e.get('edge_index', e.get('i')))), 'samples_mm': samples or []}

    def finite_circle_samples(self, source, target):
        """Read and sample a finite source edge; never construct a replacement."""
        edge_index = target['index_1based']
        key = f'{source["sha256"]}:edge{edge_index}'
        if key not in self.sample_cache:
            try:
                from OCP.BRep import BRep_Builder
                from OCP.BRepTools import BRepTools
                from OCP.TopoDS import TopoDS_Shape, TopoDS
                from OCP.TopAbs import TopAbs_EDGE
                from OCP.TopExp import TopExp
                from OCP.TopTools import TopTools_IndexedMapOfShape
                from OCP.BRepAdaptor import BRepAdaptor_Curve
                from OCP.GeomAbs import GeomAbs_Circle
            except ImportError as exc:
                raise RuntimeError('A source circle has insufficient samples; regenerate with an OCP Python runtime or retain its SHA-bound selection-samples.json') from exc
            shape = TopoDS_Shape()
            path = self.repo / source['brep']
            if not BRepTools.Read_s(shape, str(path), BRep_Builder()):
                raise ValueError('Cannot read frozen source for finite edge sampling')
            edges = TopTools_IndexedMapOfShape()
            TopExp.MapShapes_s(shape, TopAbs_EDGE, edges)
            curve = BRepAdaptor_Curve(TopoDS.Edge_s(edges.FindKey(edge_index)))
            if curve.GetType() != GeomAbs_Circle:
                raise ValueError('Historical circle selector does not identify an actual source circle')
            first, last = curve.FirstParameter(), curve.LastParameter()
            samples = []
            for i in range(65):
                p = curve.Value(first + (last - first) * i / 64)
                samples.append([p.X(), p.Y(), p.Z()])
            circle = curve.Circle()
            center = circle.Location()
            self.sample_cache[key] = {'brep': source['brep'], 'sha256': source['sha256'], 'edge_index_1based': edge_index, 'curve_type': 'Circle', 'parameter_range': [first, last], 'center_mm': [center.X(), center.Y(), center.Z()], 'radius_mm': circle.Radius(), 'samples_mm': samples, 'sample_count': 65, 'evidence_kind': 'read_only_finite_edge_sampling', 'method': 'OCP BRepAdaptor_Curve.Value over actual finite source edge parameter interval'}
        record = self.sample_cache[key]
        assert record['sha256'] == source['sha256'] and record['sample_count'] == 65
        return record

    def selections(self, trial, summary):
        candidates = [trial, summary]
        if isinstance(trial, dict) and trial.get('steps'):
            # Later steps refer to intermediate shapes, so the first-step
            # selection alone may be drawn on the initial operation input.
            candidates.insert(0, trial['steps'][0])
        for c in list(candidates):
            if isinstance(c, dict):
                for key in ('selection', 'input_front_chain', 'radius_assignment'):
                    if isinstance(c.get(key), dict):
                        candidates.append(c[key])
        edges, faces = [], []
        for c in candidates:
            if not isinstance(c, dict):
                continue
            for key in ('selected_edges', 'selected_edge', 'original_target_edge', 'operation_support_edge', 'selected_side_edges', 'selected_front_chain', 'front_chain', 'root', 'root_edges'):
                val = c.get(key)
                if val is not None and not edges:
                    edges = val if isinstance(val, list) else [val]
            for key in ('selected_faces', 'selected_support_faces'):
                if c.get(key) is not None and not faces:
                    val = c[key]
                    faces = val if isinstance(val, list) else [val]
        if not edges and isinstance(summary.get('edge_tools'), list):
            edges = [t['edge'] for t in summary['edge_tools'] if isinstance(t.get('edge'), dict)]
        if not edges and trial.get('target_edge_indices'):
            selected = set(trial['target_edge_indices'])
            edges = [e for e in summary.get('input_edge_map', []) if e.get('index_1based', e.get('index')) in selected]
        if trial.get('source_native_trial'):
            native_trial = next((t for t in summary.get('native_trials', []) if t.get('name') == trial['source_native_trial']), {})
            selected = set(native_trial.get('selected_edges', []))
            pool = summary.get('selected_side_edges', []) + summary.get('proposed_front_chain', [])
            if selected:
                edges = [e for e in pool if e.get('index_1based') in selected]
        return [self.edge(e) for e in edges], self.sanitize(faces)

    def operation(self, path, label, trial, summary, recorded=None):
        fix = self.fixture(path)
        if not fix:
            return None
        edges, faces = self.selections(trial, summary)
        return {**fix, 'label': label, 'selected_edges': edges, 'selected_faces': faces, 'recorded_sha256': recorded, 'recorded_hash_matches': recorded == fix['sha256'] if recorded else None, 'selection_sha256': fix['sha256']}

    def find_trial(self, summary, variant, artifacts):
        targets = {a.get('sha256') for a in artifacts}
        for d in dicts(summary):
            if d.get('id') == variant:
                return d
        for d in dicts(summary):
            if (d.get('brep_sha256') or d.get('sha256')) in targets:
                return d
        return {}

    def trial_parameters(self, trial):
        keys = ('id', 'radius', 'radius_mm', 'order', 'mode', 'stop_flags', 'patch_enabled', 'vertex_limit', 'edge_limit_requested', 'effective_stops', 'additional_edge_limit_effective', 'kind', 'entity_kind', 'retained_side', 'iso_plane_x', 'cap_plane_x', 'fillet_interval_x', 'sharp_interval_x', 'rho_type', 'rho_value', 'weight', 'absolute_rho_equivalent', 'construction', 'source_softness_label', 'handle_fraction_alpha', 'handle_length_mm', 'degree', 'control_points_yz', 'model_class', 'requested_internal_C2', 'softness_parameter_used', 'radius_assignment')
        return self.sanitize({k: trial[k] for k in keys if k in trial})

    def variant(self, item, v, audit, summary, summary_path):
        demo = v.get('demo', {})
        artifacts = list(demo.get('result_artifacts', []))
        if demo.get('result_brep'):
            artifacts.append({'brep': demo['result_brep'], 'sha256': demo.get('result_brep_sha256')})
        trial = self.find_trial(summary, v['id'], artifacts)
        if not trial and isinstance(summary.get('run'), dict):
            trial = summary['run']
        records = [x for x in audit.get('current_review_geometry_records', []) if v['id'] in x.get('source_view_ids', [])]
        results = []
        for art in artifacts:
            fix = self.fixture(art.get('brep'))
            if fix:
                record = {**fix, 'recorded_sha256': art.get('sha256'), 'recorded_hash_matches': art.get('sha256') == fix['sha256'] if art.get('sha256') else None}
                if records:
                    record['mesh_path_as_local_history'] = self.sanitize([z['path'] for z in records[0].get('result_mesh_candidates', [])])
                results.append(record)
        op_path = demo.get('operation_input_brep') or summary.get('operation_input_brep')
        op_obj = summary.get('operation_input', {})
        if not op_path and isinstance(op_obj, dict):
            op_path = op_obj.get('brep')
        if not op_path:
            op_path = summary.get('input_brep') or (summary.get('input', {}).get('brep') if isinstance(summary.get('input'), dict) else None) or item.get('files', {}).get('brep')
        recorded = demo.get('operation_input_sha256') or summary.get('operation_input_sha256') or (op_obj.get('brep_sha256') if isinstance(op_obj, dict) else None)
        # Capping variants operate on one selected body, not the displayed
        # packet containing both bodies and the separate cap tools.
        if item['number'] == 18:
            kind = trial.get('kind') or v['id'].split('-')[0]
            cap = summary.get('caps', {}).get(kind, {})
            part = next((p for p in summary.get('input_parts', []) if p.get('name') == kind + '_case_body'), None)
            if part:
                op_path, recorded = part['path'], part['sha256']
        if item['number'] == 19 and summary.get('preprocess', {}).get('unslotted_support'):
            op_path = summary['preprocess']['unslotted_support']
            recorded = None
        operation = self.operation(op_path, 'actual operation input' if demo.get('operation_input_brep') or summary.get('operation_input_brep') or op_obj else 'historical base input; operation preparation recorded in source_spec', trial, summary, recorded)
        if operation and item['number'] == 19:
            operation['label'] = 'derived unslotted planar support before native fillet; original slots restored explicitly'
            for edge in operation['selected_edges']:
                edge['source_index_1based'] = edge.pop('index_1based', None)
                edge['index_1based'] = None
                edge['selection_evidence'] = 'source root world-space samples; prepared-support edge index is not asserted'
        if operation and item['number'] == 18:
            operation['label'] = 'selected capping body; separate cap tool is preserved in source_spec/history'
            operation['selected_edges'] = [self.edge(cap['target_edge'])] if cap.get('target_edge') else []
            operation['selection_evidence'] = 'original uncropped 70 mm body root from summary.caps[kind].target_edge; indices belong to this single body'
            # The 29 mm support is a derived construction stage, not the
            # original requested root. Keep it as limit information only.
            operation['limit_information'] = {'derived_support_edge': self.edge(trial['operation_support_edge']) if trial.get('operation_support_edge') else None, 'stage': 'derived 29 mm left support used by explicit capped construction; not original target', 'cap_definition': self.sanitize(cap)}
        scope = demo.get('scope_note') or v.get('scope_notice') or item.get('test_spec', {}).get('scope_notice', '')
        script = records[0].get('scripts', {}) if records else {}
        summary_document = {'path': f'data/original-occ/history/{sha(summary_path)}.json', 'original_sha256': sha(summary_path)} if summary_path else None
        check_keys = ('status', 'valid', 'primitive_success', 'preserve_notch_option_supplied', 'preserve_notch_two_modes_verified', 'native_operation_succeeded', 'native_automatic_limit_api_used', 'native_automatic_capping_api_used', 'native_limit_topols_api_used', 'native_patch_switch_used', 'native_unders_switch_used', 'source_function_verified', 'all_formats_passed', 'complete_requested_root_set_generated', 'smooth_quality_passed', 'quality_status', 'failure_reason', 'failure_reasons', 'failure_stage', 'error', 'requested_support_G2_passed', 'generated_fillet_G0_G1_passed', 'all_three_formats_G0_G1_passed')
        checks = {k: trial[k] for k in check_keys if k in trial}
        method = demo.get('method_kind') or (records[0].get('method_kind') if records else None) or summary.get('method_kind') or 'native_ordinary_fillet'
        return {'id': v['id'], 'label': v.get('name') or v.get('title') or v['id'], 'title': v.get('title', ''), 'method': method, 'parameters': self.sanitize({'summary': v.get('parameter_summary'), 'radius_text': demo.get('radius_text'), 'construction': summary.get('parameters'), 'trial': self.trial_parameters(trial)}), 'radius_mm': demo.get('radius'), 'base_brep': item.get('_base', {}).get('brep'), 'base_sha256': item.get('_base', {}).get('sha256'), 'operation_inputs': [operation] if operation and method != 'input_only_preserved' else [], 'historical_results': results, 'historical_status': demo.get('status') or trial.get('status') or 'recorded', 'historical_checks': self.sanitize(checks), 'human_status': v.get('human_status', item.get('status')), 'scope_note': scope, 'source_spec': self.sanitize({'variant': v, 'execution': item.get('test_spec', {}).get('execution'), 'feature_assessment': item.get('test_spec', {}).get('feature_assessment'), 'summary_record_id': trial.get('id'), 'summary_document': summary_document, 'summary': 'history:' + self.relative(summary_path) if summary_path else None}), 'script_provenance': self.sanitize(script), 'evidence_kind': 'historical_snapshot', 'fresh_run': False}

    def freeze_case(self, item, audit):
        n = item['number']
        base = self.fixture(item.get('files', {}).get('brep')) or {}
        item['_base'] = base
        linked = self.linked_json(item)
        if audit.get('historical_ordinary'):
            p = self.resolve(audit['historical_ordinary'].get('summary', {}).get('path'))
            if p:
                linked[p] = json.loads(p.read_text())
        # Also freeze each latest original ordinary summary and its actual prepared
        # part inputs, even when the page now displays a specialized variant.
        batch = self.review / f'diagnostics/batch/case{n:02d}/summary.json'
        if batch.is_file():
            linked[batch] = json.loads(batch.read_text())
        docs = [self.archive_document(p, d) for p, d in linked.items()]
        variants = []
        if item.get('variants'):
            for v in item['variants']:
                dm = v.get('demo', {})
                key = dm.get('summary')
                if not key:
                    key = next((z for z in dm.get('outputs', {}).values() if isinstance(z, str) and z.endswith('summary.json')), None)
                sp = self.resolve(key)
                summary = linked.get(sp, {})
                variants.append(self.variant(item, v, audit, summary, sp))
        elif item.get('has_model'):
            spec = item.get('test_spec', {})
            sp = self.resolve(spec.get('batch_execution', {}).get('summary_file'))
            summary = linked.get(sp, {})
            plans = summary.get('plan', {}).get('parts', [])
            parts = summary.get('parts', [])
            if plans:
                for pi, plan in enumerate(plans, 1):
                    part = parts[pi - 1] if pi <= len(parts) else {}
                    for ri, radius in enumerate(plan.get('radii', []), 1):
                        token = str(radius).replace('.', 'p')
                        vid = f'part{pi:02d}-r{token}'
                        attempt = next((a for a in part.get('attempts', []) if a.get('radius', a.get('radius_mm')) == radius), None)
                        proto = {'id': vid, 'name': f'{plan.get("label", "part")} / R{radius}', 'parameter_summary': plan.get('selection_note', ''), 'demo': {'radius': radius, 'status': attempt.get('status') if attempt else 'not_executed', 'method_kind': 'native_ordinary_fillet', 'scope_note': plan.get('source_feature_note') or item.get('local_demo', {}).get('scope_note', '')}}
                        out = self.variant(item, proto, audit, summary, sp)
                        op = self.operation(part.get('before_brep'), plan.get('label', f'part {pi}'), part, summary, part.get('operation_input_sha256'))
                        out['operation_inputs'] = [op] if op else []
                        out['parameters'] = self.sanitize({'part_number': pi, 'request_order': ri, 'radius_mm': radius, 'plan': plan, 'preprocess': part.get('preprocess')})
                        out['source_spec'] = self.sanitize({'plan': plan, 'attempt': attempt, 'part_number': pi, 'historical_source_sha256': summary.get('input_sha256'), 'scope_notice': spec.get('scope_notice'), 'execution': spec.get('execution')})
                        out['script_provenance'] = self.sanitize((audit.get('historical_ordinary') or {}).get('scripts', {}))
                        out['historical_results'] = []
                        if attempt:
                            path = attempt.get('brep')
                            if not path and summary.get('run_dir'):
                                ai = part.get('attempts', []).index(attempt) + 1
                                candidate = Path(summary['run_dir']) / f'part{pi:02d}' / f'attempt{ai:02d}-r{radius:g}.brep'
                                path = candidate if candidate.is_file() else None
                            fix = self.fixture(path)
                            if fix:
                                out['historical_results'] = [{**fix, 'recorded_sha256': attempt.get('roundtrip_brep', {}).get('sha256'), 'historical_attempt_status': attempt.get('status'), 'checks': self.sanitize(attempt.get('checks', {})), 'roundtrip_brep': self.sanitize(attempt.get('roundtrip_brep')), 'roundtrip_step': self.sanitize(attempt.get('roundtrip_step')), 'error': self.sanitize(attempt.get('error', ''))}]
                        variants.append(out)
            else:
                demo = item.get('local_demo', {})
                candidates = [(p, d) for p, d in linked.items() if 'run' in p.name and not 'geometry' in p.name]
                sp, summary = candidates[0] if candidates else (None, {})
                variants.append(self.variant(item, {'id': 'local-demo', 'name': demo.get('title', 'Original local demo'), 'demo': demo}, audit, summary, sp))
        pub = self.repo / f'data/cases/{n:02d}.json'
        reference = json.loads(pub.read_text()).get('reference', {}) if pub.is_file() else {}
        # Companion native controls share the exact operation bytes with some
        # explicit constructions. Their target geometry can be reused only
        # under this byte-level equality, with the origin retained.
        known_selections = {op['sha256']: (op['selected_edges'], op['selected_faces']) for v in variants for op in v['operation_inputs'] if op['selected_edges']}
        for v in variants:
            v['variant_origin'] = 'original_page' if item.get('variants') else ('original_batch_plan' if v['id'].startswith('part') else 'local_demo')
            for op in v['operation_inputs']:
                if not op['selected_edges'] and op['sha256'] in known_selections:
                    edges, faces = known_selections[op['sha256']]
                    op['selected_edges'], op['selected_faces'] = edges, faces
                    op['selection_evidence'] = 'same byte-identical operation input as companion native control in this original case'
        # Draw source targets only when the selection evidence is associated
        # with the current source revision. Old ordinary preparations are kept
        # as separate operation records rather than relabelled as source edges.
        base_targets, base_faces, annotation_groups = [], [], {}
        annotation = item.get('annotation') or {}
        verified = annotation.get('verified_native_edges') or {}
        if verified.get('brep_sha256') == base.get('sha256'):
            for group, vals in verified.items():
                if isinstance(vals, list) and vals and isinstance(vals[0], dict) and ('points' in vals[0] or 'edge_index' in vals[0]):
                    for e in vals:
                        target = self.edge(e)
                        target['group'] = group
                        annotation_groups.setdefault(group, []).append(target)
                        if group == 'root' or 'target' in group.lower():
                            base_targets.append(target)
        if not base_targets:
            for v in variants:
                for op in v['operation_inputs']:
                    if op['sha256'] == base.get('sha256'):
                        base_targets.extend(op['selected_edges'])
                        base_faces.extend(op['selected_faces'])
        if not base_targets:
            for summary in linked.values():
                if summary.get('input_sha256') == base.get('sha256'):
                    targets, faces = self.selections({}, summary)
                    if not targets:
                        plans = summary.get('plan', {}).get('parts', [])
                        for component_index, plan in enumerate(plans, 1):
                            evidence = plan.get('edge_evidence') or plan.get('selection_evidence') or []
                            for evidence_edge in evidence:
                                if not isinstance(evidence_edge, dict):
                                    continue
                                target = self.edge(evidence_edge)
                                if len(plans) > 1:
                                    target['source_index_1based'] = target.pop('index_1based', None)
                                    target['index_1based'] = None
                                    target['component_index_1based'] = component_index
                                    target['component_label'] = plan.get('label')
                                    target['selection_evidence'] = 'original plan edge index is component-local; world-space samples are on the current source packet'
                                targets.append(target)
                    base_targets.extend(targets)
                    base_faces.extend(faces)
                elif summary.get('combined_input_sha256') == base.get('sha256'):
                    for v in variants:
                        for op in v['operation_inputs']:
                            for target in op['selected_edges']:
                                copied = dict(target)
                                copied['subshape_index_1based'] = copied.pop('index_1based', None)
                                copied['index_1based'] = None
                                copied['selection_evidence'] = 'same-coordinate body contained in combined current source packet; packet edge index not asserted'
                                base_targets.append(copied)
        # A few current sources are separate face packets which are sewn or
        # reoriented before the operation. Map only exact straight root
        # geometry in the already published source fixture. Component-local
        # topology IDs are never presented as global BREP edge numbers.
        source_fixture = self.repo / f'data/fixtures/{n:02d}.json'
        if not base_targets and source_fixture.is_file():
            fixture = json.loads(source_fixture.read_text())
            if fixture.get('source_sha256') == base.get('sha256'):
                operations = [e for v in variants for op in v['operation_inputs'] for e in op['selected_edges'] if e.get('curve_type') == 'Line' and len(e.get('samples_mm', [])) >= 2]
                close = lambda a, b: sum((a[i] - b[i]) ** 2 for i in range(3)) <= 1e-12
                for component in fixture.get('components', []):
                    for edge in component.get('edges', []):
                        points = edge.get('source_polyline', [])
                        if edge.get('curve', {}).get('degree') != 1 or len(points) < 2:
                            continue
                        if any((close(points[0], e['samples_mm'][0]) and close(points[-1], e['samples_mm'][-1])) or (close(points[0], e['samples_mm'][-1]) and close(points[-1], e['samples_mm'][0])) for e in operations):
                            base_targets.append({'index_1based': None, 'component_id': component['id'], 'component_edge_id': edge['id'], 'curve_type': 'Line', 'samples_mm': points, 'selection_evidence': 'current source fixture with matching source SHA; straight-root endpoints match current operation target; component-local ID only'})
        unique = lambda values: list({json.dumps(x, sort_keys=True): x for x in values}.values())
        base_targets, base_faces = unique(base_targets), unique(base_faces)
        if n == 18:
            # The packet-level ordinary batch used clipped left supports. The
            # original page's capping request is each full, uncropped body root.
            base_targets = []
            for summary in linked.values():
                if summary.get('input_sha256') != base.get('sha256') or 'caps' not in summary:
                    continue
                for kind, cap in summary['caps'].items():
                    if not cap.get('target_edge'):
                        continue
                    target = self.edge(cap['target_edge'])
                    target['source_index_1based'] = target.pop('index_1based', None)
                    target['index_1based'] = None
                    target['component_label'] = kind + '_case_body'
                    target['component_index_1based'] = 1 if kind == 'plane' else 3
                    target['selection_evidence'] = 'original 70 mm body root in shared world coordinates; local body index is not a packet-global index'
                    base_targets.append(target)
        for target in base_targets:
            if (target.get('curve_type') or target.get('curve')) == 'Circle' and len(target.get('samples_mm', [])) < 2:
                sampling = self.finite_circle_samples(base, target)
                target['samples_mm'] = sampling['samples_mm']
                target['sampling_provenance'] = {k: val for k, val in sampling.items() if k != 'samples_mm'}
        for v in variants:
            for op in v['operation_inputs']:
                if not op['selected_edges'] and op['sha256'] == base.get('sha256'):
                    op['selected_edges'] = base_targets
                    op['selection_evidence'] = 'original annotation or current source target, on byte-identical operation input'
            v['base_targets'] = base_targets
            v['operation_targets'] = [e for op in v['operation_inputs'] for e in op['selected_edges']]
            v['selection'] = {'base': {'sha256': base.get('sha256'), 'targets': base_targets, 'selected_faces': base_faces}, 'operation': [{'sha256': op['sha256'], 'targets': op['selected_edges'], 'selected_faces': op['selected_faces']} for op in v['operation_inputs']]}
        clean_item = {k: v for k, v in item.items() if not k.startswith('_')}
        result = {'schema': SCHEMA, 'number': n, 'id': item['case_id'], 'title': item['title'], 'has_model': item.get('has_model', False), 'source_brep': base.get('brep'), 'source_sha256': base.get('sha256'), 'recorded_source_sha256': item.get('snapshot', {}).get('brep_sha256'), 'human_status': item.get('status'), 'human_note': item.get('human_note', ''), 'reference': reference, 'base_targets': base_targets, 'base_annotation_groups': annotation_groups, 'selection': {'base': {'sha256': base.get('sha256'), 'targets': base_targets, 'selected_faces': base_faces}}, 'variants': variants, 'default_variant': variants[0]['id'] if variants else None, 'source_spec': self.sanitize(clean_item), 'history_documents': docs, 'historical_ordinary': self.sanitize(audit.get('historical_ordinary')), 'review_results': self.sanitize(item.get('review_results', {})), 'provenance': {'kind': 'historical_source_freeze', 'not_a_rerun': True, 'source_dimensions': 'inferred reconstruction; not original vendor CAD', 'review_state_sha256': self.review_hash, 'no_reference_artwork_distributed': True}}
        path = self.dest / f'cases/{n:02d}.json'
        write(path, result)
        return {'number': n, 'id': item['case_id'], 'title': item['title'], 'path': path.relative_to(self.repo).as_posix(), 'sha256': sha(path), 'has_model': result['has_model'], 'source_brep': base.get('brep'), 'source_sha256': base.get('sha256'), 'variant_count': len(variants), 'default_variant': result['default_variant'], 'human_status': result['human_status']}

    def run(self):
        review_file = self.review / 'review-state.json'
        audit_file = self.root / 'work/occ-coverage-audit.json'
        self.review_hash = sha(review_file)
        if self.review_hash != self.expected_review_sha256:
            raise ValueError('Review source hash differs from the explicitly frozen revision')
        state, audit = json.loads(review_file.read_text()), json.loads(audit_file.read_text())
        audit_cases = {x['number']: x for x in audit['cases']}
        cases = []
        # Case 22 is written first so an independent native worker can start.
        ordered = sorted(state['items'], key=lambda x: (x['number'] != 22, x['number']))
        for item in ordered:
            cases.append(self.freeze_case(item, audit_cases.get(item['number'], {})))
            write(self.dest / 'index.json', {'schema': SCHEMA, 'cases': sorted(cases, key=lambda x: x['number']), 'partial': len(cases) != len(ordered)})
        sample_path = self.dest / 'selection-samples.json'
        write(sample_path, {'schema': 'filletbench.original-occ-selection-samples.v1', 'edges': self.sample_cache, 'scope': 'Read-only sampling of frozen source edges; no fillet construction or source modification'})
        manifest = {'schema': 'filletbench.original-occ-manifest.v1', 'source_review_state': {'path': 'history:outputs/manual-review/review-state.json', 'sha256': self.review_hash, 'bytes': review_file.stat().st_size}, 'source_coverage_audit': {'path': 'history:work/occ-coverage-audit.json', 'sha256': sha(audit_file), 'bytes': audit_file.stat().st_size}, 'selection_samples': {'path': sample_path.relative_to(self.repo).as_posix(), 'sha256': sha(sample_path)}, 'sanitization': {'reference_artwork_copied': False, 'absolute_machine_paths_retained': False, 'sdk_binaries_copied': False, 'geometry_policy': 'Only reconstructed historical BREP bytes; original hash names; no fillet construction; source edges may be read and sampled', 'history_json_policy': 'Sanitized derivatives; original byte hashes retained separately'}, 'artifacts': sorted(self.artifacts.values(), key=lambda x: x['path']), 'history_documents': sorted(self.documents.values(), key=lambda x: x['path'])}
        write(self.dest / 'manifest.json', manifest)
        index = {'schema': SCHEMA, 'title': 'Original OCC review series', 'evidence_kind': 'historical_source_freeze', 'fresh_run': False, 'source_review_state_sha256': self.review_hash, 'case_records': len(cases), 'model_groups': sum(x['has_model'] for x in cases), 'explanation_only': [x['number'] for x in cases if not x['has_model']], 'excluded': self.sanitize(state.get('excluded_items', [])), 'variants': sum(x['variant_count'] for x in cases), 'original_page_variants': sum(len(x.get('variants', [])) for x in state['items']), 'cases': sorted(cases, key=lambda x: x['number']), 'manifest': 'data/original-occ/manifest.json', 'boundaries': ['Historical API returns, BREP checks, STEP checks, source feature correspondence and human acceptance remain independent.', 'Explicit composition is not promoted to native special feature support.', 'Planned radii not historically attempted remain not_executed.', 'Current source BREP and prepared operation inputs retain independent hashes.', 'Case 32 is an explanation page, with no independent model or native execution task.']}
        write(self.dest / 'index.json', index)
        assert sha(review_file) == self.review_hash, 'Source review state changed while freezing'
        print(json.dumps({'cases': len(cases), 'models': index['model_groups'], 'variants': index['variants'], 'breps': len(self.artifacts), 'documents': len(self.documents), 'source_review_state_sha256': self.review_hash}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--expected-review-sha256', default=EXPECTED_REVIEW_SHA256)
    args = parser.parse_args()
    Freezer(args.source_root, args.repo, args.expected_review_sha256).run()
