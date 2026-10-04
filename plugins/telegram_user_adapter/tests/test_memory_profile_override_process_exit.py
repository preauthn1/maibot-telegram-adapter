"""Manual override changes survive only a completed outer commit."""
import subprocess
import sys
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore

@pytest.mark.parametrize('operation', ['replace', 'clear'])
@pytest.mark.parametrize('phase', ['before', 'after'])
def test_override_process_exit(tmp_path, operation, phase):
    s = MetadataStore(data_dir=tmp_path); s.connect()
    original = s.set_person_profile_override('synthetic', 'original', updated_at=10)
    s.close()
    code = '''import os,sys
from src.A_memorix.core.storage.metadata_store import MetadataStore
s=MetadataStore(data_dir=sys.argv[1]);s.connect()
with s.transaction(immediate=True):
    if sys.argv[2]=='replace':
        result=s.set_person_profile_override('synthetic','replacement',updated_at=20)
        assert result['override_text']=='replacement'
    else:
        assert s.delete_person_profile_override('synthetic')
        assert s.get_person_profile_override('synthetic') is None
    if sys.argv[3]=='before': os._exit(73)
os._exit(74)
'''
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path), operation, phase],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    assert result.returncode == (73 if phase == 'before' else 74)
    s.connect()
    try:
        actual = s.get_person_profile_override('synthetic')
        if phase == 'before':
            assert actual == original
        elif operation == 'clear':
            assert actual is None
        else:
            expected = dict(original, override_text='replacement', updated_at=20)
            assert actual == expected
        conn = s._conn
        assert conn is not None
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        s.close()
