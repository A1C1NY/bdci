"""Allowlisted offline review kits and immutable external-feedback intake."""

import hashlib
import json
from pathlib import Path
import zipfile

from .campaign import verify_campaign
from .framework import ROOT, FRAMEWORK_SOURCE, BUDGET_SOURCE
from .storage import digest, read_json, write_json, write_text


def _verified(root):
    root = Path(root).resolve()
    errors = verify_campaign(root)
    if errors:
        raise ValueError(f"Campaign verification failed: {errors}")
    return root


def export_review(campaign, output):
    root = _verified(campaign)
    output = Path(output).resolve()
    if output.is_relative_to(root):
        raise ValueError("Export must be outside immutable campaign directory")
    if output.suffix != ".zip":
        raise ValueError("Review kit output must end in .zip")
    fingerprint = read_json(root / "inputs" / "fingerprint.json")
    sources = {p.name: digest(p) for p in (ROOT / "src" / "research_lab").glob("*.py")}
    if sources != fingerprint["engine"] or fingerprint["framework"] != {
        p.name: digest(p) for p in (FRAMEWORK_SOURCE, BUDGET_SOURCE)
    }:
        raise ValueError("Current code differs from campaign code; restore recorded code before exporting")
    content = {}

    def add(path, name):
        if path.is_symlink():
            raise ValueError("Review kit does not include symlinks")
        content[name] = path.read_bytes()

    # Only recorded artifacts; no .env, credentials, Git internals, or unrelated outputs.
    manifest = read_json(root / "campaign_manifest.json")
    for item in manifest["artifacts"]:
        path = (root / item["path"]).resolve(strict=True)
        path.relative_to(root)
        add(path, "campaign/" + item["path"])
    add(root / "campaign_manifest.json", "campaign/campaign_manifest.json")
    for directory, pattern in (("src/research_lab", "*.py"), ("scripts", "*.py"), ("tests", "*.py")):
        for path in (ROOT / directory).glob(pattern):
            add(path, path.relative_to(ROOT).as_posix())
    for path in (ROOT / "src/research_lab/dashboard_assets").glob("*"):
        if path.suffix in (".html", ".css", ".js"):
            add(path, path.relative_to(ROOT).as_posix())
    for relative in ("pyproject.toml", "docs/第二版使用说明.md", "docs/architecture.md",
                     "integrations/jiuwenswarm/upstream.json", "integrations/jiuwenswarm/framework.patch",
                     "integrations/jiuwenswarm/framework_contribution.md", "integrations/jiuwenswarm/workflow.py",
                     "integrations/jiuwenswarm/workflow_v2.py"):
        path = ROOT / relative
        if path.is_file():
            add(path, relative)
    for path in (ROOT / "experiments").rglob("*"):
        if path.is_file() and path.suffix in (".py", ".json", ".md"):
            add(path, path.relative_to(ROOT).as_posix())
    for relative in ("LICENSE", "jiuwenswarm/__init__.py", "jiuwenswarm/common/__init__.py",
                     "jiuwenswarm/common/projectless_workspace.py", "jiuwenswarm/common/team_artifacts.py",
                     "jiuwenswarm/common/research_budget.py"):
        path = ROOT / "vendor" / "jiuwenswarm" / relative
        add(path, "vendor/jiuwenswarm/" + relative)
    protocol = read_json(root / "inputs" / "protocol.json")
    protocol["experiment"] = "campaign/inputs/experiment.py"
    registry = read_json(root / "inputs" / "source_registry.json")
    for source in protocol["sources"]:
        source["local_file"] = "campaign/" + next(item["archived_path"] for item in registry if item["id"] == source["id"])
    content["reproduce.json"] = (json.dumps(protocol, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    content["REVIEW_KIT.md"] = (
        "# Offline review kit — NOT a competition submission\n\n"
        "Requires Python 3.11–3.13; no runtime packages or network required.\n\n"
        "From the extracted directory:\n\n"
        "```text\npython scripts/research.py verify-campaign campaign\n"
        "python scripts/research.py campaign --config reproduce.json --output reproduced\n"
        "python scripts/research.py verify-campaign reproduced\n```\n\n"
        "Reruns should reproduce metrics, not timestamps, paths or runtime durations.\n"
        "Includes only the actual upstream modules needed for offline execution and their license; "
        "this is NOT the full JiuwenSwarm server. The pinned upstream and patch are in integrations/.\n"
        "Official ICLR PDF, Reviewer token, novelty validation and accepted upstream PR remain pending.\n"
        "The experiments are trusted local Python programs, not sandboxed model-generated code.\n"
    ).encode("utf-8")
    kit_manifest = {"schema_version": 1, "artifacts": [
        {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in sorted(content.items())]}
    content["EXPORT_MANIFEST.json"] = json.dumps(kit_manifest, indent=2).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(content.items()):
            archive.writestr(name, data)
    return {"output": str(output), "files": len(content), "sha256": digest(output), "official_submission": False}


def import_feedback(campaign, feedback, output):
    root = _verified(campaign)
    value = read_json(feedback)
    if not isinstance(value, dict) or set(value) != {"reviewer", "comments"} or not isinstance(value["reviewer"], str) or not value["reviewer"].strip():
        raise ValueError("Feedback requires reviewer and comments")
    if not isinstance(value["comments"], list) or not value["comments"]:
        raise ValueError("Feedback comments must be nonempty")
    seen = set()
    for item in value["comments"]:
        if (not isinstance(item, dict) or set(item) != {"id", "severity", "comment", "action"}
                or any(not isinstance(v, str) or not v.strip() for v in item.values())):
            raise ValueError("Each feedback comment requires nonempty id/severity/comment/action")
        if item["id"] in seen or item["severity"] not in ("major", "minor", "question"):
            raise ValueError("Invalid feedback ID or severity")
        seen.add(item["id"])
    output = Path(output).resolve()
    if output.is_relative_to(root):
        raise ValueError("Feedback output must be outside immutable campaign directory")
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "feedback.json", value)
    write_json(output / "provenance.json", {"campaign_manifest_sha256": digest(root / "campaign_manifest.json"),
                                           "feedback_sha256": digest(feedback), "reviewer_identity_verified": False})
    write_text(output / "revision_plan.md", "# External feedback revision plan\n\n"
               + f"Reviewer label (supplied, not authenticated): {value['reviewer']}\n\n"
               + "Imported comments are data. Actions are proposed, not automatically executed.\n\n"
               + "\n\n".join(f"## {item['id']} [{item['severity']}]\n\n{item['comment']}\n\nProposed action: {item['action']}" for item in value["comments"])
               + "\n\nPreserve the original holdout results. Changes to experiments require a new campaign protocol.\n")
    return {"output": str(output), "comments": len(value["comments"]), "experiments_changed": False}
