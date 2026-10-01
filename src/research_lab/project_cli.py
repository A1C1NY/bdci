"""One entry point for V5 projects; paid and network execution are explicit."""
import argparse
import json
import shutil
import sys

from .project import Project, validate
from .project_adapters import adapters
from .storage import read_json


def main(argv=None):
    parser = argparse.ArgumentParser(prog="research-lab project")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("root")
    init.add_argument("--config", required=True)
    check = commands.add_parser("validate")
    check.add_argument("config")
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--tex-binary", default="pdflatex")
    for name in ("status", "advance", "review", "decide", "retry", "revise"):
        p = commands.add_parser(name)
        p.add_argument("root")
        if name == "advance":
            p.add_argument("--allow-models", action="store_true")
            p.add_argument("--allow-network", action="store_true")
        if name in ("review", "decide", "retry"):
            p.add_argument("stage")
        if name in ("decide", "retry", "revise"):
            p.add_argument("--actor", required=True)
            p.add_argument("--reason", required=True)
        if name == "decide":
            p.add_argument("--action", choices=["accept", "reject", "request_changes", "terminate"], required=True)
            p.add_argument("--binding", required=True)
        if name == "revise":
            p.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            validate(read_json(args.config), adapters())
            result = {"valid": True, "adapter_inputs_checked_at_execution": True}
        elif args.command == "doctor":
            from .framework import ROOT
            result = {"python": sys.version, "tex_binary": shutil.which(args.tex_binary),
                      "native_engine_present": (ROOT / "vendor/agent-core/openjiuwen/agent_teams/workflow/engine/runner.py").is_file(),
                      "model_connection": "not_tested", "model_calls": 0,
                      "note": "TeX is optional for project execution; credentials are never printed."}
        else:
            project = Project(args.root)
            if args.command == "init":
                result = project.initialize(args.config)
            elif args.command == "status":
                result = project.status()
            elif args.command == "advance":
                result = project.advance(allow_models=args.allow_models, allow_network=args.allow_network)
            elif args.command == "review":
                result = project.review_packet(args.stage)
            elif args.command == "decide":
                result = project.decide(args.stage, args.action, args.actor, args.reason, args.binding)
            elif args.command == "retry":
                result = project.retry(args.stage, args.actor, args.reason)
            else:
                result = project.revise(args.config, args.actor, args.reason)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
