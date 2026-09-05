#!/usr/bin/env python3
"""Front-end dead-code report for ui/index.html.

Neither ruff nor re-reading finds these: a CSS class nobody applies, or a JS
function nobody calls, in a 1500-line single file that has been edited by many
sessions.

ADVISORY, NOT A GATE. It reports false positives by construction, because the
page builds selectors dynamically — `'#chip' + n`, and class names inside
template literals. Anything it lists has to be checked by hand before deleting.
That is why it is a report and not a CI failure.
"""
import io, re, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
src = io.open(ROOT / 'ui' / 'index.html', encoding='utf-8').read()
css = '\n'.join(re.findall(r'<style[^>]*>(.*?)</style>', src, re.S))
js = '\n'.join(re.findall(r'<script[^>]*>(.*?)</script>', src, re.S))
body = re.sub(r'<style.*?</style>|<script.*?</script>', '', src, flags=re.S)

declared = set()
for sel in re.findall(r'([^{}]+)\{', re.sub(r'/\*.*?\*/', '', css, flags=re.S)):
    declared |= set(re.findall(r'\.([a-zA-Z][\w-]*)', sel))

used = {c for g in re.findall(r'class="([^"]*)"', body) for c in g.split()}
used |= set(re.findall(r"classList\.(?:add|remove|toggle|contains)\('([^']+)'", js))
used |= {c for g in re.findall(r"className\s*=\s*[`'\"]([^`'\"]*)", js) for c in g.split()}
used |= set(re.findall(r"querySelector(?:All)?\('\.([\w-]+)", js))
# class names interpolated into template literals, e.g. `toast ${kind}`
used |= set(re.findall(r'`([a-z][\w -]*)\$\{', js))
used |= {c for g in re.findall(r'`([a-z][\w -]*)`', js) for c in g.split()}

dead_css = sorted(declared - used)
fns = set(re.findall(r'function\s+([A-Za-z_$][\w$]*)\s*\(', js))
dead_js = sorted(f for f in fns
                 if len(re.findall(r'\b' + re.escape(f) + r'\b', js)) <= 1 and f not in body)

print(f'CSS classes with no obvious use ({len(dead_css)}): ' + (', '.join('.' + c for c in dead_css) or '—'))
print(f'JS functions never called ({len(dead_js)}): ' + (', '.join(dead_js) or '—'))
print('\nAdvisory only — verify by hand; dynamic selectors produce false positives.')
sys.exit(0)
