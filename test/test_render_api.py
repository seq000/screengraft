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
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import cv2
import numpy as np

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


def scrubber_reaches_the_compositor(td):
    """SG57: prove the SCRUBBER, by looking at pixels rather than at source text.

    The v0.21.1 defect was that `/api/frame` recorded an index and `_read_source`
    went on reading frame 0, so Preview and Save always composited the FIRST
    frame whatever the slider said. `test_video.py` pins this by parsing
    `ui.py` for the string `_fit_frame()` -- which pins the shape of the code
    and not what it does: it would pass unchanged if `_fit_frame()` always
    returned 0, or if the value were read and then discarded. Both reproduce the
    original bug.

    So: scrub to a late frame, ask for a preview, and compare the returned image
    against composites built locally from that frame and from frame 0. The
    fixture clip is deliberately harsh -- it ramps dark to light -- so the two
    are nowhere near each other and the comparison cannot be a coin toss.
    """
    print("\nthe scrubbed frame reaches the compositor, in pixels (SG57)")
    ui = build(td, "d")
    if ui is None:
        return ok("could build the fourth test clip", False)
    try:
        n = 11                                 # synth_clip makes 12 frames
        code, r = ui.post("/api/frame", {"index": n})
        ok("the scrubber records the frame", code == 200 and r.get("index") == n, str(r))

        code, pv = ui.post("/api/preview", {**BODY, "device": "phone"})
        if not ok("preview returned", code == 200, str(pv)[:120]):
            return
        got = cv2.imread(pv["path"])

        photo = cv2.imread(ui.state()["photo"])
        clip = ui.state()["screenshot"]
        radius_px = BODY["radius_frac"] * W.read_frame_at(clip, n).shape[1]
        want = W.compose(photo, W.read_frame_at(clip, n), CORNERS, radius_px,
                         grade=0.0, grain=False)
        first = W.compose(photo, W.read_frame_at(clip, 0), CORNERS, radius_px,
                          grade=0.0, grain=False)

        def diff(a, b):
            if a is None or b is None or a.shape != b.shape:
                return float("inf")
            return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())

        d_want, d_first = diff(got, want), diff(got, first)
        ok(f"the preview composites frame {n}, not frame 0",
           d_want < 1.0 and d_first > d_want,
           f"mean |diff| to frame {n} = {d_want:.2f}, to frame 0 = {d_first:.2f}")
        ok("...and the two frames are far enough apart for that to mean something",
           diff(want, first) > 5.0, f"{diff(want, first):.1f} levels")

        # The other half of the same contract, and the half only a live server
        # can answer: choosing a NEW screen source has to put the scrubber back
        # to frame 0, or the next clip is fitted on an index from the last one.
        ui.post("/api/use", {"role": "screenshot", "path": clip})
        ok("choosing a screen source resets the fitted frame",
           ui.state().get("fit_frame") == 0, str(ui.state().get("fit_frame")))
    finally:
        ui.stop()


