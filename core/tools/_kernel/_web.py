"""Agent web tools implementation.

Provides:
- web_search:  web search, DuckDuckGo primary with Tavily fallback
- web_fetch:   fetch page content, crawl4ai primary with Tavily extract fallback

Key constraints:
- all tools never raise: exceptions are caught and converted to error
  JSON; web_search success returns JSON with total_results and results,
  web_fetch success returns raw Markdown text
- async shell plus to_thread pattern: ddgs and tavily are synchronous
  blocking network calls without async APIs, so core IO is wrapped in
  asyncio.to_thread and runs in a thread pool, never blocking the event loop
- parameter validation stays in the event loop: type, length and mutual
  exclusion checks run in the async shell, the sync helpers trust the
  validated arguments and only do network calls
- max_results is clamped to 1..MAX_SEARCH_RESULTS instead of rejected
- allowed_domains and blocked_domains are mutually exclusive, only one
  can be passed
- SSRF guard: private, loopback and special IP addresses are blocked
  before any network call
- long fetch content is summarized by a helper LLM before being returned
- degradation: DuckDuckGo failure falls back to Tavily, crawl4ai failure
  falls back to Tavily extract, missing API key returns error

Usage notes:
- network calls take seconds, rate limiting or failure on the primary
  path triggers the fallback, an error is reported only when both fail
- the crawler is a module-level singleton guarded by double-checked
  locking and closed at process exit via an atexit hook
- output fields title, url and snippet are uniformly strip-cleaned
"""

import json
import atexit
import asyncio
import ipaddress
from urllib.parse import urlparse

from ddgs import DDGS
from tavily import TavilyClient
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

from utils.settings import settings
from utils.logging import get_logger
from core.agents.model import ainvoke_with_content_guard
from core.prompts.system_prompt_webpage_summarizer import WEB_SUMMARIZE_TEMPLATE
from core.tools._kernel.constants import (
    MAX_QUERY_LENGTH,
    MAX_SEARCH_RESULTS,
    MAX_URL_LENGTH,
    MAX_PROMPT_LENGTH,
    SUMMARIZE_LENGTH_THRESHOLD,
    MAX_CONTENT_CHARS,
    PAGE_TIMEOUT_MS,
    SSRF_BLOCKED_HOSTS,
)

logger = get_logger()
_crawler: AsyncWebCrawler | None = None
_crawler_lock = asyncio.Lock()
_crawler_started = False


async def _get_crawler() -> AsyncWebCrawler:
    """Get the singleton crawler instance, starting it on first use.

    Double-checked locking prevents concurrent crawler startups:
    - an atexit hook is registered after the first start, closing the
      crawler synchronously at process exit
    - a real macOS Chrome User-Agent, stealth mode and typical browser
      headers are configured to reduce anti-bot detection

    Returns:
        the AsyncWebCrawler singleton, module-level _crawler.
    """

    global _crawler, _crawler_started

    if _crawler is None:
        async with _crawler_lock:
            if _crawler is None:
                browser_config = BrowserConfig(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/135.0.0.0 Safari/537.36"
                    ),
                    headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept-Encoding": "gzip, deflate, br",
                        "DNT": "1",
                        "Connection": "keep-alive",
                        "Upgrade-Insecure-Requests": "1",
                    },
                    viewport_width=1920,
                    viewport_height=1080,
                    enable_stealth=True,
                )
                crawler = AsyncWebCrawler(config=browser_config)

                await crawler.start()
                _crawler = crawler

                if not _crawler_started:
                    _crawler_started = True
                    atexit.register(_close_crawler_sync)

    return _crawler


async def _close_crawler():
    """Close and clear the singleton crawler.

    Called by close_crawler while the event loop is alive and by
    _close_crawler_sync as the atexit fallback.
    """

    global _crawler

    if _crawler is not None:
        await _crawler.close()
        _crawler = None


async def close_crawler():
    """Public close entry: close the crawler while the event loop is alive.

    Called on the graceful shutdown path of the application; a force-killed
    process is covered by the atexit hook.
    """

    await _close_crawler()


