"""Tests for agent_loop.py — _detect_admin_intent and _compute_final_metrics.
Uses mock imports to avoid loading the full app stack."""

import sys
from unittest.mock import MagicMock

# Mock heavy dependencies before importing
for mod in [
    'sqlalchemy', 'sqlalchemy.orm', 'sqlalchemy.ext', 'sqlalchemy.ext.declarative',
    'sqlalchemy.ext.hybrid', 'sqlalchemy.sql', 'sqlalchemy.sql.expression',
    'src.database', 'src.endpoint_resolver',
    'src.agent_tools',
    'core.models', 'core.database',
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

from src.agent_loop import (
    _compute_final_metrics,
    _detect_admin_intent,
    _looks_like_completed_tool_round,
)
import src.agent_loop as agent_loop


# ---------------------------------------------------------------------------
# _detect_admin_intent
# ---------------------------------------------------------------------------

class TestDetectAdminIntent:
    """Test admin-intent detection from the last user message."""

    def _msgs(self, text: str):
        """Helper: wrap text in a minimal messages list."""
        return [{"role": "user", "content": text}]

    # --- Should detect admin intent ---

    def test_add_endpoint(self):
        assert _detect_admin_intent(self._msgs("add a new endpoint")) is True

    def test_create_endpoint(self):
        assert _detect_admin_intent(self._msgs("create endpoint for openai")) is True

    def test_manage_sessions(self):
        assert _detect_admin_intent(self._msgs("list all sessions")) is True

    def test_rename_session(self):
        assert _detect_admin_intent(self._msgs("rename this session")) is True

    def test_archive_session(self):
        assert _detect_admin_intent(self._msgs("archive old sessions")) is True

    def test_configure_settings(self):
        assert _detect_admin_intent(self._msgs("configure my settings")) is True

    def test_mcp_server(self):
        assert _detect_admin_intent(self._msgs("add an MCP server")) is True

    def test_api_key(self):
        assert _detect_admin_intent(self._msgs("update the API key")) is True

    def test_list_models(self):
        assert _detect_admin_intent(self._msgs("list models available")) is True

    def test_switch_model(self):
        assert _detect_admin_intent(self._msgs("switch model to gpt-4")) is True

    def test_manage_skills(self):
        assert _detect_admin_intent(self._msgs("show me my skills")) is True

    def test_schedule_task(self):
        assert _detect_admin_intent(self._msgs("schedule a cron task")) is True

    def test_case_insensitive(self):
        assert _detect_admin_intent(self._msgs("MANAGE SESSIONS")) is True

    # --- Should NOT detect admin intent ---

    def test_hello(self):
        assert _detect_admin_intent(self._msgs("hello")) is False

    def test_write_code(self):
        assert _detect_admin_intent(self._msgs("write some python code")) is False

    def test_explain_concept(self):
        assert _detect_admin_intent(self._msgs("explain how transformers work")) is False

    def test_general_question(self):
        assert _detect_admin_intent(self._msgs("what is the capital of France?")) is False

    # --- Edge cases ---

    def test_empty_messages(self):
        assert _detect_admin_intent([]) is False

    def test_no_user_message(self):
        assert _detect_admin_intent([{"role": "assistant", "content": "hi"}]) is False

    def test_multimodal_content(self):
        """Content as a list of blocks (vision messages)."""
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": "rename this session please"},
        ]}]
        assert _detect_admin_intent(msgs) is True

    def test_multimodal_no_admin(self):
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": "describe this image"},
        ]}]
        assert _detect_admin_intent(msgs) is False

    def test_uses_last_user_message(self):
        """Should check only the last user message."""
        msgs = [
            {"role": "user", "content": "rename this session"},
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "thanks, now just say hello"},
        ]
        assert _detect_admin_intent(msgs) is False


# ---------------------------------------------------------------------------
# _compute_final_metrics
# ---------------------------------------------------------------------------

