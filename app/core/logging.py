"""Application logging.

This is deliberately separate from the audit trail stored in the database:

* **Application log** (this module) — diagnostics for whoever maintains MedFlow.
  Timings, warnings, stack traces. Not shown to users, not a record of care.
* **Audit log** (``audit_log`` table via ``AuditService``) — who changed which
  record and when. Part of the clinical record, shown in the Activity view.

Conflating the two produces logs that are both noisy for developers and
incomplete for auditors.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from app.config.constants import APP_NAME, LOG_FILENAME

#: Root logger for the application. Every module logs beneath this name.
LOGGER_NAME = "medflow"

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a logger beneath the application root logger.

    ``name`` is a short component label such as ``"patient_service"``; it is
    namespaced automatically so output stays filterable.
    """
    if not name or name == LOGGER_NAME:
        return logging.getLogger(LOGGER_NAME)
    if name.startswith(f"{LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def configure_logging(
    *,
    level: str = "INFO",
    log_directory: str | Path | None = None,
    filename: str = LOG_FILENAME,
    to_console: bool = True,
    max_bytes: int = 1_000_000,
    backup_count: int = 5,
) -> logging.Logger:
    """Configure the application root logger and return it.

    Safe to call repeatedly: existing handlers are removed first, so calling this
    from several tests does not multiply output. When ``log_directory`` is
    ``None`` or cannot be created, logging falls back to the console rather than
    preventing the application from starting — MedFlow must still run if its log
    directory is read-only or on a disconnected drive.
    """
    global _configured

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(_coerce_level(level))
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    if log_directory is not None:
        try:
            directory = Path(log_directory)
            directory.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                directory / filename,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError:
            # A missing or unwritable log directory must not stop the app.
            logger.addHandler(logging.NullHandler())

    if to_console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    if not logger.handlers:
        logger.addHandler(logging.NullHandler())

    _configured = True
    logger.debug("%s logging initialised at %s level", APP_NAME, level)
    return logger


def is_configured() -> bool:
    """Whether :func:`configure_logging` has run in this process."""
    return _configured


def _coerce_level(level: str | int) -> int:
    """Turn a level name into its numeric value, defaulting to INFO."""
    if isinstance(level, int):
        return level
    resolved = logging.getLevelName(str(level).upper())
    return resolved if isinstance(resolved, int) else logging.INFO
