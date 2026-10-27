#!/usr/bin/env python3
"""Read-only, SDK-free audit of fresh runs and the publishable repository.

This is a one-sided failure oracle. Missing a failure never proves a complete
fillet, source feature, G1/G2, self-intersection freedom, or visual equivalence.
No kernel records or native models are modified. Python 3.10+ standard library.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

POSITION = 1e-6
SHARP_DEGREES = 1.0
TAU = 2 * math.pi


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sub(a, b):
    return [x-y for x, y in zip(a, b)]


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def norm(a):
    return math.sqrt(dot(a, a))


def unit(a):
    n = norm(a)
    if not n or not math.isfinite(n):
        raise ValueError('zero or nonfinite vector')
    return [x/n for x in a]


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def finite_points(points):
    return (isinstance(points, list) and len(points) >= 2 and
            all(isinstance(p, list) and len(p) == 3 and
                all(isinstance(x, (int, float)) and math.isfinite(x) for x in p) for p in points))


def unwrap(angles):
    out = [angles[0]]
    for a, b in zip(angles, angles[1:]):
        delta = (b-a+math.pi) % TAU-math.pi
        out.append(out[-1]+delta)
    return out


def coverage(intervals, total):
    merged = []
    for a, b in sorted((max(0., a), min(total, b)) for a, b in intervals):
        if b-a <= POSITION:
            continue
        if merged and a <= merged[-1][1]+POSITION:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    whole = bool(len(merged) == 1 and merged[0][0] <= POSITION and merged[0][1] >= total-POSITION)
    return dict(intervals_mm=merged, covered_length_mm=sum(b-a for a, b in merged), full_span=whole)


class Reference:
    """Actual world geometry, never equal fractions or different surface UVs."""
    def __init__(self, target):
        self.kind = target.get('kind')
        self.points = target.get('samples', target.get('samples_mm'))
        if not finite_points(self.points):
            raise ValueError('no finite reference points')
        self.origin = self.points[0]
        if self.kind == 'line':
            delta = sub(self.points[-1], self.origin)
            self.total = norm(delta)
            self.u = unit(delta)
        elif self.kind == 'circle':
            self.center = target['center']
            self.normal = unit(target['normal'])
            self.radius = float(target['radius'])
            self.u = unit(sub(self.origin, self.center))
            self.v = unit(cross(self.normal, self.u))
            ang = self.angles(self.points)
            self.direction = 1 if ang[-1] >= ang[0] else -1
            self.total = self.radius*abs(ang[-1]-ang[0])
            if self.radius <= POSITION or not POSITION < self.total <= TAU*self.radius+POSITION:
                raise ValueError('unsupported circle span')
        else:
            raise ValueError('only verified bounded lines/circles are assessed')
        if max(self.coordinate(p)[1] for p in self.points) > POSITION:
            raise ValueError('prepared reference does not fit world points')
        expected = target.get('expected_length_mm')
        if expected and abs(self.total-expected) > max(1e-5, expected*1e-7):
            raise ValueError('reference span disagrees with expected length')

    def angles(self, points):
        return unwrap([math.atan2(dot(sub(p, self.center), self.v), dot(sub(p, self.center), self.u)) for p in points])

    def coordinate(self, p):
        if self.kind == 'line':
            q = sub(p, self.origin)
            s = dot(q, self.u)
            return s, norm(sub(q, [s*x for x in self.u]))
        q = sub(p, self.center)
        rad, plane = norm(q), dot(q, self.normal)
        theta = (self.direction*math.atan2(dot(q, self.v), dot(q, self.u))) % TAU
        if theta > TAU-POSITION/self.radius:
            theta = 0.
        return theta*self.radius, math.hypot(rad-self.radius, plane)

    def candidate(self, edge):
        points = edge.get('points')
        length = edge.get('length')
        if not finite_points(points) or len(points) < 3 or not isinstance(length, (int, float)) or not math.isfinite(length):
            return None
        if edge.get('length_status') != 1000:
            return None
        coords = [self.coordinate(p) for p in points]
        error = max(row[1] for row in coords)
        if error > POSITION:
            return None
        if self.kind == 'line':
            values = [s for s, _ in coords]
            a, b = min(values), max(values)
            intervals = [[a, b]]
        else:
            values = [self.direction*t*self.radius for t in self.angles(points)]
            a, b = min(values), max(values)
            period = TAU*self.radius
            intervals = [[a+k*period, b+k*period] for k in range(-2, 3)]
        if b-a <= POSITION or abs(length-(b-a)) > max(1e-5, length*1e-7):
            return None
        covered = coverage(intervals, self.total)
        if not covered['intervals_mm']:
            return None
        return dict(edge_id=edge['id'], intervals_mm=covered['intervals_mm'], native_length_mm=length,
                    sample_count=len(points), max_carrier_residual_mm=error,
                    length_span_error_mm=abs(length-(b-a)))


def sharpness(snapshot, reference, candidate):
    coords, angles, gaps = [], [], []
    invalid = 0
    for junction in snapshot.get('junction_samples', []):
        if junction.get('edge_id') != candidate['edge_id']:
            continue
        s, residual = reference.coordinate(junction['point'])
        if residual > POSITION or s < -POSITION or s > reference.total+POSITION:
            continue
        owners = junction.get('owners', [])
        if len(owners) != 2 or owners[0].get('face_id') == owners[1].get('face_id'):
            invalid += 1
            continue
        ns, local_gaps = [], []
        try:
            for owner in owners:
                if owner.get('status') != 1000 or owner.get('uv_evaluation_status') != 1000:
                    raise ValueError('failed surface query')
                g = math.dist(owner['point'], junction['point'])
                if isinstance(owner.get('drop_gap'), (int, float)):
                    g = max(g, owner['drop_gap'])
                if g > POSITION:
                    raise ValueError('surface points not coincident')
                ns.append(unit(owner['raw_normal']))
                local_gaps.append(g)
            # Plane angle ignores sign: antiparallel raw normals are smooth.
            angle = math.degrees(math.acos(max(-1., min(1., abs(dot(*ns))))))
            coords.append(s)
            angles.append(angle)
            gaps.extend(local_gaps)
        except (ValueError, KeyError, TypeError):
            invalid += 1
    span = sum(b-a for a, b in candidate['intervals_mm'])
    sample_span = max(coords, default=0.)-min(coords, default=0.)
    enough = len(coords) >= 3 and sample_span >= .5*span-POSITION
    return dict(confirmed_sharp=bool(enough and invalid == 0 and min(angles) >= SHARP_DEGREES),
                valid_normal_samples=len(angles), invalid_normal_samples=invalid,
                normal_sample_span_mm=sample_span, minimum_plane_angle_deg=min(angles, default=None),
                maximum_plane_angle_deg=max(angles, default=None), max_actual_G0_gap_mm=max(gaps, default=None))


def target_side(snapshot, reference, allowed=None):
    matches, all_spans, sharp_spans = [], [], []
    for edge in snapshot.get('geometry', {}).get('edges', []):
        if allowed is not None and edge.get('id') not in allowed:
            continue
        candidate = reference.candidate(edge)
        if candidate is None:
            continue
        candidate['sharpness'] = sharpness(snapshot, reference, candidate)
        matches.append(candidate)
        all_spans.extend(candidate['intervals_mm'])
        if candidate['sharpness']['confirmed_sharp']:
            sharp_spans.extend(candidate['intervals_mm'])
    geo, sharp = coverage(all_spans, reference.total), coverage(sharp_spans, reference.total)
    return dict(geometry_coverage=geo, sharp_coverage=sharp, matches=matches,
                full_original_sharp_span_confirmed=geo['full_span'] and sharp['full_span'])


def retention(run, before, after):
    prepared = read(run/'prepared-targets.json', [])
    selection = read(run/'selection.json', {})
    selected = {t['id']: t for t in selection.get('targets', [])}
    rows = []
    for target in prepared:
        row = dict(target_id=target['id'], kind=target.get('kind'), retained_sharp_target=False)
        try:
            reference = Reference(target)
            sel = selected.get(target['id'], {})
            ids = {e['edge_id'] for e in sel.get('candidates', [])}
            if not (selection.get('passed') and sel.get('passed') and ids):
                raise ValueError('no certified native before selection')
            b = target_side(before, reference, ids)
            a = target_side(after, reference)
            row.update(reference_length_mm=reference.total, before=b, after=a,
                       retained_sharp_target=b['full_original_sharp_span_confirmed'] and a['full_original_sharp_span_confirmed'])
        except (ValueError, KeyError, TypeError) as e:
            row['unverified_reason'] = str(e)
        rows.append(row)
    return rows


def mesh_check(path):
    if not path.exists():
        return dict(status='missing')
    d = read(path)
    vertices, triangles = d.get('vertices', []), d.get('triangles', [])
    errors = []
    if not vertices or not triangles:
        errors.append('empty mesh')
    if not finite_points(vertices):
        errors.append('nonfinite or invalid vertices')
    degenerate = 0
    for t in triangles:
        if not isinstance(t, list) or len(t) != 3 or not all(isinstance(i, int) and 0 <= i < len(vertices) for i in t):
            errors.append('invalid triangle index')
            break
        if norm(cross(sub(vertices[t[1]], vertices[t[0]]), sub(vertices[t[2]], vertices[t[0]]))) <= 1e-18:
            degenerate += 1
    faces = d.get('face_ids', d.get('triangle_face_ids', []))
    if faces and len(faces) != len(triangles):
        errors.append('triangle face mapping count mismatch')
    return dict(status='failed' if errors else 'checked', vertices=len(vertices), triangles=len(triangles),
                degenerate_triangles=degenerate, errors=errors, sha256=sha(path),
                boundary_note='Index and finite-value checks only. Tessellation is not exact BRep closure or self-intersection proof.')


def stats_check(job, before, after):
    b, a = before.get('native_stats', {}), after.get('native_stats', {})
    findings = []
    if a.get('valid') is False:
        findings.append(dict(kind='native_invalid_result'))
    if job['expected_input_kind'] == 'solid' and b.get('manifold_solid') is True and a.get('manifold_solid') is False:
        findings.append(dict(kind='solid_became_open_or_sheet', before_material_regions=b.get('material_regions'),
                             after_material_regions=a.get('material_regions'), before_volume_mm3=b.get('volume'),
                             after_volume_mm3=a.get('volume')))
    for key in ['components', 'material_regions', 'voids', 'shells']:
        if key in b and key in a and a[key] != b[key]:
            findings.append(dict(kind='body_census_changed', metric=key, before=b[key], after=a[key]))
    v0, v1 = b.get('volume'), a.get('volume')
    if isinstance(v0, (int, float)) and isinstance(v1, (int, float)) and v0 > 0 and a.get('manifold_solid'):
        ratio = v1/v0
        if v1 <= 0 or ratio < .8 or ratio > 1.2:
            findings.append(dict(kind='volume_change_requires_review', before_mm3=v0, after_mm3=v1, ratio=ratio,
                                 reason='20 percent threshold is an anomaly screen, not a correctness verdict'))
    return findings


def probe_check(job, before, after):
    states = {'inside': True, 'outside': False, 'boundary': 'boundary'}
    b = {p['id']: p for p in before.get('protected_probes', [])}
    a = {p['id']: p for p in after.get('protected_probes', [])}
    rows = []
    for p in job.get('protected_probes', []):
        bb, aa = b.get(p['id'], {}), a.get(p['id'], {})
        observed = states.get(aa.get('state'), aa.get('state'))
        expected = p.get('expected_after_state')
        checked = bb.get('status') == aa.get('status') == 1000 and bool(bb) and bool(aa)
        passed = checked and states.get(bb.get('state'), bb.get('state')) == p.get('expected_before_state') and observed == expected
        rows.append(dict(id=p['id'], checked=checked, passed=passed, before=bb.get('state'), after=aa.get('state'),
                         expected_before=p.get('expected_before_state'), expected_after=expected))
    return rows


def source_metric_check(expected, actual, engine):
    if not actual:
        return dict(status='unverified', reason='No saved pre-call native body metrics')
    rows = {}
    keys = {'area':'area_mm2', 'volume':'volume_mm3', 'bbox':'bbox_mm'} if engine == 'occt' else {}
    for field in ['area','volume','bbox','faces','edges','vertices']:
        e, a = expected.get(field), actual.get(keys.get(field, field))
        if field == 'bbox' and e is not None and a is not None:
            error = max(abs(x-y) for x,y in zip(e,a))
            rows[field] = dict(passed=len(a)==len(e)==6 and error <= 1e-5, maximum_error=error)
        elif isinstance(e,(int,float)) and isinstance(a,(int,float)):
            limit = max(1e-5,abs(e)*1e-6) if field in {'area','volume'} else 0
            rows[field] = dict(passed=abs(e-a)<=limit, expected=e, actual=a, allowed_error=limit)
        else:
            rows[field] = dict(passed=False, reason='missing metric')
    return dict(status='checked' if all(x['passed'] for x in rows.values()) else 'failed', checks=rows,
                reported_shell_counts=dict(source_occt=expected.get('shells'), native=actual.get('shells'),
                    compared_for_equality=False, reason='OCCT geometric shells and SMLib regional shell topology have different representation conventions'),
                limitation='Scalar and face/edge/vertex census consistency with source component; not finite trim or global geometry equivalence proof')


def public_scan(root):
    command = ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z']
    proc = subprocess.run(command, cwd=root, capture_output=True, check=True)
    paths = sorted(set(p for p in proc.stdout.decode().split('\0') if p))
    findings = []
    machine = re.compile(r'/(?:Users|home|private|Applications|Volumes)/[^\s\"\'<>;,\]\)]+')
    secrets = re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16}|sk-(?:proj-)?[A-Za-z0-9_-]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
    forbidden = {'.pdf', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.smb', '.so', '.dylib', '.dll', '.a', '.o', '.exe', '.fcstd'}
    # PDF.js/Three.js are browser dependencies, not native kernel binaries.
    magic = [b'\x7fELF', b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'MZ', b'%PDF-']
    for name in paths:
        p = root/name
        if not p.is_file():
            continue
        raw = p.read_bytes()
        kinds = []
        if p.suffix.lower() in forbidden:
            kinds.append('forbidden_media_or_native_binary_extension')
        if any(raw.startswith(m) for m in magic):
            kinds.append('native_binary_or_pdf_magic')
        try:
            text = raw.decode('utf8')
            # Sanitizer regexes and PDF.js's compiled virtual filesystem name
            # are code literals, not this computer's paths.
            matches = [m.group() for m in machine.finditer(text)]
            matches = [m for m in matches if not m.split('/', 2)[-1].startswith('[')
                       and not (name == 'web/vendor/pdfjs/pdf.worker.min.mjs' and m == '/home/'+'web_user')]
            if matches:
                kinds.append('machine_absolute_path')
            if secrets.search(text):
                kinds.append('possible_credential')
        except UnicodeDecodeError:
            browser_font = name.startswith('web/vendor/pdfjs/standard_fonts/') and p.suffix in {'.pfb','.ttf'}
            if p.suffix != '.brep' and not browser_font:
                kinds.append('unrecognized_binary_requires_review')
        if kinds:
            # No matched text is printed; a potential secret never enters the report.
            findings.append(dict(path=name, kinds=kinds))
    return dict(files_scanned=len(paths), findings=findings,
                status='clear' if not findings else 'needs_review',
                scope='Git tracked and non-ignored untracked files; runs ignored. Pattern screening is not a complete secret-detector guarantee.')


def self_checks():
    reference = Reference(dict(kind='line', samples=[[0.,0.,0.],[5.,0.,0.],[10.,0.,0.]], expected_length_mm=10.))
    edge = dict(id=9, points=[[0.,0.,0.],[5.,0.,0.],[10.,0.,0.]], length=10., length_status=1000)
    rows = []
    for x in [1.,3.,5.,7.,9.]:
        owners = [dict(face_id=i, point=[x,0.,0.], raw_normal=n, status=1000, uv_evaluation_status=1000, drop_gap=0.)
                  for i,n in enumerate([[0.,1.,0.],[0.,0.,1.]])]
        rows.append(dict(edge_id=9, point=[x,0.,0.], owners=owners))
    snapshot = dict(geometry=dict(edges=[edge]), junction_samples=rows)
    assert target_side(snapshot, reference)['full_original_sharp_span_confirmed']
    for row in rows:
        row['owners'][1]['raw_normal'] = [0.,-1.,0.]
    assert not target_side(snapshot, reference)['full_original_sharp_span_confirmed']
    reversed_edge = {**edge, 'id':33, 'points':list(reversed(edge['points']))}
    assert reference.candidate(reversed_edge)['intervals_mm'] == [[0.,10.]]
    shifted_edge = {**edge, 'points':[[x,y+1.,z] for x,y,z in edge['points']]}
    assert reference.candidate(shifted_edge) is None
    circle = dict(kind='circle', center=[0.,0.,0.], normal=[0.,0.,1.], radius=2.,
                  samples=[[2*math.cos(t),2*math.sin(t),0.] for t in [i*TAU/32 for i in range(33)]], expected_length_mm=TAU*2)
    c = Reference(circle)
    ce = dict(id=4, points=[[2*math.cos(t),2*math.sin(t),0.] for t in [i*TAU/64 for i in range(65)]], length=TAU*2, length_status=1000)
    assert coverage(c.candidate(ce)['intervals_mm'], c.total)['full_span']
    assert not coverage([[0.,4.],[6.,10.]],10.)['full_span']
    return dict(status='passed', checks=['synthetic sharp line positive','antiparallel normal negative','reversed sampling and different IDs',
                'offset geometry negative','circle with 32 vs 64 sample intervals','bounded gap negative'])


def saved_smooth_control(root):
    path = root/'runs/fresh-smlib/25.part01.ordinary_challenge.r10/before.json'
    snapshot = read(path, {})
    for edge in snapshot.get('geometry',{}).get('edges',[]):
        if len(edge.get('owners',[])) != 2:
            continue
        try:
            ref = Reference(dict(kind='line', samples=edge['points'], expected_length_mm=edge['length']))
            side = target_side(snapshot, ref, {edge['id']})
        except (ValueError,KeyError):
            continue
        if not side['matches'] or not side['geometry_coverage']['full_span']:
            continue
        sharp = side['matches'][0]['sharpness']
        maximum = sharp['maximum_plane_angle_deg']
        if maximum is not None and maximum < .1 and sharp['valid_normal_samples'] >= 3:
            assert not side['full_original_sharp_span_confirmed']
            return dict(status='passed', source=path.relative_to(root).as_posix(), sha256=sha(path), edge_id=edge['id'],
                        maximum_plane_angle_deg=maximum, normal_samples=sharp['valid_normal_samples'],
                        retained_sharp_reported=False,
                        scope='Actual saved smooth shared edge used as an identity negative control, not an extra native fillet or requested target')
    return dict(status='unverified', reason='No eligible saved smooth edge')


def published_pairs(root, jobs, raw_rows):
    variants = {}
    for path in sorted((root/'web/data/cases').glob('*.json')):
        for variant in read(path, {}).get('variants', []):
            variants[variant['id']] = variant
    failures, checked = [], 0
    raw = {(r['job_id'],r['engine']):r for r in raw_rows}
    for job in jobs:
        variant = variants.get(job['job_id'])
        if variant is None:
            failures.append(dict(job_id=job['job_id'], kind='missing_published_ordinary_request'))
            continue
        for field, expected in [('radius_mm',job['radius_mm']),('source_sha256',job['source_sha256']),('targets',job['targets'])]:
            if variant.get(field) != expected:
                failures.append(dict(job_id=job['job_id'], kind='published_request_mismatch', field=field))
        if variant.get('special_protocol_verified'):
            failures.append(dict(job_id=job['job_id'], kind='ordinary_request_promoted_to_special_protocol'))
        for engine in ['occt','smlib']:
            row = raw.get((job['job_id'],engine))
            if not row:
                continue
            public = variant.get(engine, {})
            checked += 1
            if public.get('outcome') != row.get('outcome'):
                failures.append(dict(job_id=job['job_id'], engine=engine, kind='published_outcome_stale'))
            if public.get('special_feature_passed'):
                failures.append(dict(job_id=job['job_id'], engine=engine, kind='published_unsupported_feature_pass'))
            for field in ['mesh','before_mesh','summary']:
                relative = public.get(field)
                if relative and not (root/'web'/relative).is_file():
                    failures.append(dict(job_id=job['job_id'], engine=engine, kind='missing_published_artifact', field=field))
            for finding in row['scientific_findings']:
                if finding['kind'] in {'native_invalid_result','solid_became_open_or_sheet','original_sharp_target_retained'}:
                    if row.get('native_api_status') in (True,1000) and public.get('status') != 'geometry_failed':
                        failures.append(dict(job_id=job['job_id'], engine=engine, kind='published_api_success_hides_geometry_failure'))
    return dict(status='checked' if not failures else 'failed', ordinary_engine_pairs_checked=checked,
                findings=failures, historical_special_protocols_checked=False)


def audit(root, engines):
    index = read(root/'data/jobs-index.json')
    jobs = [read(root/r['path']) for r in index['jobs']]
    integrity, rows, outcomes = [], [], {}
    expected_numbers = set(range(1,29)) | {30,31,33,34,35,36}
    numbers = {j['number'] for j in jobs}
    if len(jobs) != 104 or len(numbers) != 34 or numbers != expected_numbers or sum(r['runnable'] for r in index['jobs']) != 86:
        integrity.append(dict(kind='dataset_count_or_numbering_mismatch'))
    for j in jobs:
        for path_key, hash_key in [('source_brep','source_sha256'),('source_fixture_json','source_fixture_sha256'),('source_contract_file','source_contract_sha256')]:
            path = root/j[path_key]
            if not path.is_file() or sha(path) != j[hash_key]:
                integrity.append(dict(job_id=j['job_id'], kind='frozen_input_hash_mismatch', field=path_key))
    for engine in engines:
        counts = collections.Counter()
        for job in jobs:
            run = root/f'runs/fresh-{engine}'/job['job_id']
            summary_path = run/'summary.json'
            summary = read(summary_path)
            row = dict(job_id=job['job_id'], number=job['number'], engine=engine,
                       radius_mm=job['radius_mm'], run=run.relative_to(root).as_posix(),
                       scope='ordinary_constant_radius_edge_fillet', source_feature_pass_claimed=False,
                       scientific_findings=[], integrity_findings=[])
            if summary is None:
                row['integrity_findings'].append(dict(kind='missing_summary'))
                counts['missing'] += 1
                rows.append(row)
                continue
            row['summary_sha256'] = sha(summary_path)
            row['outcome'] = summary.get('outcome')
            counts[row['outcome']] += 1
            for key in ['job_id','radius_mm','source_sha256','source_fixture_sha256']:
                if summary.get(key) != job.get(key):
                    row['integrity_findings'].append(dict(kind='summary_request_identity_mismatch', field=key))
            hashes = {}
            for key, record in summary.get('artifacts', {}).items():
                if isinstance(record, dict) and 'path' in record and 'sha256' in record:
                    path = run/record['path']
                    if not path.is_file() or sha(path) != record['sha256']:
                        row['integrity_findings'].append(dict(kind='artifact_hash_mismatch', artifact=key))
            if engine == 'smlib':
                execution = read(run/'execution.json', {})
                row['native_api_status'] = execution.get('native_api_raw_status')
                row['native_call_executed'] = execution.get('native_call_started', False)
                actual_job = read(run/'job.json')
                if actual_job and actual_job != job:
                    row['integrity_findings'].append(dict(kind='executed_job_differs_from_frozen_job'))
                before, after = read(run/'before.json', {}), read(run/'result.json', {})
                if before and after:
                    row['before_native_stats'] = before.get('native_stats')
                    row['after_native_stats'] = after.get('native_stats')
                    row['scientific_findings'].extend(stats_check(job, before, after))
                    probes = probe_check(job, before, after)
                    row['protected_probe_checks'] = probes
                    for p in probes:
                        if p['checked'] and not p['passed']:
                            row['scientific_findings'].append(dict(kind='protected_probe_changed_or_wrong', id=p['id'], evidence=p))
                    target_rows = retention(run, before, after)
                    row['target_replacement_one_sided_oracle'] = target_rows
                    retained = [t['target_id'] for t in target_rows if t['retained_sharp_target']]
                    if retained:
                        row['scientific_findings'].append(dict(kind='original_sharp_target_retained', targets=retained,
                            native_api_status=row['native_api_status'], reason='Whole bounded original span remains sharp at independently matched actual before/after junction samples'))
                for name in ['before.json','result.json','selection.json','execution.json','job.json','prepared-targets.json']:
                    if (run/name).exists():
                        hashes[name] = sha(run/name)
                row['input_import_checks'] = (summary.get('input_import') or {}).get('equivalence')
                if summary.get('source_special_feature_passed') or summary.get('full_quality_passed'):
                    row['integrity_findings'].append(dict(kind='unsupported_source_feature_pass_claim'))
            elif engine == 'occt':
                row['native_api_status'] = summary.get('api_success')
                row['native_call_executed'] = summary.get('native_call_executed', False)
                row['before_native_stats'] = summary.get('input_stats')
                row['after_native_stats'] = summary.get('result_stats')
                if (summary.get('result_stats') or {}).get('valid') is False:
                    row['scientific_findings'].append(dict(kind='native_invalid_result'))
                if summary.get('metrics', {}).get('expected_kind_preserved') is False:
                    row['scientific_findings'].append(dict(kind='expected_body_kind_not_preserved'))
                if summary.get('special_feature_certified'):
                    row['integrity_findings'].append(dict(kind='unsupported_source_feature_pass_claim'))
                req_sha = summary.get('request_sha256')
                if req_sha and req_sha != sha(root/'data/jobs'/f"{job['job_id']}.json"):
                    row['integrity_findings'].append(dict(kind='request_sha_mismatch'))
            row['raw_evidence_sha256'] = hashes
            if row.get('before_native_stats'):
                source_component = read(root/job['source_fixture_json'])['components'][job['component_index']-1]
                source_metrics = source_metric_check(source_component['source_stats'], row['before_native_stats'], engine)
                row['independent_input_metric_check'] = source_metrics
                if source_metrics['status'] == 'failed':
                    row['integrity_findings'].append(dict(kind='native_input_source_metric_mismatch', evidence=source_metrics))
            if engine == 'occt':
                for stage in ['before','result']:
                    record = (summary.get('metrics') or {}).get(f'{stage}_brep_readback', {})
                    path = run/f'{stage}.brep'
                    if record.get('sha256') and (not path.exists() or sha(path) != record['sha256']):
                        row['integrity_findings'].append(dict(kind='native_brep_readback_hash_mismatch', stage=stage))
            meshes = {}
            for label in ['before','result']:
                path = run/f'{label}.mesh.json'
                if path.exists():
                    meshes[label] = mesh_check(path)
                    if meshes[label]['status'] == 'failed':
                        row['scientific_findings'].append(dict(kind='mesh_data_failure', stage=label, errors=meshes[label]['errors']))
            row['mesh_checks'] = meshes
            if row['native_api_status'] in (True,1000) and 'result' not in meshes:
                row['scientific_findings'].append(dict(kind='successful_api_without_result_mesh'))
            rows.append(row)
        outcomes[engine] = dict(counts)
    for row in rows:
        for item in row['integrity_findings']:
            integrity.append(dict(job_id=row['job_id'], engine=row['engine'], **item))
    count_findings = collections.Counter(f['kind'] for row in rows for f in row['scientific_findings'])
    retained = [r['job_id'] for r in rows if r['engine']=='smlib' and r.get('native_api_status')==1000 and any(f['kind']=='original_sharp_target_retained' for f in r['scientific_findings'])]
    published = published_pairs(root, jobs, rows)
    integrity.extend(published['findings'])
    return dict(schema_version=1, audited_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                audit_tool='tools/audit_results.py', audit_tool_sha256=sha(__file__), source_records_modified=False,
                counts=dict(model_groups=len(numbers), ordinary_requests=len(jobs), runnable_requests=sum(r['runnable'] for r in index['jobs']),blocked_requests=18),
                oracle_controls=dict(synthetic=self_checks(), actual_saved_smooth_edge=saved_smooth_control(root)),
                outcome_counts=outcomes, integrity_findings=integrity,
                scientific_finding_counts=dict(count_findings), smlib_api_success_retained_sharp_target_jobs=retained,
                publication_scan=public_scan(root), published_pair_consistency=published, rows=rows,
                limitations=['Independent post-processing of saved real runs; this tool does not rerun either kernel.',
                             'Bounded line/circle plus native lengths and actual coincident junction normals supply one-sided retained-sharp failure evidence. Negative is unverified, never success.',
                             'No cross-kernel equal parameter fraction or surface UV comparison.',
                             'No exhaustive self-intersection, complete section-radius, G1/G2 or source-illustration acceptance test.',
                             '20 percent solid-volume change is an anomaly screen only. Declared protected probes cover only their points.',
                             'OCCT native BREP and SMLib exact NURBS exchange share frozen source lineage, world targets and requested radius; internal representations differ.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, default=Path('docs/independent-audit.json'))
    parser.add_argument('--engine', choices=['occt','smlib','both'], default='both')
    args = parser.parse_args()
    root = args.root.resolve()
    result = audit(root, ['occt','smlib'] if args.engine == 'both' else [args.engine])
    output = args.output if args.output.is_absolute() else root/args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ['counts','outcome_counts','scientific_finding_counts','smlib_api_success_retained_sharp_target_jobs']}, ensure_ascii=False, indent=2))
    print(json.dumps(dict(integrity_findings=len(result['integrity_findings']), publication_findings=len(result['publication_scan']['findings']),output=output.relative_to(root).as_posix()),ensure_ascii=False))
    return 1 if result['integrity_findings'] or result['publication_scan']['findings'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
