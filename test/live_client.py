#!/usr/bin/env python3
"""Talk to the real MCP server against whatever UI is currently running.

Not part of the automated suite — that one fakes a session in a temp HOME.
This drives the server exactly as the host would, but against a live ui.py,
so the server<->page contract is exercised for real: the page enqueues, this
returns the job, this completes it, the page picks the completion up.

  live_client.py wait [timeout]      block, print the job as JSON
  live_client.py complete done PATH  complete the current job
  live_client.py complete error MSG
"""
import json
import os
import subprocess
import sys
import threading

SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp", "server.py")


class Client:
    def __init__(self):
        self.p = subprocess.Popen([sys.executable, SERVER], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, bufsize=1)
        self._id = 0
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "live", "version": "0"}})

    def _rpc(self, method, params, timeout=400):
        self._id += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self._id,
                                       "method": method, "params": params}) + "\n")
        self.p.stdin.flush()
        box = {}

        def rd():
            box["line"] = self.p.stdout.readline()

        t = threading.Thread(target=rd, daemon=True)
        t.start()
        t.join(timeout)
        if not box.get("line"):
            raise SystemExit("no response from server")
        return json.loads(box["line"])

    def call(self, tool, args, timeout=400):
        msg = self._rpc("tools/call", {"name": tool, "arguments": args}, timeout)
        return json.loads(msg["result"]["content"][0]["text"])

    def close(self):
        self.p.terminate()


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    c = Client()
    try:
        if sys.argv[1] == "wait":
            t = float(sys.argv[2]) if len(sys.argv) > 2 else 60
            print(json.dumps(c.call("wait_for_job", {"timeout_s": t}, timeout=t + 30), indent=1))
        elif sys.argv[1] == "complete":
            status = sys.argv[2]
            args = {"status": status}
            if status == "done" and len(sys.argv) > 3:
                args["path"] = sys.argv[3]
            if status == "error":
                args["message"] = sys.argv[3] if len(sys.argv) > 3 else "test failure"
            print(json.dumps(c.call("complete_job", args), indent=1))
        else:
            raise SystemExit(__doc__)
    finally:
        c.close()


if __name__ == "__main__":
    main()
