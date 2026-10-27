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
    def test_reference_coordinates_use_the_pdf_cropbox(self):
        for p in (ROOT/'data/cases').glob('*.json'):
            ref=json.loads(p.read_text())['reference']
            self.assertEqual(ref['crop_coordinate_system'],'pdfjs_cropbox_normalized_top_left')
            m,c=ref['source_media_box'],ref['pdf_crop_box']
            x0,y0,x1,y1=ref['source_media_box_crop']
            expected=[(m[0]+x0*(m[2]-m[0])-c[0])/(c[2]-c[0]),
                      (y0*(m[3]-m[1])-(m[3]-c[3]))/(c[3]-c[1]),
                      (m[0]+x1*(m[2]-m[0])-c[0])/(c[2]-c[0]),
                      (y1*(m[3]-m[1])-(m[3]-c[3]))/(c[3]-c[1])]
            for actual,want in zip(ref['suggested_crop'],expected):
                self.assertAlmostEqual(actual,min(1,max(0,want)),places=12)
        # The actual source-page title at y=300/1287 must be inside case12,
        # rather than cropped by applying MediaBox coordinates to CropBox.
        ref=json.loads((ROOT/'data/cases/12.json').read_text())['reference']
        title_y=((300/1287)*842-97)/648
        self.assertLess(ref['suggested_crop'][1],title_y)
        self.assertGreater(ref['suggested_crop'][3],title_y)
    def test_repository_keeps_failure_candidates(self):
        c=json.loads((ROOT/'web/data/cases/23.json').read_text())
        v=next(v for v in c['variants'] if v['id']=='23.part01.ordinary_challenge.r2p5')
        self.assertEqual(v['smlib']['status'],'geometry_failed')
        self.assertIsNotNone(v['smlib']['mesh'])
        self.assertFalse(v['smlib']['special_feature_passed'])
if __name__=='__main__':unittest.main()
