"""Shared logger config — COL (UTC-5) timestamps, no duplicates."""
import logging
from datetime import datetime, timezone, timedelta

COL = timezone(timedelta(hours=-5))

_FORMAT = logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s")
_FORMAT.converter = lambda t: datetime.now(COL).timetuple()

_registry: set[str] = set()


def get_logger(name: str) -> logging.Logger:
    """Returns a logger with COL timezone and no propagation to root."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if name not in _registry:
        _registry.add(name)
        h = logging.StreamHandler()
        h.setFormatter(_FORMAT)
        logger.addHandler(h)

    return logger


def configure_root():
    """Apply COL timezone to the root logger for modules that don't use get_logger."""
    root = logging.getLogger()
    for h in root.handlers:
        h.setFormatter(_FORMAT)
