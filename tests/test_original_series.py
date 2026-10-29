"""The original reviewed inputs/targets must survive reconstruction and replay."""
import copy,hashlib,importlib.util,json,pathlib,shutil,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('original_revision_audit',ROOT/'tools/audit_original_smlib_column.py')
REVISION_AUDIT=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(REVISION_AUDIT)

def read(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

class OriginalSeriesTests(unittest.TestCase):
    def test_original_collection_is_complete_and_is_not_the_ordinary_surrogate(self):
        p=ROOT/'web/data/original-occ/catalog.json'
        self.assertTrue(p.is_file(),'Original reviewed collection is absent from the viewer')
        c=json.loads(p.read_text());numbers=[x['number'] for x in c['cases']]
        self.assertEqual(numbers,list(range(1,29))+list(range(30,37)))
        self.assertEqual(c['model_groups'],34)
        self.assertEqual(c['explanation_only'],[32])
        self.assertEqual(c['source_review_state_sha256'],'c4e90452d792e28b1b5a0c5a5237ba7043a235c98abffde445b2dbe70c0f8fa5')
        for row in c['cases']:
            d=json.loads((ROOT/'web'/row['data']).read_text())
            if row['number']==32:
                self.assertFalse(d['has_model']);continue
            self.assertTrue(d['base_mesh'])
            if d.get('revision'):
                checks,_=REVISION_AUDIT.case11_revision_checks(d,ROOT)
                self.assertTrue(all(checks.values()),{name:ok for name,ok in checks.items() if not ok})
            else:
                self.assertEqual(d['source_sha256'],json.loads((ROOT/f'data/original-occ/cases/{row["number"]:02d}.json').read_text())['source_sha256'])
            self.assertTrue(d['variants'])
            self.assertIn(d['default_variant'],[v['id'] for v in d['variants']])
            for v in d['variants']:
                self.assertEqual(v['base_mesh'],d['base_mesh'])
                self.assertEqual(v['base_sha256'],d['source_sha256'])
                self.assertTrue(v.get('scope_note'))
                for stage in ['base_mesh','operation_mesh']:
                    if v.get(stage):self.assertTrue((ROOT/'web'/v[stage]).is_file())
                if v.get('occt',{}).get('mesh'):self.assertTrue((ROOT/'web'/v['occt']['mesh']).is_file())
                for file in v.get('occt',{}).get('files',[]):
                    source=ROOT/'web'/file['path'];self.assertTrue(source.is_file())
                    self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),file['sha256'])
                if v.get('occt',{}).get('evidence_kind')=='fresh_run':
                    self.assertIsNotNone(v['occt'].get('summary'))
                    self.assertFalse(v['occt'].get('source_feature_passed',False))
    def test_case36_keeps_the_original_two_disjoint_faces_before_preparation(self):
        d=json.loads((ROOT/'web/data/original-occ/cases/36.json').read_text())
        v=next(v for v in d['variants'] if v['id']==d['default_variant'])
        self.assertEqual(v['base_mesh'],v['operation_mesh'])
        self.assertEqual(v['input_relation'],'same_as_base')
        if d.get('faceface_protocol'):
            spec=importlib.util.spec_from_file_location('case36_faceface_verifier',ROOT/'tools/verify_case36_faceface.py')
            verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)
            checks,_=verifier.case36_faceface_checks(d,ROOT)
            self.assertTrue(all(checks.values()),[name for name,ok in checks.items() if not ok])
            self.assertEqual(v['occt']['method'],'explicit_occ_composition')
            self.assertFalse(v['occt']['native_call_executed'])
        else:
            self.assertFalse(v['occt']['native_call_executed'])
            self.assertEqual(v['occt']['status'],'blocked')
            self.assertIsNone(v['occt']['mesh'])
        self.assertEqual(v['occt']['source_sha256'],v['occt']['operation_input_sha256'])
        self.assertTrue(v.get('preparation_note'))
    def test_case22_keeps_the_original_radius_and_step_failure_record(self):
        d=json.loads((ROOT/'web/data/original-occ/cases/22.json').read_text())
        v=next(v for v in d['variants'] if v['id']=='part01-r6')
        self.assertEqual(v['radius_mm'],6)
        self.assertIsNotNone(v.get('historical_status'))
        self.assertTrue(v.get('operation_targets'))

    def test_case11_revision_does_not_rewrite_frozen_source_or_confirmation(self):
        path=ROOT/'data/original-occ/cases/11.json';frozen=read(path)
        self.assertEqual(sha(path),'dbef53dd0b50e1b6dbfa9bb1151566e63e6705418932a849b77af1628ce5b1cd')
        self.assertEqual(frozen['source_sha256'],'9959f6889063c0ee1107e6ac5185035cba9dd48ba5b843679888baa3258ec7a8')
        self.assertEqual(sha(ROOT/frozen['source_brep']),frozen['source_sha256'])
        public=read(ROOT/'web/data/original-occ/cases/11.json')
        if not public.get('revision'):
            self.assertEqual(public['source_sha256'],frozen['source_sha256']);return
        checks,contract=REVISION_AUDIT.case11_revision_checks(public,ROOT)
        self.assertTrue(all(checks.values()),checks)
        self.assertNotEqual(public['source_sha256'],frozen['source_sha256'])
        self.assertEqual(contract['previous_human_confirmation_scope'],'local_strip_only')
        self.assertEqual(public['human_status'],'pending')

    def revision_fixture(self,root):
        contract_path=ROOT/REVISION_AUDIT.CASE11_CONTRACT
        if not contract_path.is_file():self.skipTest('No registered case11 revision yet')
        contract=read(contract_path);frozen=read(ROOT/'data/original-occ/cases/11.json')
        for value in [REVISION_AUDIT.CASE11_CONTRACT,'data/original-occ/cases/11.json',
                      frozen['source_brep'],contract['source_brep'],contract['geometry_audit']['path']]:
            dest=root/value;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/value,dest)
        public={'number':11,'human_status':'pending','source_sha256':contract['source_sha256'],
                'source_case_sha256':sha(root/REVISION_AUDIT.CASE11_CONTRACT),'target_world':contract['target_world'],
                'revision':dict(contract,contract=REVISION_AUDIT.CASE11_CONTRACT,
                                contract_sha256=sha(root/REVISION_AUDIT.CASE11_CONTRACT))}
        return public,contract

    def test_revision_exception_cannot_be_reused_for_another_case_or_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);public,_=self.revision_fixture(root)
            self.assertTrue(all(REVISION_AUDIT.case11_revision_checks(public,root)[0].values()))
            another=copy.deepcopy(public);another['number']=12
            self.assertFalse(REVISION_AUDIT.case11_revision_checks(another,root)[0]['registered_case11_revision'])
            replaced=copy.deepcopy(public);replaced['source_sha256']='0'*64
            self.assertFalse(REVISION_AUDIT.case11_revision_checks(replaced,root)[0]['revision_source_bytes'])

    def test_aggregate_audit_pass_cannot_hide_a_failed_material_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);public,contract=self.revision_fixture(root)
            audit_path=root/contract['geometry_audit']['path'];audit=read(audit_path)
            audit['gates']['visible_band_convex_curvature_and_material_side']=False
            audit_path.write_text(json.dumps(audit))
            contract['geometry_audit']['sha256']=sha(audit_path)
            contract_path=root/REVISION_AUDIT.CASE11_CONTRACT;contract_path.write_text(json.dumps(contract))
            public['source_case_sha256']=sha(contract_path)
            public['revision']=dict(contract,contract=REVISION_AUDIT.CASE11_CONTRACT,contract_sha256=sha(contract_path))
            checks,_=REVISION_AUDIT.case11_revision_checks(public,root)
            self.assertTrue(checks['revision_geometry_audit_hash'])
            self.assertFalse(checks['revision_geometry_gates'])

    def test_case11_smlib_revision_is_not_a_radius_only_template(self):
        public=read(ROOT/'web/data/original-occ/cases/11.json')
        if not public.get('revision'):self.skipTest('No published case11 revision yet')
        matched=[v for v in public['variants'] if v.get('smlib',{}).get('pairing_status','').startswith('matched_')]
        if not matched:self.skipTest('No actual matched SMLib revision attempt yet')
        for variant in matched:
            record=variant['smlib'];request=ROOT/record['request_file'];job=read(request)
            summary=read(ROOT/'web'/record['summary'])
            checks=REVISION_AUDIT.revised_smlib_checks(public,variant,record,job,request,summary,ROOT)
            self.assertTrue(all(checks.values()),{name:ok for name,ok in checks.items() if not ok})
            self.assertNotIn('source_template_job_id',job)
            legacy=copy.deepcopy(job);legacy['source_template_job_id']='11.part01.ordinary_control.r1'
            self.assertFalse(REVISION_AUDIT.revised_smlib_checks(public,variant,record,legacy,request,summary,ROOT)['revision_not_radius_template'])
if __name__=='__main__':unittest.main()
