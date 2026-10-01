"""Scan Git index contents before publication. Prints paths, never matched values."""
from pathlib import PurePosixPath
import re
import subprocess

PRIVATE = {".local", ".venv", "vendor", "data", "research", "paper", "submissions", "outputs", "projects", "__pycache__"}
PATTERNS = [rb"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_-]{24,}",
            rb"gh[pousr]_[A-Za-z0-9]{30,}", rb"github_pat_[A-Za-z0-9_]{30,}",
            rb"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"]


def issues(name, content):
    path = PurePosixPath(name)
    result = []
    parts = path.parts[2:] if path.parts[:2] == ("config", "projects") else path.parts
    if any(part in PRIVATE for part in parts) or path.name == "PaperReview-AccessToken.txt":
        result.append("private path")
    if path.name.startswith(".env") and path.name != ".env.example":
        result.append("credential file")
    if len(content) > 5_000_000 or path.suffix.lower() in (".zip", ".pdf", ".pyc"):
        result.append("large/binary artifact")
    if any(re.search(pattern, content) for pattern in PATTERNS):
        result.append("possible credential")
    return result


def main():
    names = subprocess.check_output(["git", "ls-files", "-z"]).decode("utf-8").split("\0")
    count = 0
    failures = []
    for name in filter(None, names):
        content = subprocess.check_output(["git", "show", ":" + name])
        failures.extend((name, problem) for problem in issues(name, content))
        count += 1
    for name, problem in failures:
        print(problem + ": " + name)
    print(f"Scanned {count} staged/tracked files; findings: {len(failures)}")
    if not count or failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
