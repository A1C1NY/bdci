import hashlib
import json

import pytest

from research_lab.release_receipt import atomic_archive, verified_receipt


def fixture_receipt(tmp_path):
    paper=tmp_path/'paper.pdf'
    paper.write_bytes(b'original PDF fixture')
    token='review-access-fixture'
    receipt=tmp_path/'receipt.json'
    data={'submission_confirmed':True,'destination':'https://paperreview.ai/',
          'venue':'ICLR','submitted_at':'2026-09-29T18:00:00+00:00','review_status':'completed',
          'paper_sha256':hashlib.sha256(paper.read_bytes()).hexdigest(),
          'token_sha256':hashlib.sha256(token.encode()).hexdigest()}
    receipt.write_text(json.dumps(data),encoding='utf-8')
    return receipt,paper,token,data


def test_repack_preserves_recorded_time_and_review_status(tmp_path):
    receipt,paper,token,data=fixture_receipt(tmp_path)
    original=receipt.read_bytes()
    assert verified_receipt(receipt,paper,token)==data
    assert verified_receipt(receipt,paper,token)==data
    assert receipt.read_bytes()==original


@pytest.mark.parametrize('change',['pdf','token','unconfirmed','missing'])
def test_rejects_missing_or_mismatched_evidence(tmp_path,change):
    receipt,paper,token,data=fixture_receipt(tmp_path)
    if change=='pdf':paper.write_bytes(b'revised PDF fixture')
    elif change=='token':token='other-review-token'
    elif change=='unconfirmed':
        data['submission_confirmed']=False
        receipt.write_text(json.dumps(data),encoding='utf-8')
    else:receipt.unlink()
    with pytest.raises((ValueError,FileNotFoundError)):
        verified_receipt(receipt,paper,token)


def test_failed_build_preserves_previous_release(tmp_path):
    target=tmp_path/'release.zip'
    target.write_bytes(b'verified original archive')
    with pytest.raises(RuntimeError):
        with atomic_archive(target) as temporary:
            temporary.write_bytes(b'partial replacement')
            raise RuntimeError('simulated interrupted build')
    assert target.read_bytes()==b'verified original archive'
    assert not list(tmp_path.glob('.release-*'))


def test_successful_build_replaces_archive(tmp_path):
    target=tmp_path/'release.zip'
    target.write_bytes(b'old')
    with atomic_archive(target) as temporary:
        temporary.write_bytes(b'complete replacement')
        assert target.read_bytes()==b'old'
    assert target.read_bytes()==b'complete replacement'
    assert not list(tmp_path.glob('.release-*'))
