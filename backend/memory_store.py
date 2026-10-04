"""Per-user memories, stored as words only.

One file per user: data_dir/memories/<user_id>.jsonl, one line per memory:
    {"timestamp": "<when the picture was taken>", "description": "<what was seen>", "received_at": "<when the server got it>"}

No picture is ever written here, or anywhere else. That is the product's promise: people are
comfortable being remembered in words ("a good evening with a friend"), not kept as photographs.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

USER_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class BadUserId(ValueError):
    """The user ID is missing or not safe to use as a file name."""


def check_user_id(user_id) -> str:
    if not isinstance(user_id, str) or not USER_ID.match(user_id):
        raise BadUserId("user_id must be 1-64 letters, digits, '-' or '_'")
    return user_id


class MemoryStore:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir) / "memories"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, user_id: str) -> Path:
        return self.root / f"{check_user_id(user_id)}.jsonl"

    def add(self, user_id: str, timestamp: str, description: str) -> dict:
        row = {"timestamp": timestamp, "description": description,
               "received_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        with self._lock, self._path(user_id).open("a", encoding="utf-8") as out:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def all(self, user_id: str) -> list[dict]:
        path = self._path(user_id)
        if not path.exists():
            return []
        with self._lock:
            lines = path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]
