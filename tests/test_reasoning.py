from src import llm_core
from src.reasoning import (
    api_reasoning_effort,
    apply_reasoning_guidance,
    normalize_reasoning_effort,
)


def test_reasoning_effort_normalization():
    assert normalize_reasoning_effort("extra high") == "xhigh"
    assert normalize_reasoning_effort("MAX") == "xhigh"
    assert normalize_reasoning_effort("medium") == "medium"
    assert normalize_reasoning_effort("invalid") == "auto"


def test_reasoning_guidance_does_not_mutate_messages():
    original = [{"role": "system", "content": "Be useful."}, {"role": "user", "content": "Solve it"}]
    guided = apply_reasoning_guidance(original, "high")

    assert guided is not original
    assert original[0]["content"] == "Be useful."
    assert "Reasoning preference: high" in guided[0]["content"]


def test_api_reasoning_mapping_is_only_used_for_compatible_models():
    assert api_reasoning_effort("openai/gpt-5", "xhigh") == "high"
    assert api_reasoning_effort("o3-mini", "low") == "low"
    assert api_reasoning_effort("qwen/qwen3.6-35b-a3b", "high") is None
    assert api_reasoning_effort("gpt-5", "auto") is None


def test_llm_call_sends_supported_reasoning_effort(monkeypatch):
    captured = {}

    class Response:
        is_success = True

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "done"}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return Response()

    monkeypatch.setattr(llm_core.httpx, "post", fake_post)
    llm_core._response_cache.clear()

    response = llm_core.llm_call(
        "https://api.openai.com/v1/chat/completions",
        "gpt-5",
        [{"role": "user", "content": "reasoning payload test"}],
        reasoning_effort="xhigh",
    )

    assert response == "done"
    assert captured["payload"]["reasoning_effort"] == "high"
    assert "Reasoning preference: extra high" in captured["payload"]["messages"][0]["content"]
