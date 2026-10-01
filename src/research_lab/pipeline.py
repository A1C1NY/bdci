"""Bounded, resumable local experiment grid with verified evidence."""

import hashlib
import json
from pathlib import Path
import platform
import shutil
import sys

from .executor import execute, validate_result
from .framework import FRAMEWORK_SOURCE, build_artifact_manifest, verify_artifact_manifest
from .plan import fingerprint, load_plan
from .report import generate_reports
from .storage import digest, event, read_json, run_lock, utc_now, write_json


def verify_run(root):
    root = Path(root).resolve()
    state = read_json(root / "state.json")
    if state.get("status") != "completed":
        return [f"Run is {state.get('status')}, not completed"]
    errors = verify_artifact_manifest(root, read_json(root / "artifact_manifest.json"))
    expected = read_json(root / "inputs" / "plan.json")
    if len(state["jobs"]) != len(expected["methods"]) * len(expected["seeds"]):
        errors.append("Experiment grid size mismatch")
    for job in state["jobs"].values():
        if job.get("status") != "completed":
            errors.append("Job not completed")
        else:
            errors.extend(verify_artifact_manifest(root, job["manifest"]))
    return errors


def run(plan_path, output, *, resume=False, max_jobs=None, before_attempt=None):
    plan, source_script = load_plan(plan_path)
    if max_jobs is not None and max_jobs < 1:
        raise ValueError("max_jobs must be positive")
    base_key, source_info = fingerprint(plan, source_script)
    source_info["framework_sha256"] = digest(FRAMEWORK_SOURCE)
    key = hashlib.sha256((base_key + source_info["framework_sha256"]).encode()).hexdigest()
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with run_lock(root):
        state_path = root / "state.json"
        events = root / "events.jsonl"
        if state_path.exists():
            if not resume:
                raise ValueError("Run exists; use --resume or choose a new output directory")
            state = read_json(state_path)
            if state.get("fingerprint") != key:
                raise ValueError("Plan, experiment, engine or framework changed; use a new run directory")
            input_errors = verify_artifact_manifest(root, state["inputs_manifest"])
            if input_errors:
                raise ValueError(f"Archived inputs changed: {input_errors}")
        else:
            if resume:
                raise ValueError("Cannot resume: state.json is missing")
            unrelated = [p for p in root.iterdir() if p.name != ".run.lock"]
            if unrelated:
                raise ValueError("New run output directory must be empty")
            inputs = root / "inputs"
            inputs.mkdir()
            write_json(inputs / "plan.json", plan)
            shutil.copyfile(source_script, inputs / "experiment.py")
            write_json(inputs / "source_fingerprint.json", source_info)
            write_json(inputs / "environment.json", {"python": sys.version, "platform": platform.platform(),
                                                     "executable": sys.executable})
            state = {"schema_version": 1, "status": "initialized", "created_at": utc_now(),
                     "fingerprint": key, "jobs": {},
                     "inputs_manifest": build_artifact_manifest(root, list(inputs.iterdir()))}
            write_json(state_path, state)
            event(events, "run_initialized", fingerprint=key, mode="offline-local")
        state["status"] = "running"
        write_json(state_path, state)
        executed = 0
        rows = []
        try:
            for method in plan["methods"]:
                for seed in plan["seeds"]:
                    job_id = f"{method}__{seed}"
                    job = state["jobs"].setdefault(job_id, {"status": "pending", "attempts": []})
                    cached = False
                    if job["status"] == "completed":
                        errors = verify_artifact_manifest(root, job["manifest"])
                        if not errors:
                            cached = True
                            event(events, "job_reused", job=job_id)
                        else:
                            job["status"] = "invalidated"
                            event(events, "job_invalidated", job=job_id, errors=errors)
                    if not cached:
                        if max_jobs is not None and executed >= max_jobs:
                            state["status"] = "paused"
                            write_json(state_path, state)
                            event(events, "run_paused", completed_this_call=executed)
                            return state
                        while len(job["attempts"]) < plan["max_attempts"]:
                            attempt_number = len(job["attempts"]) + 1
                            if before_attempt is not None:
                                before_attempt(job_id, attempt_number, plan["timeout_seconds"])
                            relative = Path("jobs") / job_id / f"attempt_{attempt_number}"
                            # Preserve an interrupted attempt directory; never overwrite it.
                            job["attempts"].append(relative.as_posix())
                            job["status"] = "running"
                            write_json(state_path, state)
                            event(events, "job_started", job=job_id, attempt=attempt_number)
                            record = execute(root / "inputs" / "experiment.py", method, seed,
                                             root / relative, plan["timeout_seconds"], plan["primary_metric"])
                            job["status"] = record["status"]
                            event(events, "job_finished", job=job_id, attempt=attempt_number, status=record["status"])
                            if record["status"] == "completed":
                                job["result_path"] = (relative / "result.json").as_posix()
                                job["manifest"] = build_artifact_manifest(root, list((root / relative).iterdir()))
                                write_json(state_path, state)
                                break
                            write_json(state_path, state)
                        if job["status"] != "completed":
                            raise RuntimeError(f"{job_id}: attempts exhausted; inspect execution.json and start a new run after fixing inputs")
                        executed += 1
                    path = root / job["result_path"]
                    result = validate_result(path, method, seed, plan["primary_metric"])
                    rows.append({"method": method, "seed": seed, "result": result,
                                 "result_path": job["result_path"], "sha256": digest(path)})
            generate_reports(root, plan, rows, state)
            # All attempts and inputs remain auditable; state/events are live control metadata.
            files = [p for p in root.rglob("*") if p.is_file() and p.name not in
                     {".run.lock", "state.json", "events.jsonl", "artifact_manifest.json"}]
            write_json(root / "artifact_manifest.json", build_artifact_manifest(root, files))
            state["status"] = "completed"
            state["finished_at"] = utc_now()
            write_json(state_path, state)
            event(events, "run_completed", jobs=len(rows))
            return state
        except BaseException as exc:
            state["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
            state["last_error"] = str(exc)
            write_json(state_path, state)
            event(events, "run_failed", error=str(exc))
            raise
