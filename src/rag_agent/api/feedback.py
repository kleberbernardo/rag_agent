"""What people thought of an answer.

The evaluation dataset is written by whoever built the system, which means it
tests the questions that person thought of. Feedback from real use is the only
source of the ones they did not.

Stored as JSON lines rather than in a database: the file is appended to, read
by any tool, and small enough that anything heavier would be infrastructure
without a reason. It is the input for new evaluation cases, so a thumbs-down
becomes a test instead of a memory.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FEEDBACK_FILE = "feedback.jsonl"


class FeedbackStore:
    """Appends one JSON object per piece of feedback."""

    def __init__(self, directory: Path) -> None:
        self._path = directory / FEEDBACK_FILE
        # Uvicorn serves sync endpoints from a thread pool, so two requests can
        # append at the same moment. A lock is cheaper than the interleaved
        # line it would otherwise write.
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def record(self, entry: dict[str, Any]) -> None:
        """Write one entry, stamped with the moment it arrived."""
        stamped = {"recorded_at": datetime.now(UTC).isoformat(timespec="seconds"), **entry}

        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(stamped, ensure_ascii=False) + "\n")

        logger.info("Feedback recorded for run %s", entry.get("run_id"))

    def read_all(self) -> list[dict[str, Any]]:
        """Every entry recorded so far, oldest first."""
        if not self._path.is_file():
            return []

        return [
            json.loads(line)
            for line in self._path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def unhelpful(self) -> list[dict[str, Any]]:
        """The answers people rejected: the candidates for new test cases."""
        return [entry for entry in self.read_all() if entry.get("useful") is False]
