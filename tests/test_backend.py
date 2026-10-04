"""Back-end tests. Standard library only: python -m unittest discover -s tests -v"""
from __future__ import annotations

import base64
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from backend import server as S
from backend.answer import answer, terms
from backend.describers import DescribeFailed, FakeDescriber, OllamaDescriber
from backend.memory_store import MemoryStore


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class RunningServer:
    """The real HTTP server on a free port, in a thread, with its data in a temporary folder."""

    TOKEN = "test-token-123"

    def __init__(self, describe=None, allowed_origins=(), keep_days=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.server = S.make_server("127.0.0.1", 0, self.data, describe or FakeDescriber(), token=self.TOKEN,
                                    allowed_origins=allowed_origins, keep_days=keep_days)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def post(self, message, raw: bytes | None = None):
        status, _headers, body = self.request("POST", "/message", message, raw,
                                              {"Content-Type": "application/json", S.TOKEN_HEADER: self.TOKEN})
        return status, body

    def request(self, method, path, message=None, raw: bytes | None = None, headers=None):
        """Any request with exactly the headers given; returns (status, headers, parsed JSON body or None)."""
        data = raw if raw is not None else (json.dumps(message).encode("utf-8") if message is not None else None)
        request = urllib.request.Request(self.url + path, data=data, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as reply:
                status, got, body = reply.status, reply.headers, reply.read()
        except urllib.error.HTTPError as error:
            status, got, body = error.code, error.headers, error.read()
        return status, got, (json.loads(body) if body else None)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()


class AccessTests(unittest.TestCase):
    """Deploy's review of 93d68ffe, finding 1: any web page could read and write the memories (ACAO *)."""

    QUESTION = {"user_id": "krish", "question": "Where are my keys?"}

    def server(self, **kwargs):
        s = RunningServer(**kwargs)
        self.addCleanup(s.close)
        return s

    def test_a_message_without_the_token_is_refused_and_stores_nothing(self):
        s = self.server()
        picture = {"user_id": "krish", "timestamp": "2026-10-04T13:00:00Z", "image_base64": b64(b"FAKE:Kitchen. Keys.")}
        status, _h, body = s.request("POST", "/message", picture, headers={"Content-Type": "application/json"})
        self.assertEqual(status, 401)
        self.assertIn("token", body["error"])
        self.assertEqual(list((s.data / "memories").iterdir()), [])

    def test_a_wrong_token_is_refused(self):
        s = self.server()
        status, _h, _b = s.request("POST", "/message", self.QUESTION,
                                   headers={"Content-Type": "application/json", S.TOKEN_HEADER: "test-token-124"})
        self.assertEqual(status, 401)

    def test_the_review_attack_a_foreign_page_with_text_plain_gets_nothing(self):
        # Deploy's exact request: Origin evil.example, text/plain (no preflight). Was 200 with ACAO *.
        s = self.server()
        status, headers, body = s.request("POST", "/message", self.QUESTION,
                                          headers={"Content-Type": "text/plain", "Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        self.assertNotIn("answer", body)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_a_foreign_origin_is_refused_even_with_the_token(self):
        s = self.server(allowed_origins=("http://localhost:9000",))
        status, headers, _b = s.request("POST", "/message", self.QUESTION, headers={
            "Content-Type": "application/json", "Origin": "https://evil.example", S.TOKEN_HEADER: s.TOKEN})
        self.assertEqual(status, 403)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_no_response_ever_carries_the_wildcard(self):
        s = self.server(allowed_origins=("null",))
        for method, path, headers in (("GET", "/health", {}), ("GET", "/nowhere", {}),
                                      ("OPTIONS", "/message", {"Origin": "null"}),
                                      ("OPTIONS", "/message", {"Origin": "https://evil.example"})):
            _status, got, _b = s.request(method, path, headers=headers)
            self.assertNotEqual(got.get("Access-Control-Allow-Origin"), "*", (method, path, headers))
        _status, got, _b = s.request("POST", "/message", self.QUESTION, headers={
            "Content-Type": "application/json", "Origin": "null", S.TOKEN_HEADER: s.TOKEN})
        self.assertNotEqual(got.get("Access-Control-Allow-Origin"), "*")

    def test_a_preflight_from_a_foreign_origin_is_refused(self):
        s = self.server(allowed_origins=("http://localhost:9000",))
        status, headers, _b = s.request("OPTIONS", "/message", headers={
            "Origin": "https://evil.example", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, " + S.TOKEN_HEADER.lower()})
        self.assertEqual(status, 403)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_the_allowed_page_origin_passes_preflight_and_is_answered(self):
        s = self.server(allowed_origins=("http://localhost:9000",))
        status, headers, _b = s.request("OPTIONS", "/message", headers={
            "Origin": "http://localhost:9000", "Access-Control-Request-Method": "POST"})
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "http://localhost:9000")
        self.assertIn(S.TOKEN_HEADER, headers.get("Access-Control-Allow-Headers"))
        status, headers, body = s.request("POST", "/message", self.QUESTION, headers={
            "Content-Type": "application/json", "Origin": "http://localhost:9000", S.TOKEN_HEADER: s.TOKEN})
        self.assertEqual(status, 200)
        self.assertIn("answer", body)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "http://localhost:9000")

    def test_a_page_opened_from_a_file_needs_the_explicit_null_flag(self):
        # A file:// page sends "Origin: null". Refused by default, allowed only when "null" is listed.
        headers = {"Content-Type": "application/json", "Origin": "null", S.TOKEN_HEADER: RunningServer.TOKEN}
        status, _h, _b = self.server().request("POST", "/message", self.QUESTION, headers=headers)
        self.assertEqual(status, 403)
        status, got, _b = self.server(allowed_origins=("null",)).request("POST", "/message", self.QUESTION, headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(got.get("Access-Control-Allow-Origin"), "null")

    def test_the_command_line_sender_sends_no_origin_and_gets_in_with_the_token(self):
        s = self.server()
        status, headers, body = s.request("POST", "/message", self.QUESTION,
                                          headers={"Content-Type": "application/json", S.TOKEN_HEADER: s.TOKEN})
        self.assertEqual(status, 200)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_health_needs_no_token_and_says_nothing_about_users(self):
        status, _h, body = self.server().request("GET", "/health")
        self.assertEqual((status, body), (200, {"ok": True}))

    def test_without_a_token_flag_the_server_makes_a_long_random_one(self):
        a, b = S.new_token(), S.new_token()
        self.assertNotEqual(a, b)
        self.assertGreaterEqual(len(a), 32)
        with self.assertRaises(ValueError):
            S.make_server("127.0.0.1", 0, Path(tempfile.mkdtemp()), FakeDescriber(), token="")


class DefaultsTests(unittest.TestCase):
    """Deploy's finding 2: 8765 is the live website's port on the deploy PC."""

    def test_the_default_port_is_8830_everywhere(self):
        from frontend import send_folder
        self.assertEqual(S.DEFAULT_PORT, 8830)
        root = Path(__file__).resolve().parent.parent
        for name in ("backend/server.py", "frontend/send_folder.py", "frontend/index.html", "README.md"):
            text = (root / name).read_text(encoding="utf-8")
            self.assertNotIn("8765", text, name)
        self.assertIn("127.0.0.1:8830", (root / "frontend/index.html").read_text(encoding="utf-8"))
        self.assertTrue(send_folder.DEFAULT_SERVER.endswith(":8830"))

    def test_the_page_sends_the_token_header_from_its_token_box(self):
        page = (Path(__file__).resolve().parent.parent / "frontend/index.html").read_text(encoding="utf-8")
        self.assertIn(f'"{S.TOKEN_HEADER}": $("token").value', page)
        self.assertIn('<input id="token"', page)

    def test_the_prompt_tells_the_model_not_to_describe_people(self):
        # Finding 5b. Only the real model can show it obeys; this pins that it is asked.
        from backend.describers import PROMPT
        self.assertIn("Do not describe what people look like.", PROMPT)


class RetentionTests(unittest.TestCase):
    """Deploy's finding 5a: memories grew without limit."""

    def test_the_default_keep_is_90_days_like_the_website(self):
        self.assertEqual(S.DEFAULT_KEEP_DAYS, 90)

    def test_memories_older_than_the_keep_are_dropped_from_disk_when_the_next_one_arrives(self):
        from datetime import datetime, timedelta, timezone
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        now = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
        store = MemoryStore(Path(tmp.name), keep_days=90, now=lambda: now)
        path = store.root / "krish.jsonl"
        rows = [{"timestamp": "x", "description": d, "received_at": (now - timedelta(days=age)).isoformat()}
                for d, age in (("old", 91), ("edge", 89), ("new", 1))]
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        store.add("krish", "2026-10-04T12:00:00Z", "today")
        self.assertEqual([r["description"] for r in store.all("krish")], ["edge", "new", "today"])
        self.assertNotIn("old", path.read_text(encoding="utf-8"))

    def test_keep_none_keeps_everything(self):
        from datetime import datetime, timedelta, timezone
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        now = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
        store = MemoryStore(Path(tmp.name), keep_days=None, now=lambda: now)
        (store.root / "krish.jsonl").write_text(json.dumps(
            {"timestamp": "x", "description": "ancient", "received_at": (now - timedelta(days=4000)).isoformat()}) + "\n",
            encoding="utf-8")
        store.add("krish", "2026-10-04T12:00:00Z", "today")
        self.assertEqual([r["description"] for r in store.all("krish")], ["ancient", "today"])


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.s = RunningServer()
        self.addCleanup(self.s.close)

    def picture(self, text, user="krish", when="2026-10-04T13:00:00Z"):
        return self.s.post({"user_id": user, "timestamp": when, "image_base64": b64(b"FAKE:" + text.encode())})

    def test_a_picture_gets_only_an_acknowledgement_and_becomes_a_memory_in_words(self):
        status, reply = self.picture("Kitchen. Keys in a white bowl on the counter.")
        self.assertEqual(status, 200)
        self.assertEqual(reply, {"ack": True, "user_id": "krish", "timestamp": "2026-10-04T13:00:00Z"})
        rows = MemoryStore(self.s.data).all("krish")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], "Kitchen. Keys in a white bowl on the counter.")
        self.assertEqual(rows[0]["timestamp"], "2026-10-04T13:00:00Z")

    def test_the_picture_itself_is_never_written_anywhere(self):
        marker = b"FAKE:Hall. A distinctive marker 7f3a9c on the coat rack."
        encoded = b64(marker)
        status, _ = self.s.post({"user_id": "krish", "timestamp": "2026-10-04T13:00:00Z", "image_base64": encoded})
        self.assertEqual(status, 200)
        files = [p for p in self.s.data.rglob("*") if p.is_file()]
        self.assertEqual([p.suffix for p in files], [".jsonl"], "only the words file may exist")
        for path in files:
            raw = path.read_bytes()
            self.assertNotIn(encoded.encode(), raw, "the base64 picture was stored")
            self.assertNotIn(marker, raw, "the raw picture bytes were stored")

    def test_a_question_is_answered_from_that_users_memories_most_recent_sighting_first(self):
        self.picture("Kitchen. Keys in a white bowl on the counter.", when="2026-10-04T13:00:00Z")
        self.picture("Living room. Sofa, television, a plant.", when="2026-10-04T13:00:01Z")
        self.picture("Bedroom. Keys on the bedside table next to a lamp.", when="2026-10-04T13:00:02Z")
        status, reply = self.s.post({"user_id": "krish", "question": "Where are my keys?"})
        self.assertEqual(status, 200)
        self.assertIn("bedside table", reply["answer"])
        self.assertIn("2026-10-04T13:00:02Z", reply["answer"])
        self.assertEqual([m["timestamp"] for m in reply["matches"]], ["2026-10-04T13:00:02Z", "2026-10-04T13:00:00Z"])

    def test_one_user_never_sees_another_users_memories(self):
        self.picture("Garage. Keys hanging on a hook by the door.", user="shobhna")
        status, reply = self.s.post({"user_id": "krish", "question": "Where are my keys?"})
        self.assertEqual(status, 200)
        self.assertEqual(reply, {"answer": "I don't have a memory of that.", "matches": []})

    def test_every_message_needs_a_safe_user_id(self):
        for user in (None, "", "../etc", "a/b", "x" * 65, 42):
            message = {"timestamp": "2026-10-04T13:00:00Z", "image_base64": b64(b"FAKE:x")}
            if user is not None:
                message["user_id"] = user
            status, reply = self.s.post(message)
            self.assertEqual(status, 400, user)
            self.assertIn("user_id", reply["error"])
            status, _ = self.s.post({"user_id": user, "question": "where?"} if user is not None else {"question": "where?"})
            self.assertEqual(status, 400, user)
        self.assertFalse(list(self.s.data.rglob("*.jsonl")), "a refused message left a file behind")

    def test_malformed_messages_are_refused_and_store_nothing(self):
        cases = [
            ({"user_id": "krish"}, "either"),
            ({"user_id": "krish", "question": "where?", "image_base64": b64(b"FAKE:x"), "timestamp": "2026-10-04T13:00:00Z"}, "not both"),
            ({"user_id": "krish", "image_base64": b64(b"FAKE:x")}, "timestamp"),
            ({"user_id": "krish", "image_base64": b64(b"FAKE:x"), "timestamp": "yesterday"}, "ISO"),
            ({"user_id": "krish", "image_base64": "not base64!!", "timestamp": "2026-10-04T13:00:00Z"}, "base64"),
            ({"user_id": "krish", "image_base64": "", "timestamp": "2026-10-04T13:00:00Z"}, "empty"),
            ({"user_id": "krish", "question": "   "}, "question"),
            ({"user_id": "krish", "question": "x" * 501}, "question"),
            (["not", "an", "object"], "object"),
        ]
        for message, why in cases:
            status, reply = self.s.post(message)
            self.assertEqual(status, 400, message)
            self.assertIn(why, reply["error"], message)
        status, reply = self.s.post(None, raw=b"{not json")
        self.assertEqual(status, 400)
        self.assertFalse(list(self.s.data.rglob("*.jsonl")))

    def test_health_answers(self):
        with urllib.request.urlopen(self.s.url + "/health", timeout=5) as reply:
            self.assertEqual(json.loads(reply.read()), {"ok": True})


class DescribeFailureTests(unittest.TestCase):
    def test_a_picture_the_describer_cannot_read_is_not_acknowledged_and_not_stored(self):
        def broken(_image):
            raise DescribeFailed("model is down")
        s = RunningServer(describe=broken)
        self.addCleanup(s.close)
        status, reply = s.post({"user_id": "krish", "timestamp": "2026-10-04T13:00:00Z", "image_base64": b64(b"FAKE:x")})
        self.assertEqual(status, 502)
        self.assertIn("model is down", reply["error"])
        self.assertEqual(MemoryStore(s.data).all("krish"), [])


class AnswerTests(unittest.TestCase):
    def test_plurals_and_filler_words_do_not_get_in_the_way(self):
        self.assertEqual(terms("Where are my keys?"), {"key"})
        self.assertEqual(terms("where did I leave the glasses"), {"glass"})
        self.assertEqual(terms("batteries"), {"battery"})

    def test_more_words_matched_beats_more_recent(self):
        memories = [{"timestamp": "2026-10-04T13:00:00Z", "description": "Car keys on the kitchen counter."},
                    {"timestamp": "2026-10-04T13:00:05Z", "description": "Keys of the piano in the living room."}]
        self.assertIn("kitchen counter", answer(memories, "where are my car keys?")["answer"])

    def test_a_question_of_only_filler_words_finds_nothing(self):
        memories = [{"timestamp": "2026-10-04T13:00:00Z", "description": "Where is it? There it is."}]
        self.assertEqual(answer(memories, "where is it?")["matches"], [])


class OllamaDescriberTests(unittest.TestCase):
    """The real describer, against a stand-in for Ollama that records what it was sent."""

    def start_fake_ollama(self, reply_body: dict, status: int = 200):
        seen = []

        class Fake(BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                data = json.dumps(reply_body).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        httpd = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return f"http://127.0.0.1:{httpd.server_address[1]}", seen

    def test_it_sends_the_picture_to_the_local_model_and_returns_its_words(self):
        url, seen = self.start_fake_ollama({"response": "  Kitchen.\n Keys in a bowl.  "})
        image = b"\x89PNG fake picture bytes"
        text = OllamaDescriber("some-vision-model", url)(image)
        self.assertEqual(text, "Kitchen. Keys in a bowl.")
        path, body = seen[0]
        self.assertEqual(path, "/api/generate")
        self.assertEqual(body["model"], "some-vision-model")
        self.assertEqual(body["images"], [b64(image)])
        self.assertIs(body["stream"], False)
        self.assertIn("where each object is", body["prompt"])

    def test_an_unreachable_or_empty_model_is_a_describe_failure(self):
        url, _ = self.start_fake_ollama({"response": "   "})
        with self.assertRaises(DescribeFailed):
            OllamaDescriber("m", url)(b"x")
        url, _ = self.start_fake_ollama({"error": "model not found"}, status=404)
        with self.assertRaises(DescribeFailed):
            OllamaDescriber("m", url)(b"x")
        with self.assertRaises(DescribeFailed):
            OllamaDescriber("m", "http://127.0.0.1:9", timeout=2)(b"x")


if __name__ == "__main__":
    unittest.main()
