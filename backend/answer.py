"""Answering a question from one user's memories.

Once pictures are words, finding things is cheap: the question becomes a set of search words, every
memory of that user is scored by how many of them it contains, and the best match wins. When several
memories match equally, the MOST RECENT wins, because for "where are my keys?" the latest sighting is
where they are now.
"""
from __future__ import annotations

import re

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "am", "do", "does", "did", "i", "my", "me", "mine",
    "you", "your", "we", "our", "it", "its", "of", "in", "on", "at", "to", "for", "from", "with", "and", "or",
    "where", "what", "when", "which", "who", "how", "did", "have", "has", "had", "see", "saw", "seen", "last",
    "put", "left", "leave", "find", "can", "could", "there", "this", "that", "these", "those", "some", "any",
    "please", "tell", "show",
}


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("es") and (word[-3] in "sxz" or word[-4:-2] in ("ch", "sh")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def terms(text: str) -> set[str]:
    return {_singular(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS}


def search(memories: list[dict], question: str, limit: int = 3) -> list[dict]:
    """Matching memories, best first: more search words matched, then more recent."""
    wanted = terms(question)
    if not wanted:
        return []
    scored = []
    for memory in memories:
        hits = len(wanted & terms(memory.get("description", "")))
        if hits:
            scored.append((hits, memory.get("timestamp", ""), memory))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [memory for _hits, _when, memory in scored[:limit]]


def answer(memories: list[dict], question: str) -> dict:
    found = search(memories, question)
    if not found:
        return {"answer": "I don't have a memory of that.", "matches": []}
    best = found[0]
    return {"answer": f"Last seen at {best['timestamp']}: {best['description']}",
            "matches": [{"timestamp": m["timestamp"], "description": m["description"]} for m in found]}
