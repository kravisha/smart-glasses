"""The Smart Glasses back end: a small service on your PC that waits for messages from the front end.

One address, POST /message, JSON. Every message carries the user's ID. There are two kinds:

  1. A picture:   {"user_id": "krish", "timestamp": "2026-10-04T13:05:00Z", "image_base64": "..."}
     The picture is turned into words straight away, the words are saved as a memory under that user,
     the picture is dropped, and the reply is only an acknowledgement:
         {"ack": true, "user_id": "krish", "timestamp": "..."}

  2. A question:  {"user_id": "krish", "question": "Where are my keys?"}
     The question is searched over that user's memories only, and the reply is the answer:
         {"answer": "Last seen at ...: ...", "matches": [...]}

GET /health answers {"ok": true}. Anything malformed gets HTTP 400 with {"error": "..."}.

The picture is never written to disk: it lives only in memory for the time it takes to describe it.

Run it:
    python -m backend.server                                  # fake describer, for trying the plumbing
    python -m backend.server --describer ollama --model <vision model>     # the real thing on your PC
    add --host 0.0.0.0 to let a phone on the same wifi reach it
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from backend.answer import answer
from backend.describers import DescribeFailed, FakeDescriber, OllamaDescriber
from backend.memory_store import BadUserId, MemoryStore, check_user_id

MAX_BODY = 5 * 1024 * 1024          # a low-resolution frame is tens of kilobytes; 5 MB is generous
MAX_QUESTION = 500


class BadMessage(ValueError):
    pass


def _check_timestamp(value) -> str:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise BadMessage("a picture needs a timestamp (ISO 8601, e.g. 2026-10-04T13:05:00Z)")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise BadMessage(f"timestamp {value!r} is not ISO 8601") from None
    return value


def handle(message, store: MemoryStore, describe, log=None) -> dict:
    """One message in, one reply out. Raises BadMessage, BadUserId or DescribeFailed."""
    if not isinstance(message, dict):
        raise BadMessage("the message must be a JSON object")
    user_id = check_user_id(message.get("user_id"))
    has_picture, has_question = "image_base64" in message, "question" in message
    if has_picture and has_question:
        raise BadMessage("send a picture or a question, not both")
    if has_picture:
        timestamp = _check_timestamp(message.get("timestamp"))
        try:
            image = base64.b64decode(message.get("image_base64") or "", validate=True)
        except (binascii.Error, TypeError, ValueError):
            raise BadMessage("image_base64 is not valid base64") from None
        if not image:
            raise BadMessage("the picture is empty")
        started = time.monotonic()
        description = describe(image)
        del image                                   # the picture goes no further than this function
        store.add(user_id, timestamp, description)
        if log:
            log(f"{user_id} {timestamp} described in {time.monotonic() - started:.2f}s: {description}")
        return {"ack": True, "user_id": user_id, "timestamp": timestamp}
    if has_question:
        question = message.get("question")
        if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION:
            raise BadMessage(f"the question must be text, 1-{MAX_QUESTION} characters")
        return answer(store.all(user_id), question)
    raise BadMessage("send either image_base64 with a timestamp, or a question")


def make_handler(store: MemoryStore, describe, log=None):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: dict) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")    # the front-end page may be opened from a file
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            if self.path == "/health":
                self._send(200, {"ok": True})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/message":
                self._send(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length <= 0 or length > MAX_BODY:
                self._send(400, {"error": f"the body must be 1 byte to {MAX_BODY} bytes of JSON"})
                return
            try:
                message = json.loads(self.rfile.read(length).decode("utf-8"))
                self._send(200, handle(message, store, describe, log))
            except (ValueError, BadMessage, BadUserId) as error:
                self._send(400, {"error": str(error)})
            except DescribeFailed as error:
                self._send(502, {"error": str(error)})

        def log_message(self, format, *args):       # no request lines in the console; the describe log is enough
            pass

    return Handler


def make_server(host: str, port: int, data_dir: Path, describe, log=None) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(MemoryStore(data_dir), describe, log))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Smart Glasses back end")
    parser.add_argument("--host", default="127.0.0.1", help="127.0.0.1 = this PC only; 0.0.0.0 = phones on your wifi too")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", type=Path, default=Path("data"), help="where the memories (words only) are kept")
    parser.add_argument("--describer", choices=("fake", "ollama"), default="fake")
    parser.add_argument("--model", help="the Ollama vision model, required with --describer ollama")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    args = parser.parse_args(argv)
    if args.describer == "ollama":
        if not args.model:
            parser.error("--describer ollama needs --model (a vision model you have pulled in Ollama)")
        describe = OllamaDescriber(args.model, args.ollama_url)
    else:
        describe = FakeDescriber()
    server = make_server(args.host, args.port, args.data, describe, log=lambda line: print(line, flush=True))
    print(f"Smart Glasses back end on http://{args.host}:{server.server_address[1]}  describer={args.describer}"
          f"{' model=' + args.model if args.model else ''}  memories in {args.data.resolve()}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
