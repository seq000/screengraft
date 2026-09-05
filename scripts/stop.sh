#!/usr/bin/env zsh
# Stop the screengraft UI.
#
# SIGTERM, not SIGKILL: ui.py catches it and runs its atexit, which clears the
# session pointer the MCP server reads. A hard kill leaves a stale pointer and
# the agent then blocks a full timeout against a session nobody is in.
set -euo pipefail
if ! pgrep -f 'scripts/ui.py' >/dev/null 2>&1; then
  echo "no screengraft UI running"
  exit 0
fi
pkill -TERM -f 'scripts/ui.py' || true
for i in $(seq 1 20); do
  pgrep -f 'scripts/ui.py' >/dev/null 2>&1 || break
  sleep 0.25
done
if pgrep -f 'scripts/ui.py' >/dev/null 2>&1; then
  echo "warning: still running after 5s, forcing" >&2
  pkill -KILL -f 'scripts/ui.py' || true
fi
echo "screengraft UI stopped"
