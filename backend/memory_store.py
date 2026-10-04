"""Per-user memories, stored as words only.

One file per user: data_dir/memories/<user_id>.jsonl, one line per memory:
    {"timestamp": "<when the picture was taken>", "description": "<what was seen>", "received_at": "<when the server got it>"}

With keep_days set, a user's memories older than that (by received_at) are dropped from the file each
time a new one is added, so the words do not pile up for ever. The server keeps 90 days by default.

No picture is ever written here, or anywhere else. That is the product's promise: people are
comfortable being remembered in words ("a good evening with a friend"), not kept as photographs.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

USER_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class BadUserId(ValueError):
    """The user ID is missing or not safe to use as a file name."""


def check_user_id(user_id) -> str:
    if not isinstance(user_id, str) or not USER_ID.match(user_id):
        raise BadUserId("user_id must be 1-64 letters, digits, '-' or '_'")
    return user_id


class MemoryStore:
    def __init__(self, data_dir: Path, keep_days: int | None = None, now=lambda: datetime.now(timezone.utc)):
        if keep_days is not None and keep_days < 1:
            raise ValueError("keep_days must be at least 1, or None to keep everything")
        self.root = Path(data_dir) / "memories"
        self.root.mkdir(parents=True, exist_ok=True)
        self.keep_days, self._now = keep_days, now
        self._lock = threading.Lock()

    def _fresh(self, row: dict, cutoff: datetime) -> bool:
        try:
            return datetime.fromisoformat(str(row.get("received_at", "")).replace("Z", "+00:00")) >= cutoff
        except ValueError:
            return True                                  # an unreadable date is kept, never silently lost

    def _prune(self, path: Path) -> None:
        """Called under the lock. Rewrites the file without the rows older than keep_days."""
        if self.keep_days is None or not path.exists():
            return
        cutoff = self._now() - timedelta(days=self.keep_days)
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        kept = [line for line in lines if self._fresh(json.loads(line), cutoff)]
        if len(kept) != len(lines):
            path.write_text("".join(line + "\n" for line in kept), encoding="utf-8")

    def _path(self, user_id: str) -> Path:
        return self.root / f"{check_user_id(user_id)}.jsonl"

    def add(self, user_id: str, timestamp: str, description: str) -> dict:
        row = {"timestamp": timestamp, "description": description,
               "received_at": self._now().isoformat(timespec="seconds")}
        path = self._path(user_id)
        with self._lock:
            self._prune(path)
            with path.open("a", encoding="utf-8") as out:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def all(self, user_id: str) -> list[dict]:
        path = self._path(user_id)
        if not path.exists():
            return []
        with self._lock:
            lines = path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]
