from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_fact_extraction_only_uses_user_statement_as_fact_source():
    from core.database.memory import MemoryStore

    store = MemoryStore("memory-user")
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content='{"facts": []}')

    with patch.object(store, "facts_to_text", return_value=""):
        with patch.object(store, "write_facts"):
            await store.extract_facts_from_turn(
                user_message="我偏好低風險資產。",
                assistant_message="你持有大量高風險部位。",
                turn_index=1,
                llm=llm,
            )

    prompt = llm.invoke.call_args.args[0][0].content
    assert "我偏好低風險資產。" in prompt
    assert "你持有大量高風險部位。" not in prompt


@pytest.mark.asyncio
async def test_fact_extraction_only_persists_valid_explicit_facts_from_current_turn():
    from core.database.memory import MemoryStore

    store = MemoryStore("memory-user")
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(
        content=(
            '{"facts": ['
            '{"key": "risk_preference", "value": "low", "source_turn": 3, '
            '"confidence": "high"}, '
            '{"key": "inferred_holding", "value": "large", "source_turn": 3, '
            '"confidence": "medium"}, '
            '{"key": "not-valid", "value": "x", "source_turn": 3, '
            '"confidence": "high"}, '
            '{"key": "old_turn", "value": "x", "source_turn": 2, '
            '"confidence": "high"}'
            "]}"
        )
    )

    with patch.object(store, "facts_to_text", return_value=""):
        with patch.object(store, "write_facts") as write_facts:
            await store.extract_facts_from_turn(
                user_message="我偏好低風險資產。",
                assistant_message="",
                turn_index=3,
                llm=llm,
            )

    write_facts.assert_called_once_with(
        [
            {
                "key": "risk_preference",
                "value": "low",
                "source_turn": 3,
                "confidence": "high",
            }
        ]
    )
