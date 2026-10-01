"""SwarmFlow entry point for a HUMAN-AUTHORED, trusted local experiment plan.

Uses the published META / async run(args) contract. Full SwarmFlow runtime
validation is deferred until model/service setup. No model calls are made here.
"""

import asyncio
from pathlib import Path
import sys

META = {
    "name": "research-lab-phase1",
    "description": "Execute a fixed research plan and publish verified evidence",
    "phases": ["experiments", "verification"],
}


async def run(args):
    from swarmflow import phase, log

    project = Path(args["project_root"]).resolve(strict=True)
    plan = (project / args.get("plan", "experiments/memory_demo/plan.json")).resolve()
    output = (project / args.get("output", "outputs/swarmflow-local")).resolve()
    plan.relative_to(project)
    output.relative_to(project)
    sys.path.insert(0, str(project / "src"))
    from research_lab.pipeline import run as run_local, verify_run

    phase("experiments")
    log("Executing the fixed local plan; no model-generated code or LLM calls")
    state = await asyncio.to_thread(run_local, plan, output, resume=bool(args.get("resume", False)))
    phase("verification")
    errors = verify_run(output)
    if errors:
        raise RuntimeError("Artifact verification failed: " + "; ".join(errors))
    log("Verified experiment grid and deterministic draft completed")
    return {"status": state["status"], "output": str(output),
            "paper_draft": str(output / "paper_draft.md"), "llm_calls": 0}
