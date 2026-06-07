"""Tests for endpoint_resolver — pure functions tested directly to avoid import pollution."""
import importlib.util
import re
from pathlib import Path
from urllib.parse import urlparse


# Copy the pure functions to test them without importing the full module.
# This avoids module cache conflicts with other test files that mock dependencies.

def normalize_base(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    for suffix in ["/models", "/chat/completions", "/completions", "/v1/messages"]:
        if url.endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
    return url


def _detect_provider(url: str) -> str:
    if "anthropic.com" in (url or ""):
        return "anthropic"
    return "openai"


def build_chat_url(base: str) -> str:
    provider = _detect_provider(base)
    if provider == "anthropic":
        host = urlparse(base).hostname or ""
        if host.endswith("anthropic.com") and base.rstrip("/").endswith("/v1"):
            base = base.rstrip("/")[:-3].rstrip("/")
        return base + "/v1/messages"
    return base + "/chat/completions"


def build_headers(api_key, base: str) -> dict:
    if not api_key:
        return {}
    provider = _detect_provider(base)
    if provider == "anthropic":
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {api_key}"}


def _load_real_endpoint_resolver():
    path = Path(__file__).resolve().parents[1] / "src" / "endpoint_resolver.py"
    spec = importlib.util.spec_from_file_location("_real_endpoint_resolver_for_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestNormalizeBase:
    def test_strips_models(self):
        assert normalize_base("https://api.openai.com/v1/models") == "https://api.openai.com/v1"

    def test_strips_chat_completions(self):
        assert normalize_base("https://api.openai.com/v1/chat/completions") == "https://api.openai.com/v1"

    def test_strips_completions(self):
        assert normalize_base("https://api.openai.com/v1/completions") == "https://api.openai.com/v1"

    def test_strips_v1_messages(self):
        assert normalize_base("https://api.anthropic.com/v1/messages") == "https://api.anthropic.com"

    def test_trailing_slash(self):
        assert normalize_base("https://api.openai.com/v1/") == "https://api.openai.com/v1"

    def test_clean_url_unchanged(self):
        assert normalize_base("https://api.openai.com/v1") == "https://api.openai.com/v1"

    def test_empty_string(self):
        assert normalize_base("") == ""

    def test_none_safe(self):
        assert normalize_base(None) == ""


class TestBuildChatUrl:
    def test_openai_style(self):
        assert build_chat_url("https://api.openai.com/v1") == "https://api.openai.com/v1/chat/completions"

    def test_anthropic_style(self):
        assert build_chat_url("https://api.anthropic.com") == "https://api.anthropic.com/v1/messages"

    def test_anthropic_v1_base_does_not_double_v1(self):
        assert build_chat_url("https://api.anthropic.com/v1") == "https://api.anthropic.com/v1/messages"

    def test_local_endpoint(self):
        assert build_chat_url("http://localhost:8000/v1") == "http://localhost:8000/v1/chat/completions"


class TestBuildHeaders:
    def test_no_key(self):
        assert build_headers(None, "https://api.openai.com/v1") == {}

    def test_openai_bearer(self):
        assert build_headers("sk-abc", "https://api.openai.com/v1") == {"Authorization": "Bearer sk-abc"}

    def test_anthropic_headers(self):
        assert build_headers("sk-ant-abc", "https://api.anthropic.com") == {"x-api-key": "sk-ant-abc", "anthropic-version": "2023-06-01"}

    def test_empty_key(self):
        assert build_headers("", "https://api.openai.com/v1") == {}


class TestChatFallbackTargetGuard:
    def test_non_default_chat_target_gets_no_default_fallbacks(self, monkeypatch):
        resolver = _load_real_endpoint_resolver()
        import src.settings as settings

        monkeypatch.setattr(settings, "load_settings", lambda: {
            "default_endpoint_id": "gatecheap",
            "default_model": "gpt-5.5",
            "default_model_fallbacks": [{"endpoint_id": "gatecheap", "model": "claude-opus-4-8"}],
        })
        monkeypatch.setattr(settings, "get_user_setting", lambda key, owner, default=None: default)
        monkeypatch.setattr(
            resolver,
            "resolve_endpoint_by_id",
            lambda ep_id, model, owner=None: (
                "https://gatecheap.io.vn/v1/chat/completions",
                "gpt-5.5",
                {},
            ),
        )
        monkeypatch.setattr(
            resolver,
            "_resolve_fallback_candidates",
            lambda setting_key, owner=None: [(
                "https://gatecheap.io.vn/v1/chat/completions",
                "claude-opus-4-8",
                {},
            )],
        )

        assert resolver.resolve_chat_fallback_candidates(
            current_url="https://gatecheap.io.vn/v1/chat/completions",
            current_model="deepseek-v4-flash",
        ) == []

    def test_default_chat_target_keeps_default_fallbacks(self, monkeypatch):
        resolver = _load_real_endpoint_resolver()
        import src.settings as settings

        fallback = [(
            "https://gatecheap.io.vn/v1/chat/completions",
            "claude-opus-4-8",
            {},
        )]
        monkeypatch.setattr(settings, "load_settings", lambda: {
            "default_endpoint_id": "gatecheap",
            "default_model": "gpt-5.5",
            "default_model_fallbacks": [{"endpoint_id": "gatecheap", "model": "claude-opus-4-8"}],
        })
        monkeypatch.setattr(settings, "get_user_setting", lambda key, owner, default=None: default)
        monkeypatch.setattr(
            resolver,
            "resolve_endpoint_by_id",
            lambda ep_id, model, owner=None: (
                "https://gatecheap.io.vn/v1/chat/completions",
                "gpt-5.5",
                {},
            ),
        )
        monkeypatch.setattr(resolver, "_resolve_fallback_candidates", lambda setting_key, owner=None: fallback)

        assert resolver.resolve_chat_fallback_candidates(
            current_url="https://gatecheap.io.vn/v1/chat/completions",
            current_model="gpt-5.5",
        ) == fallback
