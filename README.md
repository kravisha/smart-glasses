# Smart Glasses

A demo of memory glasses. Pictures go in, words come out. The back end turns each picture into a short
description the moment it arrives, saves only the words under that user, and throws the picture away.
You then ask a question ("Where are my keys?") and it answers from the words.

Why words only: people are comfortable being *remembered* ("a good evening with a friend, a couple of drinks"),
not kept as photographs. No picture is ever written to disk, by design and by test.

## What's inside

| Part | What it does |
|---|---|
| `backend/server.py` | The service on your PC. One address, `POST /message`. A **picture** (user ID + timestamp + image) is described, saved as words, dropped, and answered with an acknowledgement only. A **question** (user ID + question) is answered from that user's memories only. |
| `backend/describers.py` | Picture to words. `OllamaDescriber` uses a small vision model running locally in Ollama. `FakeDescriber` is for tests and for trying the plumbing without a GPU. |
| `backend/answer.py` | Question to answer: keyword search over the user's words; ties go to the most recent sighting. |
| `backend/memory_store.py` | One words-only file per user: `data/memories/<user_id>.jsonl`. |
| `frontend/index.html` | The app: pick a folder of pictures, it shrinks each to low resolution and sends one per second; then type a question. Open it in a browser. |
| `frontend/send_folder.py` | The same thing from the command line. |
| `demo/make_fake_pictures.py` | 60 stand-in pictures of a walk around the house, keys included, for a run with no camera or GPU. |

Python 3.10+, standard library only. Pillow is optional (`pip install pillow`) so the command-line sender can
shrink real photos; the browser page shrinks them itself.

## Try the plumbing (no GPU)

```
py -m demo.make_fake_pictures demo/fake_walk
py -m backend.server
py -m frontend.send_folder --folder demo/fake_walk --user krish --ask "Where are my keys?"
```

The last line should end with something like
`Last seen at ...: Bedroom. Keys on the bedside table next to a lamp and a glass of water.`

## The real demo, on your PC

1. Pull a small vision model in Ollama (any vision model works; check with `ollama list`):
   `ollama pull <vision model>`
2. Start the back end with it:
   `py -m backend.server --describer ollama --model <vision model>`
3. Walk around the house taking about 60 pictures with your phone, and copy them into a folder on the PC.
4. Open `frontend/index.html` in a browser, pick that folder, press **Send**, then ask *Where are my keys?*

To let a phone on the same wifi reach the back end, add `--host 0.0.0.0` and use the PC's address
(for example `http://192.168.1.20:8765`) in the page. Only do that on your home network: the service has no login yet.

## Speed

Describing is the only expensive step; answering is instant once everything is words. One picture a second
is the target. The levers are: low resolution (the page sends at most 320 pixels on the longest side), a
small vision model, and short descriptions. The server prints how long each picture took, so you can see
whether a model keeps up. For the demo it does not have to: the folder simply takes longer.

## Tests

```
py -m unittest discover -s tests -t . -v
```

15 tests, including the whole demo end to end: 60 pictures through the real sender into the real server,
one second apart, then "Where are my keys?". Each key promise was also broken on purpose to confirm a test
catches it: a picture saved to disk, one user seeing another's memories, a failed description stored anyway,
and eight more (11 of 11 caught).

## Not done yet

- The real vision model has not been run against this code; it needs the GPU on your PC (`--describer ollama`).
- No login: the user ID is trusted as sent. Fine for a home demo, not for anything public.
- The browser page has been syntax-checked, not clicked through in a browser.
