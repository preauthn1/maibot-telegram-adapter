"""Actual person helper and SQLite: second-person failure rolls back all claims."""
import sqlite3
from types import SimpleNamespace
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services.ingest_service import MemoryIngestService


def test_person_existing_reinforcement_rollback(tmp_path):
    s = MetadataStore(data_dir=tmp_path); s.connect()
    try:
        p = s.add_paragraph('synthetic batch evidence')
        origin = s.add_paragraph('synthetic original evidence')
        original = s.upsert_fact_claim(scope_type='person', scope_id='person-a',
            fact_key='synthetic-key', value_text='synthetic fact', confidence=0.25,
            authority='manual', evidence_type='paragraph', evidence_id=origin)
        s._conn.execute("CREATE TRIGGER fail_second AFTER INSERT ON fact_claims WHEN NEW.scope_id='person-b' BEGIN SELECT RAISE(FAIL, 'synthetic'); END")
        s._conn.commit()
        def snapshot():
            return {t: [tuple(r) for r in s._conn.execute(f'SELECT * FROM {t} ORDER BY rowid')]
                    for t in ('fact_claims', 'fact_evidence', 'fact_transitions')}
        before = snapshot()
        args = dict(paragraph_hash=p, content='synthetic fact', person_ids=['person-a', 'person-b'], metadata={'fact_claim': {'trust': 'manual_confirmed', 'fact_key': 'synthetic-key', 'confidence': 0.9}}, timestamp=None)
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
        assert ids[0] == original['claim_id']
        assert s.get_fact_claim(ids[0])['confidence'] == 0.9
        assert s._conn.execute('SELECT count(*) FROM fact_evidence WHERE claim_id=?', (ids[0],)).fetchone()[0] == 2
        assert {s.get_fact_claim(i)['scope_id'] for i in ids} == {'person-a', 'person-b'}
        assert s._conn.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        s.close()
