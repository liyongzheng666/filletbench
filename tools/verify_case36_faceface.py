"""Verify case36's published execution identities without running a kernel.

This does not repeat a fillet, reproduce independent measurements, certify the
general Parasolid trim laws, or accept an image. It binds those measured records
to the exact frozen input, actual calls, CAD/mesh artifacts and displayed modes.
"""
from pathlib import Path
import argparse,hashlib,json,math

ROOT=Path(__file__).resolve().parents[1]
PROTOCOL='data/case36-faceface/protocol.json'
SOURCE_SHA='c88672f2fa73d5b40f13de10442dea5e432c6bd0b8f91db4412cd54fe6fbc5a1'
MODES={'to_walls':('bevel',3),'no':('none',0),'short':('minimal',1),'long':('maximal',2)}
NATIVE_METHOD='native_surface_surface_rolling_ball_walking_and_approximation'

def read(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def valid_sha(value):return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)
def relative_reference(root,value):
    return isinstance(value,str) and bool(value) and not Path(value).is_absolute() and '..' not in Path(value).parts and (Path(root)/value).resolve().is_relative_to(Path(root).resolve())
def file_at(root,value):
    if not relative_reference(root,value):return None
    p=(Path(root)/value).resolve()
    return p if p.is_relative_to(Path(root).resolve()) and p.is_file() else None
def web_file(root,value):return file_at(Path(root)/'web',value)
def close(a,b,tol=1e-6):return isinstance(a,(int,float)) and not isinstance(a,bool) and abs(a-b)<=tol
def same_numbers(a,b,tol=1e-6):return isinstance(a,list) and len(a)==len(b) and all(close(x,y,tol) for x,y in zip(a,b))
def checked_file(root,reference,digest):
    p=file_at(root,reference)
    return p is not None and isinstance(digest,str) and sha(p)==digest

def index_binding_checks(binding,protocol,engine,root=ROOT):
    """A partial run may replace one row without relabelling cached rows.

    The canonical index remains the default. Other real indexes need an explicit
    path/hash registration; when present, an index must contain this very mode
    and raw summary. Merely registering a one-row index cannot cover four modes.
    """
    root=Path(root).resolve();checks={};path=binding.get('index');digest=binding.get('index_sha256')
    defaults=protocol.get('run_indexes',{});defaults=defaults if isinstance(defaults,dict) else {}
    default=defaults.get(engine)
    registry=protocol.get('additional_run_indexes',{});registry=registry if isinstance(registry,dict) else {}
    extras=registry.get(engine,[])
    extras=extras if isinstance(extras,list) else []
    extra_matches=[r for r in extras if isinstance(r,dict) and r.get('path')==path and r.get('sha256')==digest]
    checks['index_registered']=relative_reference(root,path) and valid_sha(digest) and (path==default or len(extra_matches)==1)
    index=file_at(root,path)
    if index is None:return checks
    checks['raw_index_current']=sha(index)==digest
    data=read(index);rows=data.get('rows',[])
    checks['index_rows_schema']=isinstance(rows,list) and bool(rows)
    rows=rows if isinstance(rows,list) else []
    checks['index_source_identity']=data.get('source_sha256')==SOURCE_SHA
    def actual_summary(row):
        return (isinstance(row,dict) and row.get('summary')==binding.get('summary') and
                row.get('summary_sha256',row.get('raw_summary_sha256'))==binding.get('summary_sha256') and
                row.get('source_sha256',data.get('source_sha256'))==SOURCE_SHA and
                row.get('radius_mm',data.get('radius_mm'))==8)
    mode=binding.get('mode')
    if engine=='occt_native':
        selected=data.get('selected_candidate');selected=selected if isinstance(selected,dict) else {}
        checks['native_selected_summary']=actual_summary(selected)
        selected_rows=[r for r in rows if actual_summary(r) and r.get('id')==(selected or {}).get('id')]
        checks['index_contains_actual_mode_summary']=len(selected_rows)==1 and binding.get('variant_id')=='native-faceface-r8'
    else:
        def same_mode(row):
            if engine=='occt_composite':return row.get('mode')==mode
            driver=MODES.get(mode,('',-1))[0]
            return engine=='smlib_native' and row.get('source_mode_candidate')==mode and row.get('mode')==driver
        matches=[r for r in rows if isinstance(r,dict) and actual_summary(r) and same_mode(r)]
        checks['index_contains_actual_mode_summary']=len(matches)==1
    return checks

