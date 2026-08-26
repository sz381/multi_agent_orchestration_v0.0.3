"""Tool descriptions for the web toolset (_web).

Tools described:
- web_search    search web content
- web_fetch     fetch web page content
"""

TOOL_DESCRIPTION = {
    "web_search": (
        "Search the web via DuckDuckGo, returning structured JSON results.\n"
        "Parameters:\n"
        "- query: search keywords (2-500 chars)\n"
        "- max_results: 1-20, default 5\n"
        "- allowed_domains / blocked_domains: optional domain filter (mutually exclusive)\n"
        "\n"
        "Returns JSON: {\"status\":\"ok\",\"total_results\":N,\"results\":[{...}]}\n"
        "Use for: up-to-date info, docs, recent news. Do NOT use for known URLs — use web_fetch."
    ),
    "web_fetch": (
        "Fetch a web page via Chromium browser and return clean Markdown.\n"
        "Parameters:\n"
        "- url: full HTTPS URL (max 2048 chars, private/internal IPs blocked)\n"
        "- prompt: what to extract from the page (1-5000 chars)\n"
        "\n"
        "Behavior: renders JavaScript; strips nav/ads/sidebars; pages >4000 chars "
        "are auto-summarized by a secondary LLM to only keep prompt-relevant content; "
        "results cached 15 min.\n"
        "Limitations: no login/paywall/CAPTCHA; social media may return incomplete content."
    ),
}
