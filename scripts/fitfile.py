#!/usr/bin/env python3
"""The fit as a portable file — written beside the mockup, loaded by dropping it in.

`fits.py` already remembers a fit automatically, keyed by the photograph's own
pixels. That covers "same photo, same machine, later" and nothing else. Three
things it cannot do, and all three are in the request this exists for:

  * there is no artefact to find, name, keep beside the project, or send to
    someone;
  * a re-export misses. The key is the decoded pixels, so the same scene saved
    again from Figma at a different quality is a different photograph -- which is
    exactly the "come back and improve it later" case;
  * nothing travels to another machine.

So: a small JSON file written next to the output it produced, and a load path
that says plainly which photograph it was made for. No OS dialog is involved --
the file lands in the folder the user already chose, Finder finds it, and the
page takes it by drag-and-drop the same way it takes a photograph.

**Geometry only.** Corners, corner radius, device. Not the grade, blend or
grain: those belong to a *composite* and are recorded in `result.json`, which is
the recipe for reproducing one exactly. A fit is the part that is expensive to
make by hand and is worth carrying between runs; keeping the two apart stops one
file quietly becoming a worse copy of the other.
"""
import json
import os

KIND = "screengraft-fit"
VERSION = 1
SUFFIX = ".fit.json"

# How far the aspect ratio may drift before a scaled fit stops being trustworthy.
# A re-export at another size keeps its aspect to within rounding; a CROP does
# not, and a crop is where scaled corners land somewhere plausible and wrong.
ASPECT_TOLERANCE = 0.01


def path_for(output_path):
    """Beside the mockup, sharing its name: photo__shot.png -> photo__shot.fit.json.

    Next to the output rather than in a store of its own, because the whole
    point is that a person can find it later without being told where to look.
    """
    stem = os.path.splitext(output_path)[0]
    return stem + SUFFIX


def build(corners, radius_frac, device, photo_path, photo_size, key):
    return {
        "kind": KIND,
        "version": VERSION,
        "corners": [[round(float(x), 2), round(float(y), 2)] for x, y in corners],
        "radius_frac": float(radius_frac or 0.0),
        "device": device,
        "photo": {
            "name": os.path.basename(photo_path or ""),
            "size": [int(photo_size[0]), int(photo_size[1])],
            # The pixel key, so a load can tell "this is that photograph" from
            # "this is something else the same size". Not a path: the file is
            # meant to be shared, and a path would be both useless elsewhere and
            # a private detail.
            "key": key,
        },
    }


def write(output_path, doc):
    p = path_for(output_path)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=1)
    os.replace(tmp, p)
    return p


def parse(raw):
    """Validate an untrusted document. Returns (doc, error).

    Anything can be dropped onto a page. A fit that is not a fit has to be
    refused with a sentence, not applied as four numbers that happen to parse.
    """
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw)
        except ValueError as e:
            return None, f"that file is not JSON ({e})"
    if not isinstance(raw, dict):
        return None, "that file does not contain a fit"
    if raw.get("kind") != KIND:
        return None, ("that file is not a screengraft fit — a fit is the "
                      f"{SUFFIX} written next to a mockup you saved")
    if int(raw.get("version", 0)) > VERSION:
        return None, ("that fit was written by a newer version of screengraft "
                      "than this one")
    c = raw.get("corners")
    if (not isinstance(c, list) or len(c) != 4
            or not all(isinstance(p, list) and len(p) == 2 for p in c)):
        return None, "that fit does not carry four corners"
    try:
        raw["corners"] = [[float(x), float(y)] for x, y in c]
    except (TypeError, ValueError):
        return None, "that fit's corners are not numbers"
    return raw, None


def apply_to(doc, photo_size, key):
    """Fit a loaded document to the photograph currently open.

    Corners are meaningless on the wrong image and *plausible but wrong* on a
    crop of the right one, which is worse. So this never silently applies: every
    return says which of four situations it is, and the page states it.
    """
    fw, fh = doc.get("photo", {}).get("size", [0, 0]) or [0, 0]
    now_w, now_h = int(photo_size[0]), int(photo_size[1])
    corners = doc["corners"]
    name = doc.get("photo", {}).get("name") or "another photograph"

    if key and doc.get("photo", {}).get("key") == key:
        return corners, "exact", "This is the photograph the fit was made for."
    if not fw or not fh:
        return corners, "unknown", ("This fit does not say which photograph it "
                                    "came from — check all four corners.")
    if (fw, fh) == (now_w, now_h):
        # The case this feature exists for: same scene, exported again, so the
        # pixels differ and the size does not.
        return corners, "same-size", (
            "Different pixels, same dimensions as %s — most likely the same "
            "photograph exported again. Corners applied unchanged." % name)

    sx, sy = now_w / float(fw), now_h / float(fh)
    scaled = [[x * sx, y * sy] for x, y in corners]
    if abs(sx - sy) / max(sx, sy) > ASPECT_TOLERANCE:
        return scaled, "reshaped", (
            "%s was %dx%d and this is %dx%d — a different SHAPE, not just a "
            "different size, so this was probably cropped. The corners are "
            "stretched to fit and will need correcting." % (name, fw, fh, now_w, now_h))
    return scaled, "scaled", (
        "%s was %dx%d and this is %dx%d — corners scaled by %.3f. Worth checking "
        "at a corner." % (name, fw, fh, now_w, now_h, sx))
