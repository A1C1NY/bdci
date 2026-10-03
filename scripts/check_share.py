"""Check a file before sharing it outside the local research checkout."""

import re


_SECRET = re.compile(rb"(?:sk-|api[_-]?key\s*=\s*)(?:[A-Za-z0-9_-]{20,})", re.I)


def issues(path, content):
    path = str(path).replace("\\", "/")
    findings = []
    lower = path.lower()
    if lower.startswith("submissions/") or "/submissions/" in lower:
        findings.append("submission archives must not be shared from the public checkout")
    if lower == ".env" or lower.endswith("/.env") or lower == ".env.local" or lower.endswith("/.env.local"):
        findings.append("local credential file")
    if _SECRET.search(content):
        findings.append("credential-like value")
    return findings


def main():
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    failed = False
    for name in args.paths:
        path = Path(name)
        findings = issues(path, path.read_bytes())
        for finding in findings:
            failed = True
            print(f"{path}: {finding}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
