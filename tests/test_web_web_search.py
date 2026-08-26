"""Tests for the web_search tool: parameter validation, clamp semantics, the DDG main path, domain filtering and the Tavily fallback chain.

Test cases:
- test_rejects_non_str_query:                    parametrized: non-str query rejected (int/None/list/dict)
- test_rejects_blank_or_short_query:             parametrized: blank/too-short query rejected (""/" "/single char)
- test_rejects_overlong_query:                   over MAX_QUERY_LENGTH rejected
- test_rejects_non_int_max_results:              parametrized: non-int max_results rejected (str/float/bool/None)
- test_rejects_conflicting_domains:              allowed+blocked mutual exclusion rejected
- test_rejects_non_list_domains:                 parametrized: domain params not list[str] rejected (str/with non-str elements)
- test_clamps_max_results:                       parametrized: clamp semantics (0/-5→1 item, oversized→MAX_SEARCH_RESULTS items)
- test_maps_and_strips_fields:                   DDG main path success (mock): href/body field mapping + strip cleanup
- test_empty_results:                            DDG returns an empty list → total_results=0
- test_allowed_domains_keeps_only_matches:       mock whitelist filter: only matching domains kept
- test_blocked_domains_excludes_matches:         mock blacklist filter: matching domains excluded
- test_subdomain_matches_parent_domain:          subdomain matching semantics (docs.github.com matches github.com)
- test_ddg_failure_without_tavily_key:           DDG fails without a Tavily key → error (offline)
- test_tavily_fallback_success:                  DDG fails, Tavily succeeds (mock) → ok
- test_both_providers_fail:                      DDG+Tavily both fail → error with combined information
- test_matches_domain:                           parametrized: domain-matching pure function
- test_format_results_*:                         result-formatting pure functions (DDG/Tavily field mapping, empty input)

Covered scenarios:
- Parameter validation: types (query/max_results/domain lists), length (2..MAX_QUERY_LENGTH),
  bool as int subclass explicitly excluded, allowed/blocked mutual exclusion — all completed in the async shell;
  validation failures must not trigger any search request (asserted via fake call records)
- Clamp semantics: out-of-range max_results converges to 1..MAX_SEARCH_RESULTS instead of being rejected;
  DDG fetches at 3x and truncates by the clamped value (text call argument assertions)
- DDG main path (mock): result formatting (href→url, body→snippet, strip cleanup), empty results
- Domain filtering: whitelist keeps matches only, blacklist excludes matches, subdomains match parent domains (docs.github.com
  matches github.com, notgithub.com does not)
- Fallback chain: DDG exception → Tavily (no-key short-circuit / mock success / mock failure combined error)
- Pure functions: deterministic behavior of _matches_domain and _format_web_search_results

Usage notes:
- All async: web_search call sites all await (aligned with kernel-layer tool async migration);
  pure functions (_matches_domain/_format_web_search_results) are called synchronously
- Fully offline: DDGS/TavilyClient are always mocked (provider capability is not this tool's logic,
  real search is out of test scope); settings.tavily_api_key is controlled with monkeypatch
- Fakes are synchronous implementations: _web_search_sync calls the provider synchronously in the thread pool,
  matching the real ddgs/tavily synchronous APIs, so no AsyncMock is needed
- fake_ddgs/fake_tavily fixtures are configured per case via class attributes; monkeypatch auto-restores
"""

import pytest

from core.tools._kernel import _web
from core.tools._kernel.constants import MAX_QUERY_LENGTH, MAX_SEARCH_RESULTS
from tests.helpers import read_json
from utils.settings import settings


_DDG_RESULTS = [
    {"title": "  GitHub ", "href": "https://github.com/", "body": "  code hosting  "},
    {"title": "Python.org", "href": "https://www.python.org/", "body": "official home"},
    {"title": "Docs", "href": "https://docs.github.com/", "body": "documentation"},
]

_TAVILY_RESULTS = [
    {"title": "Tavily", "url": "https://tavily.com/", "content": "search api"},
]