def _close_crawler_sync():
    """Synchronous wrapper for atexit: run _close_crawler in a fresh event loop.

    At process exit the event loop may be closed or still running, and
    neither case may raise:
    - loop still running, asyncio.run raises RuntimeError, swallowed
    - other exceptions such as a dead crawler are swallowed, so the
      process exit stays clean
    """

    global _crawler

    if _crawler is not None:
        try:
            asyncio.run(_close_crawler())
        except (RuntimeError, KeyboardInterrupt):
            pass
        except Exception:
            pass


async def _summarize_with_llm(
    content: str,
    prompt: str
) -> str:
    """Summarize page content with a helper LLM.

    Execution model: short content, at most SUMMARIZE_LENGTH_THRESHOLD,
    is returned as-is; long content is truncated to MAX_CONTENT_CHARS and
    then summarized via WEB_SUMMARIZE_TEMPLATE through
    ainvoke_with_content_guard, which resends the request once on an
    empty response to avoid empty summaries; any failure falls back to
    the original content.

    Args:
        content: raw page content to summarize, markdown text.
        prompt: information the user wants extracted from the page.

    Returns:
        the summarized content, or the original content when it is
        below the threshold or summarization fails.
    """
    # content below the summarize threshold is returned as-is
    if len(content) <= SUMMARIZE_LENGTH_THRESHOLD:
        return content

    # truncate content that exceeds the maximum acceptable length
    if len(content) > MAX_CONTENT_CHARS:
        content = content[:MAX_CONTENT_CHARS]
        logger.debug("web_summarize_truncated", max_chars=MAX_CONTENT_CHARS)

    # run the summary
    logger.debug("web_summarize_start", content_len=len(content), model=settings.deepseek_model_name)
    try:
        summarizer = ChatOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model_name,
            streaming=False,
            temperature=0.0,
            max_tokens=5000,
        )
        text = WEB_SUMMARIZE_TEMPLATE.format(prompt=prompt, content=content)

        # use content_guard to avoid empty responses
        response = await ainvoke_with_content_guard(
            summarizer,
            [HumanMessage(content=text)],
            role="web_summarize",
        )
        result = response.content

        # content_guard guarantees non-empty, but a tool-calling response
        # may still have content None; summaries never consume tool calls,
        # so defensively fall back to the original content
        if not result:
            return content

        logger.debug("web_summarize_done", before=len(content), after=len(result))
        return result
    except Exception as e:
        logger.warning("web_summarize_failed", error=str(e), content_len=len(content))
        return content


def _matches_domain(
    url: str,
    domains: list[str]
) -> bool:
    """Check whether a URL matches any of the given domains, exact or subdomain.

    Synchronous pure function: only string parsing and comparison, no
    network requests; called by _web_search_sync when filtering results.

    Args:
        url: URL string to check.
        domains: domain list, such as ["example.com"].

    Returns:
        True when the hostname equals a domain or ends with a dotted
        subdomain of it; False on parse failure, conservatively no match.
    """
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False

    return any(host == d or host.endswith("." + d) for d in domains)


def _format_web_search_results(
    raw_results: list[dict]
) -> str:
    """Normalize raw search-service results into a uniform JSON output.

    Synchronous pure function: adapts the DDG structure with href and
    body fields and the Tavily structure with url and content fields;
    output fields are uniformly title, url and snippet with strip
    cleaning; empty results return an empty list with total_results 0.

    Args:
        raw_results: raw result dicts returned by the search service.

    Returns:
        JSON string with status ok plus total_results and results.
    """
    if not raw_results:
        return json.dumps({
            "status": "ok",
            "total_results": 0,
            "results": [],
        }, ensure_ascii=False)

    results = []
    for i, r in enumerate(raw_results, 1):
        results.append({
            "index": i,
            "title": r.get("title", "").strip(),
            "url": r.get("url") or r.get("href", "").strip(),
            "snippet": r.get("content") or r.get("body", "").strip(),
        })

    return json.dumps({
        "status": "ok",
        "total_results": len(results),
        "results": results,
    }, ensure_ascii=False)


