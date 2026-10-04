"""The demo, end to end: 60 pictures of a walk around the house go in through the real front-end sender to the
real back-end server, one per second, and then "Where are my keys?" is answered from the words alone."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from demo.make_fake_pictures import make
from frontend.send_folder import pictures_in, post, send_folder
from tests.test_backend import RunningServer


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.s = RunningServer()
        self.addCleanup(self.s.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = make(Path(self.tmp.name) / "walk")

    def test_sixty_pictures_in_then_where_are_my_keys(self):
        sleeps = []
        clock = iter(datetime(2026, 10, 4, 17, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=i) for i in range(1000))
        replies = send_folder(self.folder, "krish", self.s.url, delay=1.0, sleep=sleeps.append, now=lambda: next(clock), out=lambda _l: None)

        self.assertEqual(len(replies), 60)
        self.assertTrue(all(r.get("ack") for r in replies), [r for r in replies if not r.get("ack")])
        self.assertEqual(sleeps, [1.0] * 59, "one second between pictures, none before the first")

        reply = post(self.s.url, {"user_id": "krish", "question": "Where are my keys?"})
        self.assertIn("bedside table", reply["answer"])              # the most recent sighting, frame 47
        self.assertIn("2026-10-04T17:00:47+00:00", reply["answer"])
        self.assertIn("kitchen", reply["matches"][1]["description"].lower())   # the earlier sighting is still there

        stored = [p for p in self.s.data.rglob("*") if p.is_file()]
        self.assertEqual([p.name for p in stored], ["krish.jsonl"], "only words were kept")

    def test_the_sender_only_picks_up_pictures(self):
        (self.folder / "notes.txt").write_text("not a picture", encoding="utf-8")
        self.assertEqual(len(pictures_in(self.folder)), 60)


if __name__ == "__main__":
    unittest.main()
