"""Application logging.

Audit logs answer "who changed what" and live in the database; application
logs answer "what did the software do" and live on disk. This module owns the
latter: a rotating file logger plus console mirror, both configurable.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_configured = False


def setup_logging(log_dir: Path | str | None = None, level: int = logging.INFO,
                  console: bool = True) -> logging.Logger:
    """Configure the root ``medflow`` logger once; safe to call repeatedly."""
    global _configured
    logger = logging.getLogger("medflow")
    if _configured:
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter(_LOG_FORMAT)

    if log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_path / "medflow.log", maxBytes=1_000_000, backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        logger.addHandler(stream)

    _configured = True
    logger.info("MedFlow logging initialised")
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"medflow.{name}")