class TestComputeFinalMetrics:
    """Test metric computation with real and estimated usage."""

    def _base_args(self, **overrides):
        defaults = dict(
            messages=[{"role": "user", "content": "hello world"}],
            full_response="This is a test response.",
            total_duration=2.0,
            time_to_first_token=0.5,
            context_length=8192,
            real_input_tokens=100,
            real_output_tokens=50,
            has_real_usage=True,
            tool_events=[],
            round_texts=[],
            model="test-model",
            last_round_input_tokens=0,
            prep_timings=None,
        )
        defaults.update(overrides)
        return defaults

    def test_real_usage_tokens(self):
        m = _compute_final_metrics(**self._base_args())
        assert m["input_tokens"] == 100
        assert m["output_tokens"] == 50
        assert m["total_tokens"] == 150
        assert m["usage_source"] == "real"

    def test_estimated_usage_tokens(self):
        m = _compute_final_metrics(**self._base_args(
            has_real_usage=False,
            real_input_tokens=0,
            real_output_tokens=0,
        ))
        # Estimated: len("hello world\n") // 4 = 3
        assert m["input_tokens"] == 3
        assert m["usage_source"] == "estimated"

    def test_tps_calculation(self):
        m = _compute_final_metrics(**self._base_args(
            real_output_tokens=100,
            total_duration=2.0,
        ))
        assert m["tokens_per_second"] == 50.0

    def test_tps_zero_duration(self):
        m = _compute_final_metrics(**self._base_args(total_duration=0.0))
        assert m["tokens_per_second"] == 0

    def test_context_percent(self):
        m = _compute_final_metrics(**self._base_args(
            real_input_tokens=4096,
            context_length=8192,
        ))
        assert m["context_percent"] == 50.0

    def test_context_percent_capped_at_100(self):
        m = _compute_final_metrics(**self._base_args(
            real_input_tokens=10000,
            context_length=8192,
        ))
        assert m["context_percent"] == 100.0

    def test_context_percent_zero_context_length(self):
        m = _compute_final_metrics(**self._base_args(context_length=0))
        assert m["context_percent"] == 0

    def test_last_round_input_tokens_used_for_context_pct(self):
        """When last_round_input_tokens > 0, it should be used for context %."""
        m = _compute_final_metrics(**self._base_args(
            real_input_tokens=100,
            last_round_input_tokens=4096,
            context_length=8192,
        ))
        assert m["context_percent"] == 50.0

    def test_response_time(self):
        m = _compute_final_metrics(**self._base_args(total_duration=3.456))
        assert m["response_time"] == 3.46

    def test_time_to_first_token(self):
        m = _compute_final_metrics(**self._base_args(time_to_first_token=0.123))
        assert m["time_to_first_token"] == 0.12

    def test_time_to_first_token_none(self):
        m = _compute_final_metrics(**self._base_args(time_to_first_token=None))
        assert m["time_to_first_token"] == 0

    def test_model_returned(self):
        m = _compute_final_metrics(**self._base_args(model="gpt-4o"))
        assert m["model"] == "gpt-4o"

    def test_prep_timings_included(self):
        m = _compute_final_metrics(**self._base_args(
            time_to_first_token=1.25,
            prep_timings={"request_setup": 0.2, "tool_selection": 0.3, "prompt_build": 0.15},
        ))
        assert m["agent_prep_time"] == 0.65
        assert m["agent_model_wait_time"] == 0.6
        assert m["agent_prep_breakdown"] == {
            "request_setup": 0.2,
            "tool_selection": 0.3,
            "prompt_build": 0.15,
        }

    def test_tool_events_included(self):
        events = [{"tool": "bash", "duration": 1.0}]
        texts = ["round 1 text"]
        m = _compute_final_metrics(**self._base_args(
            tool_events=events,
            round_texts=texts,
        ))
        assert m["tool_events"] == events
        assert m["round_texts"] == texts

    def test_no_tool_events_excluded(self):
        m = _compute_final_metrics(**self._base_args(tool_events=[], round_texts=[]))
        assert "tool_events" not in m
        assert "round_texts" not in m


