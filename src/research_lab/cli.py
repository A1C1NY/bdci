import argparse
import json
import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "project":
        from .project_cli import main as project_main
        return project_main(argv[1:])
    parser = argparse.ArgumentParser(description="Evidence-backed research workflow; model calls are explicit commands")
    parser.epilog = "V5 supervised projects: research-lab project --help"
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--plan", required=True)
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--resume", action="store_true")
    run_parser.add_argument("--max-jobs", type=int, help="Pause after this many newly executed jobs")
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("run_dir")
    validate_parser = commands.add_parser("validate-plan")
    validate_parser.add_argument("plan")
    campaign_parser = commands.add_parser("campaign", help="V2 bounded search and frozen holdout")
    campaign_parser.add_argument("--config", required=True)
    campaign_parser.add_argument("--output", required=True)
    campaign_parser.add_argument("--resume", action="store_true")
    campaign_parser.add_argument("--max-trials", type=int, help="Pause after N new development trials")
    for command in ("verify-campaign", "status"):
        commands.add_parser(command).add_argument("run_dir")
    commands.add_parser("validate-campaign").add_argument("config")
    export_parser = commands.add_parser("export-review", help="Offline review kit; NOT an official submission")
    export_parser.add_argument("run_dir")
    export_parser.add_argument("--output", required=True)
    feedback_parser = commands.add_parser("review-feedback", help="Import reviewer comments into a revision plan")
    feedback_parser.add_argument("run_dir")
    feedback_parser.add_argument("--feedback", required=True)
    feedback_parser.add_argument("--output", required=True)
    from .model_config import DEFAULT_CONFIG
    for name in ("usage", "usage-server", "model-check", "model-call", "model-review", "model-task"):
        sub = commands.add_parser(name)
        sub.add_argument("--models-config", default=None)
        if name == "usage-server":
            sub.add_argument("--port", type=int, default=8767)
        elif name in ("model-check", "model-call"):
            sub.add_argument("--model", required=True, help="Configured alias: deepseek or kimi")
            sub.add_argument("--api-format", choices=["chat", "responses"])
            sub.add_argument("--max-output-tokens", type=int, default=1800 if name == "model-check" else None)
            streaming = sub.add_mutually_exclusive_group()
            streaming.add_argument("--no-stream", dest="stream", action="store_false")
            streaming.add_argument("--stream", dest="stream", action="store_true")
            sub.set_defaults(stream=None)
            sub.add_argument("--output", help="New JSON response path (never overwrite)")
            if name == "model-call":
                sub.add_argument("--prompt-file", required=True)
        elif name == "model-review":
            sub.add_argument("run_dir")
            sub.add_argument("--model", help="Defaults to configured critic")
            sub.add_argument("--output", required=True)
        elif name == "model-task":
            sub.add_argument("--task", required=True)
            sub.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in ("usage", "usage-server", "model-check", "model-call", "model-review", "model-task"):
            from pathlib import Path
            from .model_config import load_models
            config = load_models(args.models_config)
            if args.command == "usage":
                from .token_ledger import TokenLedger
                print(json.dumps(TokenLedger(config).snapshot(), ensure_ascii=False, indent=2))
            elif args.command == "usage-server":
                from .usage_dashboard import serve_usage
                if not 1024 <= args.port <= 65535:
                    raise ValueError("Dashboard port must be 1024..65535")
                serve_usage(config, args.port)
            elif args.command == "model-review":
                from .model_review import review_campaign
                print(json.dumps(review_campaign(args.run_dir, args.output, config, alias=args.model), ensure_ascii=False))
            elif args.command == "model-task":
                from .supervised_tasks import run_assignment
                print(json.dumps(run_assignment(args.task, args.output, config), ensure_ascii=False))
            else:
                from .model_client import ModelClient
                from .storage import write_json
                if args.output and Path(args.output).exists():
                    raise ValueError("Response output already exists")
                prompt = ("Reply exactly OK. Do not explain." if args.command == "model-check" else
                          Path(args.prompt_file).read_text(encoding="utf-8-sig"))
                result = ModelClient(config).generate(args.model, [{"role": "user", "content": prompt}],
                    purpose=args.command, api_format=args.api_format,
                    max_output_tokens=args.max_output_tokens, stream=args.stream)
                if args.output:
                    write_json(args.output, result)
                print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "validate-campaign":
            from .campaign_plan import load_campaign
            protocol, _, _, fingerprint, _ = load_campaign(args.config)
            print(json.dumps({"valid": True, "fingerprint": fingerprint,
                              "candidates": protocol["candidates"], "budget": protocol["budget"]}))
            return 0
        if args.command == "campaign":
            from .campaign import run_campaign
            state = run_campaign(args.config, args.output, resume=args.resume, max_trials=args.max_trials)
            print(json.dumps({"status": state["status"], "selected": state["incumbent"],
                              "trials": len(state["history"]), "output": args.output}, ensure_ascii=False))
            return 0
        if args.command == "verify-campaign":
            from .campaign import verify_campaign
            errors = verify_campaign(args.run_dir)
            print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False))
            return 1 if errors else 0
        if args.command == "status":
            from pathlib import Path
            from .storage import read_json
            state = read_json(Path(args.run_dir) / "state.json")
            print(json.dumps({key: value for key, value in state.items() if key in
                              {"status", "incumbent", "incumbent_score", "last_error", "budget", "finished_at"}}, ensure_ascii=False))
            return 0
        if args.command in ("export-review", "review-feedback"):
            from .handoff import export_review, import_feedback
            result = (export_review(args.run_dir, args.output) if args.command == "export-review" else
                      import_feedback(args.run_dir, args.feedback, args.output))
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "validate-plan":
            from .plan import load_plan
            plan, script = load_plan(args.plan)
            print(json.dumps({"valid": True, "experiment": str(script),
                              "jobs": len(plan["methods"]) * len(plan["seeds"])}, ensure_ascii=False))
            return 0
        from .pipeline import run, verify_run
        if args.command == "verify":
            errors = verify_run(args.run_dir)
            print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False))
            return 1 if errors else 0
        state = run(args.plan, args.output, resume=args.resume, max_jobs=args.max_jobs)
        print(json.dumps({"status": state["status"], "output": args.output}, ensure_ascii=False))
        return 0
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
