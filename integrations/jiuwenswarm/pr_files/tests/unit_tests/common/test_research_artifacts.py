import shutil

import pytest

from jiuwenswarm.common.team_artifacts import build_artifact_manifest, verify_artifact_manifest


def test_manifest_survives_relocation(tmp_path):
    root = tmp_path / "before"
    root.mkdir()
    (root / "evidence.json").write_text('{"score": 0.5}', encoding="utf-8")
    manifest = build_artifact_manifest(root, ["evidence.json"])
    moved = tmp_path / "after"
    shutil.copytree(root, moved)
    assert verify_artifact_manifest(moved, manifest) == []
    (moved / "evidence.json").write_text('{"score": 0.9}', encoding="utf-8")
    assert verify_artifact_manifest(moved, manifest)


def test_missing_file_is_reported(tmp_path):
    path = tmp_path / "file"
    path.write_bytes(b"original")
    manifest = build_artifact_manifest(tmp_path, ["file"])
    path.unlink()
    assert verify_artifact_manifest(tmp_path, manifest)


def test_escape_is_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside").write_text("not an artifact", encoding="utf-8")
    with pytest.raises(ValueError):
        build_artifact_manifest(root, ["../outside"])
    assert verify_artifact_manifest(root, {"schema_version": 1, "artifacts": [
        {"path": "../outside", "bytes": 15, "sha256": "x"}]})


def test_duplicate_entries_are_rejected(tmp_path):
    (tmp_path / "file").write_bytes(b"123")
    with pytest.raises(ValueError):
        build_artifact_manifest(tmp_path, ["file", "file"])
    manifest = build_artifact_manifest(tmp_path, ["file"])
    manifest["artifacts"] *= 2
    assert verify_artifact_manifest(tmp_path, manifest)


@pytest.mark.parametrize("manifest", [{}, {"schema_version": 1, "artifacts": []},
                                     {"schema_version": 1, "artifacts": [None]},
                                     {"schema_version": 1, "artifacts": [{"path": 4}]}])
def test_malformed_manifests_fail_closed(tmp_path, manifest):
    assert verify_artifact_manifest(tmp_path, manifest)


from copy import deepcopy
from jiuwenswarm.common.research_budget import BudgetExceeded, reserve_research_attempt

def test_budget_reservations_are_pure_and_bounded():
    ledger = {"max_attempts": 2, "max_timeout_seconds": 15, "reservations": []}
    first = reserve_research_attempt(ledger, "one", 10)
    assert ledger["reservations"] == []
    with pytest.raises(BudgetExceeded):
        reserve_research_attempt(first, "two", 10)
    second = reserve_research_attempt(first, "two", 5)
    with pytest.raises(BudgetExceeded):
        reserve_research_attempt(second, "three", 0.1)
    corrupted = deepcopy(second)
    corrupted["reservations"][0]["timeout_seconds"] = -1
    with pytest.raises(ValueError):
        reserve_research_attempt(corrupted, "four", 1)