class TestWebSearchValidation:

    @pytest.fixture(autouse=True)
    def _guard_no_network(self, fake_ddgs):
        yield
        assert fake_ddgs.last_call is None, "校验失败时不应发起任何搜索请求"

    @pytest.mark.parametrize("bad", [123, None, ["py"], {"q": "x"}])
    @pytest.mark.asyncio
    async def test_rejects_non_str_query(self, bad):
        result = read_json(await _web.web_search(query=bad))
        assert result["status"] == "error"
        assert "query must be a string" in result["message"]

    @pytest.mark.parametrize("blank", ["", "   ", "a"])
    @pytest.mark.asyncio
    async def test_rejects_blank_or_short_query(self, blank):
        result = read_json(await _web.web_search(query=blank))
        assert result["status"] == "error"
        assert "at least 2 characters" in result["message"]

    @pytest.mark.asyncio
    async def test_rejects_overlong_query(self):
        result = read_json(await _web.web_search(query="x" * (MAX_QUERY_LENGTH + 1)))
        assert result["status"] == "error"
        assert "too long" in result["message"]

    @pytest.mark.parametrize("bad", ["5", 1.5, True, None])
    @pytest.mark.asyncio
    async def test_rejects_non_int_max_results(self, bad):
        result = read_json(await _web.web_search(query="python", max_results=bad))
        assert result["status"] == "error"
        assert "max_results must be an integer" in result["message"]

    @pytest.mark.asyncio
    async def test_rejects_conflicting_domains(self):
        result = read_json(await _web.web_search(
            query="python",
            allowed_domains=["github.com"],
            blocked_domains=["python.org"],
        ))
        assert result["status"] == "error"
        assert "mutually exclusive" in result["message"]

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"allowed_domains": "github.com"},
            {"blocked_domains": "github.com"},
            {"allowed_domains": ["github.com", 1]},
            {"blocked_domains": [None]},
        ],
    )
    @pytest.mark.asyncio
    async def test_rejects_non_list_domains(self, kwargs):
        result = read_json(await _web.web_search(query="python", **kwargs))
        assert result["status"] == "error"
        assert "must be a list of strings" in result["message"]


class TestWebSearchClamp:

    @pytest.mark.parametrize(
        ("given", "expected_clamped"),
        [
            (0, 1),
            (-5, 1),
            (100, MAX_SEARCH_RESULTS),
        ],
    )
    @pytest.mark.asyncio
    async def test_clamps_max_results(self, fake_ddgs, given, expected_clamped):
        fake_ddgs.results = _DDG_RESULTS
        result = read_json(await _web.web_search(query="python", max_results=given))
        assert result["status"] == "ok"
        assert fake_ddgs.last_call == ("python", expected_clamped * 3)
        assert result["total_results"] == min(len(_DDG_RESULTS), expected_clamped)
        assert len(result["results"]) == min(len(_DDG_RESULTS), expected_clamped)


class TestWebSearchDdgSuccess:

    @pytest.mark.asyncio
    async def test_maps_and_strips_fields(self, fake_ddgs):
        fake_ddgs.results = _DDG_RESULTS
        result = read_json(await _web.web_search(query="python", max_results=3))
        assert result["status"] == "ok"
        assert result["total_results"] == 3
        first = result["results"][0]
        assert first["index"] == 1
        assert first["title"] == "GitHub"
        assert first["url"] == "https://github.com/"
        assert first["snippet"] == "code hosting"
        assert fake_ddgs.last_call == ("python", 9)

    @pytest.mark.asyncio
    async def test_empty_results(self, fake_ddgs):
        fake_ddgs.results = []
        result = read_json(await _web.web_search(query="python"))
        assert result["status"] == "ok"
        assert result["total_results"] == 0
        assert result["results"] == []


