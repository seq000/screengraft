#!/usr/bin/env python3
"""Contrast + colour-vision audit for screengraft's UI. Real numbers, no eyeballing.

The tokens are PARSED OUT OF ui/index.html, never copied into this file. The
previous version of this script kept its own copy of the palette and was two
releases stale by the time anyone ran it again (it was still measuring the
v0.6.0 colours after the v0.8.0 Figma port replaced every one of them), so it
would have reported a clean run against a palette that had not shipped for days.
A script that measures a palette nobody uses is worse than no script.

Run after ANY token change:   python3 scripts/contrast_audit.py
Exit code is 1 if an UNACCEPTED failure exists, so CI can hold the line.
"""
import re, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
# Optional argv[1] lets you point the audit at any other copy of the page — used
# to measure a PREVIOUS revision so "did this regress?" is answered with numbers
# rather than memory:  git show HEAD:ui/index.html > /tmp/before.html
UI = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'ui' / 'index.html'

# ---------------------------------------------------------------- colour maths
def srgb_to_lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def luminance(rgb):
    r, g, b = (srgb_to_lin(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def ratio(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)

def over(fg, bg, alpha):
    """Composite fg at `alpha` over bg. Alpha colours are the whole reason the
    accent button's rest state cannot be read off its hex value alone."""
    # strict=: a length mismatch here would silently composite against a
    # truncated colour and return a plausible, wrong ratio.
    return tuple(f * alpha + b * (1 - alpha) for f, b in zip(fg, bg, strict=True))

# ------------------------------------------------------------- token parsing
HEX = re.compile(r'^#([0-9a-fA-F]{3,8})$')
RGBA = re.compile(r'^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)$')

def parse_colour(v):
    """-> (rgb, alpha) or None if the value isn't a colour (sizes, shadows...)."""
    v = v.strip()
    m = HEX.match(v)
    if m:
        h = m.group(1)
        if len(h) == 3: h = ''.join(c * 2 for c in h)
        if len(h) == 4: h = ''.join(c * 2 for c in h)
        if len(h) == 6: return tuple(int(h[i:i+2], 16) for i in (0, 2, 4)), 1.0
        if len(h) == 8: return tuple(int(h[i:i+2], 16) for i in (0, 2, 4)), int(h[6:8], 16) / 255
        return None
    m = RGBA.match(v)
    if m:
        r, g, b, a = m.groups()
        return (float(r), float(g), float(b)), (float(a) if a is not None else 1.0)
    return None

def load_tokens(path):
    src = path.read_text(encoding='utf-8')
    m = re.search(r':root\s*\{(.*?)\n\s*\}', src, re.S)
    if not m:
        sys.exit(f'could not find the :root block in {path}')
    body = re.sub(r'/\*.*?\*/', '', m.group(1), flags=re.S)   # strip comments
    out = {}
    for name, value in re.findall(r'--([\w-]+)\s*:\s*([^;]+);', body):
        c = parse_colour(value)
        if c: out[name] = c
    return out

T = load_tokens(UI)

def solid(name, backdrop='card'):
    """Token as it actually appears on screen, alpha composited over a backdrop."""
    rgb, a = T[name]
    if a >= 1.0: return rgb
    return over(rgb, T[backdrop][0], a)

# --------------------------------------------------------------------- checks
# An ACCEPTED entry is a measured shortfall that has been explicitly signed off, with
# the reason. Keeping them here rather than deleting the check means the number
# is still printed every run — a decision stays visible, and a REGRESSION in an
# accepted item still shows up as a changed figure.
ACCEPTED = {
    'accent label · hover':      'hover only. Rest/pressed pass; he does not want the accent muted to chase it.',
    'accent label · disabled':   'WCAG exempts disabled controls (1.4.3). Kept legible rather than faded.',
    'neutral label · disabled':  'same exemption.',
    'control edge vs card':      '1.4.11 wants 3:1. Lightened twice; going further greys out the whole UI.',
    'control fill vs card':      'the border carries identification, not the fill.',
    'control edge vs its fill':  'a third framing of the same accepted finding, not a separate one.',
    'seg track edge vs card':    'same call as border/edge, which it now uses.',
}

# CVD pairs whose collapse has been reasoned about and accepted. A pair NOT in
# here that collapses is a real finding.
ACCEPTED_CVD = {
    'ok|warn': ('protanopia only, and UNCHANGED by the new token — it measured 1.23 before '
                'and 1.24 after, so it is pre-existing, not a regression. Every other condition '
                'improved sharply (normal 1.09 -> 1.39, deuteranopia 1.01 -> 1.67, tritanopia '
                '1.21 -> 1.99), which is what the audit actually raised. A red-blind viewer sees amber '
                'lose its red and drift toward the green; separating them further means giving up '
                'either the green or the amber, and the glyph + weight channels already carry the '
                'distinction on their own.'),
    'ok|err': ('unsolvable once --ok is a mid green, and measured as such — a sweep of 7056 '
               'reds/pinks found 59 that clear the floor and every one is saturated magenta, which '
               'is not an error colour and fights the #ec4c13 accent. Accepted because ok and err '
               'are mutually exclusive states of ONE pill: they are never on screen together, so '
               'nobody has to tell them apart side by side. The pair that IS sequential — ok|warn — '
               'is the one that was fixed (1.09 -> 1.39 normal, 1.01 -> 1.67 deuteranopia).'),
}

results = []
def check(label, fg, bg, need=4.5, note=''):
    r = ratio(fg, bg)
    ok = r >= need
    results.append((label, r, need, ok, note))
    return r

print('=' * 78)
try: _shown = UI.relative_to(ROOT)
except ValueError: _shown = UI
print(f'screengraft contrast audit — tokens parsed live from {_shown}')
print('=' * 78)

print('\n1. TEXT ON ITS SURFACE')
for label, tok, bgtok, need in [
    ('body --ink on --card',   'ink',   'card', 4.5),
    ('body --ink on --bg',     'ink',   'bg',   4.5),
    ('--mute on --card',       'mute',  'card', 4.5),
    ('--mute on --bg',         'mute',  'bg',   4.5),
    ('--faint captions',       'faint', 'card', 3.0),
]:
    r = check(label, solid(tok, bgtok), T[bgtok][0], need)
    print(f'   {label:34s} {r:6.2f}:1   need {need}   {"ok" if r >= need else "FAIL"}')

print('\n2. ACCENT BUTTON LABEL, EVERY STATE  (Figma Button 4:14, variant=Primary)')
print('   The rest fill is the accent at 85%, so its real contrast depends on what')
print('   is behind it — measured composited, not from the hex.')
acc_states = [
    ('accent label · rest',     'acc-ink',     'acc-btn-rest'),
    ('accent label · hover',    'acc-ink',     'acc'),
    ('accent label · pressed',  'acc-ink',     'acc-press'),
    ('accent label · disabled', 'acc-dis-ink', 'acc-dis'),
]
for label, inktok, filltok in acc_states:
    fill = solid(filltok, 'card')
    ink = T[inktok][0] if T[inktok][1] >= 1 else over(T[inktok][0], fill, T[inktok][1])
    r = check(label, ink, fill, 4.5)
    mark = 'ok' if r >= 4.5 else ('accepted' if label in ACCEPTED else 'FAIL')
    print(f'   {label:34s} {r:6.2f}:1   need 4.5   {mark}')

print('\n3. NON-TEXT CONTRAST — 1.4.11, can you find the control?')
for label, a, b in [
    ('control edge vs card',   'edge',    'card'),
    ('control fill vs card',   'raise',   'card'),
    ('control edge vs its fill','edge',   'raise'),
    ('seg track edge vs card', 'edge',    'card'),
    ('focus ring --acc vs card','acc',    'card'),
    ('--edge-hi (hover) vs card','edge-hi','card'),
]:
    r = check(label, solid(a), solid(b), 3.0)
    mark = 'ok' if r >= 3.0 else ('accepted' if label in ACCEPTED else 'FAIL')
    print(f'   {label:34s} {r:6.2f}:1   need 3.0   {mark}')

print('\n4. SURFACE ELEVATION — is a state change actually visible?')
for label, a, b in [
    ('raise -> raise-hi (selected)', 'raise', 'raise-hi'),
    ('raise -> btn-hover',           'raise', 'btn-hover'),
    ('raise -> btn-press',           'raise', 'btn-press'),
    ('card  -> raise',               'card',  'raise'),
    # A SELECTED chip's hover surface. .chip.on rests on --raise-hi and hovers to
    # --edge, so those two tokens must not converge — if they do, hovering an
    # already-selected chip does nothing at all.
    ('raise-hi -> chip.on:hover',    'raise-hi', 'raise-highest'),
    ('raise -> chip:hover',          'raise', 'raise-mid'),
    ('raise-hi -> chip.on:active',   'raise-hi', 'raise-mid'),
]:
    la, lb = luminance(solid(a)), luminance(solid(b))
    delta = abs(la - lb) / max(la, lb, 1e-6) * 100
    direction = 'lighter' if lb > la else 'DARKER'
    flag = '  <-- barely a step' if delta < 4 else ''
    print(f'   {label:34s} {delta:5.1f}% {direction:8s}{flag}')

print('\n4b. CANVAS OVERLAY vs ARBITRARY PHOTO TONES')
print('   A flat stroke cannot survive an arbitrary photograph, so every overlay is')
print('   drawn TWICE: a dark casing, then the core. The marker is readable if EITHER')
print('   layer separates from the photo, so the score is the better of the two,')
print('   minimised over every possible photo grey.')
OVERLAY_CASING = ((0, 0, 0), .62)          # CASE_A in ui/index.html
# 2.0 is the MEASURED design point, not an aspiration: an accent core has scored
# ~2.1 since v0.6.0 (old #ec4c13 measured 2.11, current #f23b0d 2.08), and the
# overlay has been confirmed readable on hard photography in real use. The value
# of the casing is the floor it creates — a bare accent core bottoms out at
# 1.00:1, i.e. literally invisible, which is what v0.6.0 was fixing.
# NOTE: v0.6.0's note claims "worst case 1.00 -> 4.67:1". 4.67 does not reproduce
# under this model; 2.08 does. The 1.00 half does reproduce exactly. Treat the
# 4.67 figure as measuring something else until someone re-derives it.
OVERLAY_FLOOR = 2.0
def overlay_worst(core, cased=True):
    worst, at = 99.0, None
    for t in range(0, 256):
        tone = (t, t, t)
        best = ratio(core, tone)
        if cased:
            best = max(best, ratio(over(OVERLAY_CASING[0], tone, OVERLAY_CASING[1]), tone))
        if best < worst: worst, at = best, t
    return worst, at

_src = UI.read_text(encoding='utf-8')
cores = dict(re.findall(r"const (CORE_QUAD|CORE_ACTIVE)\s*=\s*'(#[0-9a-fA-F]{6})'", _src))
for name, hexv in sorted(cores.items()):
    core = parse_colour(hexv)[0]
    w, at = overlay_worst(core)
    b, bat = overlay_worst(core, cased=False)
    ok = w >= OVERLAY_FLOOR
    results.append((f'overlay {name}', w, OVERLAY_FLOOR, ok, ''))
    print(f'   {name + " " + hexv:30s} cased {w:5.2f}:1 (grey {at:3d})   '
          f'bare {b:4.2f}:1 (grey {bat:3d})   {"ok" if ok else "FAIL"}')
_idle, _iat = overlay_worst(over((255, 255, 255), (0, 0, 0), .92))
print(f'   {"CORE_IDLE white .92":30s} cased {_idle:5.2f}:1 (grey {_iat:3d})')
print(f'   floor is {OVERLAY_FLOOR}:1 — see the note in this script for why it is not 3.0.')

print('\n5. STATUS COLOURS — legible, and separable WITHOUT hue')
for tok in ('ok', 'warn', 'err'):
    r = check(f'--{tok} on --card', solid(tok), T['card'][0], 4.5)
    print(f'   {"--" + tok + " on --card":34s} {r:6.2f}:1   need 4.5   {"ok" if r >= 4.5 else "FAIL"}')

RGB2LMS = [[17.8824, 43.5161, 4.11935], [3.45565, 27.1554, 3.86714], [0.0299566, 0.184309, 1.46709]]
def _inv3(m):
    (a,b,c),(d,e,f),(g,h,i) = m
    det = a*(e*i-f*h) - b*(d*i-f*g) + c*(d*h-e*g)
    return [[(e*i-f*h)/det, (c*h-b*i)/det, (b*f-c*e)/det],
            [(f*g-d*i)/det, (a*i-c*g)/det, (c*d-a*f)/det],
            [(d*h-e*g)/det, (b*g-a*h)/det, (a*e-b*d)/det]]
LMS2RGB = _inv3(RGB2LMS)
SIM = {'protanopia':   [[0,2.02344,-2.52581],[0,1,0],[0,0,1]],
       'deuteranopia': [[1,0,0],[0.494207,0,1.24827],[0,0,1]],
       'tritanopia':   [[1,0,0],[0,1,0],[-0.395913,0.801109,0]]}
def _mul(m, v): return [sum(mi[j]*v[j] for j in range(3)) for mi in m]
def simulate(rgb, kind):
    return [min(255, max(0, c)) for c in _mul(LMS2RGB, _mul(SIM[kind], _mul(RGB2LMS, list(rgb))))]

print('\n   pairwise separation (the tool\'s honesty signal must survive CVD):')
FLOOR = 1.35
worst_pairs = []
for a, b in (('ok', 'warn'), ('warn', 'err'), ('ok', 'err')):
    ca, cb = solid(a), solid(b)
    row = [f'{a}|{b}'.ljust(12), f'normal {ratio(ca, cb):5.2f}']
    lowest = ratio(ca, cb)
    for kind in SIM:
        r = ratio(simulate(ca, kind), simulate(cb, kind))
        lowest = min(lowest, r)
        row.append(f'{kind[:4]} {r:5.2f}')
    worst_pairs.append((f'{a}|{b}', lowest))
    if lowest >= FLOOR:            flag = ''
    elif f'{a}|{b}' in ACCEPTED_CVD: flag = '  <-- collapses (accepted)'
    else:                          flag = '  <-- COLLAPSES'
    print('   ' + '   '.join(row) + flag)
print(f'\n   floor is {FLOOR}:1 — below that the two states are one colour to that viewer.')
print('   Glyph (checkmark / ! / x) and weight carry the meaning regardless; this is the')
print('   third, redundant channel, not the only one.')

print('\n' + '=' * 78)
unaccepted = [(l, r, n) for l, r, n, ok, _ in results if not ok and l not in ACCEPTED]
accepted_fails = [(l, r) for l, r, n, ok, _ in results if not ok and l in ACCEPTED]
collapsed = [p for p, low in worst_pairs if low < FLOOR and p not in ACCEPTED_CVD]
collapsed_ok = [p for p, low in worst_pairs if low < FLOOR and p in ACCEPTED_CVD]

if accepted_fails:
    print('ACCEPTED shortfalls (decided, still measured every run):')
    for l, r in accepted_fails:
        print(f'   {l:34s} {r:5.2f}:1   {ACCEPTED[l]}')
for p in collapsed_ok:
    print(f'   status pair {p:24s} collapses under CVD — {ACCEPTED_CVD[p]}')
if collapsed:
    print(f'\nSTATUS PAIRS THAT COLLAPSE UNDER CVD (not accepted): {", ".join(collapsed)}')
    unaccepted = unaccepted or [('status CVD collapse', 0.0, FLOOR)]
if unaccepted:
    print('\nNEW / UNACCEPTED FAILURES:')
    for l, r, n in unaccepted:
        print(f'   {l:34s} {r:5.2f}:1   needs {n}')
    print('\nRESULT: FAIL')
    sys.exit(1)
print('\nRESULT: no unaccepted failures.')
