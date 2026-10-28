"""Reject false success and display changes that conceal the convex revision."""
import json, pathlib, shutil, subprocess, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
def read(path):return json.loads((ROOT/path).read_text())

class Case11RevisionTests(unittest.TestCase):
    def test_real_failures_and_pending_appearance_are_preserved(self):
        c=read('web/data/original-occ/cases/11.json')
        contract=read('data/case11-convexity/revision.json')
        self.assertFalse(c['shape_acceptance']);self.assertEqual(c['human_status'],'pending')
        self.assertEqual(c['human_note'],'')
        for v in c['variants']:
            self.assertEqual(v['base_sha256'],contract['source_sha256'])
            for engine in ['occt','smlib']:
                result=v[engine];self.assertEqual(result['source_sha256'],contract['source_sha256'])
                self.assertFalse(result['source_feature_passed']);self.assertTrue(result['mesh'])
            self.assertEqual(v['smlib']['status'],'api_failed')
            self.assertTrue(v['smlib']['unchanged_input'])
            self.assertEqual(v['smlib']['raw_status'],1001)
            if v['radius_mm']>1:
                self.assertEqual(v['occt']['status'],'geometry_failed')
                self.assertFalse(v['occt']['metrics']['brep_bop_passed'])
            else:self.assertTrue(v['occt']['metrics']['step_readback_passed'])

    def test_projection_is_an_orthonormal_camera_not_a_geometry_transform(self):
        camera=read('data/case11-convexity/revision.json')['camera']
        self.assertFalse(camera['model_transformed'])
        vectors=[camera[k] for k in ['screen_right','screen_up','toward_viewer']]
        for i,a in enumerate(vectors):
            self.assertAlmostEqual(sum(x*x for x in a),1,places=10)
            for b in vectors[i+1:]:self.assertAlmostEqual(sum(x*y for x,y in zip(a,b)),0,places=10)
        r,u,d=vectors;cross=[r[1]*u[2]-r[2]*u[1],r[2]*u[0]-r[0]*u[2],r[0]*u[1]-r[1]*u[0]]
        for a,b in zip(cross,d):self.assertAlmostEqual(a,b,places=10)

    @unittest.skipUnless(shutil.which('node'),'Node required for viewer geometry regression')
    def test_sdk_shading_keeps_planar_faces_and_smooths_only_within_a_face(self):
        module=(ROOT/'web/mesh.js').read_text()
        code='import assert from "node:assert/strict";\n'+module+'''
const m={vertices:[[0,0,0],[1,0,0],[0,1,0],[0,0,1]],triangles:[[0,1,2],[0,3,1],[0,2,3]],face_ids:[0,1,0]};
const split=faceLocalMesh(m);
assert.notEqual(split.triangles[0][0],split.triangles[1][0]);
assert.equal(split.triangles[0][0],split.triangles[2][0]);
assert.deepEqual(split.triangles.map(t=>t.map(i=>split.vertices[i])),m.triangles.map(t=>t.map(i=>m.vertices[i])));
const unknown={vertices:m.vertices,triangles:m.triangles};assert.strictEqual(faceLocalMesh(unknown),unknown);
'''
        subprocess.run(['node','--input-type=module','-e',code],check=True,capture_output=True,text=True)

if __name__=='__main__':unittest.main()
