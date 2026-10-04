"""Actual profile refresh and SQLite snapshot persistence; retrieval/classification synthetic."""
import asyncio
import pytest
from typing import Any
from unittest.mock import AsyncMock, Mock
from types import SimpleNamespace
from src.maisaka.chat_loop_service import MaisakaChatLoopService
from src.llm_models.model_client.openai_client import _convert_messages
from src.services import memory_service as service_module
from src.maisaka.memory import person_profile as planner
from src.maisaka import reasoning_engine as engine_module
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.utils.person_profile_service import PersonProfileService


def test_sqlite_override_reaches_openai_messages(tmp_path, monkeypatch):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        svc = PersonProfileService(store)
        monkeypatch.setattr(svc, 'get_person_aliases', lambda pid: (['Synthetic'], 'Synthetic', []))
        monkeypatch.setattr(svc, '_collect_relation_evidence', lambda *a, **kw: [])
        monkeypatch.setattr(svc, '_collect_vector_evidence', AsyncMock(return_value=[]))
        buckets = {k: [] for k in ('identity_settings', 'relationship_settings', 'stable_facts',
                                  'interaction_preferences', 'recent_interactions', 'uncertain_notes')}
        classifier = AsyncMock(return_value=buckets)
        monkeypatch.setattr(svc, '_classify_profile_evidence', classifier)
        monkeypatch.setattr(planner, 'global_config', SimpleNamespace(a_memorix=SimpleNamespace(
            integration=SimpleNamespace(enable_person_profile_injection=True, person_profile_injection_max_profiles=3))))
        candidate = SimpleNamespace(person_id='synthetic', person_name='Synthetic', user_id='synthetic-user')
        monkeypatch.setattr(planner, 'collect_person_profile_candidates', lambda *a, **kw: [candidate])
        calls = []
        async def host_invoke(component_name, args):
            assert component_name == 'memory_profile_admin'
            calls.append(args)
            assert args['action'] == 'query'
            payload = await svc.query_person_profile(person_id=args['person_id'])
            return SimpleNamespace(payload={'result': payload})
        monkeypatch.setattr(service_module, 'a_memorix_host_service', SimpleNamespace(invoke=host_invoke))
        monkeypatch.setattr(planner, 'memory_service', service_module.MemoryService())
        engine = object.__new__(engine_module.MaisakaReasoningEngine)
        history = []
        engine._runtime = SimpleNamespace(session_id='synthetic-session', log_prefix='synthetic',
            _chat_history=history, _update_stage_status=Mock(),
            build_focus_tail_user_messages=lambda: ['SYNTHETIC_FOCUS'])
        heuristic = AsyncMock(return_value='SYNTHETIC_HEURISTIC')
        monkeypatch.setattr(engine_module, 'heuristic_memory_injector', SimpleNamespace(build_injection_message=heuristic))
        monkeypatch.setattr(engine_module, 'resolve_enable_visual_planner', lambda: True)
        monkeypatch.setattr(engine_module, 'logger', Mock())
        tools = [{'synthetic': 'tool'}]
        monkeypatch.setattr(engine, '_build_action_tool_definitions', AsyncMock(return_value=(tools, 'SYNTHETIC_REMINDER')))
        monkeypatch.setattr(engine, '_refresh_jargon_reference_message', lambda: None)
        response = object()
        assembler = object.__new__(MaisakaChatLoopService)
        monkeypatch.setattr(assembler, '_build_current_chat_attention_tail_message', lambda: 'SYNTHETIC_ATTENTION')
        monkeypatch.setattr(assembler, '_build_current_time_user_message', lambda: 'SYNTHETIC_TIME')
        wires = []
        async def assemble(history_arg, **kwargs):
            items = assembler._build_request_messages(history_arg, enable_visual_message=False,
                injected_user_messages=kwargs['injected_user_messages'],
                tail_user_messages=kwargs['tail_user_messages'], system_prompt='SYNTHETIC_SYSTEM')
            wires.append(_convert_messages(items))
            return response
        request = AsyncMock(side_effect=assemble)
        flags = []
        loop = SimpleNamespace(chat_loop_step=request, set_interrupt_flag=flags.append)
        engine._runtime._chat_loop_service = loop
        engine._runtime._max_context_size = 12
        engine._runtime._bind_planner_interrupt_flag = Mock()
        engine._runtime._unbind_planner_interrupt_flag = Mock()
        engine._active_logical_turn_id = 'synthetic-turn'
        def inject():
            state = SimpleNamespace()
            asyncio.run(engine._run_planner_request(trigger_message=object(), source_messages=[],
                round_index=0, round_text='synthetic', state=state))
            kwargs = request.await_args.kwargs
            assert request.await_args.args == (history,)
            assert kwargs['max_context_size'] == 12
            assert kwargs['logical_turn_id'] == 'synthetic-turn'
            assert flags[-1] is None
            flag = flags[-2]
            assert isinstance(flag, asyncio.Event)
            engine._runtime._bind_planner_interrupt_flag.assert_called_with(flag)
            engine._runtime._unbind_planner_interrupt_flag.assert_called_with(flag, interrupted=False)
            assert kwargs['tail_user_messages'] == ['SYNTHETIC_FOCUS']
            assert kwargs['tool_definitions'] is tools
            assert history == []
            assert state.response is response
            assert state.action_tool_count == 1
            result = kwargs['injected_user_messages']
            assert len(result) == 3
            assert result[:2] == ['SYNTHETIC_REMINDER', 'SYNTHETIC_HEURISTIC']
            wire = wires[-1]
            assert wire == [
                {'role': 'system', 'content': 'SYNTHETIC_SYSTEM'},
                *({'role': 'user', 'content': text} for text in result),
                {'role': 'user', 'content': 'SYNTHETIC_TIME'},
                {'role': 'user', 'content': 'SYNTHETIC_FOCUS'},
                {'role': 'user', 'content': 'SYNTHETIC_ATTENTION'},
            ]
            return [wire[3]['content']]
        common: dict[str, Any] = dict(scope_type='person', scope_id='synthetic', fact_key='favorite',
                      cardinality='single', authority='manual', stability='stable')
        old = store.upsert_fact_claim(**common, value_text='SYNTHETIC_OLD_VALUE')
        first = asyncio.run(svc.query_person_profile(person_id='synthetic', force_refresh=True))
        assert first['success'] and 'SYNTHETIC_OLD_VALUE' in first['profile_text']
        before = store.get_latest_person_profile_snapshot('synthetic')
        store.set_person_profile_override('other', 'SYNTHETIC_OTHER_OVERRIDE')
        store.set_person_profile_override('synthetic', 'SYNTHETIC_MANUAL_OVERRIDE')
        store.close(); store.connect()
        manual = asyncio.run(svc.query_person_profile(person_id='synthetic'))
        assert manual['from_cache'] and manual['has_manual_override']
        assert manual['profile_source'] == 'manual_override'
        assert manual['profile_text'] == 'SYNTHETIC_MANUAL_OVERRIDE'
        assert manual['auto_profile_text'] == first['profile_text']
        messages = inject()
        assert len(messages) == 1
        block = messages[0]
        assert 'SYNTHETIC_MANUAL_OVERRIDE' in block
        assert 'SYNTHETIC_OLD_VALUE' not in block
        assert 'SYNTHETIC_OTHER_OVERRIDE' not in block
        assert store.get_latest_person_profile_snapshot('synthetic') == before
        store.set_person_profile_override('synthetic', '')
        store.close(); store.connect()
        restored = asyncio.run(svc.query_person_profile(person_id='synthetic'))
        assert restored['from_cache'] and not restored['has_manual_override']
        assert restored['profile_source'] == 'auto_snapshot'
        assert restored['profile_text'] == first['profile_text']
        assert store.get_latest_person_profile_snapshot('synthetic') == before
        restored_messages = inject()
        assert len(restored_messages) == 1
        assert 'SYNTHETIC_OLD_VALUE' in restored_messages[0]
        assert 'SYNTHETIC_MANUAL_OVERRIDE' not in restored_messages[0]
        assert 'SYNTHETIC_OTHER_OVERRIDE' not in restored_messages[0]
        assert store.get_latest_person_profile_snapshot('synthetic') == before
        assert len(calls) == 2
        assert all(call == dict(action='query', person_id='synthetic', limit=planner.PROFILE_QUERY_LIMIT) for call in calls)
        assert heuristic.await_count == 2
        heuristic.assert_awaited_with(session_id='synthetic-session')
        assert classifier.await_count == 1
    finally:
        store.close()
