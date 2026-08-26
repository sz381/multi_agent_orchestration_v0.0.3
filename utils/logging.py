"""Structured logging module based on structlog.

Provides:
- setup_logging():  configure logging once at application startup
- get_logger():     get a structlog logger bound to a name

Key constraints:
- dev mode:         colored output to stderr
- production mode:  JSON to logs/orchestration.log, 10MB rotation with 
    5 backups, plus plain-text console fallback output

Usage notes:
- setup_logging() must be called before any get_logger()
- always get loggers via get_logger(), structlog; do not use standard 
    logging.getLogger, otherwise logs are lost
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
    """Configure structlog once at application startup.
    
    Behavior:
    - dev mode: colored ConsoleRenderer to stderr, returns right after setup
    - production mode: handler chain routed via ProcessorFormatter, JSON to a
      rotating file, plain text to console as fallback
    
    Key constraints:
    - dev mode does not attach standard root handlers
    - production mode attaches both file and console handlers
    
    Usage notes:
    - must run before any get_logger() call
    - repeated calls re-attach handlers; call it only once at startup
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
    """Return a structlog logger bound to the given name.
    
    Usage notes:
    - call after setup_logging(), otherwise no configuration takes effect
    - always use this function to get loggers, avoid standard logging.getLogger
      which causes lost logs
    """
    return structlog.get_logger(name)