def original_display_domain(mesh):
    """Reject the old common-band L mesh, even with self-consistent fake hashes."""
    vertices=mesh.get('vertices',[]);triangles=mesh.get('triangles',[]);areas=[0.,0.]
    def belongs(p,side):
        if not isinstance(p,list) or len(p)!=3 or not all(isinstance(q,(int,float)) and math.isfinite(q) for q in p):return False
        x,y,z=p
        return (abs(y)<=1e-6 and -7-1e-6<=x<=7+1e-6 and 5-1e-6<=z<=25+1e-6) if side==0 else (abs(z)<=1e-6 and -12.5-1e-6<=x<=12.5+1e-6 and 5-1e-6<=y<=23+1e-6)
    try:
        if not vertices or not triangles or not all(any(belongs(p,side) for side in (0,1)) for p in vertices):return False
        for t in triangles:
            if len(t)!=3:return False
            ps=[vertices[i] for i in t];sides=[side for side in (0,1) if all(belongs(p,side) for p in ps)]
            if len(sides)!=1:return False
            a,b,c=ps;u=[b[i]-a[i] for i in range(3)];v=[c[i]-a[i] for i in range(3)]
            cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
            areas[sides[0]]+=math.sqrt(sum(q*q for q in cross))/2
        return close(areas[0],280,1e-5) and close(areas[1],450,1e-5)
    except (IndexError,TypeError,ValueError):return False

def audit_reference(protocol):
    ref=protocol.get('independent_audit')
    return ref if isinstance(ref,dict) else {'path':ref,'sha256':protocol.get('independent_audit_sha256')}

