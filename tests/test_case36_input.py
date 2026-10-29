"""The actual case36 input must not shrink or extend the original finite faces."""
import copy,json,pathlib,sys,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from audit_case36_input import case36_input_checks

class Case36InputTests(unittest.TestCase):
    def setUp(self):
        # The small-radius admission baseline remains reproducible after the
        # current viewer moves on to actual R8 face-face experiments.
        self.case=json.loads((ROOT/'web/data/case36-input/published-case.json').read_text())['case']
    def test_exact_original_input_and_admission_only_evidence(self):
        checks,_=case36_input_checks(self.case,ROOT)
        self.assertTrue(all(checks.values()),[key for key,ok in checks.items() if not ok])
    def test_old_derived_input_cannot_be_reintroduced(self):
        c=copy.deepcopy(self.case);v=c['variants'][0]
        v['occt']['operation_input_sha256']='46e1'+'0'*60
        checks,_=case36_input_checks(c,ROOT)
        self.assertFalse(checks[v['id']+':source_operation_identity'])
        v['operation_mesh']='data/meshes/e7f852f358ed27ddec76423c.json'
        checks,_=case36_input_checks(c,ROOT)
        self.assertFalse(checks[v['id']+':same_input_display'])
    def test_preflight_cannot_be_promoted_to_a_successful_fillet(self):
        c=copy.deepcopy(self.case);v=c['variants'][0]
        v['occt'].update(status='candidate_unverified',mesh=v['base_mesh'],native_call_executed=True)
        checks,_=case36_input_checks(c,ROOT)
        self.assertFalse(checks[v['id']+':no_false_native_output'])

if __name__=='__main__':unittest.main()
