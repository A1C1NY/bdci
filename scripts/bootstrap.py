"""Fetch pinned upstream source and apply the reviewed patch, without model calls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PINS = {
    "jiuwenswarm": ("https://github.com/openJiuwen-ai/jiuwenswarm.git", "ce8af2051fd7c5dff85a09f8185fce64d32893a6"),
    "agent-core": ("https://github.com/openJiuwen-ai/agent-core.git", "9e3390195a9ea15235b2b5f7412cb2aa440622cc"),
}


def git(path, *args, capture=False):
    env = dict(os.environ, GIT_LFS_SKIP_SMUDGE="1", GIT_TERMINAL_PROMPT="0")
    return subprocess.run(["git", "-C", str(path), *args], check=True, env=env,
                          stdout=subprocess.PIPE if capture else None, text=True).stdout


def bootstrap(root=ROOT):
    root = Path(root)
    for name, (url, sha) in PINS.items():
        target = root / "vendor" / name
        if not (target / ".git").exists():
            if target.exists() and any(target.iterdir()):
                raise RuntimeError(f"Nonempty unmanaged directory: {target}")
            target.mkdir(parents=True, exist_ok=True)
            git(target, "init")
            git(target, "remote", "add", "origin", url)
        if git(target, "remote", "get-url", "origin", capture=True).strip() != url:
            raise RuntimeError(f"Unexpected origin for {name}")
        git(target, "config", "core.autocrlf", "false")
        head = subprocess.run(["git", "-C", str(target), "rev-parse", "--verify", "HEAD"], capture_output=True, text=True)
        if head.returncode:
            git(target, "fetch", "--depth", "1", "origin", sha)
            git(target, "checkout", "--detach", "FETCH_HEAD")
        elif head.stdout.strip() != sha:
            raise RuntimeError(f"Unexpected HEAD for {name}; existing checkout left untouched")
    target = root / "vendor/jiuwenswarm"
    patch = root / "integrations/jiuwenswarm/contribution_v4_with_tests.patch"
    manifest = json.loads((root / "integrations/jiuwenswarm/patched-files.json").read_text("utf-8"))
    def matches(name, sha):
        path = target / name
        return path.is_file() and hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == sha
    if not all(matches(name, sha) for name, sha in manifest.items()):
        git(target, "apply", "--check", str(patch))
        git(target, "apply", str(patch))
    # Exact modified file hashes catch unrelated edits and partial patch applications.
    for name, sha in manifest.items():
        if not matches(name, sha):
            raise RuntimeError(f"Patched source differs: {name}")
    print("Pinned JiuwenSwarm + agent-core and patch verified. No API calls.")


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    bootstrap()
