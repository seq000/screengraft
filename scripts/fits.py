#!/usr/bin/env python3
"""Remembered fits — the four corners, keyed by the photograph's own pixels.

Matching the edges is the only part of the job that costs real attention, and
it belongs to the PHOTOGRAPH, not to the screenshot: put a second screenshot
into the same photo and the quad is identical. Until now it was thrown away at
the end of every run, so the second screenshot meant doing the interview again.

Two decisions worth stating, because both had a cheaper wrong version:

**The key is the decoded pixels, not the path.** A photograph is re-exported,
renamed, downloaded twice and dragged in from a different folder constantly, and
a path key would miss every one of those. It would also miss the case this tool
creates itself: /api/upload copies the bytes into the session, so the same image
arriving by drag-drop has a path that never existed before and will not exist
again. Hashing what the file DECODES to costs 4ms on a 12MP photo and 18ms on
48MP (measured), which is nothing beside the read that produced the array.

**A fit is remembered when it is SAVED, not while it is being dragged.** A quad
on the canvas is a work in progress; a quad that produced an output is one the
person looked at and kept. That also keeps the store small enough never to need
thinking about — a few hundred bytes per entry, against the hundreds of
megabytes of source copies the session sweep exists to remove.

This file is the recipe, never the ingredients: numbers and a basename for
display, no image data and no absolute paths.
"""
import hashlib
import json
import os
import sys
import time

# Enough that nobody working normally reaches it — an entry is ~200 bytes, so
# the whole store stays under 100 KB — and bounded so it cannot grow without
# limit on a machine that fits mockups all day.
MAX_FITS = 500
VERSION = 1


def store_path():
    """Beside current.json, NOT inside a session directory.

    A session's contents are swept when the run ends — that is the retention
    policy — and a remembered fit has to outlive the run that made it or it has
    remembered nothing.
    """
    return os.path.join(os.path.expanduser("~"), ".screengraft", "fits.json")


def key_for(image):
    """A stable id for a photograph's CONTENT.

    The shape goes into the digest as well as the bytes: two arrays sharing a
    buffer at different dimensions are different photographs, and hashing the
    flat bytes alone would call them equal.
    """
    h = hashlib.sha256()
    h.update(("%dx%dx%d|" % (image.shape[0], image.shape[1],
                             image.shape[2] if image.ndim > 2 else 1)).encode())
    h.update(memoryview(image.tobytes()))
    return h.hexdigest()


def _load():
    """Tolerant, exactly like Session.read_job: a torn or hand-edited file reads
    as no memory at all rather than taking the request down with it. Losing a
    remembered fit costs one re-fit; refusing to serve the page costs the run.
    """
    try:
        with open(store_path()) as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("fits"), dict):
            return d["fits"]
    except (OSError, ValueError):
        pass
    return {}


def _save(fits):
    path = store_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"version": VERSION, "fits": fits}, f, indent=1)
    os.replace(tmp, path)


def remember(key, corners, radius_frac, device, photo_path=None, size=None):
    """Record the fit for this photograph, replacing any earlier one.

    The last fit wins deliberately. A photograph has one right answer for where
    its screen is; a history of near-misses would be a list to choose from,
    which is the bookkeeping this feature exists to avoid.
    """
    if not key or not corners:
        return None
    fits = _load()
    entry = {"corners": [[float(x), float(y)] for x, y in corners],
             "radius_frac": float(radius_frac or 0.0),
             "device": device,
             "saved": time.time()}
    if photo_path:
        # Basename only. It is there to say "the fit from birch-table.jpg" and
        # nothing reads it back, so a full path would be a private detail kept
        # for no purpose.
        entry["photo"] = os.path.basename(photo_path)
    if size:
        entry["size"] = [int(size[0]), int(size[1])]
    fits[key] = entry
    if len(fits) > MAX_FITS:
        oldest = sorted(fits.items(), key=lambda kv: kv[1].get("saved", 0))
        for k, _ in oldest[:len(fits) - MAX_FITS]:
            fits.pop(k, None)
    try:
        _save(fits)
    except OSError as e:
        # Remembering is a convenience wrapped around the thing the run was
        # actually for. An unwritable home must cost the next fit, not this
        # save -- but it is not allowed to be SILENT either, so it goes to the
        # log the daemon already writes.
        print(f"screengraft: could not remember this fit ({e})", file=sys.stderr)
        return None
    return entry


def recall(key):
    """The fit for this photograph, or None. Never raises."""
    if not key:
        return None
    e = _load().get(key)
    if not isinstance(e, dict) or not e.get("corners"):
        return None
    try:
        e["corners"] = [[float(x), float(y)] for x, y in e["corners"]]
    except (TypeError, ValueError):
        return None
    return e
