"""Real SQLite supersession rollback and recovery, including existing evidence."""
import sqlite3
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore


@pytest.mark.parametrize('failure_table', ['fact_transitions', 'fact_evidence'])
def test_supersession_rolls_back_all_tables(tmp_path, failure_table):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        p = store.add_paragraph('合成旧证据')
        q = store.add_paragraph('合成新证据')
        common = dict(scope_type='person', scope_id='synthetic', fact_key='favorite',
                      cardinality='single', confidence=0.75, evidence_type='paragraph')
        old = store.upsert_fact_claim(**common, value_text='旧值', evidence_id=p)
        def snapshot():
            return {t: [tuple(r) for r in store._conn.execute(f'SELECT * FROM {t} ORDER BY rowid')]
                    for t in ('fact_claims', 'fact_evidence', 'fact_transitions')}
        before = snapshot()
        assert before['fact_evidence']
        store._conn.execute(f"CREATE TRIGGER fail_supersede AFTER INSERT ON {failure_table} BEGIN SELECT RAISE(FAIL, 'synthetic'); END")
        store._conn.commit()
        request = dict(common, value_text='新值', evidence_id=q,
                       supersedes_claim_ids=[old['claim_id']])
        with pytest.raises(sqlite3.IntegrityError):
            store.upsert_fact_claim(**request)
        assert not store._conn.in_transaction
        assert snapshot() == before
        store._conn.execute('DROP TRIGGER fail_supersede'); store._conn.commit()
        store.close(); store.connect()
        assert snapshot() == before
        new = store.upsert_fact_claim(**request)
        store.close(); store.connect()
        assert store.get_fact_claim(old['claim_id'])['status'] == 'superseded'
        assert store.get_fact_claim(new['claim_id'])['status'] == 'active'
        assert store._conn.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        store.close()
