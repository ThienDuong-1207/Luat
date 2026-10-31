"""Logging dạng key=value, một dòng mỗi bản ghi, để dễ grep và đưa vào metrics."""

from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s level=%(levelname)s logger=%(name)s msg=%(message)s"
_configured = False


def setup_logging(level: str = "INFO") -> None:
    """Cấu hình root logger một lần cho tiến trình."""
    global _configured
    if _configured:
        logging.getLogger().setLevel(level.upper())
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
