"""Release tests protect identity/comparability and evidence presentation."""
import hashlib,json,math,pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class CorpusTests(unittest.TestCase):
    def test_frozen_identity_and_publication_boundaries(self):
        import sys
        sys.path.insert(0,str(ROOT/'tools'))
        import verify
        self.assertEqual(verify.main(),0)
    def test_meshes_are_real_and_indexed(self):
        files=list((ROOT/'web/data/meshes').glob('*.json'))+list((ROOT/'web/data/supplemental').rglob('*.mesh.json'))
        self.assertTrue(files)
        for p in files:
            d=json.loads(p.read_text());v=d['vertices'];t=d['triangles']
            self.assertTrue(v,p.name);self.assertTrue(t,p.name)
            self.assertTrue(all(len(x)==3 and all(math.isfinite(y) for y in x) for x in v),p.name)
            self.assertTrue(all(len(x)==3 and all(isinstance(y,int) and 0<=y<len(v) for y in x) for x in t),p.name)
            if d.get('face_ids'):self.assertEqual(len(t),len(d['face_ids']),p.name)
    def test_paired_ordinary_runs_have_matching_source_and_parameters(self):
        for p in (ROOT/'web/data/cases').glob('*.json'):
            c=json.loads(p.read_text())
            for v in c['variants']:
                if v.get('pairing')!='same_source_geometry_and_request_different_representations':continue
                job=json.loads((ROOT/f'data/jobs/{v["id"]}.json').read_text())
                for e in ['occt','smlib']:
                    a=v[e]
                    if a.get('status')=='not_run':continue
                    s=json.loads((ROOT/'web'/a['summary']).read_text())
                    self.assertEqual(s['radius_mm'],job['radius_mm'])
                    self.assertEqual(s['source_sha256'],job['source_sha256'])
                    self.assertFalse(a.get('special_feature_passed'))
    def test_repository_keeps_failure_candidates(self):
        c=json.loads((ROOT/'web/data/cases/23.json').read_text())
        v=next(v for v in c['variants'] if v['id']=='23.part01.ordinary_challenge.r2p5')
        self.assertEqual(v['smlib']['status'],'geometry_failed')
        self.assertIsNotNone(v['smlib']['mesh'])
        self.assertFalse(v['smlib']['special_feature_passed'])
if __name__=='__main__':unittest.main()
