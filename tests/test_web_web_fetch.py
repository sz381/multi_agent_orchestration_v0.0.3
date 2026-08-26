"""Tests for the web_fetch tool: parameter validation, the crawl4ai main path, Tavily extract fallback and pure functions.

Test cases:
- test_rejects_non_str_url:                 parametrized: non-str url rejected (int/None/list/dict)
- test_rejects_blank_url:                   parametrized: blank url rejected (""/" ")
- test_rejects_bad_protocol:                parametrized: non-http(s) protocols rejected (ftp/file/javascript)
- test_rejects_overlong_url:                over MAX_URL_LENGTH rejected
- test_rejects_private_urls:                parametrized: private/loopback IPs rejected (127.x/10.x/172.16.x/192.168.x/localhost)
- test_rejects_non_str_prompt:              parametrized: non-str prompt rejected (int/None/list/dict)
- test_rejects_blank_prompt:                parametrized: blank prompt rejected (""/" ")
- test_rejects_overlong_prompt:             over MAX_PROMPT_LENGTH rejected
- test_fetch_short_content:                 main path success (mock): short content returned directly without summarization
- test_fetch_falls_back_to_raw_markdown:    uses raw_markdown when fit_markdown is empty
- test_fetch_long_content_summarizes:       long content goes through assistant-model summarization (mock)
- test_fetch_crawler_failure_without_tavily_key: fetch fails without a Tavily key → error
- test_fetch_tavily_extract_success:        fetch fails, Tavily extract succeeds (mock) → content
- test_fetch_tavily_extract_no_results:     extract returns no results → error
- test_fetch_tavily_extract_empty_content:  raw_content is empty → error
- test_fetch_both_providers_fail:           both fail → error with combined information
- test_fetch_fallback_long_content_summarizes: overlong fallback content goes through assistant-model summarization (mock)
- test_summarize_short_content:             _summarize_with_llm returns short content directly
- test_summarize_failure_returns_original:  summarization exception falls back to the original content
- test_is_private_url:                      parametrized: SSRF pure function

Covered scenarios:
- Parameter validation: url/prompt types, lengths (<=MAX_URL_LENGTH / <=MAX_PROMPT_LENGTH),
  protocols (http/https only), SSRF (private/loopback/special IPs) — all completed inside the event loop;
  validation failures must not trigger any fetch/extract request (asserted via fake call records)
- Main path (mock): crawl4ai fetch success returns markdown; empty fit_markdown falls back to
  raw_markdown; long content (>SUMMARIZE_LENGTH_THRESHOLD) goes through assistant-model summarization
- Fallback chain: crawl4ai exception → Tavily extract (no-key short-circuit / mock success / no results /
  empty content / both-fail combined error / long-content summarization)
- Pure functions: deterministic behavior of _is_private_url

Usage notes:
- All async: web_fetch call sites all await; pure functions (_is_private_url) are called synchronously
- Fully offline: _get_crawler/TavilyClient are always mocked (crawl4ai/tavily are third-party libraries;
  provider capability is not this tool's logic, real fetching is out of test scope)
- fake_crawler is genuinely async (arun is an async def); fake_tavily is a synchronous implementation
  (extract is called synchronously in the thread pool, matching the real synchronous tavily API)
- settings.tavily_api_key is controlled with monkeypatch to drive the fallback branch
"""

import pytest

from core.tools._kernel import _web
from core.tools._kernel.constants import (
    MAX_PROMPT_LENGTH,
    MAX_URL_LENGTH,
    SUMMARIZE_LENGTH_THRESHOLD,
)
from tests.helpers import read_json
from utils.settings import settings


_LONG_CONTENT = "x" * (SUMMARIZE_LENGTH_THRESHOLD + 1)


