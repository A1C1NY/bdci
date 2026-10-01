"""Use the real local JiuwenSwarm artifact module without loading model services."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "vendor" / "jiuwenswarm"
FRAMEWORK_SOURCE = VENDOR / "jiuwenswarm" / "common" / "team_artifacts.py"
if not FRAMEWORK_SOURCE.is_file():
    raise RuntimeError("Missing JiuwenSwarm source checkout; run python scripts/bootstrap.py")
sys.path.insert(0, str(VENDOR))

from jiuwenswarm.common.team_artifacts import (  # noqa: E402
    build_artifact_manifest,
    verify_artifact_manifest,
)
from jiuwenswarm.common.research_budget import BudgetExceeded, reserve_research_attempt  # noqa: E402

BUDGET_SOURCE = VENDOR / "jiuwenswarm" / "common" / "research_budget.py"
