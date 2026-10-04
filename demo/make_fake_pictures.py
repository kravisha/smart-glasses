"""Make a folder of 60 stand-in "pictures" of a walk around the house, for trying the whole loop without a
camera or a GPU. Each file holds the words the fake describer will "see" (FAKE:<words>). The keys show up
twice: early on the kitchen counter, later on the bedside table, so the right answer is the bedside table.

    python -m demo.make_fake_pictures demo/fake_walk
    python -m backend.server                       # fake describer is the default
    python -m frontend.send_folder --folder demo/fake_walk --user krish --ask "Where are my keys?"

For the real demo, put your own phone pictures in a folder and run the server with --describer ollama.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOMS = [
    "Front door. Shoes on a mat, an umbrella in a stand.",
    "Hallway. A coat rack with two jackets, a mirror on the wall.",
    "Living room. A grey sofa, a television, a plant by the window.",
    "Living room. A coffee table with a remote control and two cups.",
    "Kitchen. A fridge, a kettle on the counter, a fruit bowl with bananas.",
    "Kitchen. A sink with plates, a dish rack, a window above the sink.",
    "Dining room. A table with six chairs and a vase of flowers.",
    "Study. A desk with a laptop, a lamp, a stack of books.",
    "Bathroom. A sink, a mirror, a toothbrush in a cup.",
    "Bedroom. A bed with a blue blanket, a wardrobe, curtains.",
]
KEYS_EARLY = (14, "Kitchen. Keys in a white bowl on the counter, next to a phone.")
KEYS_LATE = (47, "Bedroom. Keys on the bedside table next to a lamp and a glass of water.")


def make(folder: Path, count: int = 60) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        words = {KEYS_EARLY[0]: KEYS_EARLY[1], KEYS_LATE[0]: KEYS_LATE[1]}.get(i, ROOMS[i % len(ROOMS)])
        (folder / f"frame_{i:03d}.fake").write_bytes(b"FAKE:" + words.encode("utf-8"))
    return folder


if __name__ == "__main__":
    target = make(Path(sys.argv[1] if len(sys.argv) > 1 else "demo/fake_walk"))
    print(f"60 stand-in pictures written to {target}")
