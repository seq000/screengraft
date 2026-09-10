#!/usr/bin/env python3
"""Remembered fits, driven over HTTP the way the page drives them (SG51).

The property under test is not "a dict round-trips". It is that the SAME
PHOTOGRAPH is recognised however it arrives — re-exported to a new folder,
renamed, or dragged in so that the browser hands over bytes with no origin at
all. A key on the path passes a naive test and fails every one of those, which
is why each route gets its own check here rather than one check on the store.

The last check is the task's own acceptance line: a remembered fit must
reproduce the composite it came from, byte for byte. Corners that come back
0.5px out would look right on the canvas and quietly move boundary pixels — the
same failure mode as the rounded `radius_px` in SG15.

No ffmpeg: every path here is the still one, so this suite always runs.

Run: ~/.screengraft/venv/bin/python test/test_fits.py
"""
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, HERE)
import fits as FIT  # noqa: E402

from test_render_api import UI, FAILED, ok  # noqa: E402
from test_video import CORNERS, synth_photo  # noqa: E402

SHOT = (300, 300)
BODY = {"corners": CORNERS, "radius_frac": 0.05, "device": "phone",
        "grade": 0.0, "grain": False, "reflection": None}


def synth_shot(w=SHOT[0], h=SHOT[1], seed=3):
    """A screenshot with real structure, so a composite is not a flat fill."""
    rng = np.random.default_rng(seed)
    im = np.zeros((h, w, 3), np.uint8)
    im[:] = (40, 40, 44)
    cv2.rectangle(im, (20, 20), (w - 20, 90), (200, 190, 170), -1)
    cv2.putText(im, "screengraft", (26, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                (240, 240, 240), 2)
    im[h - 60:, :] = rng.integers(0, 255, (60, w, 3), dtype=np.uint8)
    return im


def upload(ui, role, path):
    """The drag-drop route: raw bytes, and a name the server has never seen."""
    req = urllib.request.Request(
        ui.url + "/api/upload", data=open(path, "rb").read(),
        headers={"X-Filename": urllib.parse.quote(os.path.basename(path)),
                 "X-Role": role})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)


def build(td, name):
    """A temp HOME with a photo and a screenshot in it.

    The session goes UNDER that home, where the real one lives: `_read_image`
    refuses to open anything outside the user's home, and an upload is read back
    from inside the session — so a session parked in the bare temp dir makes the
    drag-drop route answer "outside home", which is the server being right and
    the harness being wrong.
    """
    home = os.path.join(td, name, "home")
    os.makedirs(home)
    photo, shot = os.path.join(home, "photo.png"), os.path.join(home, "shot.png")
    cv2.imwrite(photo, synth_photo())
    cv2.imwrite(shot, synth_shot())
    ui = UI(home, os.path.join(home, ".screengraft", "sessions", name),
            os.path.join(td, name, "out"))
    return ui, home, photo, shot


def remembering(td):
    print("\na saved fit is remembered, and found again by the photo's PIXELS")
    ui, home, photo, shot = build(td, "a")
    try:
        _, first = ui.post("/api/use", {"role": "photo", "path": photo})
        ok("a photo nobody has fitted yet is remembered as nothing",
           "remembered" not in first, str(first.get("remembered"))[:80])

        ui.post("/api/use", {"role": "screenshot", "path": shot})
        code, saved = ui.post("/api/save", BODY)
        ok("the save succeeded", code == 200, str(saved)[:120])

        store = os.path.join(home, ".screengraft", "fits.json")
        ok("the store lives OUTSIDE the session, so the sweep cannot take it",
           os.path.isfile(store) and not store.startswith(ui.info["session"]))
        entries = json.load(open(store))["fits"]
        ok("exactly one fit was recorded", len(entries) == 1, str(len(entries)))
        entry = next(iter(entries.values()))
        ok("...with the corners that produced the output",
           entry["corners"] == [[float(x), float(y)] for x, y in CORNERS],
           str(entry["corners"]))
        ok("...the radius fraction", entry["radius_frac"] == BODY["radius_frac"])
        ok("...and the device", entry["device"] == "phone", str(entry.get("device")))
        ok("no absolute path is kept — a basename for display, nothing else",
           home not in json.dumps(entries), "the store names a real path")

        # The point of the whole feature: the same picture, arriving as a file
        # that has never existed before.
        moved = os.path.join(home, "exports", "Frame 12 (1).png")
        os.makedirs(os.path.dirname(moved))
        shutil.copy(photo, moved)
        _, again = ui.post("/api/use", {"role": "photo", "path": moved})
        r = again.get("remembered") or {}
        ok("re-picking the same image at a NEW PATH returns the fit",
           r.get("corners") == [[float(x), float(y)] for x, y in CORNERS],
           str(again.get("remembered"))[:100])
        ok("...and says when it was saved, so the page can state its age",
           isinstance(r.get("saved"), (int, float)))

        # Drag-drop: /api/upload writes a copy under a name invented from the
        # clock, so a path key could never match here even in principle.
        up = upload(ui, "photo", moved)
        ok("dragging the same image in returns it too",
           (up.get("remembered") or {}).get("corners")
           == [[float(x), float(y)] for x, y in CORNERS],
           str(up.get("remembered"))[:100])
        # realpath on both sides: the server resolves what it opens, and on a
        # Mac the temp dir is a symlink, so the raw strings differ by /private
        # while naming the same file.
        ok("...and the copy it made is NOT the path in the answer's key",
           up["path"] != moved
           and up["path"].startswith(os.path.realpath(ui.info["session"])),
           up["path"])

        other = os.path.join(home, "other.png")
        cv2.imwrite(other, synth_photo(w=880, h=700))
        _, o = ui.post("/api/use", {"role": "photo", "path": other})
        ok("a DIFFERENT photograph is not offered someone else's corners",
           "remembered" not in o, str(o.get("remembered"))[:80])
    finally:
        ui.stop()