def case36_faceface_checks(case,root=ROOT):
    root=Path(root).resolve();checks={};protocol={};ref=case.get('faceface_protocol') or {}
    checks['registered_case36_faceface']=case.get('number')==36 and ref.get('path')==PROTOCOL
    path=file_at(root,PROTOCOL);checks['protocol_exists']=path is not None
    if path is None:return checks,protocol
    protocol=read(path);digest=sha(path)
    checks['protocol_hash']=ref=={'path':PROTOCOL,'sha256':digest}
    checks['protocol_kind']=protocol.get('schema')=='filletbench.case36-faceface-protocol.v1' and protocol.get('id')=='case36-faceface-r8-v1' and protocol.get('case_number')==36
    source=file_at(root,protocol.get('source_brep'));frozen=file_at(root,protocol.get('frozen_case_file'));frozen_data=read(frozen) if frozen else {}
    checks['exact_frozen_input']=source is not None and sha(source)==protocol.get('source_sha256')==case.get('source_sha256')==frozen_data.get('source_sha256')==SOURCE_SHA
    checks['frozen_definition_unchanged']=protocol.get('frozen_case_file')=='data/original-occ/cases/36.json' and frozen is not None and sha(frozen)==protocol.get('frozen_case_sha256')==case.get('source_case_sha256')
    checks['R8_declared_reconstruction']=protocol.get('radius_mm')==8 and protocol.get('radius_is_reconstruction_test_value') is True
    fixed_thresholds={'input_mm':1e-6,'G0_mm':1e-6,'G1_degrees':.1,'profile_radius_deviation_mm':1e-5,'profile_circle_residual_mm':1e-5,'endpoints_mm':1e-6}
    checks['fixed_measurement_thresholds']=protocol.get('thresholds')==fixed_thresholds
    checks['fixed_physical_contact_law']=protocol.get('shared_contact_law')=={'center_yz_mm':[8,8],'vertical_contact_z_mm':8,'horizontal_contact_y_mm':8,'quadrant_degrees':90}
    checks['four_requested_modes']={m.get('id'):(m.get('smlib_driver_mode'),m.get('smlib_native_enum')) for m in protocol.get('modes',[])}==MODES and len(protocol.get('modes',[]))==4
    checks['working_extent_declared']=protocol.get('occt_no_working_x_interval_mm')==[-20,20] and protocol.get('no_extent_is_implementation_defined') is True
    checks['no_native_trim_or_full_acceptance_promotion']=protocol.get('native_occt_trim_enum_supported_by_selected_api') is False and protocol.get('source_feature_certified') is False and protocol.get('human_appearance_status')=='pending' and case.get('human_status')=='pending'
    source_ref=protocol.get('source_geometry_audit') or {}
    checks['source_geometry_audit_hash']=checked_file(root,source_ref.get('path'),source_ref.get('sha256'))
    audit_ref=audit_reference(protocol);ap=file_at(root,audit_ref.get('path'))
    checks['independent_audit_hash']=ap is not None and sha(ap)==audit_ref.get('sha256')
    audit=read(ap) if ap else {};audit_rows=audit.get('rows',[])
    checks['independent_audit_identity']=audit.get('schema')=='case36.faceface-independent-geometry-audit.v1' and audit.get('source',{}).get('sha256')==SOURCE_SHA and audit.get('auditor_uses_worker_pass_booleans_as_geometry_proof') is False and audit.get('auditor_repeated_fillet_calls') is False
    checks['independent_thresholds_match']=audit.get('thresholds')=={'input_and_contact_G0_mm':1e-6,'rail_endpoint_mm':1e-6,'unoriented_tangent_plane_angle_deg':.1,'profile_circle_fit_radial_residual_mm':1e-5,'profile_circle_radius_deviation_mm':1e-5}
    source_gates=audit.get('source',{}).get('gates',{})
    checks['independent_source_gates']=all(source_gates.get(k) is True for k in ['source_bytes','two_original_finite_faces','original_domains','original_area_and_gap'])
    checks['independent_scope_not_full_feature']=audit.get('source_feature_certified') is False and audit.get('human_appearance_status')=='pending'
    archive=file_at(root,protocol.get('archived_admission_snapshot'))
    checks['admission_history_retained']=archive is not None and read(archive).get('case',{}).get('input_protocol',{}).get('path')=='data/case36-input/protocol.json'
    variants=case.get('variants',[]);expected={f'trim-{m}-r8' for m in MODES}|{'native-faceface-r8'}
    checks['view_ids_and_radius']=len(variants)==5 and {v.get('id') for v in variants}==expected and all(v.get('radius_mm')==8 for v in variants)
    bp=web_file(root,case.get('base_mesh'))
    checks['displayed_original_finite_domains']=bp is not None and original_display_domain(read(bp))
    bindings=protocol.get('bindings',[]);keys=[(b.get('engine'),b.get('variant_id')) for b in bindings]
    extras=protocol.get('additional_run_indexes',{})
    checks['additional_indexes_registry']=isinstance(extras,dict) and all(engine in ['occt_composite','smlib_native','occt_native'] and isinstance(rows,list) and len({r.get('path') for r in rows if isinstance(r,dict)})==len(rows) and all(isinstance(r,dict) and relative_reference(root,r.get('path')) and valid_sha(r.get('sha256')) for r in rows) for engine,rows in extras.items())
    expected_bindings={('occt_composite',f'trim-{m}-r8') for m in MODES}|{('smlib_native',f'trim-{m}-r8') for m in MODES}|{('occt_native','native-faceface-r8')}
    checks['nine_execution_bindings']=len(bindings)==9 and len(set(keys))==9 and set(keys)==expected_bindings
    for v in variants:
        vid=v.get('id','unknown');mode=vid[len('trim-'):-len('-r8')] if vid.startswith('trim-') and vid.endswith('-r8') else None
        checks[vid+':same_original_input']=v.get('base_sha256')==SOURCE_SHA and v.get('base_mesh')==case.get('base_mesh')==v.get('operation_mesh') and v.get('input_relation')=='same_as_base' and v.get('operation_is_derived') is False
        checks[vid+':radius_parameter']=v.get('parameters',{}).get('radius_mm')==8
        for engine,record_key in ([('occt_native','occt')] if mode is None else [('occt_composite','occt'),('smlib_native','smlib')]):
            r=v.get(record_key) or {};prefix=vid+':'+record_key+':'
            found=[b for b in bindings if b.get('engine')==engine and b.get('variant_id')==vid]
            checks[prefix+'unique_registered_execution']=len(found)==1
            b=found[0] if len(found)==1 else {}
            checks[prefix+'portable_raw_references']=all(relative_reference(root,b.get(k)) for k in ['summary','index','raw_result_mesh'])
            checks[prefix+'protocol_reference']=r.get('faceface_protocol')=={'path':PROTOCOL,'sha256':digest}
            checks[prefix+'source_and_radius']=r.get('source_sha256')==SOURCE_SHA and r.get('parameters',{}).get('radius_mm',r.get('radius_mm'))==8
            checks[prefix+'operation_source_fingerprint']=r.get('operation_input_sha256')==SOURCE_SHA
            checks[prefix+'no_blanket_acceptance']=r.get('source_feature_passed') is False
            summary=web_file(root,r.get('summary'))
            checks[prefix+'published_summary_binding']=summary is not None and r.get('summary')==b.get('published_summary') and sha(summary)==r.get('published_summary_sha256')==b.get('published_summary_sha256')
            s=read(summary) if summary else {}
            checks[prefix+'actual_raw_summary_binding']=r.get('raw_summary_sha256')==b.get('summary_sha256') and summary is not None and sha(summary)==b.get('summary_sha256')
            raw=file_at(root,b.get('summary'))
            if raw is not None:checks[prefix+'raw_summary_current']=sha(raw)==b.get('summary_sha256') and read(raw)==s
            index=file_at(root,b.get('index'))
            checks.update({prefix+key:ok for key,ok in index_binding_checks(b,protocol,engine,root).items()})
            checks[prefix+'raw_result_mesh_fingerprint']=valid_sha(b.get('raw_result_mesh_sha256'))
            checks[prefix+'actual_engine_version']=r.get('version')==(s.get('engine_version') if engine!='smlib_native' else '10.0.0')
            if index is not None and engine=='smlib_native':checks[prefix+'sdk_version_recorded_by_runner']=r.get('version')==read(index).get('engine_version')
            pmesh=web_file(root,r.get('mesh'))
            checks[prefix+'published_mesh_binding']=pmesh is not None and r.get('mesh')==b.get('published_mesh') and sha(pmesh)==b.get('published_mesh_sha256')
            rawmesh=file_at(root,b.get('raw_result_mesh'))
            if rawmesh is not None:
                checks[prefix+'raw_mesh_current']=sha(rawmesh)==b.get('raw_result_mesh_sha256')
                actual_mesh=read(rawmesh);shown=read(pmesh) if pmesh else {}
                checks[prefix+'display_is_actual_result_mesh']=all(shown.get(k)==actual_mesh.get(k) for k in ['vertices','triangles']) and shown.get('face_ids',[])==actual_mesh.get('face_ids',actual_mesh.get('triangle_face_ids',[]))
            if b.get('request_file'):
                checks[prefix+'request_hash']=checked_file(root,b['request_file'],b.get('request_sha256')) and r.get('request_file')==b['request_file']
            checks[prefix+'actual_source_radius']=s.get('source_sha256')==s.get('operation_input_sha256')==SOURCE_SHA and s.get('radius_mm')==8
            if engine=='occt_composite':
                checks[prefix+'explicit_not_native']=r.get('method')==s.get('method')=='explicit_occ_composition' and r.get('native_call_executed') is False and s.get('native_face_face_call') is False and s.get('native_call_executed') is False and s.get('construction_executed') is True and s.get('walls_modified') is False and s.get('original_walls_added_to_result') is False and s.get('result_kind')=='single_blend_face'
                checks[prefix+'mode_request']=s.get('mode')==b.get('mode')==mode
                checks[prefix+'explicit_acceptance_boundary']=s.get('source_feature_certified') is False and s.get('source_feature_passed') is False and s.get('human_appearance_acceptance') is False
            elif engine=='smlib_native':
                driver,enum=MODES.get(mode,('',-1))
                checks[prefix+'native_mode_request']=s.get('mode')==driver and s.get('source_mode_candidate')==b.get('mode')==mode and s.get('trim_enum')==enum and s.get('base_trim')==0
                checks[prefix+'actual_native_call']=r.get('method')=='native_surface_surface_fillet' and s.get('fresh_native_process') is True and s.get('native_call_started') is True and s.get('explicit_post_crop') is False
                checks[prefix+'sdk_acceptance_boundary']=s.get('source_special_feature_passed') is False and s.get('full_quality_passed') is False and s.get('human_appearance_status')=='pending'
                checks[prefix+'native_input_representation_distinct']='canonical_source_brep_fingerprint' in s.get('operation_input_sha256_scope','') and 'SMB' in s.get('operation_input_sha256_scope','')
                files=s.get('native_input_files',[])
                checks[prefix+'native_input_files_bound']=len(files)==2 and {f.get('side') for f in files}=={'left','right'} and all(valid_sha(f.get('sha256')) and f['sha256']!=SOURCE_SHA and relative_reference(root,f.get('path')) for f in files)
                for f in files:
                    p=file_at(root,f.get('path'))
                    if p is not None:checks[prefix+'actual_native_'+f['side']+'_hash']=sha(p)==f['sha256']
                checks[prefix+'native_finite_input_admitted']=s.get('original_finite_input_admitted') is True and s.get('finite_input_gate',{}).get('passed') is True and len(s.get('input_imports',[]))==2 and all(q.get('passed') is True and q.get('automatic_heal') is False and q.get('stitch') is False and q.get('thickening') is False for q in s.get('input_imports',[]))
                checks[prefix+'post_input_behavior_not_hidden']=s.get('immutable_source_file_unchanged') is True and s.get('precall_finite_domains_match_source') is True and isinstance(s.get('post_input_geometry_domain_preserved'),bool) and isinstance(s.get('post_input_topology_preserved'),bool)
                checks[prefix+'native_result_kind']=s.get('result_kind')=='independent_blend_sheet' and s.get('native_readback_passed') is True
            else:
                checks[prefix+'native_walking_not_composition']=r.get('method')==s.get('method')==NATIVE_METHOD and r.get('native_call_executed') is True and s.get('native_call_executed') is True and s.get('native_walking_called') is True and s.get('native_approximation_called') is True and s.get('walking_done') is True and s.get('approximation_done') is True
                checks[prefix+'native_original_surface_scope']=s.get('source_finite_domains_preserved') is True and s.get('input_surface_extension') is False and s.get('input_common_edge_constructed') is False and s.get('original_trim_modes_native_parameter_available') is False
                checks[prefix+'native_quarter_branch']=s.get('reference_quarter_section_branch') is True and close(s.get('native_section_angle_rad'),math.pi/2) and close(s.get('native_section_radius_mm'),8)
            if mode is not None:
                method='explicit_occ_composition' if engine=='occt_composite' else 'native_surface_surface_fillet'
                measured=[a for a in audit_rows if a.get('method')==method and a.get('mode')==mode]
                checks[prefix+'unique_measured_mode']=len(measured)==1
                a=measured[0] if len(measured)==1 else {}
                checks[prefix+'measured_actual_summary_binding']=any(f.get('path')==b.get('summary') and f.get('sha256')==b.get('summary_sha256') for f in a.get('actual_evidence',[]))
                checks[prefix+'measured_source_radius']=a.get('source_sha256')==SOURCE_SHA and a.get('radius_mm')==8 and a.get('source_feature_certified') is False
                if r.get('status')=='controlled_subchecks':checks[prefix+'controlled_label_matches_measured_trim']=a.get('trim',{}).get('all_subcriteria_passed') is True
                for evidence in a.get('actual_evidence',[]):
                    actual=file_at(root,evidence.get('path'))
                    if actual is not None:checks[prefix+'measured_evidence:'+evidence['path']]=sha(actual)==evidence.get('sha256')
            for f in r.get('files',[]):
                if not isinstance(f,dict):continue
                download=web_file(root,f.get('path'))
                checks[prefix+'download:'+str(f.get('path'))]=download is not None and sha(download)==f.get('sha256')
                if str(f.get('path','')).endswith('.brep') and f.get('sha256')!=SOURCE_SHA:
                    checks[prefix+'actual_result_cad_hash']=f.get('sha256')==s.get('result_brep_sha256')
        sm=v.get('smlib') or {}
        if mode is None:checks[vid+':no_reused_sdk_control']=sm.get('mesh') is None and sm.get('pairing_status')=='not_applicable_native_api_control'
        else:checks[vid+':sdk_pairing_scope']=sm.get('pairing_status')=='matched_constraints_different_representation'
    return checks,protocol

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path);args=parser.parse_args()
    case=read(ROOT/'web/data/original-occ/cases/36.json');checks,protocol=case36_faceface_checks(case)
    report={'schema':'case36.faceface-public-identity.v1','passed':all(checks.values()),'protocol_id':protocol.get('id'),'checks':checks,'issues':[k for k,v in checks.items() if not v],
            'scope':'Published artifact and recorded execution identity only; no native call or independent geometry test is repeated here.'}
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':report['passed'],'issues':report['issues']}));return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
