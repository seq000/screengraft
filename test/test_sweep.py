#!/usr/bin/env python3
"""
Tests for the session sweep — SG63.

The sweep exists to stop `~/.screengraft/sessions/` growing without bound (492
MB in six days, 64% duplicates). SG63 is what it cost: it also deleted the
sources that sidecars name, so a fit whose photo was dragged in could no longer
be re-run from its own `result.json`. 9 of 9 such sidecars pointed at a deleted
file.

What is pinned here is the RULE, not the implementation:

  1. a session that produced nothing keeps nothing — the common case, and where
     the volume is;
  2. a session that produced output keeps exactly what its sidecar names;
  3. derived media (thumbs, preview, poster frames) is residue either way;
  4. a path-picked source outside the session is never touched — it is the
     user's own file and was never ours to delete.

Run: ~/.screengraft/venv/bin/python test/test_sweep.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import ui  # noqa: E402

failures = []


def ok(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}{('   ' + detail) if detail else ''}")
    if not cond:
        failures.append(name)


def blob(path, nbytes=4096):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\0" * nbytes)
    return path


def session(root, name, *, with_result):
    """A session directory shaped like a real one."""
    d = os.path.join(root, name)
    os.makedirs(os.path.join(d, "thumbs"), exist_ok=True)
    photo = blob(os.path.join(d, "photo-123-dragged.jpg"), 8192)
    shot = blob(os.path.join(d, "screenshot-123-dragged.png"), 8192)
    blob(os.path.join(d, "poster-123.png"), 2048)          # derived from a clip
    blob(os.path.join(d, "preview.png"), 2048)             # derived
    blob(os.path.join(d, "figma-export.png"), 2048)        # re-fetchable
    blob(os.path.join(d, "thumbs", "t1.png"), 1024)        # derived
    with open(os.path.join(d, "state.json"), "w") as f:
        json.dump({"photo": photo}, f)
    if with_result:
        with open(os.path.join(d, "result.json"), "w") as f:
            json.dump({"output": "/somewhere/else/out.png",
                       "photo": photo, "screenshot": shot,
                       "corners": [[0, 0], [1, 0], [1, 1], [0, 1]]}, f)
    return d, photo, shot


print("session sweep (SG63)")
with tempfile.TemporaryDirectory() as root:

    # --- 1. a session that produced nothing keeps nothing ---------------------
    d, photo, shot = session(root, "20260101-000000", with_result=False)
    freed = ui._sweep_session(d)
    ok("a session with no result.json is swept completely",
       not os.path.exists(photo) and not os.path.exists(shot),
       f"freed {freed} bytes")
    ok("...and its state.json survives", os.path.exists(os.path.join(d, "state.json")))

    # --- 2. a session that produced output keeps what the sidecar names -------
    d, photo, shot = session(root, "20260101-111111", with_result=True)
    freed = ui._sweep_session(d)
    ok("a session that saved a mockup keeps the photo its sidecar names",
       os.path.exists(photo))
    ok("...and the screenshot too", os.path.exists(shot))
    ok("...so the sidecar still points at files that exist",
       all(os.path.exists(json.load(open(os.path.join(d, "result.json")))[k])
           for k in ("photo", "screenshot")),
       "this is the whole of SG63")

    # --- 3. derived media is residue either way -------------------------------
    gone = [n for n in ("poster-123.png", "preview.png", "figma-export.png")
            if not os.path.exists(os.path.join(d, n))]
    ok("derived media is still swept from a session that produced output",
       len(gone) == 3, f"{len(gone)} of 3 removed")
    ok("...including thumbs",
       not os.path.exists(os.path.join(d, "thumbs", "t1.png")))
    ok("it still reclaims something from a session it protects", freed > 0,
       f"freed {freed} bytes")

    # --- 4. a path-picked source outside the session is never touched ---------
    # The reason the bug only ever affected drag-drop: /api/use records the
    # user's own path and reads through it. Deleting that would be deleting
    # their file.
    outside = blob(os.path.join(root, "user-pictures", "holiday.jpg"), 4096)
    d = os.path.join(root, "20260101-222222")
    os.makedirs(d, exist_ok=True)
    blob(os.path.join(d, "preview.png"), 1024)
    with open(os.path.join(d, "result.json"), "w") as f:
        json.dump({"output": "/somewhere/out.png", "photo": outside,
                   "screenshot": outside}, f)
    ui._sweep_session(d)
    ok("a source outside the session is left alone", os.path.exists(outside))
    ok("...and is not claimed as protected either",
       ui._sidecar_sources(d) == set(),
       "only paths inside the session are ours to keep")

    # --- 5. a corrupt sidecar must not stop the sweep -------------------------
    d, photo, _ = session(root, "20260101-333333", with_result=False)
    with open(os.path.join(d, "result.json"), "w") as f:
        f.write("{ not json")
    ui._sweep_session(d)
    ok("an unreadable sidecar protects nothing rather than everything",
       not os.path.exists(photo),
       "failing open would quietly restore the old unbounded growth")

    # --- 6. an already-broken sidecar says so, rather than looking fine -------
    # The sessions v0.23.0 emptied cannot be repaired. What can be fixed is the
    # claim: a sidecar naming a deleted file reads exactly like a working one.
    d, photo, shot = session(root, "20260101-444444", with_result=True)
    os.remove(photo)                       # as the previous release left it
    os.remove(shot)
    changed = ui._mark_unreproducible(d)
    res = json.load(open(os.path.join(d, "result.json")))
    ok("a sidecar whose source is gone is marked unreproducible",
       changed and res.get("source_retained") is False)
    ok("...and the rest of the recipe is preserved",
       res.get("corners") == [[0, 0], [1, 0], [1, 1], [0, 1]],
       "the corners are still the point")
    ok("...and marking twice changes nothing",
       ui._mark_unreproducible(d) is False)

    d, photo, shot = session(root, "20260101-555555", with_result=True)
    ui._sweep_session(d)
    ok("a sidecar whose source survived is NOT marked",
       ui._mark_unreproducible(d) is False
       and "source_retained" not in json.load(open(os.path.join(d, "result.json"))),
       "silence means it works")

print()
if failures:
    print("FAILURES: " + ", ".join(failures))
    sys.exit(1)
print("all checks passed")
