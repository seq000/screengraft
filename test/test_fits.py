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


def role_is_not_a_write_primitive(td):
    print("\nthe role names a session key, so only the two real roles are accepted")
    ui, _home, photo, _shot = build(td, "d")
    try:
        before = dict(ui.state())
        for bad in ("output", "corners", "fit_frame"):
            code, r = ui.post("/api/use", {"role": bad, "path": photo})
            ok(f"role={bad!r} is refused", code == 400, f"status {code} {str(r)[:60]}")
            ok("...and wrote no session state", ui.state().get(bad) == before.get(bad),
               f"{bad} = {ui.state().get(bad)!r}")
        # And the real thing still works, or the guard has just broken the tool.
        code, _ = ui.post("/api/use", {"role": "photo", "path": photo})
        ok("a real role still works", code == 200, f"status {code}")
    finally:
        ui.stop()


def concurrent_remembers(td):
    print("\nremembering is read-modify-write, so it holds a lock")
    home = os.path.join(td, "e")
    os.makedirs(home)
    os.environ["HOME"] = home
    # 40 writers against one file. Unlocked, load-modify-write loses entries:
    # os.replace keeps the FILE intact and says nothing about lost updates.
    import threading
    ts = [threading.Thread(target=FIT.remember,
                           args=(f"key{i}", CORNERS, 0.05, "phone"))
          for i in range(40)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    got = json.load(open(FIT.store_path()))["fits"]
    ok("every concurrent fit survived", len(got) == 40, f"{len(got)} of 40")


def fit_file(td):
    print("\na fit is a file beside the mockup, and it can be dropped back in")
    ui, home, photo, shot = build(td, "f")
    try:
        ui.post("/api/use", {"role": "photo", "path": photo})
        ui.post("/api/use", {"role": "screenshot", "path": shot})
        _, saved = ui.post("/api/save", BODY)

        fitp = saved.get("fit_file")
        ok("saving writes a fit beside the mockup",
           bool(fitp) and os.path.isfile(fitp)
           and os.path.dirname(fitp) == os.path.dirname(saved["output"]),
           str(fitp))
        ok("...named after the mockup, so the pair is obvious in Finder",
           bool(fitp) and os.path.splitext(saved["output"])[0] + ".fit.json" == fitp,
           str(fitp))
        doc = json.load(open(fitp))
        ok("...carrying the corners that produced it",
           doc["corners"] == [[float(x), float(y)] for x, y in CORNERS], str(doc["corners"]))
        ok("...the radius and device", doc["radius_frac"] == BODY["radius_frac"]
           and doc["device"] == "phone")
        ok("...and which photograph it was made for",
           doc["photo"]["size"] == [900, 700] and bool(doc["photo"]["key"])
           and doc["photo"]["name"] == "photo.png", str(doc["photo"]))
        ok("no absolute path travels with it — it is meant to be shared",
           home not in json.dumps(doc), "the fit names a real path")

        # The same photograph: the corners are used exactly as saved.
        code, r = ui.post("/api/fit", {"fit": doc})
        ok("dropping it back on the same photo is an exact match",
           code == 200 and r.get("match") == "exact"
           and r["corners"] == doc["corners"], f"{code} {str(r)[:90]}")

        # THE case this feature exists for: the same scene exported again. The
        # pixels differ, so the automatic memory cannot recognise it; the size
        # does not, so the corners still hold.
        again = os.path.join(home, "photo-again.png")
        im = synth_photo()
        im[0, 0] = (255 - im[0, 0, 0], im[0, 0, 1], im[0, 0, 2])   # one pixel
        cv2.imwrite(again, im)
        ui.post("/api/use", {"role": "photo", "path": again})
        code, r = ui.post("/api/fit", {"fit": doc})
        ok("a re-export is recognised as the same size, not refused",
           code == 200 and r.get("match") == "same-size"
           and r["corners"] == doc["corners"], f"{code} {r.get('match')}")
        ok("...and says so rather than pretending it is the same file",
           "exported again" in (r.get("message") or ""), r.get("message", "")[:80])

        # A resize: corners scale, and it says the result wants checking.
        big = os.path.join(home, "photo-2x.png")
        cv2.imwrite(big, cv2.resize(synth_photo(), (1800, 1400)))
        ui.post("/api/use", {"role": "photo", "path": big})
        code, r = ui.post("/api/fit", {"fit": doc})
        want = [[x * 2, y * 2] for x, y in doc["corners"]]
        ok("a scaled photograph gets scaled corners",
           code == 200 and r.get("match") == "scaled"
           and all(abs(a - b) < 0.01 for p, q in zip(r["corners"], want, strict=True)
                   for a, b in zip(p, q, strict=True)),
           f"{r.get('match')} {str(r.get('corners'))[:70]}")

        # A crop is the dangerous one: scaled corners land somewhere plausible
        # and wrong, so the aspect change has to be called out by name.
        crop = os.path.join(home, "photo-crop.png")
        cv2.imwrite(crop, synth_photo()[0:700, 0:600])
        ui.post("/api/use", {"role": "photo", "path": crop})
        code, r = ui.post("/api/fit", {"fit": doc})
        ok("a differently-SHAPED photograph is flagged, not quietly stretched",
           code == 200 and r.get("match") == "reshaped"
           and "cropped" in (r.get("message") or ""), f"{r.get('match')}")

        print("\n  ...and anything can be dropped on a page, so junk is refused with a sentence")
        for name, payload in [
            ("a plain object", {"corners": CORNERS}),
            ("something else's JSON", {"kind": "not-screengraft", "corners": CORNERS}),
            ("a fit with three corners", {**doc, "corners": doc["corners"][:3]}),
            ("corners that are not numbers", {**doc, "corners": [["a", "b"]] * 4}),
            ("a fit from the future", {**doc, "version": 99}),
        ]:
            code, r = ui.post("/api/fit", {"fit": payload})
            ok(f"{name}: refused with a reason",
               code == 400 and len(r.get("error", "")) > 20, f"{code} {str(r)[:70]}")
    finally:
        ui.stop()


def fit_needs_a_photo(td):
    print("\na fit is an instruction about the photo already open")
    ui, _home, _photo, _shot = build(td, "g")
    try:
        code, r = ui.post("/api/fit", {"fit": {"kind": "screengraft-fit", "version": 1,
                                               "corners": CORNERS}})
        ok("dropping a fit before a photo says what to do first",
           code == 400 and "photo" in r.get("error", ""), f"{code} {str(r)[:80]}")
    finally:
        ui.stop()


def main():
    home = os.environ.get("HOME")
    try:
        with tempfile.TemporaryDirectory() as td:
            remembering(td)
            reproduces(td)
            role_is_not_a_write_primitive(td)
            fit_file(td)
            fit_needs_a_photo(td)
            store_behaviour(td)
            concurrent_remembers(td)
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
