"""Claude Dev's second-review tests of the memory store fix (kravisha/smart-glasses PR #1): the three survivors of his hand-breaks, each a missing test: S1 an add onto an existing empty file, S2 no blank line before the rows of a healthy file, S3 one new line only after a half line.

    python -m unittest tests.test_memory_store_append -v
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.memory_store import MemoryStore

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)


class AppendShapeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.store = MemoryStore(self.data, keep_days=90, now=lambda: NOW)
        self.file = self.data / "memories" / "krish.jsonl"

    def test_S1_an_add_onto_an_existing_EMPTY_file_works(self):
        """A file that exists and is empty (a prune that dropped every row, a touched file): there is no last byte to look at, and the add must not raise."""
        self.file.write_bytes(b"")
        self.store.add("krish", "2026-10-04T10:00:00Z", "keys on the bedside table")
        self.assertEqual([row["description"] for row in self.store.all("krish")], ["keys on the bedside table"])

    def test_S2_normal_adds_leave_exactly_one_line_per_memory_and_no_blank_lines(self):
        """The new line before an append is only for a file that does not end in one: a healthy file must not gain a blank line before every row."""
        for n in range(3):
            self.store.add("krish", f"2026-10-04T10:0{n}:00Z", f"memory {n}")
        text = self.file.read_bytes().decode("utf-8")
        self.assertEqual(len(text.split("\n")), 4, "three rows, each ending in a newline, nothing else")
        self.assertTrue(text.endswith("\n") and "\n\n" not in text.replace("\r\n", "\n"), text)

    def test_S3_an_append_after_an_unterminated_line_starts_a_new_line_only_once(self):
        """A half line gets ONE newline before the next row, and the row after that follows it directly."""
        self.store.add("krish", "2026-10-04T10:00:00Z", "first")
        with self.file.open("ab") as out:
            out.write(b'{"timestamp": "x", "descr')
        self.store.add("krish", "2026-10-04T10:01:00Z", "second")
        self.store.add("krish", "2026-10-04T10:02:00Z", "third")
        text = self.file.read_bytes().decode("utf-8").replace("\r\n", "\n")
        self.assertNotIn("\n\n", text)
        self.assertEqual([row["description"] for row in self.store.all("krish")], ["first", "second", "third"])


if __name__ == "__main__":
    unittest.main()