def _is_private_url(
    url: str
) -> bool:
    """SSRF guard: block private, loopback and special IP addresses.

    Blocks local hosts, private IP ranges such as 10.x, 172.16.x and
    192.168.x, loopback addresses such as 127.x, and unspecified
    addresses. Domain names pass through, DNS resolution is left to the
    crawler.

    Args:
        url: URL string to check.

    Returns:
        True when the URL is a private, loopback or special IP address,
        otherwise False.
    """
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return True

    if host.lower() in SSRF_BLOCKED_HOSTS:
        return True

    try:
        addr = ipaddress.ip_address(host)
        return addr.is_private or addr.is_loopback or addr.is_unspecified
    except ValueError:
        pass

    return False


async def web_search(
    query: str,
    max_results: int = 5,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
) -> str:
    """Search the web via DuckDuckGo, falling back to Tavily on failure.

    Execution model: parameter validation, pure CPU, stays in the event
    loop; ddgs and tavily are synchronous blocking network calls without
    async APIs, so the core IO is wrapped in asyncio.to_thread and runs
    in a thread pool, never blocking the event loop thread.

    Args:
        query: search keywords, 2..MAX_QUERY_LENGTH chars after strip.
        max_results: max result count, an int clamped to 1..MAX_SEARCH_RESULTS.
        allowed_domains: result domain whitelist, mutually exclusive with blocked_domains.
        blocked_domains: result domain blacklist, mutually exclusive with allowed_domains.

    Returns:
        JSON with status ok plus total_results and results, or status
        error JSON on validation failure or when both providers fail.
    """
    # parameter validation, pure CPU, stays in the event loop
    if not isinstance(query, str):
        return json.dumps({
            "status": "error",
            "message": "query must be a string.",
        }, ensure_ascii=False)

    query = query.strip()

    if len(query) < 2:
        return json.dumps({
            "status": "error",
            "message": "query must be at least 2 characters."
        }, ensure_ascii=False)

    if len(query) > MAX_QUERY_LENGTH:
        return json.dumps({
            "status": "error",
            "message": f"query too long ({len(query)} chars). Max {MAX_QUERY_LENGTH}."
        }, ensure_ascii=False)

    # max_results must be an int, bool is an int subclass and True would
    # slip through as clamp 1
    if not isinstance(max_results, int) or isinstance(max_results, bool):
        return json.dumps({
            "status": "error",
            "message": "max_results must be an integer."
        }, ensure_ascii=False)

    # clamp into 1..MAX_SEARCH_RESULTS
    max_results = max(1, min(max_results, MAX_SEARCH_RESULTS))

    # allowed and blocked are mutually exclusive, only one can be passed
    if allowed_domains is not None and blocked_domains is not None:
        return json.dumps({
            "status": "error",
            "message": "allowed_domains and blocked_domains are mutually exclusive. Use one or the other, not both."
        }, ensure_ascii=False)

    # validate domain list types, a plain string would iterate char by
    # char and silently misbehave
    for label, domains in (
        ("allowed_domains", allowed_domains),
        ("blocked_domains", blocked_domains),
    ):
        if domains is not None and (
            not isinstance(domains, list)
            or any(not isinstance(d, str) for d in domains)
        ):
            return json.dumps({
                "status": "error",
                "message": f"{label} must be a list of strings."
            }, ensure_ascii=False)

    # core IO, synchronous network calls without async APIs, wrapped in to_thread
    return await asyncio.to_thread(
        _web_search_sync,
        query,
        max_results,
        allowed_domains,
        blocked_domains,
    )