class TestCompletedToolRound:
    def test_accepts_final_vietnamese_summary(self):
        text = (
            "Xong rồi. Game đã chạy ổn định trong 9 giây, các file đã được "
            "cập nhật và bước kiểm tra cuối cùng đã thành công."
        )
        assert _looks_like_completed_tool_round(text) is True

    def test_accepts_final_english_summary(self):
        text = (
            "Done. The implementation is complete, the final verification "
            "passed, and the requested files are now in place."
        )
        assert _looks_like_completed_tool_round(text) is True

    def test_rejects_short_or_continuing_claim(self):
        assert _looks_like_completed_tool_round("Xong rồi.") is False
        assert _looks_like_completed_tool_round(
            "Xong rồi phần đọc code. Giờ tôi sẽ sửa file và chạy toàn bộ kiểm tra tiếp theo."
        ) is False


# ---------------------------------------------------------------------------
# Rule gating (prompt-bloat reduction for context-limited local models)
# ---------------------------------------------------------------------------

class TestRuleGating:
    """Domain-specific rule lines are dropped when their tools aren't selected,
    but core behavioural rules and full reconstruction are preserved."""

    def _all_tools(self):
        return (
            agent_loop._RG_EMAIL | agent_loop._RG_CALENDAR | agent_loop._RG_NOTES
            | agent_loop._RG_TASKS | agent_loop._RG_MEMORY | agent_loop._RG_RESEARCH
            | agent_loop._RG_UICTRL | agent_loop._RG_COOKBOOK | agent_loop._RG_SESSIONS
            | agent_loop._RG_DOCS | agent_loop._RG_LINKABLE
        )

    def test_fenced_identity_with_all_tools(self):
        out = agent_loop._gate_rules(
            agent_loop._AGENT_RULES, agent_loop._FENCED_RULE_GATES, self._all_tools()
        )
        assert out == agent_loop._AGENT_RULES

    def test_api_identity_with_all_tools(self):
        out = agent_loop._gate_rules(
            agent_loop._API_AGENT_RULES, agent_loop._API_RULE_GATES, self._all_tools()
        )
        assert out == agent_loop._API_AGENT_RULES

    def test_gate_map_lengths_match_units(self):
        assert len(agent_loop._split_rule_units(agent_loop._AGENT_RULES)) == len(
            agent_loop._FENCED_RULE_GATES
        )
        assert len(agent_loop._split_rule_units(agent_loop._API_AGENT_RULES)) == len(
            agent_loop._API_RULE_GATES
        )

    def test_coding_request_drops_email_and_cookbook(self):
        coding = {"bash", "python", "read_file", "write_file", "edit_file"}
        fenced = agent_loop._gate_rules(
            agent_loop._AGENT_RULES, agent_loop._FENCED_RULE_GATES, coding
        )
        api = agent_loop._gate_rules(
            agent_loop._API_AGENT_RULES, agent_loop._API_RULE_GATES, coding
        )
        # Domain noise removed
        assert "Email UIDs" not in fenced
        assert "Cookbook" not in api
        # Substantially smaller
        assert len(fenced) < len(agent_loop._AGENT_RULES) * 0.6
        assert len(api) < len(agent_loop._API_AGENT_RULES) * 0.6

    def test_core_act_directive_always_kept(self):
        for tools in ({"bash"}, set(), self._all_tools()):
            fenced = agent_loop._gate_rules(
                agent_loop._AGENT_RULES, agent_loop._FENCED_RULE_GATES, tools
            )
            api = agent_loop._gate_rules(
                agent_loop._API_AGENT_RULES, agent_loop._API_RULE_GATES, tools
            )
            assert "ACT, DON'T NARRATE" in fenced
            assert "Act, don't narrate" in api

    def test_email_tools_keep_email_rules(self):
        out = agent_loop._gate_rules(
            agent_loop._AGENT_RULES, agent_loop._FENCED_RULE_GATES,
            {"list_emails", "read_email"},
        )
        assert "Email UIDs" in out

    def test_length_mismatch_falls_back_to_full(self):
        # Wrong-length gate map must not silently truncate rules.
        out = agent_loop._gate_rules(agent_loop._AGENT_RULES, [None], {"bash"})
        assert out == agent_loop._AGENT_RULES
