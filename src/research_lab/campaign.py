"""Bounded development search, frozen selection, and a single holdout evaluation."""

from pathlib import Path
import shutil

from .agents import LocalPlanner, assess_candidate
from .campaign_plan import grid_plan, load_campaign
from .framework import BudgetExceeded, build_artifact_manifest, reserve_research_attempt, verify_artifact_manifest
from .pipeline import run as run_grid, verify_run
from .storage import digest, event, read_json, run_lock, utc_now, write_json


def _manifest(root):
    return build_artifact_manifest(root, [p for p in root.rglob("*")
                                         if p.is_file() and p.name != ".run.lock"])


def _require_integrity(root, manifest):
    errors = verify_artifact_manifest(root, manifest)
    if errors:
        raise ValueError(f"Campaign artifacts changed: {errors}")


def checked_results(grid):
    errors = verify_run(grid)
    if errors:
        raise ValueError(f"Invalid experiment grid: {errors}")
    state = read_json(grid / "state.json")
    rows = []
    for job in state["jobs"].values():
        result = read_json(grid / job["result_path"])
        checksum = result.get("provenance", {}).get("dataset_sha256")
        if not isinstance(checksum, str) or len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
            raise ValueError("Version 2 requires a SHA-256 dataset identity for every result")
        rows.append({"method": result["method"], "seed": result["seed"], "result": result,
                     "result_path": job["result_path"], "sha256": digest(grid / job["result_path"])})
    return rows