def _web_search_sync(
    query: str,
    max_results: int = 5,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
) -> str:
    """Run the synchronous web search, DuckDuckGo primary with Tavily fallback.

    Only called by web_search via asyncio.to_thread: everything in this
    function is synchronous blocking network IO, ddgs and tavily have no
    async APIs, so calling it on the event loop thread is forbidden. All
    validation and clamping was done by the web_search shell, arguments
    are trusted here.

    Args:
        query: stripped search keywords, shell guarantees 2..MAX_QUERY_LENGTH chars.
        max_results: result count already clamped to 1..MAX_SEARCH_RESULTS.
        allowed_domains: domain whitelist, shell guarantees exclusivity with blocked_domains.
        blocked_domains: domain blacklist, shell guarantees exclusivity with allowed_domains.

    Returns:
        JSON with status ok on results, status error when both providers fail.
    """
    # primary path, DuckDuckGo
    try:
        with DDGS() as ddgs:
            raw_results = list(ddgs.text(query, max_results=max_results * 3))

        if allowed_domains is not None:
            raw_results = [r for r in raw_results if _matches_domain(r.get("href", ""), allowed_domains)]
        elif blocked_domains is not None:
            raw_results = [r for r in raw_results if not _matches_domain(r.get("href", ""), blocked_domains)]
        raw_results = raw_results[:max_results]

        return _format_web_search_results(raw_results)
    except Exception as e:
        return _fallback_search(query, max_results, allowed_domains, blocked_domains, ddg_error=str(e))


async def web_fetch(
    url: str,
    prompt: str,
) -> str:
    """Fetch page content, crawl4ai primary with Tavily extract fallback.

    Execution model: parameter validation, type, length and SSRF guard,
    runs in the event loop; crawl4ai crawling is truly async and reuses
    the singleton AsyncWebCrawler; content longer than
    SUMMARIZE_LENGTH_THRESHOLD is summarized by the helper LLM; on
    crawl4ai failure it falls back to Tavily extract, both failing
    returns error JSON.

    Args:
        url: fully-formed http or https URL, non-empty after strip, at
            most MAX_URL_LENGTH chars, not a private or loopback IP.
        prompt: content requirement to extract from the page, non-empty
            after strip, at most MAX_PROMPT_LENGTH chars.

    Returns:
        extracted Markdown content, summarized when long, or status
        error JSON on validation failure or when both providers fail.
    """
    # url must be a string, type check before strip, a non-str would raise AttributeError
    if not isinstance(url, str):
        return json.dumps({
            "status": "error",
            "message": "url must be a string."
        }, ensure_ascii=False)

    url = url.strip()

    # url is required
    if not url:
        return json.dumps({
            "status": "error",
            "message": "url is required."
        }, ensure_ascii=False)

    # url must start with http:// or https://
    if not url.startswith(("http://", "https://")):
        return json.dumps({
            "status": "error",
            "message": "url must be a fully-formed URL starting with http:// or https://."
        }, ensure_ascii=False)

    # url length must not exceed MAX_URL_LENGTH
    if len(url) > MAX_URL_LENGTH:
        return json.dumps({
            "status": "error",
            "message": f"url too long ({len(url)} chars). Max {MAX_URL_LENGTH}."
        }, ensure_ascii=False)

    # url must not be a private, loopback or special IP address
    if _is_private_url(url):
        return json.dumps({
            "status": "error",
            "message": f"Access to private/internal URLs is blocked: {url}"
        }, ensure_ascii=False)

    # prompt must be a string, type check before strip
    if not isinstance(prompt, str):
        return json.dumps({
            "status": "error",
            "message": "prompt must be a string."
        }, ensure_ascii=False)

    prompt = prompt.strip()

    # prompt is required
    if not prompt:
        return json.dumps({
            "status": "error",
            "message": "prompt is required."
        }, ensure_ascii=False)

    # prompt length must not exceed MAX_PROMPT_LENGTH
    if len(prompt) > MAX_PROMPT_LENGTH:
        return json.dumps({
            "status": "error",
            "message": f"prompt too long ({len(prompt)} chars). Max {MAX_PROMPT_LENGTH}."
        }, ensure_ascii=False)

    # primary path, crawl4ai
    try:
        md_gen = DefaultMarkdownGenerator(
            content_filter=PruningContentFilter(threshold=0.4, threshold_type="fixed")
        )
        config = CrawlerRunConfig(
            markdown_generator=md_gen,
            cache_mode=CacheMode.ENABLED,
            page_timeout=PAGE_TIMEOUT_MS,
            magic=True,
            simulate_user=True,
            override_navigator=True,
        )

        crawler = await _get_crawler()
        result = await crawler.arun(url=url, config=config)
        content = result.markdown.fit_markdown or result.markdown.raw_markdown or "(empty)"

        if len(content) > SUMMARIZE_LENGTH_THRESHOLD:
            content = await _summarize_with_llm(content, prompt)

        return content.strip()
    except Exception as e:
        return await _fallback_fetch(url, prompt, e)


