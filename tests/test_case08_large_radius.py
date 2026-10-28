import json,pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class Case08LargeRadiusTests(unittest.TestCase):
    def test_large_radius_and_boundary_controls_are_visible(self):
        c=json.loads((ROOT/'web/data/original-occ/cases/08.json').read_text())
        self.assertEqual(c['source_sha256'],'57ea045f7da3735141b7f21f2fbc3e3a51c39933d08a5d7c6e3374e01ab064f9')
        self.assertEqual(c['default_variant'],'r15-crossing')
        self.assertEqual([v['radius_mm'] for v in c['variants']],[12,13,14,15,18])
    def test_r15_records_actual_geometry_and_the_occ_failure(self):
        c=json.loads((ROOT/'web/data/original-occ/cases/08.json').read_text());v=next(v for v in c['variants'] if v['id']=='r15-crossing')
        self.assertEqual(v['occt']['outcome'],'native_rejected');self.assertIsNone(v['occt']['mesh'])
        self.assertTrue(v['smlib']['mesh']);self.assertTrue(v['smlib']['metrics']['valid'])
        proof=v['radius_validation'];self.assertFalse(proof['preserve_notch_option_supplied'])
        self.assertIsNone(proof['occt_actual_radius_mm'])
        self.assertAlmostEqual(proof['smlib_measured_radius_mm'],15,places=6)
        self.assertAlmostEqual(proof['smlib_actual_notch_z_mm'],25,places=8)
        self.assertAlmostEqual(proof['smlib_observed_crossing_mm'],2,places=8)
        self.assertFalse(proof['source_special_modes_certified'])
        self.assertEqual(v['processing_steps'][0]['parameters']['radius_mm'],15)
        self.assertFalse(v['processing_steps'][0]['api_success'])
        self.assertEqual(v['historical_status'],'new_requested_radius_validation')
if __name__=='__main__':unittest.main()
