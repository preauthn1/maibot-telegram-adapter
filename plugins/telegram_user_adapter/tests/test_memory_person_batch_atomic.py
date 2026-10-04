"""Actual person helper and SQLite: second-person failure rolls back all claims."""
import sqlite3
from types import SimpleNamespace
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services.ingest_service import MemoryIngestService


def test_person_batch_atomic(tmp_path):
    s = MetadataStore(data_dir=tmp_path); s.connect()
    try:
        p = s.add_paragraph('synthetic batch evidence')
        s._conn.execute("CREATE TRIGGER fail_second AFTER INSERT ON fact_claims WHEN NEW.scope_id='person-b' BEGIN SELECT RAISE(FAIL, 'synthetic'); END")
        s._conn.commit()
        def snapshot():
            return {t: [tuple(r) for r in s._conn.execute(f'SELECT * FROM {t} ORDER BY rowid')]
                    for t in ('fact_claims', 'fact_evidence', 'fact_transitions')}
        before = snapshot()
        args = dict(paragraph_hash=p, content='synthetic fact', person_ids=['person-a', 'person-b'], metadata={}, timestamp=None)
        with pytest.raises(sqlite3.IntegrityError):
            MemoryIngestService._write_person_fact_claims(SimpleNamespace(metadata_store=s), **args)
        assert not s._conn.in_transaction
        assert snapshot() == before
        s._conn.execute('DROP TRIGGER fail_second'); s._conn.commit()
        s.close(); s.connect()
        assert snapshot() == before
        ids = MemoryIngestService._write_person_fact_claims(SimpleNamespace(metadata_store=s), **args)
        s.close(); s.connect()
        assert len(ids) == 2
        assert {s.get_fact_claim(i)['scope_id'] for i in ids} == {'person-a', 'person-b'}
        assert s._conn.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        s.close()
