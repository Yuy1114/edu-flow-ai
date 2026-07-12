"""V3.5 pipeline constants.

This module defines shared path constants used by V3.5 scripts.
The old two-stage placement model (V35PlacementModel) has been removed.
Only V35SinglePlacementModel in placement_single_model.py is active.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_PATH = REPO_ROOT / "backend" / "data" / "training" / "v3_training_samples.csv"
OUTPUT_DIR = REPO_ROOT / "backend" / "data" / "pipeline" / "v3.5"
MODELS_DIR = REPO_ROOT / "backend" / "models" / "v3.5" / "placement"
