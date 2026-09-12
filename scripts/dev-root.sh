#!/usr/bin/env zsh
# Point the installed plugin at a checkout, or stop doing so.
#
#   scripts/dev-root.sh            -> use THIS checkout (the one the script is in)
#   scripts/dev-root.sh /some/tree -> use that one
#   scripts/dev-root.sh off        -> back to the installed copy
#   scripts/dev-root.sh status     -> say which
#
# Writes ~/.screengraft/dev-root, which launch.sh reads. See launch.sh for why.
set -euo pipefail
FILE="$HOME/.screengraft/dev-root"
case "${1:-}" in
  off)    rm -f "$FILE"; echo "dev root off — launch.sh uses the installed copy" ;;
  status) if [ -s "$FILE" ]; then echo "dev root: $(head -n1 "$FILE")"; else echo "dev root off"; fi ;;
  *)
    TREE="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
    TREE="$(cd "$TREE" && pwd)"
    [ -f "$TREE/scripts/ui.py" ] || { echo "error: $TREE has no scripts/ui.py" >&2; exit 2; }
    mkdir -p "$(dirname "$FILE")"
    printf '%s\n' "$TREE" > "$FILE"
    echo "dev root: $TREE — every session's launch.sh now runs this tree; the badge will read 'dev <sha>'"
    ;;
esac
