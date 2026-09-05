#!/usr/bin/env python3
"""Fail if .claude-plugin/marketplace.json would not install.

`claude plugin validate .` is the real validator, but it needs the Claude Code
CLI, which CI does not have. This checks the parts that actually break an
install and that are cheap to get wrong:

  - the catalog parses, and carries the three required fields
  - the marketplace name is kebab-case, unreserved, and inside the character
    set Claude Desktop's managed sync accepts (it silently drops entries that
    fail, rather than erroring)
  - every relative source resolves inside the repo and holds a plugin.json
  - the entry's name matches that plugin.json's name

The last one is the reason this file exists: the marketplace entry and the
plugin manifest are two places saying the same thing, and nothing else notices
when they drift.
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CATALOG = ROOT / '.claude-plugin' / 'marketplace.json'

# Reserved for Anthropic's own marketplaces; a catalog using one stops loading.
RESERVED = {
    'claude-code-marketplace', 'claude-code-plugins', 'claude-plugins-official',
    'claude-plugins-community', 'claude-community', 'anthropic-marketplace',
    'anthropic-plugins', 'agent-skills', 'anthropic-agent-skills',
    'knowledge-work-plugins', 'life-sciences', 'claude-for-legal',
    'claude-for-financial-services', 'financial-services-plugins',
    'first-party-plugins', 'healthcare', 'org', 'org-provisioned', 'unknown',
}
# What Claude Desktop's managed sync accepts for a marketplace or plugin name.
DESKTOP_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')

errors = []


def check(cond, msg):
    if not cond:
        errors.append(msg)
    return cond


if not CATALOG.exists():
    sys.exit(f'{CATALOG.relative_to(ROOT)} is missing')

try:
    cat = json.loads(CATALOG.read_text(encoding='utf-8'))
except json.JSONDecodeError as e:
    sys.exit(f'marketplace.json is not valid JSON: {e}')

name = cat.get('name', '')
check(bool(name), 'marketplace.json has no "name"')
check(name.lower() not in RESERVED, f'marketplace name {name!r} is reserved for Anthropic')
check(bool(DESKTOP_NAME.match(name)), f'marketplace name {name!r} is rejected by Claude Desktop sync')
check(name == name.lower() and ' ' not in name, f'marketplace name {name!r} should be kebab-case')
check(isinstance(cat.get('owner'), dict) and cat['owner'].get('name'),
      'marketplace.json needs owner.name')
plugins = cat.get('plugins')
check(isinstance(plugins, list) and plugins, 'marketplace.json lists no plugins')

for i, entry in enumerate(plugins or []):
    where = f'plugins[{i}]'
    pname = entry.get('name', '')
    check(bool(pname), f'{where} has no name')
    check(bool(DESKTOP_NAME.match(pname)),
          f'{where} name {pname!r} is silently dropped by Claude Desktop sync')
    src = entry.get('source')
    if not isinstance(src, str):
        continue  # github/url/git-subdir sources are not ours to resolve here
    if not check(src.startswith('./'), f'{where} relative source {src!r} must start with "./"'):
        continue
    target = (ROOT / src).resolve()
    check(target == ROOT or ROOT in target.parents,
          f'{where} source {src!r} escapes the marketplace root')
    manifest = target / '.claude-plugin' / 'plugin.json'
    if not check(manifest.exists(), f'{where} source {src!r} has no .claude-plugin/plugin.json'):
        continue
    pj = json.loads(manifest.read_text(encoding='utf-8'))
    check(pj.get('name') == pname,
          f'{where} is named {pname!r} but its plugin.json says {pj.get("name")!r}')
    if 'version' in entry:
        check(entry['version'] == pj.get('version'),
              f'{where} pins version {entry["version"]!r}, plugin.json says {pj.get("version")!r}')

if errors:
    print(f'{len(errors)} problem(s) in the marketplace catalog:\n')
    for e in errors:
        print(f'  {e}')
    sys.exit(1)
print(f'marketplace catalog ok — {len(plugins)} plugin(s) under "{name}".')
