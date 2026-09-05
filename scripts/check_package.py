#!/usr/bin/env python3
"""Fail if the npm tarball would carry something it must not.

npm's `files` list wins over .npmignore for anything it has already included,
so an .npmignore entry for a path inside an included directory does nothing.
The first tarball built here shipped scripts/leak-patterns.local — the file that
holds the private strings every other check exists to keep out. Nothing noticed
until the pack listing was read.

So this reads the pack listing itself rather than trusting the config, and also
checks that package.json and plugin.json agree about the version, since a
release publishes both and they are two places stating one fact.
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FORBIDDEN = (
    'leak-patterns.local', 'check_leaks.py', 'check_package.py',
    'check_marketplace.py', 'build-plugin.sh', 'deadcode.py',
    'marketplace.json', '.plugin', '.env',
    # A .pyc records the absolute path of the source it was compiled from, and a
    # text search skips it as binary — so bytecode smuggled a home directory
    # past every other check here. It is also the wrong Python version for
    # almost everyone installing this.
    '__pycache__', '.pyc',
)

pkg = json.loads((ROOT / 'package.json').read_text())
plugin = json.loads((ROOT / '.claude-plugin' / 'plugin.json').read_text())
errors = []
if pkg['version'] != plugin['version']:
    errors.append(f"package.json is {pkg['version']}, plugin.json is {plugin['version']}")

try:
    out = subprocess.run(['npm', 'pack', '--dry-run', '--json'],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    files = [f['path'] for f in json.loads(out)[0]['files']]
except FileNotFoundError:
    sys.exit('npm is not on PATH — cannot check the tarball')
except (subprocess.CalledProcessError, KeyError, ValueError) as e:
    sys.exit(f'could not read the pack listing: {e}')

for f in files:
    if any(bad in f for bad in FORBIDDEN):
        errors.append(f'{f} would be published')

# The engine and the page have to be in there, or the package is a stub.
for needed in ('scripts/warp.py', 'scripts/ui.py', 'ui/index.html', 'bin/screengraft.js'):
    if needed not in files:
        errors.append(f'{needed} is missing from the tarball')

if errors:
    print(f'{len(errors)} problem(s) with the npm package:\n')
    for e in errors:
        print(f'  {e}')
    sys.exit(1)
print(f'npm package ok — {len(files)} files, version {pkg["version"]}.')