class TestWebFetchValidation:

    @pytest.fixture(autouse=True)
    def _guard_no_network(self, fake_crawler, fake_tavily):
        yield
        assert fake_crawler.arun_called is False, "校验失败时不应发起任何抓取请求"
        assert fake_tavily.last_kwargs is None, "校验失败时不应初始化 Tavily 客户端"

    @pytest.mark.parametrize("bad", [123, None, ["https://x.com"], {"u": "https://x.com"}])
    @pytest.mark.asyncio
    async def test_rejects_non_str_url(self, bad):
        result = read_json(await _web.web_fetch(url=bad, prompt="提取内容"))
        assert result["status"] == "error"
        assert "url must be a string" in result["message"]

    @pytest.mark.parametrize("blank", ["", "   "])
    @pytest.mark.asyncio
    async def test_rejects_blank_url(self, blank):
        result = read_json(await _web.web_fetch(url=blank, prompt="提取内容"))
        assert result["status"] == "error"
        assert "url is required" in result["message"]

    @pytest.mark.parametrize(
        "bad", ["ftp://x.com/file", "file:///etc/passwd", "javascript:alert(1)"]
    )
    @pytest.mark.asyncio
    async def test_rejects_bad_protocol(self, bad):
        result = read_json(await _web.web_fetch(url=bad, prompt="提取内容"))
        assert result["status"] == "error"
        assert "fully-formed URL" in result["message"]

    @pytest.mark.asyncio
    async def test_rejects_overlong_url(self):
        result = read_json(await _web.web_fetch(
            url="https://x.com/" + "a" * MAX_URL_LENGTH, prompt="提取内容"
        ))
        assert result["status"] == "error"
        assert "url too long" in result["message"]

    @pytest.mark.parametrize(
        "bad_url",
        [
            "http://127.0.0.1:9/x",
            "http://localhost:9/x",
            "http://10.0.0.1/x",
            "http://172.16.0.1/x",
            "http://192.168.1.1/x",
            "http://0.0.0.0/x",
            "http://[::1]:9/x",
        ],
    )
    @pytest.mark.asyncio
    async def test_rejects_private_urls(self, bad_url):
        result = read_json(await _web.web_fetch(url=bad_url, prompt="提取内容"))
        assert result["status"] == "error"
        assert "private/internal" in result["message"]

    @pytest.mark.parametrize("bad", [123, None, ["提取"], {"p": "提取"}])
    @pytest.mark.asyncio
    async def test_rejects_non_str_prompt(self, bad):
        result = read_json(await _web.web_fetch(url="https://example.com", prompt=bad))
        assert result["status"] == "error"
        assert "prompt must be a string" in result["message"]

    @pytest.mark.parametrize("blank", ["", "   "])
    @pytest.mark.asyncio
    async def test_rejects_blank_prompt(self, blank):
        result = read_json(await _web.web_fetch(url="https://example.com", prompt=blank))
        assert result["status"] == "error"
        assert "prompt is required" in result["message"]

    @pytest.mark.asyncio
    async def test_rejects_overlong_prompt(self):
        result = read_json(await _web.web_fetch(
            url="https://example.com", prompt="x" * (MAX_PROMPT_LENGTH + 1)
        ))
        assert result["status"] == "error"
        assert "prompt too long" in result["message"]


class TestWebFetchMainPath:

    @pytest.mark.asyncio
    async def test_fetch_short_content(self, fake_crawler):
        fake_crawler.markdown = ("  short content  ", "raw")
        content = await _web.web_fetch(url="https://example.com", prompt="提取内容")
        assert content == "short content"

    @pytest.mark.asyncio
    async def test_fetch_falls_back_to_raw_markdown(self, fake_crawler):
        fake_crawler.markdown = (None, "raw content")
        content = await _web.web_fetch(url="https://example.com", prompt="提取内容")
        assert content == "raw content"

    @pytest.mark.asyncio
    async def test_fetch_long_content_summarizes(self, fake_crawler, monkeypatch):
        fake_crawler.markdown = (_LONG_CONTENT, "")
        calls = []

        async def fake_summarize(content, prompt):
            calls.append((content, prompt))
            return "摘要结果"

        monkeypatch.setattr(_web, "_summarize_with_llm", fake_summarize)
        content = await _web.web_fetch(url="https://example.com", prompt="提取要点")
        assert content == "摘要结果"
        assert len(calls) == 1
        assert calls[0][0] == _LONG_CONTENT
        assert calls[0][1] == "提取要点"


