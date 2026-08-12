"""Agent Web 工具实现

提供函数：
- web_search:               执行网页搜索
- web_fetch:                获取网页内容

关键约束：
- 

使用注意：
- 
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
# from utils.model import ainvoke_with_retry
from core.prompts.web_page_summarizer import WEB_SUMMARIZE_TEMPLATE

logger = get_logger()




