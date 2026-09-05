#!/usr/bin/env python3
"""screengraft MCP server — lets the browser UI reach the agent.

WHY THIS EXISTS
---------------
The UI is a local web page. When the designer pastes a Figma link or presses
"Import to Claude", something has to happen *in the agent*. The agent cannot
poll: it runs in turns, and between turns nothing of it is executing. The old
SKILL.md told it to "poll job.json every few seconds", which was never
achievable, and the page told the user "(it watches this job)", which was
false. The user sat waiting for an agent that was not running.

The fix is to invert it. The agent cannot poll, but it CAN block: a tool call
may take as long as the host allows (measured 4 Sep 2026: 94s returns cleanly;
the bash cap on the same host is 600s). So the page gets an outbox and the
agent gets a blocking inbox. `wait_for_job` parks until the user presses a
button and returns within ~150ms of the press.

DESIGN CONSTRAINTS
------------------
1. **Stdlib only, system python3.** A plugin's MCP server starts when the
   plugin is enabled — which is before preflight has necessarily built
   ~/.screengraft/venv. Importing cv2, numpy or the `mcp` package here would
   make the server fail to load on a fresh install, and the tools would simply
   be missing with no good error. So: no third-party imports in this file.
2. **Threaded dispatch.** Blocking inside the stdin read loop would stall the
   host's own traffic (ping, tools/list) for the length of the wait, and a host
   that gets no reply may treat the server as dead. Each request is handled on
   its own thread; stdout writes are serialised by a lock.
3. **No state of its own.** The session dir on disk is the only truth. The
   server can be restarted mid-job and lose nothing.
"""

import json
import os
import sys
import threading
import time

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, ".screengraft")
CURRENT = os.path.join(ROOT, "current.json")

POLL_S = 0.15          # how often the wait loop looks at the outbox
DEFAULT_TIMEOUT = 90   # measured safe; also bounds how long a chat message waits
# The host kills an MCP tool call well before the shell tool's own cap. Measured
# 4 Sep 2026: a bash call blocked 94s cleanly and the bash cap is 600s, so 300
# looked safe here -- but a real wait_for_job(300) was killed by the host at
# exactly 180s. The orphaned call loses no data (an unanswered job stays pending
# and the next wait picks it up) but the agent misses the wake it was parked
# for, which is the one thing this server exists to deliver. So: stay clearly
# under the observed ceiling rather than at it, and clamp rather than trust the
# caller, because the caller is an agent reading a description.
HOST_CALL_CEILING = 180
MAX_TIMEOUT = 150

_out_lock = threading.Lock()


# ---------------------------------------------------------------- transport

def _send(msg):
    """One JSON-RPC message per line on stdout, serialised across threads."""
    with _out_lock:
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()


def _result(req_id, payload):
    _send({"jsonrpc": "2.0", "id": req_id, "result": payload})


def _error(req_id, code, message):
    _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def _text(payload):
    """MCP tool results are content blocks; we always return one JSON block."""
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=1)}]}


# ------------------------------------------------------------------ session

def _read_json(path):
    """Tolerant read: a torn file is treated as absent, not as an error.

    ui.py writes atomically (tmp + os.replace) so this shouldn't happen, but a
    half-read here would surface as a crashed tool call rather than a retry,
    and the retry is free — we're in a poll loop.
    """
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def current_session():
    """The UI instance the agent should be talking to, or None.

    A pointer file left behind by a crashed UI is worse than no pointer: the
    agent would wait out a full timeout against a session nobody is looking at.
    So the pid is checked on every read and a dead pointer is reported as gone.
    """
    cur = _read_json(CURRENT)
    if not cur:
        return None
    if not _pid_alive(cur.get("pid")):
        return None
    if not os.path.isdir(cur.get("session") or ""):
        return None
    return cur


# -------------------------------------------------------------------- tools

TOOLS = [
    {
        "name": "wait_for_job",
        "description": (
            "Block until the screengraft UI asks the agent to do something, then return "
            "that request. Call this immediately after launching the UI and again after "
            "each completed job, so a button press is picked up without the user having "
            "to type anything in chat.\n\n"
            "Returns one of:\n"
            "  status=job        — a request to handle. `job.type` is 'figma_export' "
            "(export job.url via the Figma MCP at 3x PNG, save to job.save_to, then call "
            "complete_job) or 'present' (show job.paths to the user with present_files, "
            "then call complete_job).\n"
            "  status=timeout    — nothing happened within timeout_s. The UI is still up; "
            "call again to keep waiting.\n"
            "  status=ui_closed  — the UI exited. Stop waiting and tell the user.\n"
            "  status=no_ui      — no UI is running. Launch it first.\n\n"
            "Blocking is the point: the agent cannot poll between turns, so this call is "
            "how a local web page reaches it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "timeout_s": {
                    "type": "number",
                    "description": f"Seconds to block before returning status=timeout "
                                   f"(default {DEFAULT_TIMEOUT}, max {MAX_TIMEOUT} \u2014 the host kills a tool call at "
                                   f"~{HOST_CALL_CEILING}s, so anything larger is clamped). Shorter "
                                   f"timeouts return control sooner so the user's own chat "
                                   f"messages are not delayed behind the wait.",
                }
            },
        },
    },
    {
        "name": "complete_job",
        "description": (
            "Report the outcome of the job most recently returned by wait_for_job. The page "
            "is polling for this and will not move on until it arrives — always call it, "
            "including on failure, or the user is left watching a spinner."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["done", "error"]},
                "path": {"type": "string", "description": "For figma_export: the saved PNG."},
                "message": {"type": "string", "description": "For status=error: what went wrong, in a sentence the designer can act on."},
                "job_id": {"type": "string",
                           "description": "The `id` from the job wait_for_job returned. Pass it: it "
                                          "stops a late completion from landing on a different job "
                                          "the user has since started."},
            },
            "required": ["status"],
        },
    },
]


