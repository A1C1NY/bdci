"""Create a member's ignored local model profile without overwriting it."""

import argparse
import json
from pathlib import Path
import shutil


def setup(member, deepseek_budget, kimi_budget, root=None):
    root = Path(root or Path(__file__).resolve().parents[1]).resolve()
    local = root / ".local"
    config_path = local / "models.json"
    if config_path.exists():
        raise ValueError(f"Local member configuration already exists: {config_path}")
    example = root / "config" / "models.example.json"
    if not example.is_file():
        raise FileNotFoundError(example)
    config = json.loads(example.read_text(encoding="utf-8-sig"))
    config["models"]["deepseek"]["token_budget"] = int(deepseek_budget)
    config["models"]["kimi"]["token_budget"] = int(kimi_budget)
    local.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    env_example = root / ".env.example"
    env_local = root / ".env.local"
    if env_example.is_file():
        shutil.copyfile(env_example, env_local)
    return config_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--member", required=True)
    parser.add_argument("--deepseek-budget", type=int, required=True)
    parser.add_argument("--kimi-budget", type=int, required=True)
    args = parser.parse_args()
    print(setup(args.member, args.deepseek_budget, args.kimi_budget))


if __name__ == "__main__":
    main()
