"""真实规范化与写入适配器组合；底层ingest替身，不实际改记忆。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.A_memorix.core.runtime.services.feedback_correction_service import MemoryFeedbackCorrectionService as Service

@pytest.mark.parametrize('score',[0,0.5,1])
def test_normalized_score_reaches_ingest_unchanged(score):
    decision=Service._normalize_feedback_decision({'decision':'correct','confidence':1.0,'corrected_relations':[{'subject':'合成甲','predicate':'喜欢','object':'合成乙','confidence':score}]},hit_hashes=[])
    ingest=AsyncMock(return_value={'success':True,'stored_ids':['synthetic-new']})
    asyncio.run(Service._ingest_feedback_relations(SimpleNamespace(ingest_text=ingest, _chat_source=lambda s:'synthetic:'+s),query_tool_id='synthetic-query',session_id='synthetic-session',relation_hashes=['synthetic-old'],corrected_relations=decision['corrected_relations']))
    ingest.assert_awaited_once()
    assert ingest.await_args.kwargs['relations'][0]['confidence']==float(score)
    assert ingest.await_args.kwargs['chat_id']=='synthetic-session'