class TestWebSearchDomainFilter:

    @pytest.mark.asyncio
    async def test_allowed_domains_keeps_only_matches(self, fake_ddgs):
        fake_ddgs.results = _DDG_RESULTS
        result = read_json(await _web.web_search(
            query="python", max_results=5, allowed_domains=["github.com"],
        ))
        assert result["status"] == "ok"
        assert result["total_results"] == 2
        assert all("github.com" in r["url"] for r in result["results"])

    @pytest.mark.asyncio
    async def test_blocked_domains_excludes_matches(self, fake_ddgs):
        fake_ddgs.results = _DDG_RESULTS
        result = read_json(await _web.web_search(
            query="python", max_results=5, blocked_domains=["python.org"],
        ))
        assert result["status"] == "ok"
        assert result["total_results"] == 2
        assert all("python.org" not in r["url"] for r in result["results"])

    @pytest.mark.asyncio
    async def test_subdomain_matches_parent_domain(self, fake_ddgs):
        fake_ddgs.results = [
            {"title": "A", "href": "https://docs.github.com/", "body": "a"},
            {"title": "B", "href": "https://notgithub.com/", "body": "b"},
            {"title": "C", "href": "https://github.com/", "body": "c"},
        ]
        result = read_json(await _web.web_search(
            query="python", max_results=5, allowed_domains=["github.com"],
        ))
        urls = [r["url"] for r in result["results"]]
        assert "https://docs.github.com/" in urls
        assert "https://github.com/" in urls
        assert "https://notgithub.com/" not in urls
        assert result["total_results"] == 2


class TestWebSearchFallback:

    @pytest.mark.asyncio
    async def test_ddg_failure_without_tavily_key(self, fake_ddgs, monkeypatch):
        fake_ddgs.error = RuntimeError("rate limited")
        monkeypatch.setattr(settings, "tavily_api_key", None)
        result = read_json(await _web.web_search(query="python"))
        assert result["status"] == "error"
        assert "no Tavily API key" in result["message"]
        assert "rate limited" in result["message"]

    @pytest.mark.asyncio
    async def test_tavily_fallback_success(self, fake_ddgs, fake_tavily, monkeypatch):
        fake_ddgs.error = RuntimeError("rate limited")
        fake_tavily.results = _TAVILY_RESULTS
        monkeypatch.setattr(settings, "tavily_api_key", "test-key")
        result = read_json(await _web.web_search(query="python", max_results=3))
        assert result["status"] == "ok"
        assert result["total_results"] == 1
        assert result["results"][0]["url"] == "https://tavily.com/"
        assert fake_tavily.last_kwargs["max_results"] == 3

    @pytest.mark.asyncio
    async def test_both_providers_fail(self, fake_ddgs, fake_tavily, monkeypatch):
        fake_ddgs.error = RuntimeError("ddg down")
        fake_tavily.error = RuntimeError("tavily down")
        monkeypatch.setattr(settings, "tavily_api_key", "test-key")
        result = read_json(await _web.web_search(query="python"))
        assert result["status"] == "error"
        assert "Both DuckDuckGo and Tavily search failed" in result["message"]
        assert "ddg down" in result["message"]
        assert "tavily down" in result["message"]


class TestMatchesDomain:

    @pytest.mark.parametrize(
        ("url", "domains", "expected"),
        [
            ("https://github.com/", ["github.com"], True),
            ("https://sub.github.com/x", ["github.com"], True),
            ("https://notgithub.com/", ["github.com"], False),
            ("https://github.com.evil.com/", ["github.com"], False),
            ("not a url", ["github.com"], False),
            ("https://github.com/", [], False),
        ],
    )
    def test_matches_domain(self, url, domains, expected):
        assert _web._matches_domain(url, domains) is expected


class TestFormatResults:

    def test_ddg_field_mapping(self):
        raw = [{"title": "  T ", "href": "https://x.com/", "body": "  b  "}]
        result = read_json(_web._format_web_search_results(raw))
        assert result["status"] == "ok"
        assert result["results"][0] == {
            "index": 1,
            "title": "T",
            "url": "https://x.com/",
            "snippet": "b",
        }

    def test_tavily_field_mapping(self):
        raw = [{"title": "T2", "url": "https://y.com/", "content": "c"}]
        result = read_json(_web._format_web_search_results(raw))
        assert result["status"] == "ok"
        assert result["results"][0]["url"] == "https://y.com/"
        assert result["results"][0]["snippet"] == "c"

    def test_empty_input(self):
        result = read_json(_web._format_web_search_results([]))
        assert result == {"status": "ok", "total_results": 0, "results": []}
