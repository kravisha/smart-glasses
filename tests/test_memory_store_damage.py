"""A memory file damaged by a crash must not take the user's memories with it (Claude Dev's review probes of c4e5ed3b, 2026-10-04: R1, R2, R3; fixes by Claude Deploy).

  R1  a half-written line does not make every later question fail: the readable memories still answer
  R2  a half-written line does not stop new pictures, and the next row is not glued onto it
  R3  a crash while pruning leaves the file exactly as it was (the rewrite is whole or absent)
  R4  pruning keeps an unreadable line as it is, and still drops the old readable rows
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from backend.memory_store import MemoryStore

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)
HALF = '{"timestamp": "2026-10-04T10:05:00Z", "descr'


class StoreDamageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)

    def store(self, keep_days=90):
        return MemoryStore(self.data, keep_days=keep_days, now=lambda: NOW)

    def file(self):
        return self.data / "memories" / "krish.jsonl"

    def test_R1_a_half_written_line_does_not_lock_the_user_out_of_their_questions(self):
        store = self.store()
        store.add("krish", "2026-10-04T10:00:00Z", "keys on the bedside table")
        with self.file().open("a", encoding="utf-8") as out:
            out.write(HALF)
        self.assertEqual([row["description"] for row in store.all("krish")], ["keys on the bedside table"])

    def test_R2_a_half_written_line_does_not_stop_new_pictures_and_does_not_eat_the_next_one(self):
        store = self.store()
        store.add("krish", "2026-10-04T10:00:00Z", "keys on the bedside table")
        with self.file().open("a", encoding="utf-8") as out:
            out.write(HALF)
        store.add("krish", "2026-10-04T10:10:00Z", "a lamp")
        self.assertEqual([row["description"] for row in store.all("krish")], ["keys on the bedside table", "a lamp"])
        self.assertEqual(self.file().read_text(encoding="utf-8").count("\n"), 3, "the broken line is still its own line, the new row is its own line")

    def test_R3_a_crash_while_pruning_loses_nothing(self):
        store = self.store(keep_days=30)
        old = (NOW - timedelta(days=60)).isoformat(timespec="seconds")
        fresh = (NOW - timedelta(days=1)).isoformat(timespec="seconds")
        self.file().parent.mkdir(parents=True, exist_ok=True)
        rows = [{"timestamp": old, "description": "an old one", "received_at": old}, {"timestamp": fresh, "description": "keys on the bedside table", "received_at": fresh}]
        self.file().write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        before = self.file().read_text(encoding="utf-8")
        real = Path.write_text

        def dies_half_way(path, text, *args, **kwargs):
            if path.parent == self.file().parent:
                real(path, text[: len(text) // 2], *args, **kwargs)      # whatever is being written is cut in half ...
                raise OSError("the process was killed")                    # ... and the process dies
            return real(path, text, *args, **kwargs)

        with mock.patch.object(Path, "write_text", dies_half_way):
            with self.assertRaises(OSError):
                store.add("krish", "2026-10-04T11:00:00Z", "a lamp")
        self.assertEqual(self.file().read_text(encoding="utf-8"), before, "the memories are exactly as they were: the rewrite is whole or absent")

    def test_R4_pruning_keeps_an_unreadable_line_and_still_drops_the_old_rows(self):
        store = self.store(keep_days=30)
        old = (NOW - timedelta(days=60)).isoformat(timespec="seconds")
        fresh = (NOW - timedelta(days=1)).isoformat(timespec="seconds")
        self.file().parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps({"timestamp": old, "description": "an old one", "received_at": old}), HALF,
                 json.dumps({"timestamp": fresh, "description": "keys on the bedside table", "received_at": fresh})]
        self.file().write_text("\n".join(lines) + "\n", encoding="utf-8")
        store.add("krish", "2026-10-04T11:00:00Z", "a lamp")
        text = self.file().read_text(encoding="utf-8")
        self.assertNotIn("an old one", text)
        self.assertIn(HALF, text, "the unreadable line is kept untouched")
        self.assertEqual([row["description"] for row in store.all("krish")], ["keys on the bedside table", "a lamp"])

    def test_R5_a_line_that_is_valid_json_but_not_a_memory_is_skipped_too(self):
        store = self.store()
        store.add("krish", "2026-10-04T10:00:00Z", "keys on the bedside table")
        with self.file().open("a", encoding="utf-8") as out:
            out.write("42\n[1, 2]\nnull\n")
        self.assertEqual([row["description"] for row in store.all("krish")], ["keys on the bedside table"])
        store.add("krish", "2026-10-04T10:10:00Z", "a lamp")
        self.assertEqual(len(store.all("krish")), 2)


if __name__ == "__main__":
    unittest.main()