def _fallback_search(
    query: str,
    max_results: int = 5,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
    ddg_error: str = "",
) -> str:
    """Fallback search via Tavily when DuckDuckGo fails.

    Synchronous blocking network call, TavilyClient.search, only called
    from the except path of _web_search_sync; without an API key no
    network request is made and an error is returned directly.

    Args:
        query: search keywords, already stripped.
        max_results: max result count, already clamped.
        allowed_domains: result domain whitelist, mutually exclusive with blocked_domains.
        blocked_domains: result domain blacklist, mutually exclusive with allowed_domains.
        ddg_error: DuckDuckGo failure message, passed through to the user.

    Returns:
        JSON with status ok on results, status error without an API key
        or when Tavily fails.
    """
    # without a Tavily API key, return an error directly
    if not settings.tavily_api_key:
        return json.dumps({
            "status": "error",
            "message": f"DuckDuckGo search failed and no Tavily API key configured. DDG error: {ddg_error}"
        }, ensure_ascii=False)

    # run the search with TavilyClient
    try:
        client = TavilyClient(api_key=settings.tavily_api_key)

        response = client.search(
            query=query,
            max_results=max_results,
            include_domains=list(allowed_domains) if allowed_domains else None,
            exclude_domains=list(blocked_domains) if blocked_domains else None,
        )

        results = response.get("results", [])
        return _format_web_search_results(results)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Both DuckDuckGo and Tavily search failed. DDG: {ddg_error} | Tavily: {e}"
        }, ensure_ascii=False)


async def _fallback_fetch(
    url: str,
    prompt: str,
    crawl_error: Exception
) -> str:
    """Extract page content via Tavily when crawl4ai fails.

    Only called from the except path of web_fetch; without an API key no
    network request is made and an error is returned directly. The
    extracted content is also subject to SUMMARIZE_LENGTH_THRESHOLD,
    long content goes through the helper LLM summary.

    Execution model: TavilyClient.extract is a synchronous blocking
    network call without an async API, so the core IO is wrapped in
    asyncio.to_thread and runs in a thread pool, never blocking the
    event loop, same pattern as web_search and _web_search_sync.

    Args:
        url: full URL to extract.
        prompt: content requirement from the page, passed to the summary.
        crawl_error: crawl4ai failure reason, passed through to the user.

    Returns:
        extracted Markdown content, or status error JSON without an API
        key, no results, empty content or Tavily failure.
    """
    # without a Tavily API key, return an error directly
    if not settings.tavily_api_key:
        return json.dumps({
            "status": "error",
            "message": f"web_fetch failed: {crawl_error}"
        }, ensure_ascii=False)

    try:
        # TavilyClient.extract is a synchronous blocking call, wrap it in to_thread and
        # never wait on the event loop thread, otherwise the fallback path would freeze the loop
        def _extract():
            client = TavilyClient(api_key=settings.tavily_api_key)
            return client.extract(urls=[url])

        response = await asyncio.to_thread(_extract)
        results = response.get("results", [])

        if not results:
            return json.dumps({
                "status": "error",
                "message": f"Tavily extract returned no results for {url}"
            }, ensure_ascii=False)

        content = results[0].get("raw_content", "")

        if not content:
            return json.dumps({
                "status": "error",
                "message": f"Tavily extract for {url} returned empty raw_content."
            }, ensure_ascii=False)

        if len(content) > SUMMARIZE_LENGTH_THRESHOLD:
            content = await _summarize_with_llm(content, prompt)

        return content.strip()
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Both crawl4ai and Tavily extract failed. crawl4ai: {crawl_error} | Tavily: {e}"
        }, ensure_ascii=False)
