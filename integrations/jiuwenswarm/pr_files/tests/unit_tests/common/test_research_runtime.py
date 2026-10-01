"""Evidence gate tests for the optional research integration."""
import hashlib
import pytest
from jiuwenswarm.common.research_runtime import evidence_gate, load_research_engine

def test_missing_engine_fails_explicitly(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_research_engine(tmp_path)

def test_missing_evidence_and_modified_content_fail(tmp_path):
    path = tmp_path / "result.json"
    path.write_text("original")
    evidence = {"result": {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}
    claims = [{"id": "claim", "evidence_ids": ["result"]}]
    assert evidence_gate(claims, evidence)
    path.write_text("changed")
    with pytest.raises(ValueError, match="Evidence changed"):
        evidence_gate(claims, evidence)
    with pytest.raises(ValueError, match="no evidence"):
        evidence_gate([{"id": "claim", "evidence_ids": []}], evidence)
    with pytest.raises(KeyError):
        evidence_gate(claims, {})
