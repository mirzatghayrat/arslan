"""Frozen sources fail loudly when their provenance or contents are damaged."""
import json

import pytest

from tests.server import folder_revision_data as data


@pytest.mark.parametrize('damage', ('manifest', 'source', 'missing'))
def test_frozen_sources_reject_damage(damage, tmp_path, monkeypatch):
    manifest = (data.DATA / 'manifest.json').read_bytes()
    entries = json.loads(manifest)[data.MAIN]
    for digest in entries.values():
        (tmp_path / (digest + '.txt')).write_bytes((data.DATA / (digest + '.txt')).read_bytes())
    (tmp_path / 'manifest.json').write_bytes(manifest)
    source = tmp_path / (entries['shell_grammar'] + '.txt')
    if damage == 'manifest':
        (tmp_path / 'manifest.json').write_bytes(manifest + b' ')
    elif damage == 'source':
        source.write_bytes(source.read_bytes() + b'\n')
    else:
        source.unlink()
    monkeypatch.setattr(data, 'DATA', tmp_path)
    with pytest.raises(FileNotFoundError if damage == 'missing' else AssertionError,
                       match=None if damage == 'missing' else 'hash mismatch'):
        data.sources(data.MAIN)


def test_all_frozen_revisions_load_their_own_modules(monkeypatch):
    manifest = json.loads((data.DATA / 'manifest.json').read_bytes())
    for revision, entries in manifest.items():
        policy = data.load_revision(revision, monkeypatch)
        assert revision in policy.shell_text.__name__
        if 'shell_grammar' in entries:
            assert revision in policy.shell_grammar.__name__
        assert policy.assess('echo ok').level == 'run'
