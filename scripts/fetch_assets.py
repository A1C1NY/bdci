"""Fetch attributed data/template files with exact hashes; never call models."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def fetch(group):
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
        hasher = hashlib.sha256()
        with urlopen(item["url"], timeout=120) as response, partial.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                hasher.update(chunk)
        if hasher.hexdigest() != item["sha256"]:
            raise ValueError("Downloaded hash differs; partial file retained: " + item["path"])
        partial.replace(path)
        print("Verified", item["path"])


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("group", choices=["stale", "iclr"])
    fetch(p.parse_args().group)
