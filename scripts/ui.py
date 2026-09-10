#!/usr/bin/env python3
"""
screengraft — the local UI. One browser tab, the whole job.

    python3 scripts/ui.py [--port 0] [--no-open] [--session DIR]

Serves ui/index.html on 127.0.0.1 and opens it in the default browser. The
page walks the designer through: pick a photo (recent Desktop/Downloads
thumbnails, drag-drop, browse, or paste a path) -> pick the screenshot (same,
or paste a Figma frame link) -> device/radius -> drag the four corners over the
photo -> Preview -> Save to ~/Desktop/screengraft/.

Everything geometric happens here in Python (detect.py, warp.py). The page
only collects intent and shows results.

The one thing the page can't do is talk to Figma. For a Figma link it writes
    <session>/job.json   {"type":"figma_export"|"present", ..., "status":"pending"}
This is an OUTBOX, not a mailbox the agent happens to check: the agent cannot
poll between turns, so it parks in the screengraft MCP server's `wait_for_job`,
which watches this file and returns within ~150ms of a button press. The agent
answers with `complete_job`, which rewrites the file with status done|error.
The page polls /api/job for that. Errors: {"status":"error","message":...}.

When the user saves, <session>/result.json is written — the agent reads it to
know what was produced (and to verify the output image before claiming done).

stdlib only on the server side; OpenCV via detect/warp.
"""
import argparse
import atexit
import json
import mimetypes
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import detect as D  # noqa: E402
import fitfile as FF  # noqa: E402
import fits as FIT  # noqa: E402
import scan as S  # noqa: E402
import warp as W  # noqa: E402

HOME = os.path.expanduser("~")
# Overridden by --out-dir. The skill passes <project>/mockups so that saves land
# inside the folder the designer is working in: present_files refuses anything
# outside a connected folder, so a Desktop path cannot be shown in chat at all.
OUT_DIR = os.path.join(HOME, "Desktop", "screengraft")
UI_HTML = os.path.join(ROOT, "ui", "index.html")

# Pointer to the UI instance the agent should talk to. The MCP server reads this
# to find the session, and checks the pid so a pointer left by a crashed UI is
# treated as no UI at all rather than one that never answers.
CURRENT = os.path.join(HOME, ".screengraft", "current.json")


def _write_json_atomic(path, obj):
    """Write via tmp + rename.

    The MCP server reads job.json in a 150ms poll loop, so a plain truncating
    write is a real chance to be read half-formed. os.replace is atomic on the
    same filesystem.
    """
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)

# Corner radius as a fraction of the SCREEN'S WIDTH, per device preset.
# Approximations from public specs (pt): iPhone 15/16 393pt wide, ~55pt radius;
# Pro Max 430pt; iPads ~18pt on 744-1024pt; MacBook display corners ~12px on
# ~1500pt; monitors square. Good enough to start a drag from; measure beats these.
PRESETS = [
    {"id": "phone-iphone", "type": "phone", "label": "iPhone 15 / 16 / Pro", "frac": 0.140},
    {"id": "phone-iphone-max", "type": "phone", "label": "iPhone Plus / Pro Max", "frac": 0.128},
    {"id": "phone-android", "type": "phone", "label": "Android (typical)", "frac": 0.090},
    {"id": "tablet-ipad-pro-11", "type": "tablet", "label": "iPad Pro 11 / Air", "frac": 0.022},
    {"id": "tablet-ipad-pro-13", "type": "tablet", "label": "iPad Pro 13", "frac": 0.018},
    {"id": "tablet-ipad-mini", "type": "tablet", "label": "iPad mini", "frac": 0.024},
    {"id": "laptop-macbook", "type": "laptop", "label": "MacBook Air / Pro", "frac": 0.008},
    {"id": "laptop-other", "type": "laptop", "label": "Other laptop (square)", "frac": 0.0},
    {"id": "desktop", "type": "desktop", "label": "Desktop monitor (square)", "frac": 0.0},
]


class BusyError(Exception):
    """A job is already in flight; enqueueing another would discard it."""


