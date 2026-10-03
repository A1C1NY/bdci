"""Validate the ZIP, then replay in a fresh extracted directory without API calls."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from research_lab.storage import read_json, write_json, digest, utc_now
from research_lab.framework import verify_artifact_manifest


def main():
    package = ROOT / 'submissions/能工智人_待评审.zip'
    destination = Path(tempfile.mkdtemp(prefix='package-replay-', dir=ROOT / '.local'))
    with zipfile.ZipFile(package) as archive:
        assert archive.testzip() is None, 'ZIP CRC mismatch'
        for name in archive.namelist():
            path = Path(name)
            assert not path.is_absolute() and '..' not in path.parts
            assert path.parts[0] == '能工智人'
            assert not any(p in {'.env.local', '.git', '.local', '__pycache__'} for p in path.parts)
        archive.extractall(destination)
    release = destination / '能工智人'
    errors = verify_artifact_manifest(release, read_json(release / 'package_manifest.json'))
    assert not errors, errors
    assert digest(release / 'paper/paper.pdf') == digest(ROOT / 'paper/paper.pdf')
    assert not (release / 'AgenticReviewer/PaperReview-AccessToken.txt').exists()
    print('ZIP, all file hashes, paper identity, and credential-file exclusions passed.', flush=True)
    subprocess.run([sys.executable, 'scripts/audit_source_release.py'], cwd=release / 'code', check=True)
    report = {'checked_at': utc_now(), 'valid': True, 'zip_sha256': digest(package),
              'fresh_extraction': str(destination),
              'replay': read_json(release / 'code/research/memory_v3/release_audit.json')}
    write_json(ROOT / 'research/memory_v3/package_replay_audit.json', report)
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__':
    main()
