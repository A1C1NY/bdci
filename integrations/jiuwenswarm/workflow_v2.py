"""V2 SwarmFlow bridge. Full service execution requires separate integration validation."""

import asyncio
from pathlib import Path
import sys

META = {"name": "research-lab-v2", "description": "Bounded offline research search with frozen holdout",
        "phases": ["research_campaign", "evidence_audit"]}


async def run(args):
    from swarmflow import phase, log

    project = Path(args["project_root"]).resolve(strict=True)
    config = (project / args.get("config", "experiments/memory_search/campaign.json")).resolve()
    output = (project / args.get("output", "outputs/swarmflow-v2")).resolve()
    config.relative_to(project)
    output.relative_to(project)
    sys.path.insert(0, str(project / "src"))
    from research_lab.campaign import run_campaign, verify_campaign

    phase("research_campaign")
    log("Local rule-driven search; trusted scripts; no LLM calls")
    state = await asyncio.to_thread(run_campaign, config, output, resume=bool(args.get("resume", False)))
    phase("evidence_audit")
    errors = verify_campaign(output)
    if errors:
        raise RuntimeError(str(errors))
    return {"status": state["status"], "selected": state["incumbent"], "output": str(output), "llm_calls": 0}
