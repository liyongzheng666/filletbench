"""Verify the registered exact-input case36 correction without calling a kernel."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sys
from run_case36_input import definition_sha256

ROOT=Path(__file__).resolve().parents[1]
PROTOCOL='data/case36-input/protocol.json'
SOURCE_SHA='c88672f2fa73d5b40f13de10442dea5e432c6bd0b8f91db4412cd54fe6fbc5a1'
RADII={'part01-r1p0':1.0,'part01-r2p0':2.0,'part01-r0p5':0.5}
GEOMETRY_GATES=('source_two_disjoint_faces','source_area_730','source_no_shared_edge','source_gap_sqrt50','source_unchanged')

def read(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def file_at(root,value):
    if not isinstance(value,str) or not value or Path(value).is_absolute():return None
    p=(root/value).resolve()
    return p if p.is_relative_to(root.resolve()) and p.is_file() else None
def close(a,b,tol=1e-8):return isinstance(a,(int,float)) and abs(a-b)<tol
def source_mesh_geometry(path):
    if path is None:return False
    mesh=read(path);vertices=mesh.get('vertices',[]);triangles=mesh.get('triangles',[])
    if len(vertices)!=8 or len(triangles)!=4:return False
    area={'vertical':0.0,'horizontal':0.0}
    try:
        for tri in triangles:
            points=[vertices[i] for i in tri]
            vertical=all(abs(p[1])<1e-8 and -7-1e-8<=p[0]<=7+1e-8 and 5-1e-8<=p[2]<=25+1e-8 for p in points)
            horizontal=all(abs(p[2])<1e-8 and -12.5-1e-8<=p[0]<=12.5+1e-8 and 5-1e-8<=p[1]<=23+1e-8 for p in points)
            if not (vertical or horizontal):return False
            a=[points[1][i]-points[0][i] for i in range(3)];b=[points[2][i]-points[0][i] for i in range(3)]
            cross=[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
            area['vertical' if vertical else 'horizontal']+=math.sqrt(sum(x*x for x in cross))/2
    except (IndexError,TypeError,ValueError):return False
    return close(area['vertical'],280) and close(area['horizontal'],450)

def case36_input_checks(case,root=ROOT):
    """A single-case, hash-registered exception; frozen case/source stay intact.

    Checks imported measurement evidence, not a new geometry calculation and not
    native kernel success. Every public result must remain an admission block.
    """
    root=Path(root).resolve();checks={};contract={};ref=case.get('input_protocol') or {}
    checks['registered_case36_input_protocol']=case.get('number')==36 and ref.get('path')==PROTOCOL
    path=file_at(root,PROTOCOL);checks['protocol_exists']=path is not None
    if path is None:return checks,contract
    contract=read(path);protocol_hash=sha(path)
    checks['protocol_hash']=ref=={'path':PROTOCOL,'sha256':protocol_hash}
    checks['protocol_definition']=contract.get('schema')=='filletbench.case36-input-protocol.v1' and contract.get('case_number')==36 and contract.get('id')=='case36-exact-disjoint-input-v1' and definition_sha256(contract)==contract.get('definition_sha256')
    frozen=file_at(root,contract.get('frozen_case_file'));frozen_data=read(frozen) if frozen else {}
    checks['frozen_case_definition_retained']=frozen is not None and sha(frozen)==contract.get('frozen_case_sha256')==case.get('source_case_sha256')
    source=file_at(root,contract.get('source_brep'))
    checks['original_source_retained']=source is not None and sha(source)==contract.get('source_sha256')==case.get('source_sha256')==frozen_data.get('source_sha256')==SOURCE_SHA
    audit_ref=contract.get('geometry_audit') or {};audit_file=file_at(root,audit_ref.get('path'))
    checks['independent_audit_hash']=audit_file is not None and sha(audit_file)==audit_ref.get('sha256')
    audit=read(audit_file) if audit_file else {}
    checks['independent_source_measurements']=audit.get('schema')=='case36.exact-source-independent-measurements.v1' and audit.get('source_sha256')==audit.get('current_operation_sha256')==SOURCE_SHA and audit.get('author_summary_used_as_evidence') is False
    checks['independent_geometry_gates']=audit.get('automated_measurements_passed') is True and all(audit.get('gates',{}).get(k) is True for k in GEOMETRY_GATES)
    correction=case.get('input_correction') or {}
    checks['correction_registry']=correction.get('id')==contract.get('id') and correction.get('source_sha256')==correction.get('operation_input_sha256')==SOURCE_SHA and correction.get('geometry_audit')==audit_ref and correction.get('native_call_executed') is False and correction.get('legacy_archive')=='data/case36-input/legacy-derived-case.json'
    legacy_file=file_at(root,'web/data/case36-input/legacy-derived-case.json')
    legacy=read(legacy_file) if legacy_file else {}
    checks['legacy_derivative_archive_preserved']=legacy.get('number')==36 and legacy.get('source_sha256')==SOURCE_SHA and {v.get('id'):v.get('radius_mm') for v in legacy.get('variants',[])}==RADII and all(v.get('occt',{}).get('operation_input_sha256') not in [None,SOURCE_SHA] and v.get('occt',{}).get('mesh') for v in legacy.get('variants',[]))
    variants=case.get('variants',[]);registered=contract.get('variants',[])
    checks['radii_and_ids_retained']=len(variants)==len(registered)==3 and {v.get('id'):v.get('radius_mm') for v in variants}=={v.get('id'):v.get('radius_mm') for v in registered}==RADII
    for v in variants:
        vid=v.get('id','unknown');oc=v.get('occt') or {};prefix=vid+':'
        reg=next((r for r in registered if r.get('id')==vid),{})
        checks[prefix+'source_operation_identity']=v.get('base_sha256')==oc.get('source_sha256')==oc.get('operation_input_sha256')==SOURCE_SHA
        checks[prefix+'same_input_display']=bool(v.get('base_mesh')) and v.get('base_mesh')==case.get('base_mesh')==v.get('operation_mesh')==oc.get('before_mesh') and v.get('input_relation')=='same_as_base' and v.get('operation_is_derived') is False
        for key in ['base_mesh','operation_mesh']:
            checks[prefix+key+'_exists']=file_at(root,'web/'+v[key]) is not None if isinstance(v.get(key),str) else False
        mesh_path=file_at(root,'web/'+v['base_mesh']) if isinstance(v.get('base_mesh'),str) else None
        checks[prefix+'displayed_mesh_preserves_original_finite_domains']=source_mesh_geometry(mesh_path)
        checks[prefix+'no_false_native_output']=oc.get('status')=='blocked' and oc.get('method')=='input_admission_check' and oc.get('outcome')=='blocked_no_shared_edge' and oc.get('mesh') is None and oc.get('native_call_executed') is False and oc.get('api_success') is None and oc.get('source_feature_passed') is False
        checks[prefix+'parameters_not_prepared']=v.get('parameters',{}).get('radius_mm')==v.get('radius_mm') and v.get('parameters',{}).get('preprocess',{}).get('type','none') in ['none','read_exact_source']
        targets=sum([v.get(key,[]) for key in ['targets','base_targets','operation_targets']],[])
        checks[prefix+'no_fabricated_native_selected_edge']=all(t.get('target_kind')=='auxiliary_guide' for t in targets)
        files=oc.get('files',[]);breps=[f for f in files if str(f.get('path','')).endswith('.brep')]
        checks[prefix+'public_brep_is_exact_source']=bool(breps) and all(file_at(root,'web/'+f['path']) is not None and sha(file_at(root,'web/'+f['path']))==f.get('sha256')==SOURCE_SHA for f in breps)
        summary_file=file_at(root,'web/'+oc['summary']) if isinstance(oc.get('summary'),str) else None
        checks[prefix+'published_summary_hash']=summary_file is not None and sha(summary_file)==oc.get('published_summary_sha256')
        summary=read(summary_file) if summary_file else {}
        checks[prefix+'registered_actual_summary']=bool(reg.get('summary_sha256')) and oc.get('raw_summary_sha256')==reg.get('summary_sha256')
        serialized=(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
        checks[prefix+'published_content_is_registered_actual_summary']=hashlib.sha256(serialized).hexdigest()==reg.get('summary_sha256')
        raw_file=file_at(root,reg.get('summary'))
        if raw_file is not None:checks[prefix+'raw_execution_summary_bytes']=sha(raw_file)==reg.get('summary_sha256') and read(raw_file)==summary
        checks[prefix+'actual_input_and_parameters']=summary.get('number')==36 and summary.get('variant_id')==vid and summary.get('radius_mm')==v.get('radius_mm') and summary.get('source_sha256')==summary.get('operation_input_sha256')==SOURCE_SHA and summary.get('source_case_sha256')==contract.get('frozen_case_sha256') and summary.get('input_protocol')=={'path':PROTOCOL,'definition_sha256':contract.get('definition_sha256')}
        checks[prefix+'actual_no_native_call']=summary.get('schema')=='case36.exact-input-admission.v1' and summary.get('method')=='input_admission_check' and summary.get('outcome')=='blocked_no_shared_edge' and summary.get('preprocessing_executed') is False and summary.get('native_call_executed') is False and summary.get('api_success') is None and summary.get('execution',{}).get('native_call_started') is False and summary.get('source_feature_certified') is False and summary.get('source_unchanged') is True and summary.get('operation_equals_source_bytes') is True
        stats=summary.get('input_measurements',{}).get('stats',{})
        checks[prefix+'actual_original_finite_domains']=stats.get('faces')==2 and stats.get('shells')==0 and stats.get('solids')==0 and close(stats.get('area_mm2'),730) and close(summary.get('input_measurements',{}).get('finite_face_gap_mm'),50**0.5) and summary.get('input_measurements',{}).get('shared_edges')==[] and bool(summary.get('input_checks')) and all(x is True for x in summary['input_checks'].values())
        checks[prefix+'actual_no_edge_admitted']=summary.get('selection',{}).get('shared_edge_candidate_count')==0 and summary.get('selection',{}).get('selected_native_edges')==[] and summary.get('selection',{}).get('theoretical_line_is_existing_edge') is False
        contacts=summary.get('theoretical_circular_contacts',{})
        checks[prefix+'requested_small_radius_contacts_are_outside']=contacts.get('radius_mm')==v.get('radius_mm') and contacts.get('actual_fillet_generated') is False and contacts.get('both_contacts_within_original_finite_faces') is False and len(contacts.get('contact_samples',[]))==2 and all(r.get('state')=='TopAbs_OUT' for r in contacts.get('contact_samples',[]))
        sm=v.get('smlib') or {}
        checks[prefix+'no_unmatched_sdk_substitution']=sm.get('mesh') is None and sm.get('status')=='not_run' and sm.get('pairing_status')=='protocol_not_encoded'
    return checks,contract

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path);args=parser.parse_args()
    case=read(ROOT/'web/data/original-occ/cases/36.json')
    baseline_scope='current original-input admission view'
    if case.get('faceface_protocol'):
        case=read(ROOT/'web/data/case36-input/published-case.json')['case']
        baseline_scope='archived small-radius admission baseline; current R8 face-face results use verify_case36_faceface.py'
    checks,contract=case36_input_checks(case)
    report={'schema':'case36.published-input-verification.v1','passed':all(checks.values()),'protocol_id':contract.get('id'),'checks':checks,'issues':[k for k,v in checks.items() if not v],
            'scope':'Exact input and recorded preflight identity; no new native call, kernel limitation claim or human appearance acceptance.','baseline_scope':baseline_scope}
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':report['passed'],'issues':report['issues'],'baseline_scope':baseline_scope}));return 0 if report['passed'] else 1

if __name__=='__main__':sys.exit(main())
