"""基于 structlog 的结构化日志模块。

提供：
- setup_logging()：应用启动时一次性配置日志
- get_logger()：获取绑定名称的 structlog logger

关键约束：
- dev 模式：彩色输出到 stderr
- 生产模式：JSON 写入 logs/orchestration.log（10MB 轮转 × 5 份）+ 纯文本控制台兜底输出

使用注意：
- setup_logging() 必须在任何 get_logger() 之前调用
- 获取 logger 必须走 get_logger()（structlog），不要使用标准 logging.getLogger，否则日志会丢失
"""

import logging
import structlog
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(
    dev_mode: bool = True,
    log_level: int = logging.INFO,
) -> None:
    """应用启动时一次性配置 structlog。

    行为：
    - dev 模式：彩色 ConsoleRenderer 输出到 stderr，配置后直接返回
    - 生产模式：处理器链经 ProcessorFormatter 分发，JSON 写入轮转文件，纯文本输出到控制台兜底

    关键约束：
    - dev 模式不挂载标准 root handler
    - 生产模式同时挂载文件与控制台两个 handler

    使用注意：
    - 必须在任何 get_logger() 调用之前执行
    - 重复调用会重复挂载 handler，应保证仅启动时调用一次
    """
    timestamper = structlog.processors.TimeStamper(fmt="iso")

    if dev_mode:
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.stdlib.add_log_level,
                timestamper,
                structlog.dev.ConsoleRenderer(colors=True),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(sys.stderr),
            cache_logger_on_first_use=True,
        )
        return

    log_path = Path("logs/orchestration.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            timestamper,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    file_handler = RotatingFileHandler(
        str(log_path), maxBytes=10 * 1024 * 1024, backupCount=5,
    )
    file_handler.setFormatter(structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
    ))

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(colors=False),
    ))

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def get_logger(name: str = __name__) -> structlog.stdlib.BoundLogger:
    """返回绑定到指定名称的 structlog logger。

    使用注意：
    - 须在 setup_logging() 之后调用，否则无配置效果
    - 一律使用本函数获取 logger，避免标准 logging.getLogger 导致日志丢失
    """
    return structlog.get_logger(name)
