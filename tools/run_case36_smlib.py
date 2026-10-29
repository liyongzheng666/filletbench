#!/usr/bin/env python3
"""Entry point for four fresh original-finite-input SMLib face-face calls."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "adapters/smlib/case36-faceface/run.py"), run_name="__main__")