class TestWebFetchFallback:

    @pytest.mark.asyncio
    async def test_fetch_crawler_failure_without_tavily_key(self, fake_crawler, fake_tavily, monkeypatch):
        fake_crawler.error = RuntimeError("crawl down")
        monkeypatch.setattr(settings, "tavily_api_key", None)
        result = read_json(await _web.web_fetch(url="https://example.com", prompt="提取内容"))
        assert result["status"] == "error"
        assert "crawl down" in result["message"]

    @pytest.mark.asyncio
    async def test_fetch_tavily_extract_success(self, fake_crawler, fake_tavily, monkeypatch):
        fake_crawler.error = RuntimeError("crawl down")
        fake_tavily.extract_results = [{"raw_content": "  tavily content  "}]
        monkeypatch.setattr(settings, "tavily_api_key", "test-key")
        content = await _web.web_fetch(url="https://example.com", prompt="提取内容")
        assert content == "tavily content"
        assert fake_tavily.last_kwargs["urls"] == ["https://example.com"]

    @pytest.mark.asyncio
    async def test_fetch_tavily_extract_no_results(self, fake_crawler, fake_tavily, monkeypatch):
        fake_crawler.error = RuntimeError("crawl down")
        fake_tavily.extract_results = []
        monkeypatch.setattr(settings, "tavily_api_key", "test-key")
        result = read_json(await _web.web_fetch(url="https://example.com", prompt="提取内容"))
        assert result["status"] == "error"
        assert "no results" in result["message"]

    @pytest.mark.asyncio
    async def test_fetch_tavily_extract_empty_content(self, fake_crawler, fake_tavily, monkeypatch):
        fake_crawler.error = RuntimeError("crawl down")
        fake_tavily.extract_results = [{"raw_content": ""}]
        monkeypatch.setattr(settings, "tavily_api_key", "test-key")
        result = read_json(await _web.web_fetch(url="https://example.com", prompt="提取内容"))
        assert result["status"] == "error"
        assert "empty raw_content" in result["message"]

    @pytest.mark.asyncio
    async def test_fetch_both_providers_fail(self, fake_crawler, fake_tavily, monkeypatch):
        fake_crawler.error = RuntimeError("crawl down")
        fake_tavily.error = RuntimeError("tavily down")
        monkeypatch.setattr(settings, "tavily_api_key", "test-key")
        result = read_json(await _web.web_fetch(url="https://example.com", prompt="提取内容"))
        assert result["status"] == "error"
        assert "Both crawl4ai and Tavily extract failed" in result["message"]
        assert "crawl down" in result["message"]
        assert "tavily down" in result["message"]

    @pytest.mark.asyncio
    async def test_fetch_fallback_long_content_summarizes(self, fake_crawler, fake_tavily, monkeypatch):
        fake_crawler.error = RuntimeError("crawl down")
        fake_tavily.extract_results = [{"raw_content": _LONG_CONTENT}]
        monkeypatch.setattr(settings, "tavily_api_key", "test-key")
        calls = []

        async def fake_summarize(content, prompt):
            calls.append(content)
            return "回退摘要"

        monkeypatch.setattr(_web, "_summarize_with_llm", fake_summarize)
        content = await _web.web_fetch(url="https://example.com", prompt="提取要点")
        assert content == "回退摘要"
        assert calls == [_LONG_CONTENT]


class TestSummarizeWithLlm:

    @pytest.mark.asyncio
    async def test_summarize_short_content(self):
        content = await _web._summarize_with_llm("short content", "提取要点")
        assert content == "short content"

    @pytest.mark.asyncio
    async def test_summarize_failure_returns_original(self, monkeypatch):
        async def boom(*args, **kwargs):
            raise RuntimeError("llm down")

        monkeypatch.setattr(_web, "ainvoke_with_content_guard", boom)
        content = await _web._summarize_with_llm(_LONG_CONTENT, "提取要点")
        assert content == _LONG_CONTENT


class TestIsPrivateUrl:

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("http://127.0.0.1:9/", True),
            ("http://localhost:9/", True),
            ("http://10.1.2.3/", True),
            ("http://172.16.0.1/", True),
            ("http://192.168.0.1/", True),
            ("http://0.0.0.0/", True),
            ("http://[::1]:9/", True),
            ("https://example.com/", False),
            ("https://docs.github.com/x", False),
        ],
    )
    def test_is_private_url(self, url, expected):
        assert _web._is_private_url(url) is expected