class Session:
    def __init__(self, path):
        self.dir = path
        os.makedirs(os.path.join(path, "thumbs"), exist_ok=True)
        self.state_path = os.path.join(path, "state.json")
        self.job_path = os.path.join(path, "job.json")
        self.result_path = os.path.join(path, "result.json")
        self.state = {"photo": None, "screenshot": None, "corners": None,
                      "radius_frac": None, "device": None, "output": None}
        self._save()

    def _save(self):
        _write_json_atomic(self.state_path, self.state)

    def read_job(self):
        """Tolerant read — a torn file reads as absent rather than raising."""
        try:
            with open(self.job_path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def enqueue(self, job):
        """Put a request in the outbox for the agent's blocking wait to pick up.

        There is one job slot. Overwriting a pending job would silently discard
        a request the agent may already be working on — press Import while a
        Figma export is in flight and the export result would be dropped with
        no sign of it. Refuse instead, and let the page say why.
        """
        current = self.read_job()
        if current and current.get("status") == "pending":
            raise BusyError("Claude is still working on the previous request. "
                            "Wait for it to finish, or reload the page to start over.")
        job.setdefault("id", f"{int(time.time() * 1000)}")
        job["status"] = "pending"
        job["requested"] = time.time()
        _write_json_atomic(self.job_path, job)
        return job

    def update(self, **kw):
        self.state.update(kw)
        self._save()


SESSION: Session = None


# Media a session COPIES rather than produces for keeps. Everything here is
# either a duplicate of a file the user already has, or something regenerable
# from the sidecar in seconds. The sidecar and state are not in the list: they
# are a few hundred bytes and they are the record of what was fitted, with the
# ORIGINAL paths in them. Keep the recipe, stop keeping the ingredients.
_RESIDUE_PREFIXES = ("photo-", "screenshot-", "poster-", "frame-")
# figma-export.png is a copy too -- the agent fetches the frame and drops it
# here -- and re-exporting is one MCP round trip, so it is residue like the rest.
_RESIDUE_NAMES = ("preview.png", "figma-export.png")


def _sidecar_sources(d):
    """Absolute paths inside `d` that this session's result.json still names.

    v0.23.0 swept these too, and the sidecar's whole promise is that a fit can
    be re-run from it. That promise held for a source picked by PATH, which
    was never copied -- and quietly broke for a drag-drop or browse, where the
    browser hands over bytes with no origin and the copy in the session IS the
    original as far as the sidecar is concerned. Measured after the first sweep:
    9 of 9 such sidecars pointed at a deleted file.

    So the rule is now: a session that produced output keeps what its sidecar
    names. A session that produced nothing keeps nothing -- there is no recipe
    to protect, which is the common case and where the volume is.

    Only paths INSIDE the session are returned. A path-picked source lives in
    the user's own folders and was never ours to keep or delete.

    Note the sidecar is rewritten on every save, so it names the LAST fit. An
    earlier source replaced within the same session is not protected: the record
    is what survives, and the record says what it says.
    """
    try:
        with open(os.path.join(d, "result.json")) as f:
            res = json.load(f)
    except (OSError, ValueError):
        return set()
    root = os.path.realpath(d)
    keep = set()
    for key in ("photo", "screenshot"):
        p = res.get(key)
        if not p:
            continue
        rp = os.path.realpath(p)
        if rp == root or rp.startswith(root + os.sep):
            keep.add(rp)
    return keep


def _sweep_session(d):
    """Delete a session's copied and derived media. Returns bytes reclaimed.

    Never touches *.json, never touches OUT_DIR -- the actual outputs live in
    the project folder and are the point of the whole exercise -- and never
    touches a source the session's own result.json still names (see above).
    """
    freed = 0
    thumbs = os.path.join(d, "thumbs")
    protected = _sidecar_sources(d)
    for base, _, files in os.walk(d):
        for f in files:
            keep = f.endswith(".json")
            residue = (f.startswith(_RESIDUE_PREFIXES) or f in _RESIDUE_NAMES
                       or base == thumbs)
            if keep or not residue:
                continue
            fp = os.path.join(base, f)
            if os.path.realpath(fp) in protected:
                continue
            try:
                freed += os.path.getsize(fp)
                os.remove(fp)
            except OSError:
                pass
    return freed


def _mark_unreproducible(d):
    """Stamp a sidecar whose named source no longer exists.

    For the sessions v0.23.0 already swept, nothing can be recovered -- the
    bytes are gone and the browser never said where they came from. What can be
    fixed is the claim: a sidecar that names a deleted file reads exactly like
    one that works, and the difference only shows up when someone tries to
    re-run it. `source_retained: false` says so up front.

    Idempotent, and it never touches a sidecar whose files are intact.
    """
    path = os.path.join(d, "result.json")
    try:
        with open(path) as f:
            res = json.load(f)
    except (OSError, ValueError):
        return False
    if "source_retained" in res:
        return False
    named = [res.get(k) for k in ("photo", "screenshot")]
    if not any(named) or all(p and os.path.exists(p) for p in named if p):
        return False
    res["source_retained"] = False
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(res, f, indent=1)
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def _prune_sessions(keep):
    """Sweep every session but the live one, at launch.

    Sessions are per-run scratch that nothing reads back, and a session keeps a
    full copy of every uploaded input -- a 21s clip is ~80 MB. Measured before
    this existed: 492 MB across 90 directories in six days, 64% of it duplicates
    of files the user already had, and nothing ever deleted any of it.

    A file chosen by PATH (the recent list, or typing one) was never copied --
    /api/use records the path and reads through it. Only a drag-drop or a browse
    has to be copied, because the browser hands over bytes and will not say
    where they came from. So this is the other half of the same policy: what
    cannot avoid being copied does not outlive the run that needed it --
    UNLESS the run produced something, in which case its sidecar names the
    source and _sweep_session keeps it. See _sidecar_sources: reproducibility
    beats disk exactly where a fit actually happened, and nowhere else.
    """
    root = os.path.dirname(keep)
    freed = 0
    try:
        names = os.listdir(root)
    except OSError:
        return 0
    for n in names:
        d = os.path.join(root, n)
        if d == keep or not os.path.isdir(d):
            continue
        freed += _sweep_session(d)
        # After sweeping, not before: a sidecar is only unreproducible once its
        # source is actually gone, and from here on the sweep leaves it alone.
        # This is for the sessions the previous release already emptied.
        _mark_unreproducible(d)
    return freed


def _version() -> str:
    """The shipped version, read from plugin.json rather than restated here.

    A second place to write a version is a second place for it to go stale --
    which is why check_package.py exists at all, after SKILL.md claimed the
    wrong one for three releases. The page asks the server; the server reads the
    manifest it was packaged with. Falls back to package.json, then to empty,
    because a missing badge is a far better failure than a confidently wrong
    one: a wrong version in a bug report costs more than no version.
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel in (os.path.join(".claude-plugin", "plugin.json"), "package.json"):
        try:
            with open(os.path.join(here, rel)) as f:
                v = json.load(f).get("version")
            if v:
                return str(v)
        except (OSError, ValueError, AttributeError):
            continue
    return ""


def _build_label() -> str:
    """Where this code came from: "" when installed, "dev <sha>[+]" from a tree.

    The distinction the badge exists for. A session materialises its own private
    copy of every installed plugin at start and keeps that snapshot for its whole
    life, so the installed copy and the tree you are editing drift apart within
    minutes -- and the symptom is a feature that is "not there", which reads
    exactly like a bug in the feature. That has cost two debugging sessions.

    `.git` is the discriminator because the packager excludes it: a tree has one,
    an unpacked .plugin never does. The commit and the dirty marker are here
    because on a day with four releases a bare "dev" is not enough to say WHICH
    dev, and a sha without a `+` when the tree is dirty would be a confident lie
    -- the failure mode this badge is supposed to prevent.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isdir(os.path.join(root, ".git")):
        return ""                              # an unpacked .plugin: just the version
    def git(*a):
        return subprocess.run(("git", "-C", root) + a, capture_output=True,
                              text=True, timeout=5)
    try:
        r = git("rev-parse", "--short", "HEAD")
        sha = r.stdout.strip() if r.returncode == 0 else ""
        d = git("status", "--porcelain")
        dirty = "+" if (d.returncode == 0 and d.stdout.strip()) else ""
    except (OSError, subprocess.SubprocessError):
        return "dev"                           # a tree, and that is the part that matters
    return f"dev {sha}{dirty}".strip() if sha else "dev"


VERSION = None                                 # resolved once, in main()
BUILD = ""                                     # ditto -- no per-request subprocess


def _quad(raw):
    """Four corners of two finite numbers, or a ValueError naming the problem.

    The compositing routes used to hand whatever arrived straight to the engine,
    so a malformed quad became a failure deep inside a worker thread -- or, on
    the render path, a job that was accepted, started, and then died somewhere
    the user could not see. The shape of the request is the route's business.
    """
    try:
        pts = [[float(x), float(y)] for x, y in raw]
    except (TypeError, ValueError) as e:
        raise ValueError(f"corners must be four [x, y] pairs ({e})") from e
    if len(pts) != 4:
        raise ValueError(f"corners must be four points, got {len(pts)}")
    if not all(v == v and abs(v) != float("inf") for pt in pts for v in pt):
        raise ValueError("corners contain a non-finite value")
    return pts


def _need_sources():
    """Both sources chosen, or a clean 400 saying which one is missing.

    Without this the compositing routes indexed straight into the session and
    handed `None` to `os.path.expanduser`, which raises TypeError -- a type the
    handler does not catch, so the worker thread died and the browser saw the
    connection drop with no status and no message at all. A request that cannot
    be served should be answered, not hung up on.
    """
    missing = [k for k in ("photo", "screenshot") if not SESSION.state.get(k)]
    if missing:
        raise ValueError("choose a " + " and a ".join(missing) + " first")


def _safe_local_path(p: str) -> str:
    """Only serve files under the user's home (the UI is local, but still)."""
    p = os.path.realpath(os.path.expanduser(p))
    if not p.startswith(os.path.realpath(HOME) + os.sep):
        raise PermissionError("outside home")
    if not os.path.isfile(p):
        raise FileNotFoundError(p)
    return p


def _read_image(path: str):
    p = _safe_local_path(path)
    im = cv2.imread(p, cv2.IMREAD_COLOR)
    if im is None and p.lower().endswith((".heic", ".heif")) and sys.platform == "darwin":
        conv = os.path.join(SESSION.dir, os.path.splitext(os.path.basename(p))[0] + ".jpg")
        subprocess.run(["sips", "-s", "format", "jpeg", p, "--out", conv], capture_output=True)
        im = cv2.imread(conv, cv2.IMREAD_COLOR)
        if im is not None:
            return im, conv
    if im is None:
        raise ValueError(f"could not read image: {p}")
    return im, p


VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv")


def _have_ffmpeg() -> bool:
    try:
        W.ffmpeg_exe()
        return True
    except RuntimeError:
        return False


def _is_video(path: str) -> bool:
    return str(path).lower().endswith(VIDEO_EXT)


def _fit_frame() -> int:
    try:
        return int(SESSION.state.get("fit_frame") or 0)
    except (TypeError, ValueError):
        return 0


def _read_source(path: str):
    """Read the screen source, which may be a still OR a video.

    Returns (frame, real_path, meta). For a video the frame is the poster —
    the frame the designer fits on — and `meta` carries what the page needs to
    show a scrubber. Everything downstream of this point treats that frame
    exactly like a screenshot, which is the point: the fit, the loupe, the
    compare view and the preview are all unchanged by video.
    """
    real = _safe_local_path(path)
    if not _is_video(real):
        im, rp = _read_image(real)
        return im, rp, {"video": False}
    n, fps, vw, vh = W.probe_video(real)
    # The frame the designer scrubbed to, NOT frame 0. Preview and Save read the
    # source through here, so reading frame 0 unconditionally made the scrubber
    # look decorative: it moved the thumbnail and the composite never changed
    # (reported 9 Sep 2026). The fitted frame is session state for exactly this
    # reason — more than one route needs it.
    frame = W.read_frame_at(real, _fit_frame())
    # Report the encoder's absence HERE, when the clip is chosen, rather than
    # letting the render fail at the end of the job. Someone who installed
    # screengraft before video existed has a working venv with no ffmpeg in it,
    # and nothing else would tell them until they had done all the fitting.
    # A poster for the chip. The chip used to be handed the .mov path directly,
    # and an <img> cannot render a video, so the thumbnail was silently blank for
    # every clip. It is always FRAME 0 and never follows the scrubber: at chip
    # size one frame looks like any other, so redrawing it would be movement
    # without information.
    poster = os.path.join(SESSION.dir,
                          "poster-" + os.path.splitext(os.path.basename(real))[0] + ".jpg")
    if not os.path.exists(poster):
        cv2.imwrite(poster, W.read_frame_at(real, 0), [cv2.IMWRITE_JPEG_QUALITY, 82])
    return frame, real, {"video": True, "frames": n, "fps": fps, "size": [vw, vh],
                         "ffmpeg": _have_ffmpeg(), "poster": poster}


# Render progress, read by /api/render_status. A ten-second clip is a few
# hundred frames and a good few seconds of work, which is far too long to hold
# an HTTP request open — so the render runs on its own thread and the page
# polls. ThreadingHTTPServer is already the server class, so this needs no
# other machinery.
RENDER = {"state": "idle", "done": 0, "total": 0, "output": None, "message": None}
RENDER_LOCK = threading.Lock()


def _render_worker(photo, video_path, corners, dest, radius_px, gr, grain, preset, fit_frame,
                   blend="replace", reflection=None, result=None):
    """Encode the clip, and only if that SUCCEEDS publish what it produced.

    `result` is the sidecar this render would write. It is handed to the worker
    rather than written by the route, because a sidecar written before the
    encode asserts `saved` for a file that may never exist -- and the sidecar is
    the first thing the bug template asks for, so a misleading one sends the
    next investigation the wrong way.

    Publication order matters: the sidecar and the session output are written
    BEFORE the state flips to "done". The page polls for "done" and may ask to
    send the file to Claude the moment it sees it, so the artefacts have to be
    in place first or that request races the worker.
    """
    def progress(done, total):
        with RENDER_LOCK:
            RENDER["done"], RENDER["total"] = done, total
    try:
        info = W.compose_video(photo, video_path, corners, dest,
                               corner_radius=radius_px, grade=gr, grain=grain,
                               preset=preset, fit_frame=fit_frame, progress=progress,
                               blend=blend,
                               reflection=(W.DEFAULT_REFLECTION if reflection is None
                                           else reflection))
        if result is not None:
            _write_json_atomic(SESSION.result_path, {**result, "saved": time.time()})
            # Same rule as /api/save, and for the same reason it lives after the
            # encode: the fit is remembered by the run that produced a file.
            key = FIT.key_for(photo)
            FIT.remember(key, corners, result.get("radius_frac"),
                         result.get("device"), result.get("photo"),
                         (photo.shape[1], photo.shape[0]))
            FF.write(dest, FF.build(corners, result.get("radius_frac"),
                                    result.get("device"), result.get("photo"),
                                    (photo.shape[1], photo.shape[0]), key))
        # The still path has always done this (see /api/save); the render path
        # never did, so /api/import -- which reads SESSION.state["output"] --
        # either found nothing or, worse, silently handed over the PREVIOUS
        # still image after a successful render.
        SESSION.update(output=dest)
        with RENDER_LOCK:
            RENDER.update(state="done", output=dest, info=info,
                          done=info["frames"], total=info["frames"], message=None)
    except Exception as e:                     # noqa: BLE001 - surfaced to the page
        with RENDER_LOCK:
            RENDER.update(state="error", message=str(e))


def _blend_args(b):
    """(blend, reflection) from the page's single `reflection` field.

    One field, not two: the page sends a number when the switch is on and null
    when it is off, so there is no way to express the contradictory state
    "emissive with no strength" — which is just `replace` under a different
    name. compose() still takes both, because the engine should not have to
    infer intent from a null.
    """
    r = b.get("reflection")
    if r is None:
        return "replace", W.DEFAULT_REFLECTION
    return "emissive", float(max(0.0, min(1.0, float(r))))


ROLES = ("photo", "screenshot")


def _adopt(role, path):
    """Make a chosen source the session's, and answer what the page needs.

    /api/use and /api/upload differ only in where the bytes came from --
    everything after that (the video probe, the session state, and now the
    remembered fit) has to be identical for a drag-drop and a path pick, or the
    feature works one way in and not the other. It was already written twice;
    the fit lookup would have made it three, and a set of writers that
    disagree is a defect this project has already shipped once.
    """
    # The role names a session-state key, and the line below writes it, so an
    # unchecked role is a write primitive: role="output" sets the pointer
    # /api/import reads, and the agent is then asked to show whatever file that
    # names. Nothing on this port authenticates, so the caller is not
    # necessarily the page. Two roles exist; anything else is a 400.
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    if role == "screenshot":
        SESSION.update(fit_frame=0)
        im, real, meta = _read_source(path)
    else:
        im, real = _read_image(path)
        meta = {"video": False}
    SESSION.update(**{role: real})
    if role == "photo":
        # The quad is a property of the PHOTOGRAPH, so a fit saved on an earlier
        # run is a better starting position than any detector -- and a stronger
        # claim, which is why the page states where the quad came from rather
        # than presenting a memory as a detection.
        e = FIT.recall(FIT.key_for(im))
        if e:
            meta["remembered"] = e
    return {"path": real, "size": [im.shape[1], im.shape[0]], **meta}


def _guess_type(corners):
    c = np.array(corners, dtype=float)
    w = (np.linalg.norm(c[1] - c[0]) + np.linalg.norm(c[2] - c[3])) / 2
    h = (np.linalg.norm(c[3] - c[0]) + np.linalg.norm(c[2] - c[1])) / 2
    if w <= 0 or h <= 0:
        return None
    r = h / w
    if r > 1.6:
        return "phone"
    if r > 1.1:
        return "tablet"
    if r > 0.5:
        return "laptop"
    return "desktop"


class Handler(BaseHTTPRequestHandler):
    server_version = "screengraft/0.3"

    def log_message(self, fmt, *args):  # quiet
        pass

    # ---- helpers ----
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype=None):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return self._json({"error": "not found"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", ctype or mimetypes.guess_type(path)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _jbody(self):
        raw = self._body()
        return json.loads(raw.decode() or "{}")

    # ---- GET ----
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path == "/":
                return self._file(UI_HTML, "text/html; charset=utf-8")
            if u.path == "/api/state":
                return self._json({**SESSION.state, "session": SESSION.dir, "out_dir": OUT_DIR,
                                   "home": HOME, "presets": PRESETS, "version": VERSION,
                                   "build": BUILD})
            if u.path == "/api/recent":
                items = S.scan(days=int(q.get("days", ["14"])[0]), limit=int(q.get("limit", ["40"])[0]))
                for it in items:
                    it["thumb"] = S.thumb(it, os.path.join(SESSION.dir, "thumbs"))
                return self._json({"items": items})
            if u.path == "/file":
                return self._file(_safe_local_path(q["path"][0]))
            if u.path == "/api/job":
                return self._json(SESSION.read_job() or {"status": "none"})

            if u.path == "/api/job/wait":
                # LONG POLL, not a timer. setInterval is throttled to roughly
                # once a minute in a hidden tab, and the tab is hidden for the
                # exact workflow this exists for: paste a Figma link, switch to
                # Figma. The agent would answer in 200ms and the page would sit
                # there for up to a minute. A pending fetch is not throttled, so
                # the answer lands as soon as it exists. (ThreadingHTTPServer,
                # so a blocked request does not hold up the rest of the page.)
                timeout = min(float(q.get("timeout", ["25"])[0]), 60.0)
                deadline = time.time() + timeout
                while True:
                    job = SESSION.read_job()
                    if not job:
                        return self._json({"status": "none"})
                    if job.get("status") != "pending":
                        return self._json(job)
                    if time.time() >= deadline:
                        return self._json({"status": "pending", "waited": True})
                    time.sleep(0.15)
            if u.path == "/api/render_status":
                # A poll, so a GET: no body, safe to repeat, and the page hits
                # it once a second while a render runs.
                with RENDER_LOCK:
                    return self._json(dict(RENDER))

            return self._json({"error": "no such route"}, 404)
        except (PermissionError, FileNotFoundError, KeyError, ValueError) as e:
            return self._json({"error": str(e)}, 400)
        except Exception as e:                 # noqa: BLE001 - the last resort
            # A type nobody enumerated must still produce a RESPONSE. Without
            # this the handler thread dies and the browser sees the connection
            # drop with no status and no message -- indistinguishable from the
            # server being gone, and impossible to report usefully. Twice in one
            # afternoon a bad input did exactly that: a None photo path reaching
            # expanduser, and a truncated clip whose frame read came back empty.
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    # ---- POST ----
    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        try:
            if u.path == "/api/upload":
                # raw bytes + X-Filename + X-Role (photo|screenshot); no multipart, no cgi module.
                name = os.path.basename(urllib.parse.unquote(self.headers.get("X-Filename") or "upload.png"))
                role = self.headers.get("X-Role") or "photo"
                dest = os.path.join(SESSION.dir, f"{role}-{int(time.time())}-{name}")
                with open(dest, "wb") as f:
                    f.write(self._body())
                # A video is only ever a screen source; a photo must be a still.
                return self._json(_adopt(role, dest))

            b = self._jbody()

            if u.path == "/api/use":
                return self._json(_adopt(b["role"], b["path"]))

            if u.path == "/api/figma":
                return self._json(SESSION.enqueue({
                    "type": "figma_export", "url": b["url"],
                    "save_to": os.path.join(SESSION.dir, "figma-export.png"),
                    "instructions": "Export this node as PNG at 3x via the Figma MCP "
                                    "(download_assets), save it to save_to, then call "
                                    "complete_job with status=done and path=<saved file>.",
                }))

            if u.path == "/api/import":
                # "Import to Claude". The page cannot put an image in the chat
                # panel — only the agent can, via present_files — so this is a
                # request, not an action. The file is already in OUT_DIR, which
                # the skill points at the project folder precisely so that
                # present_files will accept it.
                out = SESSION.state.get("output")
                if not out or not os.path.isfile(out):
                    return self._json({"error": "nothing saved yet"}, 400)
                return self._json(SESSION.enqueue({
                    "type": "present", "paths": [out],
                    "instructions": "Show these files to the user with present_files, say what "
                                    "you checked in the composite, then call complete_job "
                                    "with status=done.",
                }))

            if u.path == "/api/job/adopt":
                # page calls this once job.status == done, to make the export the screenshot
                with open(SESSION.job_path) as f:
                    job = json.load(f)
                im, real = _read_image(job["path"])
                SESSION.update(screenshot=real)
                return self._json({"path": real, "size": [im.shape[1], im.shape[0]]})

            if u.path == "/api/fit":
                # A fit file dropped onto the page. The page reads the bytes and
                # posts the parsed document; only the server can judge it,
                # because judging it means knowing what the OPEN photograph is.
                #
                # It never applies silently. Corners are meaningless on the wrong
                # image and *plausible but wrong* on a crop of the right one,
                # which is the more dangerous of the two — so every answer says
                # which of four situations it is and the page says it out loud.
                if not SESSION.state.get("photo"):
                    raise ValueError("choose the photo first, then drop the fit onto it")
                doc, err = FF.parse(b.get("fit"))
                if err:
                    return self._json({"error": err}, 400)
                photo, _p = _read_image(SESSION.state["photo"])
                corners, match, message = FF.apply_to(
                    doc, (photo.shape[1], photo.shape[0]), FIT.key_for(photo))
                return self._json({"corners": corners, "match": match,
                                   "message": message,
                                   "radius_frac": doc.get("radius_frac"),
                                   "device": doc.get("device"),
                                   "from": doc.get("photo", {}).get("name")})

            if u.path == "/api/detect":
                if not SESSION.state.get("photo"):
                    raise ValueError("choose a photo first")
                photo, _ = _read_image(SESSION.state["photo"])
                gray = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY)
                # An optional seed point, in PHOTO pixels. The detectors already
                # find the screen on these photographs -- 23 of 93 candidates
                # contained the click on the iPad that used to abstain -- they
                # just cannot tell which region is a screen. That is the one
                # question a person answers instantly, so the click filters the
                # candidate list and the existing score ranks what is left.
                click = b.get("click") if isinstance(b, dict) else None
                if click is not None:
                    try:
                        click = (float(click[0]), float(click[1]))
                    except (TypeError, ValueError, IndexError) as e:
                        raise ValueError(f"click must be [x, y] in photo pixels ({e})") from e
                    h, w = photo.shape[:2]
                    if not (0 <= click[0] < w and 0 <= click[1] < h):
                        raise ValueError("the click is outside the photograph")
                # `color` gives detect() the saturation detector — devices are
                # neutral, furniture is not, and grayscale throws that away.
                # The instrument, off unless asked for: the full
                # candidate list, with each quad's score and what became of it,
                # written beside the session. The page never shows it -- it is
                # for the next person diagnosing a detection failure, and for a
                # benchmark that needs to tell "never proposed" from "proposed
                # and beaten". The response carries the counts and the path, not
                # several hundred quads nobody asked the page to render.
                trace = [] if (isinstance(b, dict) and b.get("trace")) else None
                res = D.detect(gray, None, color=photo, click=click, trace=trace)
                if trace is not None:
                    tpath = os.path.join(SESSION.dir, "candidates.json")
                    counts = D.write_trace(tpath, SESSION.state["photo"], photo.shape,
                                           click, res, trace)
                    trace_info = {"path": tpath, "candidates": len(trace), **counts}
                if res is None:
                    return self._json({"found": False, "clicked": click is not None,
                                       **({"trace": trace_info} if trace is not None else {}),
                                       "message": ("Nothing screen-shaped was found around that "
                                                   "point — try clicking nearer the middle of the "
                                                   "screen." if click is not None else
                                                   "Neither detector could find a screen here "
                                                   "(nothing separable by tone, no screen-shaped "
                                                   "boundary). Place the four corners by hand.")})
                # An abstention is a miss, and must reach the page as one. On
                # 7 Sep 2026 a quad on a table was shown as a checkable guess
                # with two corners off the canvas, which cannot be dragged back
                # — worse than no guess at all. detect() keeps the
                # quad for inspection; the page gets the default rectangle.
                if res.get("abstained"):
                    return self._json({"found": False,
                                       "message": res["abstain_reason"],
                                       "abstained": True,
                                       **({"trace": trace_info} if trace is not None else {}),
                                       "inspect": res["corners"]})
                res.pop("_corners_np", None)
                res["found"] = True
                # How much the page should trust this. Both detectors agreeing is
                # the only case worth stating plainly; everything else is a guess
                # the human has to check, and must not be shown as a success.
                res["confidence"] = ("corroborated" if res.get("agreement", {}).get("agree")
                                     else "unconfirmed")
                res["type_guess"] = _guess_type(res["corners"])
                if trace is not None:
                    res["trace"] = trace_info
                return self._json(res)

            if u.path == "/api/frame":
                # One frame of the source video as a PNG the page can show — the
                # poster, or whichever frame the scrubber is on. The fit, the
                # loupe and the compare view all work on this exactly as they
                # work on a screenshot, which is why none of them needed
                # changing for video.
                spath = _safe_local_path(SESSION.state["screenshot"])
                if not _is_video(spath):
                    return self._json({"error": "the screen source is not a video"}, 400)
                # Records which frame the fit is judged on. Nothing is written:
                # the page re-renders the COMPOSITE from it, and the chip stays
                # on frame 0 deliberately, so a per-step PNG would be disk churn
                # nobody looks at.
                idx = int(b.get("index") or 0)
                SESSION.update(fit_frame=idx)
                return self._json({"index": idx})

            if u.path == "/api/render":
                # Video: same fit, same geometry, N frames instead of one.
                _need_sources()
                photo, ppath = _read_image(SESSION.state["photo"])
                spath = _safe_local_path(SESSION.state["screenshot"])
                if not _is_video(spath):
                    return self._json({"error": "the screen source is not a video"}, 400)
                if not _have_ffmpeg():
                    return self._json({"error": "ffmpeg is not installed",
                                       "needs_ffmpeg": True}, 400)
                # Cheap early out. The flag that actually reserves the render
                # is set further down, once nothing is left that can throw.
                with RENDER_LOCK:
                    if RENDER["state"] == "running":
                        return self._json({"error": "a render is already running"}, 409)
                corners = _quad(b["corners"])
                frac = float(b.get("radius_frac") or 0.0)
                fit_frame = int(b.get("fit_frame") if b.get("fit_frame") is not None
                                else _fit_frame())
                first = W.read_frame_at(spath, fit_frame)
                radius_px = frac * first.shape[1]
                gr = float(b.get("grade") if b.get("grade") is not None else 0.0)
                grain = bool(b.get("grain", gr > 0))
                blend, reflection = _blend_args(b)
                preset = "prores" if b.get("preset") == "prores" else "web"
                ext = ".mov" if preset == "prores" else ".mp4"
                os.makedirs(OUT_DIR, exist_ok=True)
                stem = (f"{os.path.splitext(os.path.basename(ppath))[0]}__"
                        f"{os.path.splitext(os.path.basename(spath))[0]}")
                dest = os.path.join(OUT_DIR, stem + ext)
                i = 2
                while os.path.exists(dest):
                    dest = os.path.join(OUT_DIR, f"{stem}-{i}{ext}"); i += 1
                SESSION.update(corners=corners, radius_frac=frac,
                               device=b.get("device"), grade=gr)
                # Everything that changes the output goes in the sidecar, for the
                # third time of asking (radius_px, then grade/grain, now the video
                # fields). A render that cannot be reproduced from its own sidecar
                # undercuts the determinism claim.
                result = {"output": dest, "photo": ppath, "screenshot": spath,
                          "corners": corners, "radius_frac": frac, "radius_px": radius_px,
                          "device": b.get("device"), "grade": gr, "grain": grain,
                          "video": True, "preset": preset, "fit_frame": fit_frame,
                          "blend": blend, "reflection": reflection}
                # `state="running"` means "a thread is running", so it is set
                # here -- after every line that can raise, immediately before the
                # thread exists. It used to be set at the top of this route, so a
                # KeyError on corners, a bad radius, an unreadable frame or an
                # unwritable out_dir left the flag stuck ON with no worker to
                # clear it, and every later render answered 409 for the rest of
                # the session. The only recovery was restarting the server, and
                # nothing said so.
                with RENDER_LOCK:
                    if RENDER["state"] == "running":
                        return self._json({"error": "a render is already running"}, 409)
                    RENDER.update(state="running", done=0, total=0,
                                  output=None, message=None)
                try:
                    threading.Thread(target=_render_worker, daemon=True,
                                     args=(photo, spath, corners, dest, radius_px,
                                           gr, grain, preset, fit_frame,
                                           blend, reflection, result)).start()
                except BaseException:
                    # If the thread cannot even be created, the flag must not
                    # outlive the request.
                    with RENDER_LOCK:
                        RENDER.update(state="error", message="could not start the render")
                    raise
                return self._json({"started": True, "output": dest, "preset": preset})

            if u.path in ("/api/preview", "/api/save"):
                _need_sources()
                photo, ppath = _read_image(SESSION.state["photo"])
                shot, spath, _meta = _read_source(SESSION.state["screenshot"])
                corners = _quad(b["corners"])
                frac = float(b.get("radius_frac") or 0.0)
                radius_px = frac * shot.shape[1]
                # M2 realism pass. Off is a real option, not a fallback: a flat
                # composite is the right output when the screenshot's own colour
                # is the point (a brand review), and the grade is the right one
                # when the photograph is (a portfolio shot).
                gr = float(b.get("grade") if b.get("grade") is not None else 0.0)
                blend, reflection = _blend_args(b)
                out = W.compose(photo, shot, corners, radius_px,
                                grade=gr, grain=bool(b.get("grain", gr > 0)),
                                blend=blend, reflection=reflection)
                SESSION.update(corners=corners, radius_frac=frac, device=b.get("device"),
                               grade=gr)
                if u.path == "/api/preview":
                    dest = os.path.join(SESSION.dir, "preview.png")
                    # preview at <=1600px wide for speed; Save renders full-res
                    h, w = out.shape[:2]
                    if w > 1600:
                        s = 1600 / w
                        out = cv2.resize(out, (1600, int(h * s)), interpolation=cv2.INTER_AREA)
                    cv2.imwrite(dest, out, [cv2.IMWRITE_PNG_COMPRESSION, 3])
                    return self._json({"path": dest, "radius_px": round(radius_px, 1)})
                os.makedirs(OUT_DIR, exist_ok=True)
                stem = f"{os.path.splitext(os.path.basename(ppath))[0]}__{os.path.splitext(os.path.basename(spath))[0]}"
                dest = os.path.join(OUT_DIR, stem + ".png")
                i = 2
                while os.path.exists(dest):
                    dest = os.path.join(OUT_DIR, f"{stem}-{i}.png"); i += 1
                cv2.imwrite(dest, out, [cv2.IMWRITE_PNG_COMPRESSION, 9])
                # radius_px is NOT rounded here. It was, and re-running
                # compose from the sidecar then reproduced neither the old nor
                # the new code path — 144.7 vs the actual 144.72 was enough to
                # move boundary pixels. A sidecar that cannot reproduce its own
                # output undercuts the determinism claim; round for display only.
                # EVERY argument that changes the output belongs here. `grade` and
                # `grain` were added to compose() and not to this dict, so a save
                # made with the realism pass on could not be reproduced from its
                # own sidecar — the same defect fixed earlier for radius_px, in a new
                # field, with the warning above it. test_sidecar.py now compares
                # these keys against compose()'s signature so the next parameter
                # cannot be forgotten the same way.
                result = {"output": dest, "photo": ppath, "screenshot": spath, "corners": corners,
                          "radius_frac": frac, "radius_px": radius_px, "device": b.get("device"),
                          "grade": gr, "grain": bool(b.get("grain", gr > 0)),
                          "blend": blend, "reflection": reflection,
                          "saved": time.time()}
                # A fit is remembered when it PRODUCED something, not while it
                # is being dragged: a quad on the canvas is a work in progress,
                # a quad that made an output is one the person looked at and
                # kept. Next run on this photograph starts from it.
                key = FIT.key_for(photo)
                FIT.remember(key, corners, frac, b.get("device"),
                             ppath, (photo.shape[1], photo.shape[0]))
                # ...and the portable half: a file beside the mockup, in the
                # folder the user already chose. The store above is invisible and
                # keyed on this machine's copy of the pixels; this one can be
                # found in Finder, kept with the project, sent to someone, and
                # dragged back in against a re-export the key would miss.
                result["fit_file"] = FF.write(dest, FF.build(
                    corners, frac, b.get("device"), ppath,
                    (photo.shape[1], photo.shape[0]), key))
                # Sidecar first, THEN the session output: /api/import reads that
                # pointer and may be called the moment this returns, and the
                # bug template asks for the sidecar first. Same publication order
                # the render worker uses, and for the same reason.
                _write_json_atomic(SESSION.result_path, result)
                SESSION.update(output=dest)
                return self._json(result)

            return self._json({"error": "no such route"}, 404)
        except BusyError as e:
            return self._json({"error": str(e)}, 409)
        except (PermissionError, FileNotFoundError, KeyError, ValueError) as e:
            return self._json({"error": str(e)}, 400)
        except Exception as e:                 # noqa: BLE001 - the last resort
            # A type nobody enumerated must still produce a RESPONSE. Without
            # this the handler thread dies and the browser sees the connection
            # drop with no status and no message -- indistinguishable from the
            # server being gone, and impossible to report usefully. Twice in one
            # afternoon a bad input did exactly that: a None photo path reaching
            # expanduser, and a truncated clip whose frame read came back empty.
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _daemonise(log_path):
    """Detach fully: double-fork, setsid, reopen stdio.

    A plain `nohup ... &` was tried on 3 Sep 2026 and the server died silently
    between turns, twice — the launching shell's session teardown took the
    merely-backgrounded child with it. The fix then was a Terminal window,
    which survives but leaves a dead "[Process completed]" window behind after
    every session. setsid puts this process in its own session with no
    controlling terminal, so it survives the parent AND leaves nothing to
    clean up.

    The first fork lets the parent exit so the shell gets its prompt back; the
    second stops the daemon from ever acquiring a controlling terminal.
    """
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    log = open(log_path or os.devnull, "a", buffering=1)
    os.dup2(log.fileno(), sys.stdout.fileno())
    os.dup2(log.fileno(), sys.stderr.fileno())
    devnull = open(os.devnull, "r")
    os.dup2(devnull.fileno(), sys.stdin.fileno())


def _publish_current(payload):
    """Announce this UI instance to the MCP server, and clear it on the way out.

    The pointer carries our pid so a stale file from a crashed UI reads as
    'no UI' rather than as one that never answers — the agent would otherwise
    block for a full timeout against a session nobody is looking at.
    """
    os.makedirs(os.path.dirname(CURRENT), exist_ok=True)
    _write_json_atomic(CURRENT, payload)

    def clear():
        cur = None
        try:
            with open(CURRENT) as f:
                cur = json.load(f)
        except (OSError, ValueError):
            return
        # Only remove our own pointer: a newer UI may have replaced it, and
        # deleting that one would strand the session the user is actually in.
        if cur.get("pid") == os.getpid():
            try:
                os.remove(CURRENT)
            except OSError:
                pass

    atexit.register(clear)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: sys.exit(0))   # sys.exit runs atexit; kill -9 cannot be caught, which is why the pid check exists


