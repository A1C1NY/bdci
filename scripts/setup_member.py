"""Create a local member profile once; never copy credentials or reset budgets."""
import argparse
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]


def setup(member, deepseek_budget, kimi_budget, root=ROOT):
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", member):
        raise ValueError("Member ID must use letters, digits, _ or -")
    if min(deepseek_budget, kimi_budget) < 200000:
        raise ValueError("Allocate at least 200000 tokens per model (including request reservations)")
    root = Path(root)
    local = root / ".local"
    local.mkdir(exist_ok=True)
    destination = local / "models.json"
    if destination.exists():
        raise ValueError("Local profile already exists; edit it explicitly, do not reset the ledger")
    config = json.loads((root / "config/models.example.json").read_text("utf-8"))
    config["ledger_directory"] = "model-usage"
    config["credentials_file"] = "../.env.local"
    config["models"]["deepseek"]["token_budget"] = deepseek_budget
    config["models"]["kimi"]["token_budget"] = kimi_budget
    destination.write_text(json.dumps(config, indent=2) + "\n", "utf-8")
    (local / "member.json").write_text(json.dumps({"member": member}, indent=2) + "\n", "utf-8")
    if not (root / ".env.local").exists():
        shutil.copyfile(root / ".env.example", root / ".env.local")
    print("Created local profile. Edit .local/models.json and .env.local before paid calls.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--member", required=True)
    p.add_argument("--deepseek-budget", type=int, required=True)
    p.add_argument("--kimi-budget", type=int, required=True)
    a = p.parse_args()
    setup(a.member, a.deepseek_budget, a.kimi_budget)
