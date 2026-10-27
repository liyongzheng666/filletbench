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


if __name__ == "__main__":
    unittest.main()
