"""Check ordinary-edge admission on the exact, unmodified case36 input.

This is an input applicability test, not a native face-face fillet or trim-mode
implementation. Source BREP bytes are copied verbatim and are never prepared.
"""
from pathlib import Path
import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import hashlib
import json
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
CONTRACT='data/case36-input/protocol.json'
PIN='7.9.3.1.1'

def read(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def relative(path):
    path=Path(path).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('Use a repository-local output directory for portable evidence paths')
    return path.relative_to(ROOT).as_posix()
def definition_sha256(protocol):
    definition={k:protocol[k] for k in ['schema','id','case_number','source_brep','source_sha256','frozen_case_file','frozen_case_sha256','geometry_audit','expected_input']}
    definition['variants']=[{'id':v['id'],'radius_mm':v['radius_mm']} for v in protocol['variants']]
    return hashlib.sha256(json.dumps(definition,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def measure(shape):
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.TopAbs import TopAbs_FACE,TopAbs_EDGE,TopAbs_VERTEX
    from OCP.TopoDS import TopoDS
    import geometry as g
    faces=g.shapes(shape,TopAbs_FACE);rows=[]
    for i,f in enumerate(faces,1):
        surface=BRepAdaptor_Surface(TopoDS.Face_s(f));plane=surface.Plane()
        rows.append({'index_1based':i,'stats':g.stats(f),'plane_normal':g.xyz(plane.Axis().Direction()),
                     'plane_location':g.xyz(plane.Location()),'vertices_mm':[g.xyz(BRep_Tool.Pnt_s(TopoDS.Vertex_s(v))) for v in g.shapes(f,TopAbs_VERTEX)]})
    gap=BRepExtrema_DistShapeShape(faces[0],faces[1]);gap.Perform()
    edges=[g.edge_record(shape,TopoDS.Edge_s(e)) for e in g.shapes(shape,TopAbs_EDGE)]
    return {'stats':g.stats(shape),'faces':rows,'finite_face_gap_mm':gap.Value(),
            'shared_edges':[e for e in edges if len(e['adjacent_faces_1based'])==2],
            'method':'Independent finite BREP distance, plane, area, bounding-box and edge-owner measurements; no preprocessing.'}

def contact_classification(shape,radius):
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Pnt
    import geometry as g
    rows=[]
    for face,p in zip(g.shapes(shape,TopAbs_FACE),[[0,0,radius],[0,radius,0]]):
        state=str(BRepClass_FaceClassifier(TopoDS.Face_s(face),gp_Pnt(*p),1e-7).State()).split('.')[-1]
        rows.append({'point_mm':p,'state':state,'inside_or_on_original_finite_face':state in ['TopAbs_IN','TopAbs_ON']})
    return {'radius_mm':radius,'hypothesis':'Positive-quadrant circular cross-section tangent to the two underlying planes, center (y,z)=(R,R).',
            'contact_samples':rows,'both_contacts_within_original_finite_faces':all(r['inside_or_on_original_finite_face'] for r in rows),
            'actual_fillet_generated':False,'native_face_face_call':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('runs/case36-input/canonical'))
    parser.add_argument('--variant',help='One registered ID; default checks all three radii')
    args=parser.parse_args();output=args.output.resolve();relative(output)
    if output.exists() and any(output.iterdir()):parser.error('Refusing to overwrite existing evidence; choose a fresh --output')
    protocol=read(ROOT/CONTRACT)
    if definition_sha256(protocol)!=protocol['definition_sha256']:raise ValueError('case36 protocol definition hash mismatch')
    source=ROOT/protocol['source_brep'];original=sha(source)
    if original!=protocol['source_sha256']:raise ValueError('case36 source identity mismatch')
    if sha(ROOT/protocol['frozen_case_file'])!=protocol['frozen_case_sha256']:raise ValueError('Frozen case36 definition mismatch')
    if sha(ROOT/protocol['geometry_audit']['path'])!=protocol['geometry_audit']['sha256']:raise ValueError('Independent case36 audit identity mismatch')
    binding=version('cadquery-ocp')
    if binding!=PIN:raise ValueError('Use the pinned cadquery-ocp runtime')
    sys.path.insert(0,str(ROOT/'adapters/occt/original'))
    import geometry as g
    shape=g.read(source);measurements=measure(shape);expected=protocol['expected_input'];st=measurements['stats']
    gates={'source_bytes':original==protocol['source_sha256'],
           'brep_valid':st['valid'],'two_independent_faces':st['faces']==2 and st['shells']==0 and st['solids']==0,
           'source_topology':st['edges']==8 and st['vertices']==8,
           'source_area':abs(st['area_mm2']-730)<1e-8,
           'original_finite_gap':abs(measurements['finite_face_gap_mm']-expected['finite_face_gap_mm'])<1e-8,
           'no_shared_native_edge':len(measurements['shared_edges'])==0,
           'vertical_finite_domain':all(abs(a-b)<1e-8 for a,b in zip(measurements['faces'][0]['stats']['bbox_mm'],expected['vertical_bbox_mm'])),
           'horizontal_finite_domain':all(abs(a-b)<1e-8 for a,b in zip(measurements['faces'][1]['stats']['bbox_mm'],expected['horizontal_bbox_mm']))}
    if not all(gates.values()):raise ValueError('Exact-source admission measurements failed: '+str(gates))
    variants=[v for v in protocol['variants'] if not args.variant or v['id']==args.variant]
    if not variants:parser.error('Unknown registered variant ID')
    output.mkdir(parents=True,exist_ok=True);rows=[]
    for v in variants:
        run=output/v['id'];run.mkdir();before=run/'before.brep';shutil.copyfile(source,before)
        write(run/'before.mesh.json',g.mesh(g.read(before)))
        contacts=contact_classification(shape,float(v['radius_mm']))
        summary={'schema':'case36.exact-input-admission.v1','number':36,'variant_id':v['id'],'radius_mm':v['radius_mm'],
                 'engine':'OCCT','engine_version':'7.9.3','binding_version':binding,'runner_sha256':sha(__file__),
                 'source_brep':protocol['source_brep'],'source_sha256':original,'operation_input_sha256':sha(before),
                 'source_case_sha256':protocol['frozen_case_sha256'],
                 'input_protocol':{'path':CONTRACT,'definition_sha256':protocol['definition_sha256']},
                 'method':'input_admission_check','input_relation':'same_as_base','preprocessing_executed':False,
                 'native_call_executed':False,'api_success':None,'outcome':'blocked_no_shared_edge',
                 'reason':'Exact original faces are disjoint and have no common native edge. The ordinary shared-edge selector admits no edge, so no fillet API call was made.',
                 'source_feature_certified':False,'source_feature_passed':False,'human_appearance_acceptance':False,
                 'input_measurements':measurements,'input_checks':gates,
                 'selection':{'shared_edge_candidate_count':0,'selected_native_edges':[],
                              'theoretical_line_is_existing_edge':False,'theoretical_underlying_plane_intersection_mm':[[-7,0,0],[7,0,0]]},
                 'theoretical_circular_contacts':contacts,
                 'execution':{'native_call_started':False,'ordinary_edge_admitted':False,'native_face_face_call':False},
                 'validation_boundary':'No shared edge is an ordinary-runner applicability boundary; it is not an executed native API failure or a finding that the whole kernel cannot blend disjoint faces.',
                 'artifacts':{'before_brep':'before.brep','before_mesh':'before.mesh.json','actual_after_available':False},
                 'source_unchanged':sha(source)==original,'operation_equals_source_bytes':sha(before)==original}
        write(run/'summary.json',summary)
        rows.append({'number':36,'variant_id':v['id'],'id':v['id'],'radius_mm':v['radius_mm'],
                     'run_dir':relative(run),'summary':relative(run/'summary.json'),'summary_sha256':sha(run/'summary.json'),
                     'before_brep':relative(before),'before_mesh':relative(run/'before.mesh.json'),
                     'source_sha256':original,'operation_input_sha256':sha(before),
                     'outcome':summary['outcome'],'native_call_executed':False})
    index={'schema':'case36.exact-input-run-index.v1','case_number':36,'source_brep':protocol['source_brep'],'source_sha256':original,
           'input_protocol':{'path':CONTRACT,'definition_sha256':protocol['definition_sha256']},'rows':rows,
           'source_unchanged':sha(source)==original,'native_call_executed':False,
           'scope':'Exact-input eligibility measurements only; no edge or face-face fillet API call and no new blend result.'}
    write(output/'index.json',index)
    print(json.dumps({'output':relative(output),'variants':len(rows),'source_sha256':original,'outcome':'blocked_no_shared_edge','native_call_executed':False,'source_unchanged':index['source_unchanged']}))
    return 0

if __name__=='__main__':sys.exit(main())
