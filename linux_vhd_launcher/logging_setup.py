"""Logging configuration helpers."""

from __future__ import annotations

import logging


def setup_logging(level: str = "INFO") -> None:
    """Initialize root logging once for CLI/GUI entrypoints."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
