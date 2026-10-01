"""Validate saved review evidence without claiming to contact the reviewer."""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import os
from pathlib import Path
import tempfile

from .storage import digest, read_json


def verified_receipt(path, paper, token):
    """Read-only binding check. A local receipt is not a fresh website check."""
    receipt = read_json(path)
    if receipt.get('submission_confirmed') is not True:
        raise ValueError('Review submission has not been confirmed')
    if receipt.get('destination', '').rstrip('/') != 'https://paperreview.ai':
        raise ValueError('Unexpected review destination')
    if receipt.get('venue') != 'ICLR':
        raise ValueError('Unexpected review standard')
    if not token or token.startswith('sk-'):
        raise ValueError('Missing or invalid review token')
    if receipt.get('paper_sha256') != digest(paper):
        raise ValueError('Review receipt belongs to a different PDF')
    if receipt.get('token_sha256') != hashlib.sha256(token.encode()).hexdigest():
        raise ValueError('Review token does not match the saved receipt')
    timestamp = datetime.fromisoformat(receipt.get('submitted_at', ''))
    if timestamp.tzinfo is None:
        raise ValueError('Submission time must include a timezone')
    if receipt.get('review_status') not in {'pending', 'completed', 'failed'}:
        raise ValueError('Unknown review status')
    return receipt


@contextmanager
def atomic_archive(target):
    """Keep the previous archive intact if building its replacement fails."""
    target = Path(target)
    fd, name = tempfile.mkstemp(prefix='.release-', suffix='.zip', dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        yield temporary
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
