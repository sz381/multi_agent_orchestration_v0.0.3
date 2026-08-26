""" System Prompt

This prompt is used for the secondary model of the web_fetch tool.
Trigger condition: When the fetched page content exceeds a certain threshold 
(in terms of number of characters), the secondary model will reduce the input prompt.

Provide
- WEB_SUMMARIZE_TEMPLATE:       web page summarization template
"""

WEB_SUMMARIZE_TEMPLATE = """\
Extract and summarize content from the web page below. Focus specifically on:

{prompt}

Return ONLY the relevant extracted information — no commentary, no meta-level analysis, no "according to the webpage" preambles. If the page does not contain information relevant to the prompt, respond with exactly: [NO_RELEVANT_CONTENT]

WEB PAGE CONTENT:
{content}
"""
