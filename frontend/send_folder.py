"""The Smart Glasses front end, command-line version: play a folder of pictures into the back end as if they
came off the glasses, one per second, then ask a question.

    python -m frontend.send_folder --folder demo/pictures --user krish
    python -m frontend.send_folder --user krish --ask "Where are my keys?"

Each picture is sent with the user's ID and a timestamp (the moment it is sent, like a live capture).
Pictures are shrunk to low resolution first when Pillow is installed (pip install pillow); without it they
are sent as they are, and the browser front end (frontend/index.html) shrinks them itself.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PICTURE_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".fake"}


def pictures_in(folder: Path) -> list[Path]:
    return sorted(p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in PICTURE_TYPES)


def shrink(data: bytes, max_side: int) -> bytes:
    """Low resolution before it leaves the device: faster to describe, and less of a photograph to begin with."""
    try:
        from PIL import Image
    except ImportError:
        return data
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = image.convert("RGB")
            image.thumbnail((max_side, max_side))
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=70)
            return out.getvalue()
    except Exception:                                   # not a real image (e.g. a .fake test file): send it unchanged
        return data


def post(server: str, message: dict, timeout: float = 120.0) -> dict:
    request = urllib.request.Request(server.rstrip("/") + "/message", data=json.dumps(message).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return json.loads(reply.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return {"error": f"HTTP {error.code}: {error.read().decode('utf-8', errors='replace')}"}


def send_folder(folder: Path, user_id: str, server: str, delay: float = 1.0, max_side: int = 320,
                sleep=time.sleep, now=lambda: datetime.now(timezone.utc), out=print) -> list[dict]:
    replies = []
    files = pictures_in(folder)
    for index, path in enumerate(files):
        if index:
            sleep(delay)                                # one frame a second, the glasses' own pace
        image = shrink(path.read_bytes(), max_side)
        reply = post(server, {"user_id": user_id, "timestamp": now().isoformat(timespec="seconds"),
                              "image_base64": base64.b64encode(image).decode("ascii")})
        out(f"{index + 1}/{len(files)} {path.name}: {'ok' if reply.get('ack') else reply.get('error', reply)}")
        replies.append(reply)
    return replies


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Smart Glasses front end (command line)")
    parser.add_argument("--server", default="http://127.0.0.1:8765")
    parser.add_argument("--user", required=True, help="your user ID")
    parser.add_argument("--folder", type=Path, help="a folder of pictures to send, one per second")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between pictures")
    parser.add_argument("--max-side", type=int, default=320, help="longest side in pixels after shrinking")
    parser.add_argument("--ask", help="a question to ask after sending (or on its own)")
    args = parser.parse_args(argv)
    if not args.folder and not args.ask:
        parser.error("give --folder, --ask, or both")
    if args.folder:
        replies = send_folder(args.folder, args.user, args.server, args.delay, args.max_side)
        failed = sum(1 for r in replies if not r.get("ack"))
        print(f"sent {len(replies)} pictures, {failed} failed")
    if args.ask:
        reply = post(args.server, {"user_id": args.user, "question": args.ask})
        print(reply.get("answer") or reply.get("error"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
