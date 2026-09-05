#!/usr/bin/env python3
"""Tests for the screengraft MCP server.

Drives the REAL stdio protocol in a subprocess rather than importing the tool
functions. The point of this server is that a host talks to it over JSON-RPC
on a pipe; a test that skipped the transport would pass on a server the host
cannot speak to, which is the failure that actually matters.

Everything runs against a temp HOME, so a live ~/.screengraft and any UI the
developer has open are untouched.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(os.path.dirname(HERE), "mcp", "server.py")

failures = 0


def check(name, cond, detail=""):
    global failures
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}{(' - ' + detail) if detail else ''}")
    if not cond:
        failures += 1
    return cond


class Server:
    """A live server subprocess, spoken to exactly as a host would."""

    def __init__(self, home):
        env = {**os.environ, "HOME": home}
        self.p = subprocess.Popen(
            [sys.executable, SERVER], env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1)
        self._id = 0

    def send(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self._id += 1
            msg["id"] = self._id
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def read(self, timeout=20):
        """Read one message, giving up rather than hanging the suite forever."""
        box = {}

        def rd():
            box["line"] = self.p.stdout.readline()

        t = threading.Thread(target=rd, daemon=True)
        t.start()
        t.join(timeout)
        if not box.get("line"):
            return None
        return json.loads(box["line"])

    def call(self, tool, args=None, timeout=20):
        self.send("tools/call", {"name": tool, "arguments": args or {}})
        msg = self.read(timeout)
        if msg is None:
            return None
        content = msg.get("result", {}).get("content", [{}])
        return json.loads(content[0].get("text", "{}"))

    def close(self):
        try:
            self.p.stdin.close()
        except OSError:
            pass
        self.p.terminate()
        try:
            self.p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.p.kill()


def make_session(home, pid=None, out_dir="/tmp/out"):
    """Fake what ui.py publishes: a session dir plus a current.json pointer."""
    sess = os.path.join(home, ".screengraft", "sessions", "test")
    os.makedirs(sess, exist_ok=True)
    cur = {"session": sess, "url": "http://127.0.0.1:1/", "pid": pid or os.getpid(),
           "out_dir": out_dir, "started": time.time()}
    with open(os.path.join(home, ".screengraft", "current.json"), "w") as f:
        json.dump(cur, f)
    return sess


def enqueue(sess, job):
    job.setdefault("status", "pending")
    p = os.path.join(sess, "job.json")
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(job, f)
    os.replace(tmp, p)
    return p


def run(home):
    print("handshake and discovery")
    s = Server(home)
    s.send("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                          "clientInfo": {"name": "t", "version": "0"}})
    init = s.read()
    check("initialize is answered", bool(init) and "result" in (init or {}))
    if init:
        r = init["result"]
        check("echoes the client's protocol version",
              r.get("protocolVersion") == "2025-06-18", str(r.get("protocolVersion")))
        check("declares the tools capability", "tools" in r.get("capabilities", {}))
    s.send("notifications/initialized", {}, notify=True)

    s.send("tools/list")
    lst = s.read()
    names = sorted(t["name"] for t in lst["result"]["tools"]) if lst else []
    check("tools/list returns both tools", names == ["complete_job", "wait_for_job"], str(names))
    check("every tool has an inputSchema",
          bool(lst) and all("inputSchema" in t for t in lst["result"]["tools"]))

    print("\nno UI running")
    r = s.call("wait_for_job", {"timeout_s": 5})
    check("returns no_ui instead of blocking", r and r.get("status") == "no_ui", str(r))

    print("\na job already waiting is returned at once")
    sess = make_session(home)
    enqueue(sess, {"type": "figma_export", "url": "u", "save_to": "/tmp/x.png"})
    t0 = time.time()
    r = s.call("wait_for_job", {"timeout_s": 20})
    dt = time.time() - t0
    check("status=job", r and r.get("status") == "job", str(r and r.get("status")))
    check("carries the job body", r and r["job"].get("type") == "figma_export")
    check("carries out_dir so the agent knows where saves land",
          r and r.get("out_dir") == "/tmp/out")
    check("returns without waiting out the timeout", dt < 1.0, f"{dt:.2f}s")

    print("\ncomplete_job round-trip")
    r = s.call("complete_job", {"status": "done", "path": "/nope.png"})
    check("rejects a figma_export completion whose file does not exist",
          r and r.get("ok") is False, str(r))
    real = os.path.join(home, "real.png")
    with open(real, "wb") as f:
        f.write(b"x")
    r = s.call("complete_job", {"status": "done", "path": real})
    check("accepts a real file", r and r.get("ok") is True, str(r))
    job = json.load(open(os.path.join(sess, "job.json")))
    check("job.json now reads done", job.get("status") == "done", str(job.get("status")))
    check("job.json carries the path the page will adopt", job.get("path") == real)

    print("\nblocking, then waking on a job that arrives mid-wait")
    # The behaviour the whole design rests on: the agent is parked, the user
    # presses a button, and the call returns promptly rather than at timeout.
    def press_later():
        time.sleep(1.5)
        enqueue(sess, {"type": "present", "paths": ["/tmp/a.png"]})

    threading.Thread(target=press_later, daemon=True).start()
    t0 = time.time()
    r = s.call("wait_for_job", {"timeout_s": 30})
    dt = time.time() - t0
    check("woke on the enqueue", r and r.get("status") == "job", str(r and r.get("status")))
    check("job type is present", r and r["job"].get("type") == "present")
    check("woke promptly, not at timeout", 1.4 < dt < 3.0, f"{dt:.2f}s")

    print("\npresent jobs complete without a path")
    r = s.call("complete_job", {"status": "done"})
    check("no path required for a present job", r and r.get("ok") is True, str(r))

    print("\nerror completion")
    enqueue(sess, {"type": "figma_export", "url": "u", "save_to": "/tmp/x.png"})
    r = s.call("complete_job", {"status": "error", "message": "Figma MCP not available"})
    check("error is accepted", r and r.get("ok") is True)
    job = json.load(open(os.path.join(sess, "job.json")))
    check("the message reaches the page", job.get("message") == "Figma MCP not available")
    r = s.call("complete_job", {"status": "banana"})
    check("rejects an unknown status", r and r.get("ok") is False)

    print("\nstale completions cannot land on a newer job")
    # Only bites when the agent is slow and the user restarted, but silently
    # completing the wrong job leaves them on a spinner that never resolves.
    enqueue(sess, {"type": "present", "paths": ["/tmp/a.png"], "id": "JOB-A"})
    r = s.call("complete_job", {"status": "done", "job_id": "JOB-OLD"})
    check("a completion for a different job id is refused", r and r.get("ok") is False, str(r))
    r = s.call("complete_job", {"status": "done", "job_id": "JOB-A"})
    check("the matching job id is accepted", r and r.get("ok") is True, str(r))
    r = s.call("complete_job", {"status": "done", "job_id": "JOB-A"})
    check("completing an already-finished job is refused", r and r.get("ok") is False, str(r))

    print("\ntimeout is clamped below the host's tool-call ceiling")
    # A wait_for_job(300) was killed by the host at 180s on 4 Sep 2026 — the
    # call never returned, so the agent missed the wake it was parked for.
    # Anything the caller asks for must be clamped to something the host will
    # actually let finish.
    import importlib.util as _il
    _sp = _il.spec_from_file_location("sgserver", SERVER)
    _m = _il.module_from_spec(_sp); _sp.loader.exec_module(_m)
    check("MAX_TIMEOUT stays under the observed host ceiling",
          _m.MAX_TIMEOUT < _m.HOST_CALL_CEILING,
          f"max {_m.MAX_TIMEOUT}s vs ceiling {_m.HOST_CALL_CEILING}s")
    check("the default leaves plenty of headroom",
          _m.DEFAULT_TIMEOUT < _m.MAX_TIMEOUT, f"default {_m.DEFAULT_TIMEOUT}s")
    # Don't actually wait out the clamp here — 150s in a test suite is worse
    # than useless. Prove the call ACCEPTS an absurd value and still behaves,
    # by making sure a job is already waiting so it returns at once.
    enqueue(sess, {"type": "present", "paths": ["/tmp/a.png"], "id": "CLAMP"})
    t0 = time.time()
    r = s.call("wait_for_job", {"timeout_s": 99999}, timeout=20)
    check("an absurd timeout is accepted and does not hang the call",
          r is not None and r.get("status") == "job" and time.time() - t0 < 5,
          f"{time.time() - t0:.2f}s")
    s.call("complete_job", {"status": "done", "job_id": "CLAMP"})

    print("\ntimeout path")
    t0 = time.time()
    r = s.call("wait_for_job", {"timeout_s": 2})
    dt = time.time() - t0
    check("returns status=timeout", r and r.get("status") == "timeout", str(r))
    check("honours the requested timeout", 1.8 < dt < 4.0, f"{dt:.2f}s")

    print("\nthe UI going away")
    # A pointer whose process is gone must read as closed, not as a live UI,
    # or the agent blocks a full timeout against a session nobody is in.
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    make_session(home, pid=dead.pid)
    r = s.call("wait_for_job", {"timeout_s": 5})
    check("a pointer with a dead pid reads as no_ui", r and r.get("status") == "no_ui", str(r))

    make_session(home)

    def close_later():
        time.sleep(1.0)
        os.remove(os.path.join(home, ".screengraft", "current.json"))

    threading.Thread(target=close_later, daemon=True).start()
    t0 = time.time()
    r = s.call("wait_for_job", {"timeout_s": 30})
    check("a UI that exits mid-wait returns ui_closed",
          r and r.get("status") == "ui_closed", str(r and r.get("status")))
    check("and returns promptly", time.time() - t0 < 3.0)

    print("\nrobustness")
    sess = make_session(home)
    # A torn job.json must be retried, not crash the call. ui.py writes
    # atomically so it should not happen, but a crash here would reach the user
    # as a failed tool call instead of a harmless retry.
    with open(os.path.join(sess, "job.json"), "w") as f:
        f.write('{"type": "figma_ex')
    r = s.call("wait_for_job", {"timeout_s": 2})
    check("a half-written job file is tolerated", r and r.get("status") == "timeout", str(r))

    s.send("tools/call", {"name": "no_such_tool", "arguments": {}})
    msg = s.read()
    check("an unknown tool is a protocol error", bool(msg) and "error" in msg)

    s.send("nonsense/method")
    msg = s.read()
    check("an unknown method returns method-not-found",
          bool(msg) and msg.get("error", {}).get("code") == -32601)

    s.p.stdin.write("this is not json\n")
    s.p.stdin.flush()
    s.send("ping")
    msg = s.read()
    check("a garbage line does not kill the server", bool(msg) and "result" in msg)

    print("\nblocking does not stall other traffic")
    # If the wait ran on the read loop, ping would queue behind it and a host
    # could decide the server is dead.
    os.remove(os.path.join(sess, "job.json"))
    make_session(home)
    s.send("tools/call", {"name": "wait_for_job", "arguments": {"timeout_s": 6}})
    time.sleep(0.4)
    s.send("ping")
    first = s.read(timeout=4)
    check("ping is answered while a wait is in flight",
          bool(first) and first.get("result") == {}, str(first))
    rest = s.read(timeout=15)
    check("the blocked wait still returns afterwards", bool(rest) and "result" in rest)

    s.close()


def main():
    home = tempfile.mkdtemp(prefix="sg-mcp-test-")
    os.makedirs(os.path.join(home, ".screengraft"), exist_ok=True)
    try:
        run(home)
    finally:
        shutil.rmtree(home, ignore_errors=True)

    print()
    if failures:
        print(f"{failures} check(s) failed")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
