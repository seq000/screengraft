#!/usr/bin/env python3
"""Tests for the render ROUTE, driven over HTTP the way the page drives it.

`test_video.py` proves the engine: same geometry, identical frames, frame 0 of a
render equal to the still composite. None of that touches the route -- and all
three defects this file was written for lived in the route, not the engine: a
finished render never recorded as the session output, a flag set before
validation, a sidecar published before the encode. Every one would pass an
engine test, and every one broke a shipped feature.

So this starts the real server and speaks HTTP to it. Everything runs against a
temp HOME, so a live ~/.screengraft and any UI the developer has open are
untouched.

Run: ~/.screengraft/venv/bin/python test/test_render_api.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, HERE)
import warp as W  # noqa: E402

from test_video import CORNERS, synth_clip, synth_photo  # noqa: E402

FAILED = []


def ok(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}" + (f" - {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)
    return cond


class UI:
    """The real ui.py in a subprocess, spoken to over HTTP.

    --port 0 so a developer's own running UI is never contended for, --no-open
    so the suite does not throw a browser at whoever ran it.
    """

    def __init__(self, home, session, out_dir):
        self.p = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "scripts", "ui.py"),
             "--port", "0", "--no-open", "--session", session, "--out-dir", out_dir],
            env={**os.environ, "HOME": home},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError("server did not start: " + self.p.stderr.read())
        self.info = json.loads(line)
        self.url = self.info["url"].rstrip("/")

    def post(self, path, body):
        """-> (status, json). A 4xx is an ANSWER here, not an exception: half
        these checks are about what the server says when it refuses."""
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def get(self, path):
        with urllib.request.urlopen(self.url + path, timeout=60) as r:
            return r.status, json.load(r)

    def wait_render(self, timeout=180):
        end = time.time() + timeout
        while time.time() < end:
            _, s = self.get("/api/render_status")
            if s["state"] in ("done", "error"):
                return s
            time.sleep(0.25)
        return {"state": "timeout"}

    def state(self):
        return json.load(open(os.path.join(self.info["session"], "state.json")))

    def sidecar(self):
        if not os.path.exists(self.info["result"]):
            return None
        return json.load(open(self.info["result"]))

    def stop(self):
        self.p.terminate()
        try:
            self.p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.p.kill()


BODY = {"corners": CORNERS, "radius_frac": 0.05, "grade": 0.0, "grain": False}


def build(td, name):
    """A temp HOME with a photo and a clip already chosen as the session source."""
    home = os.path.join(td, name, "home")
    os.makedirs(home)
    # Under the fake HOME on purpose: _safe_local_path refuses to open anything
    # outside the user's home, so fixtures parked in the bare temp dir are
    # rejected -- the server being right and the harness being wrong.
    photo = os.path.join(home, "photo.png")
    clip = os.path.join(home, "clip.mp4")
    cv2.imwrite(photo, synth_photo())
    if not synth_clip(clip):
        return None
    ui = UI(home, os.path.join(td, name, "sess"), os.path.join(td, name, "out"))
    ui.post("/api/use", {"role": "photo", "path": photo})
    ui.post("/api/use", {"role": "screenshot", "path": clip})
    return ui


def happy_path(td):
    ui = build(td, "a")
    if ui is None:
        return ok("could build the test clip", False)
    try:
        print("\na validation failure must not lock rendering (SG54)")
        # The flag used to be set before any of this was checked, so ONE bad
        # request poisoned every later one for the life of the server. These
        # three throw at three different points in the route.
        for name, bad in [
            ("missing corners", {k: v for k, v in BODY.items() if k != "corners"}),
            ("corners not a quad", {**BODY, "corners": [[0, 0]]}),
            ("radius_frac is junk", {**BODY, "radius_frac": "banana"}),
        ]:
            code, _ = ui.post("/api/render", bad)
            ok(f"{name}: refused", code >= 400, f"status {code}")
            _, s = ui.get("/api/render_status")
            ok(f"{name}: state is not stuck on running", s["state"] != "running",
               f"state={s['state']}")

        code, r = ui.post("/api/render", BODY)
        ok("a good request after all of those still starts",
           code == 200 and bool(r.get("started")), f"status {code} {r.get('error', '')}")

        print("\na finished render is the session output (SG53)")
        s = ui.wait_render()
        ok("the render completed", s["state"] == "done", s.get("message") or s["state"])
        dest = s.get("output")
        ok("the file exists", bool(dest) and os.path.isfile(dest), str(dest))
        ok("SESSION output points at the RENDER, not at a previous still",
           ui.state().get("output") == dest, str(ui.state().get("output")))

        code, imp = ui.post("/api/import", {})
        ok("Send to Claude accepts it", code == 200, str(imp)[:120])
        job = json.load(open(ui.info["job"])) if os.path.exists(ui.info["job"]) else {}
        ok("...and the job names that exact file", job.get("paths") == [dest],
           str(job.get("paths")))

        print("\nthe sidecar describes the render (SG55)")
        side = ui.sidecar() or {}
        ok("sidecar points at the render", side.get("output") == dest)
        ok("...and carries every argument that changes the output",
           all(k in side for k in ("corners", "radius_px", "grade", "grain",
                                   "preset", "fit_frame", "blend", "reflection")),
           ", ".join(sorted(side)))
        ok("...and is stamped saved", isinstance(side.get("saved"), (int, float)))
    finally:
        ui.stop()


def failed_encode(td):
    print("\na FAILED encode must not leave a sidecar claiming success (SG55)")
    ui = build(td, "b")
    if ui is None:
        return ok("could build the second test clip", False)
    try:
        had = ui.sidecar()
        # Corrupt the clip under the server's feet. The route's own checks pass
        # (the path still ends .mp4 and the fit frame was read at adopt time),
        # so the failure lands where it belongs: inside the encode, on the
        # worker thread, AFTER the point where the sidecar used to be written.
        with open(ui.state()["screenshot"], "wb") as f:
            f.write(b"not a video at all")
        code, r = ui.post("/api/render", BODY)
        if code == 200:
            s = ui.wait_render()
            ok("the encode reported failure rather than success",
               s["state"] == "error", str(s.get("state")))
            side = ui.sidecar()
            ok("no sidecar claims a file the encode never produced",
               side is None or side == had or not side.get("output")
               or os.path.isfile(side["output"]),
               str(side.get("output") if side else None))
            out = ui.state().get("output")
            ok("the session output was not advanced to a missing file",
               not out or os.path.isfile(out), str(out))
        else:
            ok("the route refused the broken source outright", code >= 400,
               f"status {code} - {r.get('error', '')}")
            ok("...and wrote no sidecar for it", ui.sidecar() == had)
        _, s2 = ui.get("/api/render_status")
        ok("a failed render leaves the route usable", s2["state"] != "running",
           f"state={s2['state']}")
    finally:
        ui.stop()


def encode_fails_late(td):
    """The case SG55 is actually about: the route ACCEPTS, then the encode dies.

    Corrupting the clip no longer reaches this -- the route now rejects an
    unreadable source up front, which is the better behaviour and leaves this
    scenario uncovered. An unwritable output directory gets there instead:
    every check the route makes passes, `os.makedirs(exist_ok=True)` is happy
    with a directory that already exists, and ffmpeg fails when it tries to
    write. That is precisely the window in which a sidecar written by the route
    would already be on disk claiming a saved file.
    """
    print("\nan encode that fails AFTER the route accepts (SG55)")
    ui = build(td, "c")
    if ui is None:
        return ok("could build the third test clip", False)
    out_dir = os.path.join(td, "c", "out")
    try:
        os.makedirs(out_dir, exist_ok=True)
        os.chmod(out_dir, 0o500)               # readable, listable, NOT writable
        had = ui.sidecar()
        code, r = ui.post("/api/render", BODY)
        if code != 200:
            ok("the route accepted the render (else this case is not exercised)",
               False, f"status {code} - {r.get('error', '')}")
            return
        s = ui.wait_render()
        ok("the encode failed", s["state"] == "error", str(s.get("state")))
        side = ui.sidecar()
        ok("the sidecar was not advanced past the failure", side == had,
           str(side.get("output") if side else None))
        out = ui.state().get("output")
        ok("the session output was not advanced to a missing file",
           not out or os.path.isfile(out), str(out))
        _, s2 = ui.get("/api/render_status")
        ok("the route is usable again", s2["state"] != "running", f"state={s2['state']}")
    finally:
        os.chmod(out_dir, 0o755)
        ui.stop()


def main():
    if not W.ffmpeg_exe():
        msg = "ffmpeg unavailable - the render route cannot be exercised"
        if os.environ.get("SCREENGRAFT_REQUIRE_FFMPEG"):
            # A suite that can pass by NOT RUNNING holds no line at all. CI sets
            # this, so an absent ffmpeg there is a red build rather than a skip.
            print("FAIL  " + msg + " (SCREENGRAFT_REQUIRE_FFMPEG is set)")
            return 1
        print("SKIP  " + msg)
        return 0
    with tempfile.TemporaryDirectory() as td:
        happy_path(td)
        failed_encode(td)
        encode_fails_late(td)
    print()
    if FAILED:
        print(f"FAILED ({len(FAILED)}): " + "; ".join(FAILED))
        return 1
    print("all render-route checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
