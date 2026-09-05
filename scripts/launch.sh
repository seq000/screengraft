#!/usr/bin/env zsh
# screengraft — start ui.py as a detached daemon.
#
# HISTORY, because this has been wrong twice.
#   1. `nohup ui.py & disown` from the agent's shell (3 Sep 2026): the
#      server died silently between turns, twice, losing whatever the designer
#      had already entered. nohup blocks SIGHUP but not the session teardown
#      some launchers use.
#   2. A Terminal.app window via osascript: survives, but leaves a dead
#      "[Process completed]" window behind after every single session. The author
#      ended up with a row of them (4 Sep 2026). Closing them again from
#      AppleScript proved unreliable — Terminal reports stale ttys for dead
#      windows and can leave zero-tab window husks that `close` reports
#      success on without removing.
#
# So: `--daemon` double-forks and calls setsid, putting the server in its own
# session with no controlling terminal. It outlives the launching shell for
# the same reason a Terminal window did, and there is no window to clean up.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT=0
OUT_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --out-dir) OUT_DIR="${2:-}"; shift 2 ;;
    --out-dir=*) OUT_DIR="${1#*=}"; shift ;;
    --port) PORT="${2:-0}"; shift 2 ;;
    --port=*) PORT="${1#*=}"; shift ;;
    ''|*[!0-9]*) echo "error: unknown argument: $1" >&2; exit 2 ;;
    *) PORT="$1"; shift ;;
  esac
done

PYEXE="$HOME/.screengraft/venv/bin/python"
[ -x "$PYEXE" ] || PYEXE="python3"
LOG="$(mktemp -t screengraft-ui.XXXXXX).log"

if [ -n "$OUT_DIR" ]; then
  "$PYEXE" "$ROOT/scripts/ui.py" --port "$PORT" --no-open --daemon --log "$LOG" --out-dir "$OUT_DIR"
else
  "$PYEXE" "$ROOT/scripts/ui.py" --port "$PORT" --no-open --daemon --log "$LOG"
fi

# The daemon writes its startup JSON to the log; wait for it, then confirm the
# server actually answers before telling anyone it is ready.
for i in $(seq 1 40); do
  [ -s "$LOG" ] && break
  sleep 0.25
done
if [ ! -s "$LOG" ]; then
  echo "error: no output from ui.py after 10s; log: $LOG" >&2
  exit 1
fi
URL=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['url'])" "$LOG" 2>/dev/null || true)
if [ -z "$URL" ]; then
  echo "error: couldn't parse url from $LOG:" >&2
  cat "$LOG" >&2
  exit 1
fi
sleep 1
if ! curl -sf -o /dev/null "${URL}api/state"; then
  echo "error: server not responding at $URL after launch. Log: $LOG" >&2
  cat "$LOG" >&2
  exit 1
fi
cat "$LOG"
echo "log: $LOG"
open "$URL" >/dev/null 2>&1 || true
