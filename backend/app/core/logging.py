"""
Central logging configuration.

Every module logs under the "docintel.*" namespace so evaluators can grep
a single logfile for the full lifecycle of a request: validation -> OCR ->
extraction -> financial validation -> persistence.
"""
from __future__ import annotations

import logging
import logging.handlers
import os

from app.core.config import get_settings

_CONFIGURED = False


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    settings = get_settings()
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    root = logging.getLogger("docintel")
    root.setLevel(level)
    root.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    log_file = os.path.join(settings.LOG_DIR, "app.log")
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Keep third-party libraries quieter unless something goes wrong.
    for noisy in ("pdfminer", "PIL", "urllib3", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
