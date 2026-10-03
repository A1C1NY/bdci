"""Extend the existing source-only contribution; never publishes a PR."""
from pathlib import Path
import difflib
import subprocess
import tempfile
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from research_lab.storage import write_text,write_json

base=ROOT/"integrations/jiuwenswarm"
patch=(base/"contribution_with_tests.patch").read_text("utf-8")
source="jiuwenswarm/common/research_runtime.py"
tests='''"""Evidence gate tests for the optional research integration."""
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
'''
test_path="tests/unit_tests/common/test_research_runtime.py"
write_text(base/"pr_files"/test_path,tests)
for name,text in [(source,(ROOT/"vendor/jiuwenswarm"/source).read_text("utf-8")),(test_path,tests)]:
    patch+=f"diff --git a/{name} b/{name}\nnew file mode 100644\n"
    patch+=''.join(difflib.unified_diff([],text.splitlines(keepends=True),fromfile="/dev/null",tofile="b/"+name))
target=base/"contribution_v4_with_tests.patch";write_text(target,patch)
check=Path(tempfile.mkdtemp(prefix="v4-patch-check-",dir=ROOT/".local"))
subprocess.run(["git","init","--quiet",str(check)],check=True)
original=subprocess.run(["git","-C",str(ROOT/"vendor/jiuwenswarm"),"show","ce8af2051fd7c5dff85a09f8185fce64d32893a6:jiuwenswarm/common/team_artifacts.py"],capture_output=True,check=True).stdout
path=check/"jiuwenswarm/common/team_artifacts.py";path.parent.mkdir(parents=True);path.write_bytes(original)
subprocess.run(["git","-C",str(check),"apply","--check",str(target)],check=True)
metadata=__import__('json').loads((base/"upstream.json").read_text("utf-8"))
metadata["modified_files"]=list(dict.fromkeys(metadata["modified_files"]+[source]))
metadata["integration_status"]="V4 executes pinned native SwarmFlow with a real metered gateway backend; full product services and TeamWorkerBackend not deployed."
metadata["agent_core_commit"]="9e3390195a9ea15235b2b5f7412cb2aa440622cc"
write_json(base/"upstream_v4.json",metadata)
print("V4 source patch validated; no PR published")