def main():
    global SESSION, OUT_DIR, VERSION, BUILD
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=0, help="0 = pick a free port")
    ap.add_argument("--no-open", action="store_true", help="Don't open the browser")
    ap.add_argument("--session", help="Session dir (default ~/.screengraft/sessions/<timestamp>)")
    ap.add_argument("--out-dir", help="Where Save writes (default ~/Desktop/screengraft). "
                                      "The skill passes <project>/mockups so saves land in the "
                                      "folder the designer is working in.")
    ap.add_argument("--daemon", action="store_true",
                    help="Detach into the background (double-fork + setsid) instead of running "
                         "in a Terminal window. Survives the launching shell being torn down, "
                         "which a plain background job does not — see an earlier finding.")
    ap.add_argument("--log", help="With --daemon: where stdout/stderr go.")
    args = ap.parse_args()

    if args.daemon:
        _daemonise(args.log)

    VERSION = _version()
    BUILD = _build_label()
    if args.out_dir:
        OUT_DIR = os.path.abspath(os.path.expanduser(args.out_dir))
    sdir = args.session or os.path.join(HOME, ".screengraft", "sessions", time.strftime("%Y%m%d-%H%M%S"))
    SESSION = Session(sdir)
    port = args.port or free_port()
    url = f"http://127.0.0.1:{port}/"
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    freed = _prune_sessions(sdir)
    # The live session's own copies go when this process does. Registered before
    # serve_forever, and the SIGTERM handler exits via sys.exit so atexit runs --
    # scripts/stop.sh sends SIGTERM for exactly this reason. A kill -9 cannot be
    # caught, which is what the launch-time sweep above is for.
    atexit.register(lambda: _sweep_session(sdir))
    _publish_current({"session": sdir, "url": url, "pid": os.getpid(),
                      "out_dir": OUT_DIR, "started": time.time()})
    print(json.dumps({"url": url, "session": sdir, "job": SESSION.job_path,
                      "result": SESSION.result_path, "out_dir": OUT_DIR,
                      "reclaimed_mb": round(freed / 1e6, 1)}), flush=True)
    if not args.no_open:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        threading.Timer(0.3, lambda: subprocess.Popen([opener, url])).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
