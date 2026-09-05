#!/usr/bin/env python3
"""Fail if anything personal or project-local is about to ship.

The plugin is meant for other designers, so it must not carry the author's home
paths, private file keys, private vault structure, or the internal tracker ids
that mean nothing outside this project. Comments explaining WHY a thing is the
way it is are wanted and stay; the names and handles attached to them do not.

Scans the files the packager actually includes, so it measures what ships rather
than what happens to be in the working tree.

The rules below are deliberately generic. A guard that hard-codes the secret it
is guarding publishes that secret to everyone who reads the guard -- which is
exactly what happened here: this script was excluded from the plugin package for
carrying a private Figma key, and then went public in the repo anyway. Anything
that identifies one person or one file belongs in `scripts/leak-patterns.local`
(gitignored, one regex per line, `#` comments allowed), which is read if present.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
# mirrors build-plugin.sh's include list, minus what it excludes
INCLUDE = ['.claude-plugin', 'skills', 'scripts', 'mcp', 'ui', 'README.md', 'LICENSE']
# leak-patterns.local is the list of forbidden strings, so of course it contains
# them; it is gitignored and never packaged.
SKIP_NAMES = {'build-plugin.sh', 'deadcode.py', 'check_leaks.py', 'leak-patterns.local'}
SKIP_SUFFIX = {'.pyc', '.woff2', '.png', '.jpg', '.jpeg', '.gif'}

# (pattern, what it is, why it must not ship)
RULES = [
    (r'/Users/[a-z]', 'a home directory path', 'points at one machine and names its owner'),
    (r'/home/[a-z]', 'a home directory path', 'points at one machine and names its owner'),
    (r'figma\.com/(?:file|design)/[A-Za-z0-9]{16,}', 'a Figma file key',
     'anyone holding it can try to open the file'),
    (r'\bSG\d+\b', 'an internal tracker id', "meaningless outside the project's own task database"),
    (r'app\.notion\.(?:com|so)', 'a Notion link', 'private workspace'),
    (r'\bmaterials/[a-z-]+\.md', 'a link to notes that do not ship', 'a dead end for any reader'),
]

# Identifying literals -- a name, a bare file key, a vault path -- live outside
# the repo so this file can be published. Missing file just means no extra rules.
EXTRA = pathlib.Path(__file__).with_name('leak-patterns.local')
if EXTRA.exists():
    for raw in EXTRA.read_text(encoding='utf-8').splitlines():
        rule = raw.split('#', 1)[0].strip()
        if rule:
            RULES.append((rule, 'a private string from leak-patterns.local',
                          'identifies one person, machine or file'))
# fraczyk.design and the author's name in plugin.json are DELIBERATE — that is
# the tool's attribution, and the only personal detail meant to travel with it.
ALLOW = [re.compile(r'fraczyk\.design'), re.compile(r'Dariusz Fraczyk')]

def files():
    for entry in INCLUDE:
        p = ROOT / entry
        if p.is_file():
            yield p
        elif p.is_dir():
            for f in p.rglob('*'):
                if (f.is_file() and f.name not in SKIP_NAMES
                        and f.suffix not in SKIP_SUFFIX and '__pycache__' not in f.parts):
                    yield f

hits = []
for f in files():
    try:
        text = f.read_text(encoding='utf-8')
    except (UnicodeDecodeError, OSError):
        continue
    for i, line in enumerate(text.splitlines(), 1):
        if any(a.search(line) for a in ALLOW):
            continue
        for pat, what, why in RULES:
            if re.search(pat, line):
                hits.append((f.relative_to(ROOT), i, what, why, line.strip()[:88]))

if hits:
    print(f'{len(hits)} thing(s) that must not ship:\n')
    for path, line, what, why, snippet in hits:
        print(f'  {path}:{line}  {what} — {why}')
        print(f'      {snippet}')
    sys.exit(1)
print('nothing personal or project-local in the shipped files.')