def reproduces(td):
    print("\na remembered fit reproduces the composite it came from")
    ui, home, photo, shot = build(td, "b")
    try:
        ui.post("/api/use", {"role": "photo", "path": photo})
        ui.post("/api/use", {"role": "screenshot", "path": shot})
        _, saved = ui.post("/api/save", BODY)
        first = cv2.imread(saved["output"])

        # A second run, from scratch, driven only by what came back in
        # `remembered` — which is exactly what the page does with it.
        ui2 = UI(home, os.path.join(home, ".screengraft", "sessions", "b2"),
                 os.path.join(td, "b", "out2"))
        try:
            _, p = ui2.post("/api/use", {"role": "photo", "path": photo})
            r = p.get("remembered")
            if not ok("the second run was offered the fit", bool(r)):
                return
            ui2.post("/api/use", {"role": "screenshot", "path": shot})
            _, s2 = ui2.post("/api/save", {**BODY, "corners": r["corners"],
                                           "radius_frac": r["radius_frac"],
                                           "device": r["device"]})
            second = cv2.imread(s2["output"])
            ok("the two composites are identical, pixel for pixel",
               first is not None and second is not None
               and first.shape == second.shape
               and int(np.abs(first.astype(int) - second.astype(int)).max()) == 0,
               "max |diff| = " + str(None if second is None else
                                     int(np.abs(first.astype(int)
                                                - second.astype(int)).max())))
        finally:
            ui2.stop()
    finally:
        ui.stop()


def store_behaviour(td):
    print("\nthe store itself: tolerant to read, bounded, and never fatal")
    home = os.path.join(td, "c")
    os.makedirs(home)
    os.environ["HOME"] = home
    ok("the store path is under the home, beside current.json",
       FIT.store_path() == os.path.join(home, ".screengraft", "fits.json"),
       FIT.store_path())

    ok("recalling from nothing is None, not an exception", FIT.recall("nope") is None)
    os.makedirs(os.path.dirname(FIT.store_path()))
    open(FIT.store_path(), "w").write('{"fits": {"a": {"corn')   # torn write
    ok("a torn or hand-edited file reads as no memory rather than raising",
       FIT.recall("a") is None)
    FIT.remember("k", CORNERS, 0.05, "phone", "/tmp/x.png", (900, 700))
    ok("...and remembering over it repairs the file",
       (FIT.recall("k") or {}).get("device") == "phone")

    # The cap has to evict the OLDEST, or a machine that fits mockups all day
    # loses the fit it just made.
    keep = FIT.MAX_FITS
    try:
        FIT.MAX_FITS = 3
        for i in range(5):
            FIT.remember(f"k{i}", CORNERS, 0.05, "phone")
        left = sorted(json.load(open(FIT.store_path()))["fits"])
        ok("the store stays capped", len(left) == 3, str(left))
        ok("...by dropping the oldest, keeping the newest",
           left == ["k2", "k3", "k4"], str(left))
    finally:
        FIT.MAX_FITS = keep


def main():
    home = os.environ.get("HOME")
    try:
        with tempfile.TemporaryDirectory() as td:
            remembering(td)
            reproduces(td)
            store_behaviour(td)
    finally:
        if home:
            os.environ["HOME"] = home
    print()
    if FAILED:
        print(f"FAILED ({len(FAILED)}): " + "; ".join(FAILED))
        return 1
    print("all remembered-fit checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
