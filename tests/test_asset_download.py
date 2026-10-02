import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest


def loader(tmp_path, monkeypatch, expected=b"verified fixture"):
    file = Path(__file__).resolve().parents[1] / "scripts/fetch_assets.py"
    spec = importlib.util.spec_from_file_location("fetch_fixture_assets", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/assets.json").write_text(json.dumps({"reranker": [{
        "path": ".local/model.bin", "url": "https://example.invalid/pinned-model",
        "sha256": hashlib.sha256(expected).hexdigest()}]}), encoding="utf-8")
    return module


def test_download_hash_failure_preserves_partial_and_existing_file(tmp_path, monkeypatch):
    module = loader(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "urlopen", lambda *a, **kw: io.BytesIO(b"wrong"))
    with pytest.raises(ValueError, match="Downloaded hash differs"):
        module.fetch("reranker")
    target = tmp_path / ".local/model.bin"
    assert not target.exists()
    assert target.with_suffix(".bin.part").read_bytes() == b"wrong"
    target.write_bytes(b"existing unrelated")
    with pytest.raises(ValueError, match="Existing file differs"):
        module.fetch("reranker")
    assert target.read_bytes() == b"existing unrelated"


def test_powershell_receives_url_as_data_and_still_checks_hash(tmp_path, monkeypatch):
    module = loader(tmp_path, monkeypatch)
    def run(argv, env, check):
        assert check is True
        assert "example.invalid" not in " ".join(argv)
        assert env["RESEARCH_ASSET_URL"].startswith("https://")
        assert "SkipCertificateCheck" not in argv[-1]
        Path(env["RESEARCH_ASSET_PATH"]).write_bytes(b"verified fixture")
    monkeypatch.setattr(module.subprocess, "run", run)
    module.fetch("reranker", "powershell")
    assert (tmp_path / ".local/model.bin").read_bytes() == b"verified fixture"
    # Existing verified objects must not require a working network.
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **kw: pytest.fail("unexpected download"))
    module.fetch("reranker", "powershell")
