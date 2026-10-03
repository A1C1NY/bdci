"""Add the real reviewer receipt to a new ZIP; preserve the audited study bytes."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from research_lab.storage import read_json, write_json, digest, utc_now


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def main():
    old = ROOT / 'submissions/能工智人_待评审.zip'
    new = ROOT / 'submissions/能工智人_交接包.zip'
    assert not new.exists(), 'Never overwrite a release'
    receipt = read_json(ROOT / 'research/memory_v3/reviewer_submission.json')
    replay = read_json(ROOT / 'research/memory_v3/package_replay_audit.json')
    assert replay['valid'] and replay['zip_sha256'] == digest(old)
    assert receipt['submission_confirmed'] and receipt['paper_sha256'] == digest(ROOT / 'paper/paper.pdf')
    token = (ROOT / receipt['token_local_path']).read_bytes()
    assert token.strip(), 'Missing real reviewer token'
    prefix = '能工智人/'
    with zipfile.ZipFile(old) as source:
        status = json.loads(source.read(prefix + 'submission_status.json'))
        status.update(prepared_at=utc_now(), reviewer_submission=receipt, pr_owner='user_will_submit',
                      blockers=['Public JiuwenSwarm contribution PR URL still required', 'Official review is still being generated'])
        changes = {
            'code/README.md': (ROOT / 'README.md').read_bytes(),
            'code/research/progress.json': (ROOT / 'research/progress.json').read_bytes(),
            'docs/交接状态.md': (ROOT / 'docs/release/交接状态.md').read_bytes(),
            'code/integrations/jiuwenswarm/contribution_with_tests.patch': (ROOT / 'integrations/jiuwenswarm/contribution_with_tests.patch').read_bytes(),
            'code/integrations/jiuwenswarm/PR_DESCRIPTION.md': (ROOT / 'integrations/jiuwenswarm/PR_DESCRIPTION.md').read_bytes(),
            'code/scripts/prepare_contribution.py': (ROOT / 'scripts/prepare_contribution.py').read_bytes(),
            'AgenticReviewer/PaperReview-AccessToken.txt': token,
            'AgenticReviewer/README.md': '真实评审Token已保存。当前paper.pdf已按ICLR标准提交paperreview.ai；评审仍在生成，尚无分数。Token仅供比赛评测，不应公开到代码仓库。\n'.encode(),
            'AgenticReviewer/submission.json': encoded(receipt),
            'submission_status.json': encoded(status),
            'code/research/memory_v3/reviewer_submission.json': encoded(receipt),
            'code/scripts/verify_source_package.py': (ROOT / 'scripts/verify_source_package.py').read_bytes(),
            'release_validation.json': encoded({'previous_zip_sha256': digest(old), 'offline_replay': replay['replay'],
                                              'note': 'Research files and final paper preserved byte-for-byte from the independently replayed ZIP.'}),
            '提交说明.md': ('# 能工智人：已送评，待框架贡献PR\n\n论文已成功提交AgenticReviewer，真实Access Token在指定目录，评审仍在生成。框架源码及patch齐备，但公开PR链接尚缺。尚未上传比赛平台。\n\n本包保留已独立复现的全部研究记录和论文；token应仅向比赛官方提供，不要公开发布此ZIP。\n\n论文SHA-256：' + receipt['paper_sha256'] + '\n').encode(),
        }
        manifest = json.loads(source.read(prefix + 'package_manifest.json'))
        expected = {row['path']: row for row in manifest['artifacts']}
        with zipfile.ZipFile(new, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as target:
            for info in source.infolist():
                relative = info.filename[len(prefix):]
                if relative in changes or relative == 'package_manifest.json':
                    continue
                data = source.read(info.filename)
                assert hashlib.sha256(data).hexdigest() == expected[relative]['sha256']
                target.writestr(info.filename, data)
            for relative, data in changes.items():
                target.writestr(prefix + relative, data)
                expected[relative] = {'path': relative, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            target.writestr(prefix + 'package_manifest.json', encoded({'schema_version': 1, 'artifacts': [expected[k] for k in sorted(expected)]}))
    with zipfile.ZipFile(new) as final:
        assert final.testzip() is None
        for row in expected.values():
            data = final.read(prefix + row['path'])
            assert len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']
    write_json(ROOT / 'research/memory_v3/reviewer_package_status.json', {
        **status, 'zip': new.name, 'zip_sha256': digest(new), 'bytes': new.stat().st_size,
        'all_zip_hashes_verified': True, 'study_bytes_unchanged': True})
    print(json.dumps({'bytes': new.stat().st_size, 'all_zip_hashes_verified': True,
                      'reviewer_receipt_present': True, 'competition_submitted': False}))


if __name__ == '__main__':
    main()
