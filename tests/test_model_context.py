"""Tests for model_context.py — local endpoint detection, token estimation, known model lookup."""

import pytest

import src.model_context as model_context
from src.model_context import (
    _apply_provider_context_limit,
    _is_local_endpoint,
    _lookup_known,
    estimate_tokens,
)


class TestIsLocalEndpoint:
    def test_localhost(self):
        assert _is_local_endpoint("http://localhost:5000/v1/chat/completions") is True

    def test_loopback_ipv4(self):
        assert _is_local_endpoint("http://127.0.0.1:8080/v1/chat/completions") is True

    def test_private_192_168(self):
        assert _is_local_endpoint("http://192.168.1.1:11434/v1/chat/completions") is True

    def test_private_10(self):
        assert _is_local_endpoint("http://10.0.0.5:8000/v1/chat/completions") is True

    def test_tailscale_100(self):
        # 100.64.0.0/10 is the CGNAT range Tailscale uses.
        assert _is_local_endpoint("http://100.64.0.1:5000/v1/chat/completions") is True

    def test_openai_is_remote(self):
        assert _is_local_endpoint("https://api.openai.com/v1/chat/completions") is False

    def test_anthropic_is_remote(self):
        assert _is_local_endpoint("https://api.anthropic.com/v1/messages") is False

    def test_empty_url(self):
        assert _is_local_endpoint("") is False

    def test_malformed_url(self):
        assert _is_local_endpoint("not-a-url") is False


class TestEstimateTokens:
    def test_empty_list(self):
        assert estimate_tokens([]) == 0

    def test_single_short_message(self):
        messages = [{"role": "user", "content": "Hello"}]
        tokens = estimate_tokens(messages)
        # 4 overhead + int(5 * 0.3) = 4 + 1 = 5
        assert tokens == 5

    def test_multiple_messages(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi there"},
        ]
        tokens = estimate_tokens(messages)
        assert tokens > 0
        # Each message adds 4 overhead + chars * 0.3
        assert tokens == 4 + int(16 * 0.3) + 4 + int(8 * 0.3)

    def test_multimodal_content_list(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image"},
                    {"type": "image_url", "image_url": {"url": "data:..."}},
                ],
            }
        ]
        tokens = estimate_tokens(messages)
        # 4 overhead + int(19 * 0.3) for the text item; image_url is ignored
        assert tokens == 4 + int(19 * 0.3)

    def test_missing_content_key(self):
        messages = [{"role": "assistant"}]
        tokens = estimate_tokens(messages)
        # 4 overhead + 0 content
        assert tokens == 4

    def test_scales_with_length(self):
        short = estimate_tokens([{"role": "user", "content": "short"}])
        long_text = "a" * 10000
        long = estimate_tokens([{"role": "user", "content": long_text}])
        assert long > short * 10


class TestLookupKnown:
    def test_claude_sonnet(self):
        assert _lookup_known("claude-sonnet-4-5") == 200000

    @pytest.mark.parametrize(
        "model",
        [
            "claude-opus-4-6",
            "claude-opus-4-7",
            "claude-opus-4-8",
            "claude-opus-4.8",
        ],
    )
    def test_claude_opus_long_context(self, model):
        assert _lookup_known(model) == 1000000

    def test_claude_sonnet_46_long_context(self):
        assert _lookup_known("claude-sonnet-4.6") == 1000000

    @pytest.mark.parametrize("model", ["gpt-5.4", "gpt-5.5"])
    def test_latest_gpt_long_context(self, model):
        assert _lookup_known(model) == 1050000

    @pytest.mark.parametrize(
        "model",
        ["deepseek-v4-pro", "deepseek-v4-flash", "deepseek-v4-flash-search"],
    )
    def test_deepseek_v4_long_context(self, model):
        assert _lookup_known(model) == 1000000

    @pytest.mark.parametrize(
        "model",
        ["gemini-3.1-pro", "gemini-3-flash", "gemini-3.5-flash"],
    )
    def test_gemini_3_long_context(self, model):
        assert _lookup_known(model) == 1048576

    def test_gpt4o(self):
        assert _lookup_known("gpt-4o") == 128000

    def test_deepseek_r1(self):
        assert _lookup_known("deepseek-r1") == 64000

    def test_gemini_pro(self):
        assert _lookup_known("gemini-2.5-pro") == 1048576

    def test_unknown_model(self):
        assert _lookup_known("totally-unknown-model-xyz") is None

    def test_namespaced_model(self):
        """Models prefixed with provider/ should still match."""
        result = _lookup_known("openrouter/deepseek-r1")
        assert result == 64000

    def test_model_with_tag(self):
        """Models with :free or :extended suffixes should still match."""
        result = _lookup_known("deepseek-r1:free")
        assert result == 64000


def test_query_context_prefers_persisted_per_model_metadata(monkeypatch):
    monkeypatch.setattr(model_context, "_configured_model_context", lambda url, model: 262144)
    monkeypatch.setattr(model_context, "_configured_endpoint_kind", lambda url: "local")

    def fail_if_queried(*args, **kwargs):
        raise AssertionError("network should not be queried when metadata is persisted")

    monkeypatch.setattr(model_context.httpx, "get", fail_if_queried)
    assert model_context._query_context_length(
        "http://127.0.0.1:1234/v1/chat/completions",
        "qwen/qwen3.6-35b-a3b",
    ) == 262144


def test_microsoft_foundry_caps_claude_opus_48():
    assert _apply_provider_context_limit(
        "https://example.services.ai.azure.com/anthropic/v1/messages",
        "claude-opus-4-8",
        1000000,
    ) == 200000


def test_generic_proxy_keeps_claude_opus_48_long_context():
    assert _apply_provider_context_limit(
        "https://gateway.example/v1/chat/completions",
        "claude-opus-4-8",
        1000000,
    ) == 1000000
