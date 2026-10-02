"""Fetch attributed data/template files with exact hashes; never call models."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def fetch(group, transport="urllib"):
    config = json.loads((ROOT / "config/assets.json").read_text("utf-8"))[group]
    for item in config:
        path = ROOT / item["path"]
        if path.exists():
            with path.open("rb") as source:
                actual = hashlib.file_digest(source, "sha256").hexdigest()
            if actual != item["sha256"]:
                raise ValueError("Existing file differs; left untouched: " + item["path"])
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".part")
        if transport == "powershell":
            # Pass values as data, not interpolated shell source. TLS verification stays enabled.
            env = {**os.environ, "RESEARCH_ASSET_URL": item["url"], "RESEARCH_ASSET_PATH": str(partial)}
            subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                            "$ErrorActionPreference='Stop'; Invoke-WebRequest -UseBasicParsing "
                            "-Uri $env:RESEARCH_ASSET_URL -OutFile $env:RESEARCH_ASSET_PATH -TimeoutSec 120"],
                           env=env, check=True)
        else:
            with urlopen(item["url"], timeout=120) as response, partial.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
        with partial.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != item["sha256"]:
            raise ValueError("Downloaded hash differs; partial file retained: " + item["path"])
        partial.replace(path)
        print("Verified", item["path"])


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("group", choices=["stale", "iclr", "reranker"])
    p.add_argument("--transport", choices=["urllib", "powershell"], default="urllib")
    args = p.parse_args()
    fetch(args.group, args.transport)
