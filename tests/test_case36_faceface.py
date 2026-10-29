"""Protect actual input/call/mode identity when case36 leaves preflight."""
import copy,json,pathlib,sys,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from verify_case36_faceface import case36_faceface_checks,original_display_domain,index_binding_checks,sha,SOURCE_SHA

class Case36PartialIndexTests(unittest.TestCase):
    def fixture(self,root):
        path='runs/fresh-short/index.json';summary='runs/fresh-short/short/summary.json'
        index={'source_sha256':SOURCE_SHA,'radius_mm':8,'rows':[{'mode':'short','radius_mm':8,'source_sha256':SOURCE_SHA,'summary':summary,'summary_sha256':'a'*64}]}
        p=root/path;p.parent.mkdir(parents=True);p.write_text(json.dumps(index))
        binding={'engine':'occt_composite','mode':'short','variant_id':'trim-short-r8','index':path,'index_sha256':sha(p),'summary':summary,'summary_sha256':'a'*64}
        protocol={'run_indexes':{'occt_composite':'runs/canonical/index.json'},'additional_run_indexes':{'occt_composite':[{'path':path,'sha256':sha(p)}]}}
        return binding,protocol,index
    def test_an_explicitly_registered_partial_index_can_bind_its_actual_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);binding,protocol,_=self.fixture(root)
            self.assertTrue(all(index_binding_checks(binding,protocol,'occt_composite',root).values()))
    def test_cached_long_result_cannot_be_relabelled_as_part_of_a_short_only_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);binding,protocol,_=self.fixture(root)
            binding.update(mode='long',variant_id='trim-long-r8',summary='runs/old-long/long/summary.json',summary_sha256='b'*64)
            checks=index_binding_checks(binding,protocol,'occt_composite',root)
            self.assertTrue(checks['index_registered'])
            self.assertTrue(checks['raw_index_current'])
            self.assertFalse(checks['index_contains_actual_mode_summary'])
    def test_an_unregistered_index_cannot_be_used_even_if_its_row_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);binding,protocol,_=self.fixture(root)
            protocol.pop('additional_run_indexes')
            self.assertFalse(index_binding_checks(binding,protocol,'occt_composite',root)['index_registered'])
    def test_native_baseline_must_be_the_index_selected_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);binding,protocol,index=self.fixture(root)
            path=binding['index'];row=index['rows'][0];row['id']='native-r8';index['selected_candidate']=dict(row,summary='runs/another-branch/summary.json')
            (root/path).write_text(json.dumps(index));digest=sha(root/path)
            binding.update(engine='occt_native',mode='native-baseline',variant_id='native-faceface-r8',index_sha256=digest)
            protocol={'run_indexes':{'occt_native':path}}
            checks=index_binding_checks(binding,protocol,'occt_native',root)
            self.assertTrue(checks['index_registered']);self.assertFalse(checks['native_selected_summary'])

class Case36FacefaceTests(unittest.TestCase):
    def setUp(self):
        self.case=json.loads((ROOT/'web/data/original-occ/cases/36.json').read_text())
        if not self.case.get('faceface_protocol'):self.skipTest('Actual R8 face-face snapshot is not published yet')
    def test_exact_input_actual_calls_and_measured_modes_are_registered(self):
        checks,_=case36_faceface_checks(self.case,ROOT)
        self.assertTrue(all(checks.values()),[name for name,ok in checks.items() if not ok])
    def test_protocol_cannot_be_borrowed_by_another_case(self):
        c=copy.deepcopy(self.case);c['number']=35
        self.assertFalse(case36_faceface_checks(c,ROOT)[0]['registered_case36_faceface'])
    def test_success_mesh_cannot_be_swapped_for_an_input_or_other_mode(self):
        c=copy.deepcopy(self.case);v=next(v for v in c['variants'] if v['id']=='trim-to_walls-r8')
        v['occt']['mesh']=v['base_mesh']
        checks,_=case36_faceface_checks(c,ROOT)
        self.assertFalse(checks[v['id']+':occt:published_mesh_binding'])
    def test_explicit_construction_cannot_be_promoted_to_native(self):
        c=copy.deepcopy(self.case);v=next(v for v in c['variants'] if v['id']=='trim-short-r8')
        v['occt'].update(method='native_surface_surface_fillet',native_call_executed=True)
        self.assertFalse(case36_faceface_checks(c,ROOT)[0][v['id']+':occt:explicit_not_native'])
    def test_radius_mismatch_cannot_use_an_R8_execution(self):
        c=copy.deepcopy(self.case);c['variants'][0]['radius_mm']=4
        self.assertFalse(case36_faceface_checks(c,ROOT)[0]['view_ids_and_radius'])
    def test_old_common_width_mesh_is_not_an_original_input(self):
        p=ROOT/'web/data/meshes/e7f852f358ed27ddec76423c.json'
        self.assertFalse(original_display_domain(json.loads(p.read_text())))
    def test_matching_endpoints_do_not_hide_the_actual_end_curve_difference(self):
        p=ROOT/'docs/case36-faceface-differences.json';d=json.loads(p.read_text())
        row=next(r for r in d['rows'] if r['mode']=='to_walls')
        self.assertTrue(d['same_endpoints_do_not_prove_whole_curve_identity'])
        self.assertGreater(row['maximum_observed_boundary_dx_mm'],0.01)
        for side in row['sides'].values():
            self.assertEqual(side['sample_count'],8193)
            self.assertTrue(side['plot_samples'])
        no=next(r for r in d['rows'] if r['mode']=='no')
        self.assertFalse(no['same_finite_working_extent'])
        self.assertFalse(d['fresh_fillet_call_executed'])

if __name__=='__main__':unittest.main()