def tool_wait_for_job(args):
    timeout = args.get("timeout_s")
    try:
        timeout = float(timeout) if timeout is not None else DEFAULT_TIMEOUT
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    timeout = max(1.0, min(timeout, MAX_TIMEOUT))

    cur = current_session()
    if not cur:
        return {"status": "no_ui",
                "hint": "No screengraft UI is running. Launch it with scripts/launch.sh."}

    job_path = os.path.join(cur["session"], "job.json")
    deadline = time.time() + timeout
    while True:
        job = _read_json(job_path)
        if job and job.get("status") == "pending":
            return {"status": "job", "job": job, "session": cur["session"],
                    "out_dir": cur.get("out_dir")}
        if not current_session():
            return {"status": "ui_closed",
                    "hint": "The UI exited. Anything not yet saved is gone; say so rather than waiting."}
        if time.time() >= deadline:
            return {"status": "timeout", "waited_s": round(timeout, 1),
                    "hint": "Still up, nothing pressed. Call wait_for_job again to keep waiting."}
        time.sleep(POLL_S)


def tool_complete_job(args):
    cur = current_session()
    if not cur:
        return {"ok": False, "error": "no UI running"}
    job_path = os.path.join(cur["session"], "job.json")
    job = _read_json(job_path)
    if not job:
        return {"ok": False, "error": "no job to complete"}

    status = args.get("status")
    if status not in ("done", "error"):
        return {"ok": False, "error": "status must be 'done' or 'error'"}

    # Guard against completing something other than what was handed out. The
    # page refuses to enqueue over a pending job, so this only bites when the
    # agent is slow and the user has reloaded and started again — but silently
    # marking the new job done would leave them waiting on a spinner forever.
    want = args.get("job_id")
    if want and str(job.get("id")) != str(want):
        return {"ok": False,
                "error": f"job {want} is no longer current (the session is on {job.get('id')}). "
                         f"The user has started something else; do not complete this one."}
    if job.get("status") != "pending":
        return {"ok": False,
                "error": f"this job is already {job.get('status')}, nothing to complete"}

    job["status"] = status
    job["completed"] = time.time()
    if status == "done":
        path = args.get("path")
        # figma_export is the only job whose completion carries a file; for a
        # 'present' job there is nothing to hand back and path is meaningless.
        if job.get("type") == "figma_export":
            if not path or not os.path.isfile(path):
                return {"ok": False,
                        "error": f"figma_export needs `path` to be a file that exists (got {path!r})"}
            job["path"] = path
    else:
        job["message"] = args.get("message") or "The agent could not complete this."

    tmp = job_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(job, f, indent=1)
    os.replace(tmp, job_path)
    return {"ok": True, "status": status}


DISPATCH = {"wait_for_job": tool_wait_for_job, "complete_job": tool_complete_job}


# ----------------------------------------------------------------- protocol

def handle(req):
    method = req.get("method")
    req_id = req.get("id")

    # Notifications carry no id and must never be answered.
    if req_id is None:
        return

    if method == "initialize":
        params = req.get("params") or {}
        # Echo the client's protocol version rather than pinning one: this
        # server uses nothing version-specific, and echoing avoids a mismatch
        # rejection when the host moves forward.
        version = (params.get("protocolVersion")
                   if isinstance(params.get("protocolVersion"), str) else "2025-06-18")
        return _result(req_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "screengraft", "version": "0.7.0"},
        })

    if method == "ping":
        return _result(req_id, {})

    if method == "tools/list":
        return _result(req_id, {"tools": TOOLS})

    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        fn = DISPATCH.get(name)
        if not fn:
            return _error(req_id, -32602, f"unknown tool: {name}")
        try:
            return _result(req_id, _text(fn(params.get("arguments") or {})))
        except Exception as e:                                    # noqa: BLE001
            # A tool that raises should report a failed tool call, not kill the
            # server — the UI may still be mid-job.
            return _result(req_id, {**_text({"error": str(e)}), "isError": True})

    return _error(req_id, -32601, f"method not found: {method}")


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        # One thread per request so a 90s wait_for_job cannot stall ping or
        # tools/list behind it.
        threading.Thread(target=handle, args=(req,), daemon=True).start()


if __name__ == "__main__":
    main()
