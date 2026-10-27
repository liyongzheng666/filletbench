"""Adversarial checks of geometry selection and bounded execution.

Run with the pinned OCP Python: python adapters/occt/test_runner.py
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "adapters/occt/run.py"


class RunnerSafetyTests(unittest.TestCase):
    def execute(self, job_id, mutate=None, timeout=120):
        job = json.loads((ROOT / f"data/jobs/{job_id}.json").read_text())
        if mutate:
            mutate(job)
        with tempfile.TemporaryDirectory(prefix="test-", dir=ADAPTER.parent) as temporary:
            directory = Path(temporary)
            source = directory / "job.json"
            source.write_text(json.dumps(job))
            subprocess.run([sys.executable, str(ADAPTER), str(source),
                "--output", str(directory / "run"), "--timeout", str(timeout)],
                cwd=ROOT, capture_output=True, text=True, check=True)
            return json.loads((directory / "run/summary.json").read_text())

    def test_interior_world_sample_cannot_be_ignored(self):
        def perturb(job):
            job["targets"][0]["samples_mm"][16][2] += 0.1
        result = self.execute("01.part01.ordinary_control.r8", perturb)
        self.assertEqual(result["outcome"], "selection_rejected")
        self.assertFalse(result["native_call_executed"])

    def test_wrong_source_part_is_rejected(self):
        def wrong_part(job):
            job["source_part_indices"] = [0]
        result = self.execute("09.part02.ordinary_control.r3", wrong_part)
        self.assertEqual(result["outcome"], "selection_rejected")
        self.assertFalse(result["native_call_executed"])

    def test_source_hash_is_checked(self):
        def wrong_hash(job):
            job["source_sha256"] = "0"*64
        result = self.execute("01.part01.ordinary_control.r8", wrong_hash)
        self.assertIn("SHA-256 mismatch", result["reason"])
        self.assertFalse(result["native_call_executed"])

    def test_timeout_is_explicit(self):
        result = self.execute("01.part01.ordinary_control.r8", timeout=0.001)
        self.assertEqual(result["outcome"], "timeout")
        self.assertTrue(result["process"]["timed_out"])
        self.assertIsNotNone(result["process"]["returncode"])

    def test_nurbs_line_and_circle_select_without_reconstruction(self):
        result = self.execute("12.part02.ordinary_control.r2")
        self.assertTrue(result["native_call_executed"])
        self.assertEqual(len(result["selection"]), 8)
        self.assertTrue(all(t["candidate_count"] == 1 for t in result["selection"]))
        self.assertTrue(any(t["candidates"][0]["curve_type"] == "GeomAbs_BSplineCurve"
                            for t in result["selection"]))

    def test_partial_variable_request_is_not_silently_constant(self):
        def incomplete(job):
            del job["variable_physical_end"]
        result=self.execute("33.part01.ordinary_challenge.r2p43305-variable-control",incomplete)
        self.assertEqual(result["outcome"],"unsupported_parameters")
        self.assertFalse(result["native_call_executed"])

    def test_unhandled_variable_law_is_rejected(self):
        def unsupported(job):
            job["variable_custom_law"]="unhandled"
        result=self.execute("33.part01.ordinary_challenge.r2p43305-variable-control",unsupported)
        self.assertEqual(result["outcome"],"unsupported_parameters")
        self.assertFalse(result["native_call_executed"])

    def test_unmatched_physical_endpoint_is_rejected(self):
        def unmatched(job):
            job["variable_physical_end"][0]+=1
        result=self.execute("33.part01.ordinary_challenge.r2p43305-variable-control",unmatched)
        self.assertEqual(result["outcome"],"unsupported_parameters")
        self.assertFalse(result["native_call_executed"])

    def test_forward_variable_binding_measures_nonconstant_contact(self):
        result=self.execute("33.part01.ordinary_challenge.r2p43305-variable-control")
        self.assertEqual(result["outcome"],"ok")
        self.assertFalse(result["variable_radius_binding"]["reversed_from_physical_endpoints"])
        self.assertTrue(result["variable_radius_validation"]["endpoint_radii_verified"])
        self.assertTrue(result["variable_radius_validation"]["nonconstant_radius_observed"])
        self.assertFalse(result["variable_radius_validation"]["full_linear_contact_law_passed"])

    def test_reversed_variable_binding_uses_opposite_native_radius_order(self):
        result=self.execute("34.part01.ordinary_challenge.r16p8574-variable-control")
        self.assertEqual(result["outcome"],"ok")
        binding=result["variable_radius_binding"]
        self.assertTrue(binding["reversed_from_physical_endpoints"])
        self.assertEqual(binding["native_first_point_mm"],[0.,0.,24.])
        self.assertLess(binding["native_start_radius_mm"],binding["native_end_radius_mm"])
        self.assertTrue(result["variable_radius_validation"]["passed"])
        self.assertFalse(result["full_variable_law_equivalence_verified"])


if __name__ == "__main__":
    unittest.main()