def version_badge(td):
    """The page's version badge must be the PACKAGE's version, not a copy.

    A second place to write a version is a second place for it to go stale --
    the reason check_package.py exists at all. A badge that quietly disagrees
    with the build is worse than no badge, because it goes into bug reports.
    """
    print("\nthe version the page shows is the version that shipped")
    ui = build(td, "v")
    if ui is None:
        return ok("could build the version fixture", False)
    try:
        manifest = json.load(open(os.path.join(ROOT, ".claude-plugin", "plugin.json")))
        _, st = ui.get("/api/state")
        ok("/api/state carries a version", bool(st.get("version")), str(st.get("version")))
        ok("...and it is the manifest's, not a copy",
           st.get("version") == manifest.get("version"),
           f"served {st.get('version')} vs manifest {manifest.get('version')}")
        ok("a working tree is labelled as one",
           st.get("build", "").startswith("dev"), f"build={st.get('build')!r}")

        # The discrimination this badge exists for, tested the only way that
        # means anything: run the server from a tree with no .git -- which is
        # exactly the shape of an installed copy -- and require it NOT to claim
        # to be a dev build.
        #
        # Built from a COPY rather than from dist/*.plugin on purpose. Depending
        # on a build artefact would make this test pass or fail on the order the
        # steps happen to run in: CI never builds the .plugin at all, so the
        # artefact version of this check was red there and green locally, which
        # is the worst of both. The .plugin is still checked below, when one
        # happens to exist.
        installed = os.path.join(td, "installed")
        shutil.copytree(ROOT, installed,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "dist",
                                                      "test-output", "node_modules"))
        home2 = os.path.join(td, "vhome"); os.makedirs(home2, exist_ok=True)
        proc = subprocess.Popen(
            [sys.executable, os.path.join(installed, "scripts", "ui.py"),
             "--port", "0", "--no-open", "--session", os.path.join(td, "vsess"),
             "--out-dir", os.path.join(td, "vout")],
            env={**os.environ, "HOME": home2},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        try:
            info = json.loads(proc.stdout.readline())
            with urllib.request.urlopen(info["url"].rstrip("/") + "/api/state",
                                        timeout=30) as r:
                st2 = json.load(r)
            ok("a copy with no .git is NOT labelled dev", st2.get("build") == "",
               f"build={st2.get('build')!r}")
            ok("...and still reports its version", st2.get("version") == manifest["version"],
               str(st2.get("version")))
        finally:
            proc.terminate()
            try: proc.wait(timeout=10)
            except subprocess.TimeoutExpired: proc.kill()

        # And when a build does exist, it must not be carrying .git either --
        # that is what makes the copy above a fair stand-in for it.
        import zipfile
        plug = os.path.join(ROOT, "dist", f"screengraft-{manifest['version']}.plugin")
        if os.path.exists(plug):
            with zipfile.ZipFile(plug) as z:
                names = z.namelist()
            ok("the packaged plugin carries no .git (the discriminator)",
               not any(n.startswith(".git/") or "/.git/" in n for n in names))
        else:
            print("  ..    no dist/*.plugin to cross-check (not built yet)")

        page = open(os.path.join(ROOT, "ui", "index.html"), encoding="utf-8").read()
        hardcoded = manifest["version"] in page
        ok("the page does not hardcode a version of its own", not hardcoded,
           "the literal version string is in index.html" if hardcoded else "")
    finally:
        ui.stop()


def click_to_pick(td):
    """SG46: a single click picks the screen out of the candidate list.

    The detectors nearly always FIND the screen; what they cannot do is say
    which of the regions they found is one. On the two real photographs that
    defeated every detector, the correct quad was already among the candidates
    both times -- so the click filters, and the existing score ranks what is
    left. No new segmentation, and every existing guard still applies.
    """
    print("\na click picks the screen out of the candidates (SG46)")
    ui = build(td, "k")
    if ui is None:
        return ok("could build the click fixture", False)
    try:
        # Ground truth on this fixture is the UNCLICKED answer, not CORNERS:
        # CORNERS is where the screenshot gets warped TO, deliberately inset
        # from the body rectangle synth_photo draws, so a detector that is
        # working perfectly still sits ~30px from it. Comparing against it
        # would be measuring the fixture's geometry, not the click.
        code, r0 = ui.post("/api/detect", {})
        ok("plain detection answers on the fixture", code == 200 and r0.get("found"),
           str(r0.get("message", ""))[:90])
        q0 = np.array(r0["corners"], float) if r0.get("found") else None

        cx = sum(c[0] for c in CORNERS) / 4.0
        cy = sum(c[1] for c in CORNERS) / 4.0
        code, r = ui.post("/api/detect", {"click": [cx, cy]})
        ok("a click inside the screen finds it", code == 200 and r.get("found"),
           str(r.get("message", ""))[:90])
        if r.get("found") and q0 is not None:
            q1 = np.array(r["corners"], float)
            moved = float(np.max(np.linalg.norm(q1 - q0, axis=1)))
            # The property that matters: pointing at a screen the detector had
            # ALREADY found must confirm it, not perturb it. Where detection
            # works the click is a no-op; where it fails the click is the whole
            # answer, and that half is measured on real photographs.
            ok("...and does not move an answer detection already had",
               moved < 2.0, f"moved {moved:.1f}px")

        # The instrument, over HTTP. Asked for, or it does not appear:
        # the page renders none of this and a few hundred quads in a response
        # nobody reads is a cost with no reader.
        code, plain = ui.post("/api/detect", {})
        ok("no trace unless it is asked for", "trace" not in plain, str(plain.get("trace"))[:60])
        code, tr = ui.post("/api/detect", {"trace": True})
        info = tr.get("trace") or {}
        ok("asking for a trace answers with where it went",
           code == 200 and info.get("candidates", 0) > 0 and os.path.isfile(info.get("path", "")),
           str(info)[:120])
        if info.get("path"):
            doc = json.load(open(info["path"]))
            ok("...and the file holds one row per candidate",
               len(doc["candidates"]) == info["candidates"] == doc["counts"]["candidates"],
               f"{len(doc['candidates'])} rows")
            ok("...beside the session, where a .json survives the sweep",
               os.path.realpath(os.path.dirname(info["path"]))
               == os.path.realpath(ui.info["session"])
               and info["path"].endswith(".json"),
               info["path"])

        # The click must not be able to invent a screen where there is none.
        code, r2 = ui.post("/api/detect", {"click": [2.0, 2.0]})
        far_ok = code == 200 and (not r2.get("found") or q0 is None or float(np.max(
            np.linalg.norm(np.array(r2["corners"], float) - q0, axis=1))) > 20.0)
        ok("a click in the far corner does not return the screen anyway", far_ok,
           "found=%s" % r2.get("found"))

        # And it is validated like any other input.
        for bad, why in [([-5, 10], "outside the photograph"),
                         (["x", 1], "not a number"),
                         ([10], "not a pair")]:
            code, r = ui.post("/api/detect", {"click": bad})
            ok(f"a click that is {why} is refused", code >= 400, f"status {code}")
    finally:
        ui.stop()


def session_sweep(td):
    """SG39: copied and derived media must not outlive the run that needed it.

    Measured before this existed: 492 MB across 90 session directories in six
    days, 64% of it duplicates of files the user already had, and nothing ever
    deleted any of it. What must survive is the sidecar -- a few hundred bytes
    recording the fit and referencing the ORIGINALS -- so a composite stays
    reproducible without keeping a copy of everything it was made from.
    """
    print("\nsession residue does not outlive the run (SG39)")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "uimod", os.path.join(ROOT, "scripts", "ui.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    root = os.path.join(td, "sweep")
    live = os.path.join(root, "20260909-000002")
    old_s = os.path.join(root, "20260909-000001")
    for d in (live, old_s):
        os.makedirs(os.path.join(d, "thumbs"), exist_ok=True)
    heavy = {
        "photo-123-shot.png": 40_000,          # a copy of the user's own file
        "screenshot-123-clip.mov": 90_000,     # ditto, and the big one
        "poster-clip.jpg": 3_000,
        "preview.png": 20_000,
        "figma-export.png": 10_000,
        "frame-000004.png": 5_000,
    }
    keep = {"state.json": b'{"photo": "/Users/x/real.png"}',
            "result.json": b'{"output": "/Users/x/out.png", "corners": []}'}
    for d in (live, old_s):
        for n, sz in heavy.items():
            open(os.path.join(d, n), "wb").write(b"\0" * sz)
        open(os.path.join(d, "thumbs", "t1.jpg"), "wb").write(b"\0" * 7_000)
        for n, data in keep.items():
            open(os.path.join(d, n), "wb").write(data)

    before = sum(os.path.getsize(os.path.join(b, f))
                 for b, _, fs in os.walk(root) for f in fs)
    freed = m._prune_sessions(live)
    after = sum(os.path.getsize(os.path.join(b, f))
                for b, _, fs in os.walk(root) for f in fs)

    ok("the reclaimed figure is the real one", before - after == freed,
       f"{before - after} vs {freed}")
    ok("every copied and derived file in the old session is gone",
       not any(os.path.exists(os.path.join(old_s, n)) for n in heavy),
       ", ".join(n for n in heavy if os.path.exists(os.path.join(old_s, n))))
    ok("...including its thumbnails",
       not os.path.exists(os.path.join(old_s, "thumbs", "t1.jpg")))
    ok("the sidecar and state SURVIVE -- the fit stays reproducible",
       all(os.path.exists(os.path.join(old_s, n)) for n in keep))
    ok("...with their contents untouched",
       all(open(os.path.join(old_s, n), "rb").read() == data
           for n, data in keep.items()))
    ok("the LIVE session is not touched",
       all(os.path.exists(os.path.join(live, n)) for n in heavy)
       and os.path.exists(os.path.join(live, "thumbs", "t1.jpg")))

    # and the end-of-run sweep clears the live one
    m._sweep_session(live)
    ok("the run's own copies go when the run ends",
       not any(os.path.exists(os.path.join(live, n)) for n in heavy))
    ok("...and its sidecar still does not",
       all(os.path.exists(os.path.join(live, n)) for n in keep))


def preview_is_not_a_render(td):
    """A played preview must publish NOTHING (SG73).

    It is a proxy: smaller, in the session, thrown away by the sweep. The
    failure to guard against is the SG53 defect inverted — a preview that set
    the session output would have `/api/import` hand Claude a 720px proxy
    instead of the mockup, and the page would look exactly the same while it
    happened.
    """
    print("\na preview is a proxy, and publishes nothing (SG73)")
    ui = build(td, "p")
    if ui is None:
        return ok("could build the preview fixture", False)
    try:
        had_side = ui.sidecar()
        had_out = ui.state().get("output")

        code, r = ui.post("/api/preview_video", BODY)
        ok("the preview starts", code == 200 and bool(r.get("started")),
           f"{code} {r.get('error', '')}")
        s = ui.wait_render()
        ok("...and finishes", s["state"] == "done", s.get("message") or s["state"])
        ok("...tagged as a preview, so the page can tell the two apart",
           s.get("kind") == "preview", str(s.get("kind")))

        dest = s.get("output") or ""
        ok("the proxy lives in the session, not in the output folder",
           os.path.realpath(os.path.dirname(dest)) == os.path.realpath(ui.info["session"]),
           dest)
        ok("...and is called preview.mp4, which the sweep already treats as residue",
           os.path.basename(dest) == "preview.mp4", os.path.basename(dest))

        ok("the session output is UNCHANGED — Send to Claude must not offer a proxy",
           ui.state().get("output") == had_out, str(ui.state().get("output")))
        ok("no sidecar was written for it", ui.sidecar() == had_side)
        ok("no fit file was written beside it",
           not os.path.exists(os.path.splitext(dest)[0] + ".fit.json"))

        # Smaller than the photo, or it is not a proxy and the wait was pointless.
        w, h = (s.get("info") or {}).get("output_size", [0, 0])
        photo = cv2.imread(ui.state()["photo"])
        ok("the proxy is smaller than the photograph", 0 < w < photo.shape[1],
           f"{w}x{h} against {photo.shape[1]}x{photo.shape[0]}")
        # H.264 with yuv420p refuses odd dimensions, and refuses by killing
        # ffmpeg mid-stream — which arrives as a broken pipe with the real
        # complaint nowhere in sight. Found this way, not by reading.
        ok("...with EVEN dimensions, which is what H.264 requires",
           w % 2 == 0 and h % 2 == 0, f"{w}x{h}")
        ok("...and it plays: the file has bytes", os.path.getsize(dest) > 1000,
           str(os.path.getsize(dest)))

        print("\n  the fit is the same fit — a proxy you cannot trust is not a preview")
        # The quad is scaled by what the resize ACTUALLY did. If the preview
        # composited a differently-placed screen, watching it would tell you
        # nothing about the render.
        frames = os.path.join(td, "pf")
        os.makedirs(frames, exist_ok=True)
        scale = w / float(photo.shape[1])
        small = cv2.resize(photo, (w, h), interpolation=cv2.INTER_AREA)
        sx, sy = w / float(photo.shape[1]), h / float(photo.shape[0])
        want = W.compose(small, W.read_frame_at(ui.state()["screenshot"], 0),
                         [[x * sx, y * sy] for x, y in CORNERS],
                         BODY["radius_frac"] * W.read_frame_at(
                             ui.state()["screenshot"], 0).shape[1],
                         grade=0.0, grain=False)
        cap = cv2.VideoCapture(dest)
        okf, got = cap.read()
        cap.release()
        d = (float(np.abs(got.astype(np.int16) - want.astype(np.int16)).mean())
             if okf and got is not None and got.shape == want.shape else float("inf"))
        # What this can and cannot see, measured rather than assumed: encode
        # noise against the correct quad is 3.4 levels, a quad 20px out is 4.7 —
        # so a whole-frame mean does NOT discriminate small drift and must not
        # claim to. What it catches with an 8x margin is the quad not being
        # scaled with the photo at all: 27.0. That is the actual failure mode
        # here, because the resize is rounded to even dimensions and the scale
        # the corners get has to be the one the resize really used.
        ok("the proxy composites the SCALED quad, not the original",
           d < 8.0, f"mean |diff| {d:.2f} (unscaled would be ~27), scale {scale:.3f}")
    finally:
        ui.stop()


def preview_refuses_a_still(td):
    print("\nplaying a still is not a thing")
    home = os.path.join(td, "q", "home")
    os.makedirs(home)
    photo, shot = os.path.join(home, "photo.png"), os.path.join(home, "shot.png")
    cv2.imwrite(photo, synth_photo())
    cv2.imwrite(shot, synth_photo(w=300, h=300))
    ui = UI(home, os.path.join(home, ".screengraft", "sessions", "q"),
            os.path.join(td, "q", "out"))
    try:
        ui.post("/api/use", {"role": "photo", "path": photo})
        ui.post("/api/use", {"role": "screenshot", "path": shot})
        code, r = ui.post("/api/preview_video", BODY)
        ok("a still screen source is refused, not encoded",
           code == 400 and "not a video" in r.get("error", ""), f"{code} {str(r)[:70]}")
    finally:
        ui.stop()


def clear_a_source(td):
    """Un-choosing a source, over HTTP, and what the session keeps.

    The page had no way to start over: picking a different file was the only
    exit, and a reload restores the session's fit. /api/clear is the mirror of
    /api/use. What it takes with it is decided by what the source IS -- the
    photo owns the corners, the screenshot owns the fitted frame, either owns
    the output -- and each of those is asserted here from the session file,
    not from the response.
    """
    print("\nclearing a source")
    home = os.path.join(td, "clr", "home")
    os.makedirs(home)
    photo, shot = os.path.join(home, "photo.png"), os.path.join(home, "shot.png")
    cv2.imwrite(photo, synth_photo())
    cv2.imwrite(shot, synth_photo(w=300, h=300))
    ui = UI(home, os.path.join(home, ".screengraft", "sessions", "clr"),
            os.path.join(td, "clr", "out"))
    try:
        ui.post("/api/use", {"role": "photo", "path": photo})
        ui.post("/api/use", {"role": "screenshot", "path": shot})
        code, r = ui.post("/api/save", BODY)
        ok("a save exists to be invalidated", code == 200 and ui.state().get("output"),
           f"{code} output={ui.state().get('output')}")
        ui.post("/api/frame", {"index": 0})

        code, r = ui.post("/api/clear", {"role": "screenshot"})
        st = ui.state()
        ok("clearing the screenshot answers 200 and names what it cleared",
           code == 200 and r.get("cleared") == "screenshot", f"{code} {r}")
        ok("...the screenshot is gone from the session", not st.get("screenshot"))
        # The session stores the resolved path (macOS: /private/tmp for /tmp).
        ok("...the photo is still there",
           os.path.realpath(st.get("photo") or "") == os.path.realpath(photo),
           f"{st.get('photo')}")
        ok("...the corners are KEPT — they belong to the photo", bool(st.get("corners")))
        ok("...and the stale output is dropped, so Send to Claude cannot hand it over",
           not st.get("output"), f"output={st.get('output')}")
        code, r = ui.post("/api/save", BODY)
        ok("...and a save now refuses, naming the missing source",
           code == 400 and "screenshot" in r.get("error", ""), f"{code} {r}")

        code, r = ui.post("/api/clear", {"role": "photo"})
        st = ui.state()
        ok("clearing the photo drops it AND the corners", code == 200
           and not st.get("photo") and not st.get("corners"), f"{code} {st.get('corners')}")

        code, r = ui.post("/api/clear", {"role": "output"})
        ok("a role that is not a source is refused — the same write primitive _adopt guards",
           code == 400, f"{code} {r}")
    finally:
        ui.stop()

    # Clearing while a render is in flight would let the worker publish an
    # output and sidecar from a source that is no longer loaded -- the stale
    # artefact /api/clear exists to prevent. Found in the v0.41.0 code review.
    print("\nclearing a source mid-render")
    ui = build(td, "clr2")
    if ui is None:
        return ok("could build the clip for the mid-render clear", False)
    try:
        code, r = ui.post("/api/render", BODY)
        ok("a render is running", code == 200 and r.get("started"), f"{code} {r}")
        code, r = ui.post("/api/clear", {"role": "screenshot"})
        ok("clearing the screenshot mid-render is refused with 409",
           code == 409 and "render" in r.get("error", ""), f"{code} {r}")
        ok("...and the screenshot is still loaded", bool(ui.state().get("screenshot")))
        s = ui.wait_render()
        ok("the render still finishes", s["state"] == "done", s["state"])
        code, r = ui.post("/api/clear", {"role": "screenshot"})
        ok("...after which clearing works", code == 200, f"{code} {r}")
    finally:
        ui.stop()


def file_route_supports_ranges(td):
    """A browser cannot seek in a video the server hands over whole (SG73).

    It plays from the start and every jump snaps back to zero. Measured in the
    live page before this existed: setting currentTime to 9.0s read back as 0.0,
    which made "stop returns to the fitted frame" quietly impossible and broke
    the video element's own scrubber with it.
    """
    print("\n/file answers a Range request, or video cannot seek")
    ui = build(td, "r")
    if ui is None:
        return ok("could build the range fixture", False)
    try:
        clip = ui.state()["screenshot"]
        url = ui.url + "/file?path=" + urllib.parse.quote(clip)
        whole = urllib.request.urlopen(url, timeout=30).read()

        req = urllib.request.Request(url, headers={"Range": "bytes=100-199"})
        with urllib.request.urlopen(req, timeout=30) as r:
            part, status, hdrs = r.read(), r.status, dict(r.headers)
        ok("a range request is answered 206", status == 206, str(status))
        ok("...with the bytes asked for", part == whole[100:200], f"{len(part)} bytes")
        ok("...and a Content-Range naming the whole size",
           hdrs.get("Content-Range") == f"bytes 100-199/{len(whole)}",
           str(hdrs.get("Content-Range")))
        ok("...and Accept-Ranges, which is how the player knows it may seek",
           hdrs.get("Accept-Ranges") == "bytes", str(hdrs.get("Accept-Ranges")))

        # bytes=-N is the tail, and an open end runs to EOF. Both are ordinary
        # for a media element deciding where the moov atom is.
        for header, want in [("bytes=-50", whole[-50:]), (f"bytes={len(whole)-10}-", whole[-10:])]:
            req = urllib.request.Request(url, headers={"Range": header})
            with urllib.request.urlopen(req, timeout=30) as r:
                ok(f"{header} is served", r.status == 206 and r.read() == want, str(r.status))

        # Nonsense must not 500 or truncate: the spec says ignore it.
        for bad in ["bytes=abc-", "bytes=999999999-1000000000", "chunks=0-1"]:
            req = urllib.request.Request(url, headers={"Range": bad})
            with urllib.request.urlopen(req, timeout=30) as r:
                body, status = r.read(), r.status
            ok(f"{bad!r} falls back to the whole file",
               status == 200 and body == whole, f"{status}, {len(body)} of {len(whole)}")
    finally:
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
        scrubber_reaches_the_compositor(td)
        click_to_pick(td)
        session_sweep(td)
        version_badge(td)
        preview_is_not_a_render(td)
        preview_refuses_a_still(td)
        clear_a_source(td)
        file_route_supports_ranges(td)
    print()
    if FAILED:
        print(f"FAILED ({len(FAILED)}): " + "; ".join(FAILED))
        return 1
    print("all render-route checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