def run_campaign(config, output, *, resume=False, max_trials=None):
    protocol, script, source_files, fingerprint, source_info = load_campaign(config)
    if max_trials is not None and (type(max_trials) is not int or max_trials < 1):
        raise ValueError("max_trials must be positive")
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with run_lock(root):
        state_path = root / "state.json"
        if state_path.exists():
            if not resume:
                raise ValueError("Campaign exists; use --resume or a new output")
            state = read_json(state_path)
            if state["fingerprint"] != fingerprint:
                raise ValueError("Campaign inputs, engine or framework changed; use a new output")
            _require_integrity(root, state["inputs_manifest"])
            if state["status"] == "completed":
                errors = verify_campaign(root)
                if errors:
                    raise ValueError(f"Completed campaign changed: {errors}")
                return state
            for item in state["history"]:
                _require_integrity(root / item["grid"], item["manifest"])
            if state.get("selection_sha256"):
                if digest(root / "selection.json") != state["selection_sha256"]:
                    raise ValueError("Frozen selection changed")
        else:
            if resume:
                raise ValueError("Cannot resume: missing campaign state")
            if any(p.name != ".run.lock" for p in root.iterdir()):
                raise ValueError("New campaign output must be empty")
            inputs = root / "inputs"
            inputs.mkdir()
            shutil.copyfile(script, inputs / "experiment.py")
            write_json(inputs / "protocol.json", protocol)
            write_json(inputs / "fingerprint.json", source_info)
            registry = []
            for source in protocol["sources"]:
                destination = inputs / "sources" / (source["id"] + source_files[source["id"]].suffix)
                destination.parent.mkdir(exist_ok=True)
                shutil.copyfile(source_files[source["id"]], destination)
                registry.append({**source, "archived_path": destination.relative_to(root).as_posix(),
                                 "sha256": digest(destination), "verification": "local snapshot only; not independently verified"})
            write_json(inputs / "source_registry.json", registry)
            state = {"schema_version": 2, "status": "initialized", "created_at": utc_now(),
                     "fingerprint": fingerprint, "history": [], "incumbent": protocol["baseline"],
                     "incumbent_score": None, "dataset_identities": {},
                     "budget": {**protocol["budget"], "reservations": []},
                     "inputs_manifest": _manifest(inputs)}
            # Manifest entries above are relative to inputs, convert to campaign paths.
            state["inputs_manifest"] = build_artifact_manifest(root, [p for p in inputs.rglob("*") if p.is_file()])
            write_json(state_path, state)
            event(root / "events.jsonl", "campaign_initialized", mode="offline-rules", fingerprint=fingerprint)

        def save():
            write_json(state_path, state)

        def execute_grid(name, methods, seeds):
            plan = grid_plan(protocol, methods, seeds)
            path = root / "inputs" / "plans" / f"{name}.json"
            if path.exists():
                if read_json(path) != plan:
                    raise ValueError("Archived grid plan changed")
            else:
                write_json(path, plan)
            grid = root / "runs" / name

            def admit(job, attempt, timeout):
                state["budget"] = reserve_research_attempt(state["budget"], f"{name}/{job}/{attempt}", timeout)
                save()  # Durable admission comes before subprocess creation, including retry/resume.
                event(root / "events.jsonl", "attempt_reserved", grid=name, job=job, attempt=attempt)

            run_grid(path, grid, resume=(grid / "state.json").exists(), before_attempt=admit)
            rows = checked_results(grid)
            for row in rows:
                seed = str(row["seed"])
                checksum = row["result"]["provenance"]["dataset_sha256"]
                previous = state["dataset_identities"].get(seed)
                if previous and previous != checksum:
                    raise ValueError("Dataset changed between candidates or methods")
                state["dataset_identities"][seed] = checksum
            return grid, read_json(grid / "summary.json")

        try:
            planner = LocalPlanner()
            completed_here = 0
            if not state.get("selection_sha256"):
                state["status"] = "searching"
                save()
                while True:
                    candidate = planner.propose(protocol["candidates"], state["history"],
                                                max_trials=protocol["search"]["max_trials"],
                                                patience=protocol["search"]["patience"])
                    if candidate is None:
                        state["search_stop"] = "registered candidate/trial/patience limit"
                        break
                    if max_trials is not None and completed_here >= max_trials:
                        state["status"] = "paused"
                        save()
                        return state
                    # Keep enough admitted capacity for final comparisons (including retries).
                    needed = (2 * len(protocol["development_seeds"]) +
                              (2 + len(protocol["ablations"])) * len(protocol["holdout_seeds"])) * protocol["max_attempts"]
                    remaining = state["budget"]["max_attempts"] - len(state["budget"]["reservations"])
                    seconds_left = state["budget"]["max_timeout_seconds"] - sum(x["timeout_seconds"] for x in state["budget"]["reservations"])
                    # An interrupted trial already has reservations; resume it under per-attempt admission.
                    name = f"trial_{len(state['history']) + 1:03d}"
                    in_progress = (root / "runs" / name / "state.json").exists()
                    if not in_progress and (remaining < needed or seconds_left < needed * protocol["timeout_seconds"]):
                        if not state["history"]:
                            raise BudgetExceeded("Budget cannot admit a first trial and reserved holdout attempts")
                        state["search_stop"] = "budget reserve for holdout"
                        break
                    grid, summary = execute_grid(name, [protocol["baseline"], candidate], protocol["development_seeds"])
                    decision = assess_candidate(candidate, summary, state["incumbent"], state["incumbent_score"],
                                                protocol["search"]["min_improvement"])
                    if decision["accepted"]:
                        state["incumbent"], state["incumbent_score"] = candidate, decision["score"]
                    elif state["incumbent_score"] is None:
                        state["incumbent_score"] = decision["previous_score"]
                    state["history"].append({**decision, "grid": grid.relative_to(root).as_posix(),
                                             "manifest": _manifest(grid)})
                    save()
                    event(root / "events.jsonl", "candidate_reviewed", **decision)
                    completed_here += 1
                methods = list(dict.fromkeys([protocol["baseline"], state["incumbent"], *protocol["ablations"]]))
                selection = {"method": state["incumbent"], "development_score": state["incumbent_score"],
                             "holdout_methods": methods, "frozen_at": utc_now(),
                             "stop_reason": state["search_stop"], "trials": len(state["history"]),
                             "rule": "Strict development improvement; ties retain incumbent; no holdout reselection"}
                write_json(root / "selection.json", selection)
                state["selection_sha256"] = digest(root / "selection.json")
                save()
                event(root / "events.jsonl", "selection_frozen", method=selection["method"])
            selection = read_json(root / "selection.json")
            state["status"] = "evaluating_holdout"
            save()
            execute_grid("holdout", selection["holdout_methods"], protocol["holdout_seeds"])
            from .campaign_report import generate_campaign_reports, audit_campaign_content
            state["status"] = "writing"
            save()
            generate_campaign_reports(root, protocol, state)
            audit = audit_campaign_content(root)
            write_json(root / "audit.json", audit)
            if not audit["valid"]:
                raise ValueError(f"Evidence audit failed: {audit['errors']}")
            state["status"] = "completed"
            state["finished_at"] = utc_now()
            save()
            event(root / "events.jsonl", "campaign_completed", trials=len(state["history"]))
            paths = [p for p in root.rglob("*") if p.is_file() and p.name != ".run.lock"
                     and p != root / "campaign_manifest.json"]
            write_json(root / "campaign_manifest.json", build_artifact_manifest(root, paths))
            return state
        except BaseException as exc:
            state["status"] = ("budget_exhausted" if isinstance(exc, BudgetExceeded) else
                               "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed")
            state["last_error"] = str(exc)
            save()
            event(root / "events.jsonl", "campaign_stopped", status=state["status"], error=str(exc))
            raise


def verify_campaign(root):
    root = Path(root).resolve()
    state = read_json(root / "state.json")
    if state["status"] != "completed":
        return [f"Campaign is {state['status']}, not completed"]
    errors = verify_artifact_manifest(root, read_json(root / "campaign_manifest.json"))
    if not errors:
        from .campaign_report import audit_campaign_content
        errors.extend(audit_campaign_content(root)["errors"])
    return errors
