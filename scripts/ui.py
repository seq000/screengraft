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
                                   "home": HOME, "presets": PRESETS})
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
            return self._json({"error": "no such route"}, 404)
        except (PermissionError, FileNotFoundError, KeyError, ValueError) as e:
            return self._json({"error": str(e)}, 400)

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
                im, real = _read_image(dest)
                SESSION.update(**{role: real})
                return self._json({"path": real, "size": [im.shape[1], im.shape[0]]})

            b = self._jbody()

            if u.path == "/api/use":
                role = b["role"]
                im, real = _read_image(b["path"])
                SESSION.update(**{role: real})
                return self._json({"path": real, "size": [im.shape[1], im.shape[0]]})

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

            if u.path == "/api/detect":
                photo, _ = _read_image(SESSION.state["photo"])
                gray = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY)
                res = D.detect(gray, None)
                if res is None:
                    return self._json({"found": False,
                                       "message": "Neither detector could find a screen here "
                                                  "(nothing separable by tone, no screen-shaped "
                                                  "boundary). Place the four corners by hand."})
                res.pop("_corners_np", None)
                res["found"] = True
                # How much the page should trust this. Both detectors agreeing is
                # the only case worth stating plainly; everything else is a guess
                # the human has to check, and must not be shown as a success.
                res["confidence"] = ("corroborated" if res.get("agreement", {}).get("agree")
                                     else "unconfirmed")
                res["type_guess"] = _guess_type(res["corners"])
                return self._json(res)

            if u.path in ("/api/preview", "/api/save"):
                photo, ppath = _read_image(SESSION.state["photo"])
                shot, spath = _read_image(SESSION.state["screenshot"])
                corners = b["corners"]
                frac = float(b.get("radius_frac") or 0.0)
                radius_px = frac * shot.shape[1]
                # M2 realism pass. Off is a real option, not a fallback: a flat
                # composite is the right output when the screenshot's own colour
                # is the point (a brand review), and the grade is the right one
                # when the photograph is (a portfolio shot).
                gr = float(b.get("grade") if b.get("grade") is not None else 0.0)
                out = W.compose(photo, shot, corners, radius_px,
                                grade=gr, grain=bool(b.get("grain", gr > 0)))
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
                          "saved": time.time()}
                _write_json_atomic(SESSION.result_path, result)
                SESSION.update(output=dest)
                return self._json(result)

            return self._json({"error": "no such route"}, 404)
        except BusyError as e:
            return self._json({"error": str(e)}, 409)
        except (PermissionError, FileNotFoundError, KeyError, ValueError) as e:
            return self._json({"error": str(e)}, 400)


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
    global SESSION, OUT_DIR
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

    if args.out_dir:
        OUT_DIR = os.path.abspath(os.path.expanduser(args.out_dir))
    sdir = args.session or os.path.join(HOME, ".screengraft", "sessions", time.strftime("%Y%m%d-%H%M%S"))
    SESSION = Session(sdir)
    port = args.port or free_port()
    url = f"http://127.0.0.1:{port}/"
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    _publish_current({"session": sdir, "url": url, "pid": os.getpid(),
                      "out_dir": OUT_DIR, "started": time.time()})
    print(json.dumps({"url": url, "session": sdir, "job": SESSION.job_path,
                      "result": SESSION.result_path, "out_dir": OUT_DIR}), flush=True)
    if not args.no_open:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        threading.Timer(0.3, lambda: subprocess.Popen([opener, url])).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
