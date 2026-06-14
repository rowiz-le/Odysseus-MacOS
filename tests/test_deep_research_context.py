import pytest


def test_research_context_scans_allowed_text_files_and_redacts_secrets(tmp_path, monkeypatch):
    from src import research_context as rc

    (tmp_path / "topic.md").write_text(
        "vibration market notes\napi_key=supersecret\npassword: hunter2",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("vibration SHOULD_NOT_APPEAR=1", encoding="utf-8")
    (tmp_path / "private.key").write_text("vibration key material", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n")

    monkeypatch.setattr(rc, "_allowed_scan_roots", lambda: [tmp_path])
    monkeypatch.setattr(
        rc,
        "_collect_odysseus_items",
        lambda terms, owner: ([], {"chats": 0, "documents": 0}),
    )

    text, stats = rc.collect_research_context("vibration market", "alice", "all_allowed", 5000)

    assert "topic.md" in text
    assert "supersecret" not in text
    assert "hunter2" not in text
    assert "[REDACTED]" in text
    assert "SHOULD_NOT_APPEAR" not in text
    assert "private.key" not in text
    assert stats["files_inspected"] == 1
    assert stats["matching_files"] == 1


def test_all_search_engines_merge_and_deduplicate(monkeypatch):
    from services.search import core

    monkeypatch.setattr(core, "_get_search_settings", lambda: {})
    monkeypatch.setattr(core, "_get_provider_key", lambda provider: "")

    def fake_call_provider(provider, query, count, time_filter=None):
        if provider == "searxng":
            return [
                {"title": "A", "url": "https://example.com/a", "snippet": "query"},
                {"title": "B", "url": "https://example.com/b", "snippet": "query"},
            ]
        if provider == "duckduckgo":
            return [
                {"title": "A duplicate", "url": "https://example.com/a", "snippet": "query"},
                {"title": "C", "url": "https://example.org/c", "snippet": "query"},
            ]
        return []

    monkeypatch.setattr(core, "_call_provider", fake_call_provider)
    results = core.search_all_providers("query", count=5)
    urls = [item["url"] for item in results]

    assert urls.count("https://example.com/a") == 1
    assert set(urls) == {
        "https://example.com/a",
        "https://example.com/b",
        "https://example.org/c",
    }
    assert {item["search_provider"] for item in results} <= {"searxng", "duckduckgo"}


def test_all_search_provider_dispatches_for_web_search(tmp_path, monkeypatch):
    from services.search import core

    monkeypatch.setattr(core, "_get_search_settings", lambda: {
        "search_provider": "all",
        "search_result_count": 3,
    })
    monkeypatch.setattr(core, "_get_provider_key", lambda provider: "")
    monkeypatch.setattr(core, "SEARCH_CACHE_DIR", tmp_path)
    core.search_cache_index.clear()

    calls = []

    def fake_all(query, count=10, time_filter=None):
        calls.append((query, count, time_filter))
        return [
            {"title": "A", "url": "https://example.com/a", "snippet": "query", "search_provider": "searxng"},
            {"title": "B", "url": "https://example.org/b", "snippet": "query", "search_provider": "duckduckgo"},
        ]

    monkeypatch.setattr(core, "search_all_providers", fake_all)
    results = core.searxng_search_results("query", count=3)

    assert calls == [("query", 3, None)]
    assert {item["search_provider"] for item in results} == {"searxng", "duckduckgo"}
    assert {item["url"] for item in results} == {"https://example.com/a", "https://example.org/b"}


def test_comprehensive_web_search_uses_all_engines(monkeypatch):
    from services.search import core

    monkeypatch.setattr(core, "_get_search_settings", lambda: {
        "search_provider": "all",
        "search_result_count": 3,
    })

    def fake_all(query, count=10, time_filter=None):
        return [
            {"title": "A", "url": "https://example.com/a", "snippet": "query", "search_provider": "searxng"},
            {"title": "B", "url": "https://example.org/b", "snippet": "query", "search_provider": "duckduckgo"},
        ]

    monkeypatch.setattr(core, "search_all_providers", fake_all)
    monkeypatch.setattr(core, "fetch_webpage_content", lambda url, timeout, retry_attempt=0: {
        "success": True,
        "url": url,
        "title": "Fetched",
        "content": "query page content long enough",
    })

    text, sources = core.comprehensive_web_search("query", max_pages=1, return_sources=True)

    assert "WEB SEARCH RESULTS" in text
    assert {item["url"] for item in sources} == {"https://example.com/a", "https://example.org/b"}


@pytest.mark.asyncio
async def test_local_context_can_produce_fallback_report_without_web_queries():
    from src.deep_research import DeepResearcher

    class DummyResearcher(DeepResearcher):
        async def _create_plan(self, question):
            return "plan"

        async def _classify_category(self, question):
            return None

        async def _generate_queries(self, question, report, round_num):
            return []

    researcher = DummyResearcher(
        llm_endpoint="http://example.invalid/v1/chat/completions",
        llm_model="test-model",
        max_rounds=1,
        local_context="LOCAL CONTEXT\nImportant internal product notes.",
        context_stats={"items": 1},
    )

    report = await researcher.research("What should the report include?")

    assert "Important internal product notes" in report
    assert "(unknown)" not in report
    assert researcher.get_stats()["Local context"] == "1 items"
