"""Generic data-driven tasks executed by the native upstream SwarmFlow engine."""
from swarmflow import agent, phase, map_parallel

META = {"name": "supervised-research-v4", "description": "Typed evidence-driven bounded research",
        "workflow_token_limit": 2000000, "phases": ["Research tasks"]}


async def run(args):
    if args.get("parallel", False):
        phase("Bounded parallel tasks")
        async def execute(task):
            try:
                return await agent(task["prompt"], label=task["id"], schema=task["schema"],
                                   options={"model":task["model"]})
            except Exception as exc:
                if not args.get("continue_on_error", False):
                    raise
                return {"_error": type(exc).__name__}
        values = await map_parallel(args["tasks"], execute)
        return dict(zip([task["id"] for task in args["tasks"]], values))
    results = {}
    for task in args["tasks"]:
        phase(task["phase"])
        results[task["id"]] = await agent(task["prompt"], label=task["id"],
            schema=task["schema"], options={"model":task["model"]})
    return results
