"""Turning a picture into words. The only expensive step in the whole system.

Two describers, same shape: describe(image_bytes) -> str.

- OllamaDescriber: a small vision model running locally through Ollama on your PC. The picture goes to
  localhost only and is never written to disk.
- FakeDescriber: for tests and for trying the plumbing without a GPU. It cannot see. A "picture" whose
  bytes start with FAKE: is described as the text after it; anything else gets a fixed placeholder.
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request

PROMPT = ("You are the memory of a pair of smart glasses. In one or two short sentences, say what is in "
          "this picture: the room or place, the objects you can see, and where each object is "
          "(for example: 'Kitchen. Keys in a white bowl on the counter, next to a phone.'). "
          "Plain words only. Do not describe what people look like.")


class DescribeFailed(RuntimeError):
    """The describer could not turn the picture into words."""


class FakeDescriber:
    PREFIX = b"FAKE:"

    def __call__(self, image: bytes) -> str:
        if image.startswith(self.PREFIX):
            return image[len(self.PREFIX):].decode("utf-8", errors="replace").strip()
        return "A picture (the fake describer cannot see)."


class OllamaDescriber:
    def __init__(self, model: str, url: str = "http://localhost:11434", timeout: float = 60.0, max_words: int = 80):
        self.model, self.url, self.timeout, self.max_words = model, url.rstrip("/"), timeout, max_words

    def __call__(self, image: bytes) -> str:
        body = json.dumps({
            "model": self.model,
            "prompt": PROMPT,
            "images": [base64.b64encode(image).decode("ascii")],
            "stream": False,
            "options": {"num_predict": self.max_words * 2, "temperature": 0},
        }).encode("utf-8")
        request = urllib.request.Request(f"{self.url}/api/generate", data=body,
                                         headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as reply:
                text = json.loads(reply.read().decode("utf-8")).get("response", "")
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise DescribeFailed(f"Ollama at {self.url} did not describe the picture: {error}") from error
        text = " ".join(text.split())
        if not text:
            raise DescribeFailed("Ollama returned an empty description")
        return text
