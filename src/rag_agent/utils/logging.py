"""Logging setup for console and file output."""

from __future__ import annotations

import logging
from pathlib import Path

from rag_agent.config import get_settings

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_LOG_FILE = "rag_agent.log"


def setup_logging(*, verbose: bool = False, to_file: bool = True) -> None:
    """Configure the root logger once, for the whole process.

    Console output follows the verbose flag; the file always keeps INFO so a
    problem reported after the fact is still traceable.
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setLevel(logging.INFO if verbose else logging.WARNING)
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(console)

    if to_file:
        root.addHandler(_build_file_handler(get_settings().log_dir))


def _build_file_handler(log_dir: Path) -> logging.Handler:
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_dir / _LOG_FILE, encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    return handler
