"""The original reviewed inputs/targets must survive reconstruction and replay."""
import hashlib,json,pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
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
        self.assertNotEqual(v['base_mesh'],v['operation_mesh'])
        self.assertTrue(v.get('preparation_note'))
    def test_case22_keeps_the_original_radius_and_step_failure_record(self):
        d=json.loads((ROOT/'web/data/original-occ/cases/22.json').read_text())
        v=next(v for v in d['variants'] if v['id']=='part01-r6')
        self.assertEqual(v['radius_mm'],6)
        self.assertIsNotNone(v.get('historical_status'))
        self.assertTrue(v.get('operation_targets'))
if __name__=='__main__':unittest.main()
