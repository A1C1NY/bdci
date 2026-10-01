"""Run from any working directory without installing project dependencies."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from research_lab.cli import main

raise SystemExit(main())
