#!/usr/bin/env bash
# Package the Claude/Cowork plugin: a flat zip with .claude-plugin/ and skills/
# at the root, plus the scripts and docs the skill reads at runtime.
#   scripts/build-plugin.sh [outDir]   -> <outDir>/screengraft-<version>.plugin
# Mirrors protoreel's scripts/build-plugin.mjs. Tests and fixtures are excluded.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
version="$(python3 -c "import json;print(json.load(open('$root/.claude-plugin/plugin.json'))['version'])")"
outDir="$(cd "${1:-$root/dist}" 2>/dev/null && pwd || { mkdir -p "${1:-$root/dist}" && cd "${1:-$root/dist}" && pwd; })"
out="$outDir/screengraft-$version.plugin"
rm -f "$out"
cd "$root"
include=()
# mcp/ MUST be here: plugin.json points mcpServers at ${CLAUDE_PLUGIN_ROOT}/mcp/server.py,
# and a build that omits it installs a plugin whose declared tools silently fail
# to start — the UI's buttons would then reach nobody, which is the whole thing
# v0.7 exists to fix.
# build-plugin.sh is deliberately NOT packaged: it is only useful to someone
# rebuilding from the repo, and its default output path is the author's own
# machine. Same for the dead-code report and the leak check — and the leak
# check especially, since it necessarily CONTAINS every pattern it looks for,
# so shipping it would put them all back in the package it just cleared.
for p in .claude-plugin skills scripts mcp ui docs README.md LICENSE; do
  [ -e "$p" ] && include+=("$p")
done
# docs/ carries README imagery for GitHub, not anything the skill reads at
# runtime. Packaging it once took the plugin from 75KB to 2.5MB — a 2.4MB image
# downloaded by every installer to be looked at by nobody.
zip -q -r "$out" "${include[@]}" -x '*.DS_Store' -x '*__pycache__*' -x '*.pyc' \
    -x 'docs/*.png' -x 'docs/*.jpg' -x 'docs/*.jpeg' -x 'docs/*.gif' \
    -x 'scripts/build-plugin.sh' -x 'scripts/deadcode.py' -x 'scripts/check_leaks.py' -x 'scripts/leak-patterns.local' \
    -x 'scripts/check_marketplace.py' -x '.claude-plugin/marketplace.json'
printf '%s  %s KB\n' "$out" "$(( $(stat -f%z "$out") / 1024 ))"
