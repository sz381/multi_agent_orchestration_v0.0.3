"""系统提示词

此提示词用于 fetch_web 工具的 secondary model
触发条件：当 fetch 的页面内容超过 某个threshold 个字符时，触发 secondary model 对 input prompt 进行削减

提供
- WEB_SUMMARIZE_TEMPLATE:       web page summarization template
"""

WEB_SUMMARIZE_TEMPLATE = """\
Extract and summarize content from the web page below. Focus specifically on:

{prompt}

Return ONLY the relevant extracted information — no commentary, no meta-level analysis, no "according to the webpage" preambles. If the page does not contain information relevant to the prompt, respond with exactly: [NO_RELEVANT_CONTENT]

WEB PAGE CONTENT:
{content}
"""
