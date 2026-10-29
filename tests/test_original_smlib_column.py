"""The fourth panel may only show SMLib evidence bound to this original request."""
import json,pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class OriginalSmlibColumnTests(unittest.TestCase):
    def test_every_original_view_has_an_explicit_smlib_state(self):
        for p in (ROOT/'web/data/original-occ/cases').glob('*.json'):
            c=json.loads(p.read_text())
            for v in c['variants']:
                self.assertTrue('smlib' in v,f'{c["number"]}/{v["id"]}: fourth column has no state')
                sm=v['smlib'];self.assertTrue(sm.get('pairing_status'))
                if sm.get('mesh'):
                    self.assertEqual(sm['source_sha256'],c['source_sha256'])
                    self.assertIn(sm['pairing_status'],['matched_constraints_different_representation','matched_exact_operation_input'])
                    self.assertTrue((ROOT/'web'/sm['mesh']).is_file())
                    self.assertTrue((ROOT/'web'/sm['summary']).is_file())
                    self.assertFalse(sm.get('source_feature_passed',False))
    def test_case22_radius6_has_the_real_corresponding_smlib_run(self):
        c=json.loads((ROOT/'web/data/original-occ/cases/22.json').read_text())
        v=next(v for v in c['variants'] if v['id']=='part01-r6')
        sm=v['smlib'];self.assertEqual(sm['radius_mm'],6)
        self.assertEqual(sm['source_job_id'],'22.part01.ordinary_challenge.r6')
        self.assertTrue(sm['mesh'])
    def test_different_special_protocols_are_not_paired(self):
        for case,variant in [(35,'proxy-s1p0'),(36,'part01-r1p0')]:
            c=json.loads((ROOT/f'web/data/original-occ/cases/{case:02d}.json').read_text())
            if case==36 and c.get('faceface_protocol'):
                c=json.loads((ROOT/'web/data/case36-input/published-case.json').read_text())['case']
            sm=next(v for v in c['variants'] if v['id']==variant)['smlib']
            self.assertIsNone(sm.get('mesh'))
            self.assertIn(sm['pairing_status'],['protocol_not_encoded','no_comparable_run'])
if __name__=='__main__':unittest.main()
