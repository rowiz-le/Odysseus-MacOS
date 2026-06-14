"""Tests for context_compactor.py — constants and prompt templates.
Uses mock imports to avoid loading the full app stack."""

import asyncio
import sys
from unittest.mock import MagicMock

# Mock heavy dependencies before importing
for mod in [
    'sqlalchemy', 'sqlalchemy.orm', 'sqlalchemy.ext', 'sqlalchemy.ext.declarative',
    'sqlalchemy.ext.hybrid', 'sqlalchemy.sql', 'sqlalchemy.sql.expression',
    'src.database', 'src.endpoint_resolver',
    'core.models', 'core.database',
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

from src.context_compactor import (
    COMPACTION_TIMEOUT_SECONDS,
    COMPACT_THRESHOLD,
    SELF_SUMMARY_SYSTEM_PROMPT,
    SUMMARY_MAX_TOKENS,
)
import src.context_compactor as context_compactor


class TestCompactThreshold:
    def test_value(self):
        assert COMPACT_THRESHOLD == 0.85

    def test_summary_max_tokens(self):
        assert SUMMARY_MAX_TOKENS == 1024

    def test_compaction_timeout_allows_slow_reasoning_models(self):
        assert COMPACTION_TIMEOUT_SECONDS == 120


class TestSelfSummaryPrompt:
    def test_contains_goal_section(self):
        assert "### User Goal" in SELF_SUMMARY_SYSTEM_PROMPT

    def test_contains_what_was_done_section(self):
        assert "### What Was Done" in SELF_SUMMARY_SYSTEM_PROMPT

    def test_contains_current_state_section(self):
        assert "### Current State" in SELF_SUMMARY_SYSTEM_PROMPT

    def test_contains_pending_section(self):
        assert "### Pending / Next Steps" in SELF_SUMMARY_SYSTEM_PROMPT

    def test_contains_key_context_section(self):
        assert "### Key Context" in SELF_SUMMARY_SYSTEM_PROMPT

    def test_count_placeholder(self):
        assert "{count}" in SELF_SUMMARY_SYSTEM_PROMPT

    def test_n_placeholder(self):
        assert "{n}" in SELF_SUMMARY_SYSTEM_PROMPT

    def test_mentions_compactions(self):
        assert "Compactions so far" in SELF_SUMMARY_SYSTEM_PROMPT


def test_failed_auto_compaction_keeps_original_messages(monkeypatch):
    messages = [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "two"},
        {"role": "user", "content": "three"},
        {"role": "assistant", "content": "four"},
    ]

    async def fail_summary(*args, **kwargs):
        raise RuntimeError("upstream timeout")

    monkeypatch.setattr(context_compactor, "get_context_length", lambda *args: 100)
    monkeypatch.setattr(context_compactor, "estimate_tokens", lambda _messages: 90)
    monkeypatch.setattr(context_compactor, "resolve_endpoint", lambda *_args: (None, None, None))
    monkeypatch.setattr(context_compactor, "llm_call_async", fail_summary)

    compacted, context_length, was_compacted = asyncio.run(
        context_compactor.maybe_compact(
            MagicMock(history=[]),
            "https://gateway.example/v1/chat/completions",
            "test-model",
            messages,
        )
    )

    assert compacted == messages
    assert context_length == 100
    assert was_compacted is False
