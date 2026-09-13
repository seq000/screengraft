#!/usr/bin/env python3
"""The recents store: what was used, per role, newest first, dead paths dropped."""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

FAILED = []


def ok(name, cond, detail=""):
    print(("  ok    " if cond else "  FAIL  ") + name + (("   " + detail) if detail else ""))
    if not cond:
        FAILED.append(name)


with tempfile.TemporaryDirectory() as td:
    os.environ["HOME"] = td                     # the store lives under ~/.screengraft
    import recents as R
    a = os.path.join(td, "a.png"); b = os.path.join(td, "b.png"); c = os.path.join(td, "c.mp4")
    for p in (a, b, c):
        open(p, "wb").write(b"x")

    ok("empty at first", R.items("photo") == [] and R.items("screenshot") == [])
    ok("the first read writes the store, so the seed runs once", os.path.exists(R.store_path()))
    ok("...owner-only", (os.stat(R.store_path()).st_mode & 0o777) == 0o600, oct(os.stat(R.store_path()).st_mode & 0o777))
    R.record("photo", a); time.sleep(0.01); R.record("photo", b); R.record("screenshot", c)
    names = [i["name"] for i in R.items("photo")]
    ok("newest used first", names == ["b.png", "a.png"], str(names))
    ok("roles are separate lists", [i["name"] for i in R.items("screenshot")] == ["c.mp4"])
    R.record("photo", a)
    ok("re-using moves to the front, no duplicate", [i["name"] for i in R.items("photo")] == ["a.png", "b.png"])
    ok("an unknown role records nothing", (R.record("output", a), R.items("output"))[1] == [])
    os.remove(b)
    got = R.items("photo")
    ok("a file that is gone is dropped", [i["name"] for i in got] == ["a.png"], str([i["name"] for i in got]))
    ok("...and the store itself forgets it", all(e["path"] != b for e in R._load()["photo"]))
    it = got[0]
    ok("an item carries what the picker shows", {"path", "name", "used", "mtime", "bytes", "ext", "folder"} <= set(it), str(sorted(it)))
    for i in range(80):
        R.record("photo", os.path.join(td, f"z{i}.png"))
    ok("the list is capped", len(R._load()["photo"]) <= R.CAP, str(len(R._load()["photo"])))

if FAILED:
    print("FAILURES: " + ", ".join(FAILED)); sys.exit(1)
print("all recents checks passed")
