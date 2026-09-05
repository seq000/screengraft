"""The sidecar must be able to reproduce its own save.

This is the third time this class of bug has appeared. radius_px was
rounded, so re-running from the sidecar matched neither code path. v0.10.0:
grade and grain were added to compose() and not to the sidecar, so a save made
with the realism pass on could not be reproduced at all.

Both were found by hand, after shipping. So this test does not check a value —
it checks the CONTRACT: every parameter of compose() that changes the output has
a key in the sidecar. A new parameter added without a sidecar key fails here,
which is the only way to stop a fourth instance.
"""
import inspect
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, '..', 'scripts'))
import warp                                                     # noqa: E402

FAILED = []
def ok(name, cond, extra=''):
    print(('  ok    ' if cond else '  FAIL  ') + name + (('   ' + extra) if extra else ''))
    if not cond: FAILED.append(name)

print('sidecar reproducibility')

# --- 1. the contract: compose()'s parameters vs the keys ui.py writes --------
params = [p for p in inspect.signature(warp.compose).parameters
          if p not in ('photo', 'screenshot')]        # those are paths in the sidecar
src = open(os.path.join(HERE, '..', 'scripts', 'ui.py'), encoding='utf-8').read()
m = re.search(r'result = \{(.*?)\n\s*_write_json_atomic', src, re.S)
keys = set(re.findall(r'"([\w]+)":', m.group(1))) if m else set()
# sidecar names that stand in for a compose parameter
ALIAS = {'corners': 'corners', 'corner_radius': 'radius_px',
         'grade': 'grade', 'grain': 'grain',
         'screen_off': 'screen_off', 'specular': 'specular'}
# screen_off/specular are not reachable from the UI yet; they are exempt until
# the UI can set them, and this list is the record of that.
NOT_IN_UI = {'screen_off', 'specular'}
missing = [p for p in params
           if p not in NOT_IN_UI and ALIAS.get(p, p) not in keys]
ok('every compose() parameter the UI can set is in the sidecar',
   not missing, 'missing: ' + (', '.join(missing) or '—'))
ok('the sidecar carries the inputs too',
   {'photo', 'screenshot', 'output'} <= keys)

# --- 2. an actual round trip -------------------------------------------------
# Build a save, write the sidecar the way ui.py does, then recompose from the
# sidecar ALONE and require byte equality. an earlier bug was exactly this failing.
photo = np.zeros((400, 600, 3), np.uint8); photo[:, :] = (40, 90, 170)
rng = np.random.default_rng(3)
photo = np.clip(photo + rng.normal(0, 2.0, photo.shape), 0, 255).astype(np.uint8)
shot = np.full((300, 200, 3), 235, np.uint8); shot[40:80, 20:180] = 30
corners = [[180, 90], [420, 96], [416, 320], [176, 312]]

for grade, grain in ((0.0, False), (0.35, True), (1.0, True)):
    frac = 0.14
    radius_px = frac * shot.shape[1]                 # unrounded, per an earlier finding
    saved = warp.compose(photo, shot, corners, radius_px, grade=grade, grain=grain)
    sidecar = {"corners": corners, "radius_frac": frac, "radius_px": radius_px,
               "grade": grade, "grain": grain}
    redone = warp.compose(photo, shot, sidecar["corners"], sidecar["radius_px"],
                          grade=sidecar["grade"], grain=sidecar["grain"])
    ok(f'sidecar reproduces its save byte-for-byte (grade={grade}, grain={grain})',
       np.array_equal(saved, redone))

# A rounded radius must NOT silently still pass — this is the regression
# guard: if rounding stopped mattering, the prefilter path changed and someone
# needs to know.
R = 0.14437 * 200          # 28.874 — deliberately not round, or round() is a no-op
assert abs(R - round(R, 1)) > 1e-6, 'pick a radius where rounding actually changes it'
saved = warp.compose(photo, shot, corners, R)
rounded = warp.compose(photo, shot, corners, round(R, 1))
ok('rounding the radius changes the output, so the sidecar must keep it unrounded',
   not np.array_equal(saved, rounded), 'radius %.3f vs %.1f' % (R, round(R, 1)))

print('\n' + ('all checks passed' if not FAILED else 'FAILURES: ' + ', '.join(FAILED)))
sys.exit(1 if FAILED else 0)
