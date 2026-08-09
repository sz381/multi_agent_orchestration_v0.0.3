"""应用配置模块，基于 pydantic-settings 从 .env 文件加载。

提供：
- settings 单例：全局配置入口，所有字段均有合理默认值
- setup_langsmith_tracing()：启动时一次性接入 LangSmith 追踪

关键约束：
- 配置字段名与 .env 键名严格对应，字段均可被 .env 覆盖
- extra="forbid"：禁止未声明字段，尽早暴露拼写错误

使用注意：
- 配置在模块导入时即实例化，修改 .env 后需重启进程生效
- setup_langsmith_tracing() 幂等，仅当 langsmith_tracing 与 langsmith_api_key 同时配置时才会生效
"""

import logging
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

import structlog

_logger = structlog.get_logger(__name__)


class Settings(BaseSettings):
    """
    全局应用配置类
    """
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model_name: str = "deepseek-v4-flash"

    xiaomi_mimo_api_key: str | None = None
    xiaomi_mimo_base_url: str = "https://api.xiaomimimo.com/v1"
    xiaomi_mimo_model_name: str = "mimo-v2.5"

    tavily_api_key: str | None = None

    workspace_dir: str | None = None

    langsmith_tracing: bool = False
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_api_key: str | None = None
    langsmith_project: str = "Mr Orchestra"

    log_level: str = "INFO"
    dev_mode: bool = True
    console_print: bool = True

    database_url: str = ""


settings = Settings()

_langsmith_initialized = False


def setup_langsmith_tracing() -> None:
    """
    将 LangSmith 配置注入环境变量，完成启动期追踪接入。
    """
    global _langsmith_initialized

    if _langsmith_initialized:
        return

    if settings.langsmith_api_key and settings.langsmith_tracing:
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
        os.environ["LANGSMITH_TRACING"] = "true"
        _logger.info("LangSmith automatic tracking is Enabled", project=settings.langsmith_project)
    else:
        _logger.info("LangSmith automatic tracking is Disabled")

    _langsmith_initialized = True
    