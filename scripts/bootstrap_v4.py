"""Archive the prior implementation and acquire attributed public research assets."""
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
local = ROOT / '.local/v4'
local.mkdir(parents=True, exist_ok=True)
baseline = local / 'v031-source-baseline.zip'
if not baseline.exists():
    with zipfile.ZipFile(baseline, 'x', zipfile.ZIP_DEFLATED) as z:
        for directory in ('src', 'scripts', 'tests', 'config', 'integrations'):
            for p in (ROOT / directory).rglob('*'):
                if p.is_file() and '__pycache__' not in p.parts:
                    z.write(p, p.relative_to(ROOT))
        z.write(ROOT / 'paper/paper.pdf', 'paper/paper.pdf')
    print('Archived v0.3.1 implementation and submitted PDF.', flush=True)
dest = ROOT / 'research/v4/assets/stale'
dest.mkdir(parents=True, exist_ok=True)
metadata = json.load(urllib.request.urlopen('https://huggingface.co/api/datasets/STALEproj/STALE', timeout=45))
revision = metadata['sha']
manifest = {'dataset': 'STALEproj/STALE', 'revision': revision, 'files': {}}
for name in ('README.md', 'LICENSE', 'LongMemEval_LICENSE', 'T1_T2_400_FULL.json'):
    url = f'https://huggingface.co/datasets/STALEproj/STALE/resolve/{revision}/{name}'
    p = dest / name
    if not p.exists():
        with urllib.request.urlopen(url, timeout=120) as r, p.with_suffix(p.suffix + '.part').open('wb') as f:
            while chunk := r.read(1024 * 1024): f.write(chunk)
        p.with_suffix(p.suffix + '.part').replace(p)
    manifest['files'][name] = {'url': url, 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
    print('Saved', name, p.stat().st_size, flush=True)
(dest / 'source.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
data = json.loads((dest / 'T1_T2_400_FULL.json').read_text(encoding='utf-8'))
print('Dataset shape:', type(data).__name__, len(data), flush=True)
if isinstance(data, dict): print('Top-level fields:', list(data)[:20])
elif data: print('Record field types:', {k: type(v).__name__ for k,v in data[0].items()})
