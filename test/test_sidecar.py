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
import ast
import inspect
import os
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

# The sidecar dicts are found by PARSING ui.py, not by regex over its text.
#
# The regex here was `result = \{(.*?)\n\s*_write_json_atomic` with re.S, and it
# was wrong twice over. `.*?` still spans whatever lies between the first
# `result = {` and the first `_write_json_atomic`, so it swallowed a route's
# response dicts as well — the "video sidecar" it reported carried `started`,
# `running`, `path` and `saved`, which are not sidecar keys at all. And
# `re.search` took the FIRST match for the STILL contract, while the video dict
# comes first in the file, so the still check was reading the video sidecar.
#
# Both faults pointed the same way: the check passed because it was looking at a
# superset of the right thing. Planting the removal of `corner_smoothing` from
# the still sidecar on 11 Sep 2026 changed nothing at all — a guard that cannot
# fail, three releases after this file's own comments said that is the one thing
# a guard must never be.
#
# ast.literal_eval is not usable (the values are expressions), so this walks for
# `result = {...}` assignments and takes the literal string keys of each.
_tree = ast.parse(src)
_dicts = [n.value for n in ast.walk(_tree)
          if isinstance(n, ast.Assign) and isinstance(n.value, ast.Dict)
          and any(isinstance(t, ast.Name) and t.id == 'result' for t in n.targets)]
_keysets = [{k.value for k in d.keys
             if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            for d in _dicts]
ok('ui.py writes exactly two sidecars', len(_keysets) == 2, f'{len(_keysets)} found')
_still = [k for k in _keysets if 'video' not in k]
_video = [k for k in _keysets if 'video' in k]
keys = _still[0] if _still else set()
ok('a still-save sidecar was found at all', bool(keys), str(sorted(keys)))

# sidecar names that stand in for a compose parameter
ALIAS = {'corners': 'corners', 'corner_radius': 'radius_px',
         'corner_smoothing': 'corner_smoothing',
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

# --- 1b. the same contract for the VIDEO path -------------------------------
# ui.py now writes TWO sidecars — one for a still save, one for a video render
# — and the render one is a second place a new parameter can be forgotten. This
# is the third time this class of bug has been guarded (radius_px, then
# grade/grain); guarding it once per writer is the only version that holds.
vparams = [q for q in inspect.signature(warp.compose_video).parameters
           if q not in ('photo', 'video_path', 'output', 'progress', 'frames_dir')]
VALIAS = {'corners': 'corners', 'corner_radius': 'radius_px',
          'corner_smoothing': 'corner_smoothing', 'grade': 'grade',
          'grain': 'grain', 'preset': 'preset', 'fit_frame': 'fit_frame',
          'audio': 'audio'}
V_NOT_IN_UI = {'audio'}      # always on; no UI control for it yet
vkeys = _video[0] if _video else set()
vmissing = [q for q in vparams
            if q not in V_NOT_IN_UI and VALIAS.get(q, q) not in vkeys]
ok('a video render sidecar was found at all', bool(vkeys), str(sorted(vkeys)))
ok('every compose_video() parameter the UI can set is in its sidecar',
   not vmissing, 'missing: ' + (', '.join(vmissing) or '—'))
ok('the video sidecar is marked as one', 'video' in vkeys)

# --- 2. an actual round trip -------------------------------------------------
# Build a save, write the sidecar the way ui.py does, then recompose from the
# sidecar ALONE and require byte equality. an earlier bug was exactly this failing.
photo = np.zeros((400, 600, 3), np.uint8); photo[:, :] = (40, 90, 170)
rng = np.random.default_rng(3)
photo = np.clip(photo + rng.normal(0, 2.0, photo.shape), 0, 255).astype(np.uint8)
shot = np.full((300, 200, 3), 235, np.uint8); shot[40:80, 20:180] = 30
corners = [[180, 90], [420, 96], [416, 320], [176, 312]]

for grade, grain, smooth in ((0.0, False, 0.0), (0.35, True, 0.0),
                             (1.0, True, 0.0), (0.35, True, 0.6)):
    frac = 0.14
    radius_px = frac * shot.shape[1]                 # unrounded, per an earlier finding
    saved = warp.compose(photo, shot, corners, radius_px, corner_smoothing=smooth,
                         grade=grade, grain=grain)
    sidecar = {"corners": corners, "radius_frac": frac, "radius_px": radius_px,
               "corner_smoothing": smooth, "grade": grade, "grain": grain}
    redone = warp.compose(photo, shot, sidecar["corners"], sidecar["radius_px"],
                          corner_smoothing=sidecar["corner_smoothing"],
                          grade=sidecar["grade"], grain=sidecar["grain"])
    ok(f'sidecar reproduces its save byte-for-byte '
       f'(grade={grade}, grain={grain}, smoothing={smooth})',
       np.array_equal(saved, redone))

# Recording a parameter and APPLYING it are different contracts, and the key
# check above only proves the first. This proves the second: smoothing has to
# change the pixels, or a sidecar that faithfully records 0.6 describes an
# output nobody produced. Planting the route's `corner_smoothing=` away leaves
# every key check green and turns this red.
flat = warp.compose(photo, shot, corners, 0.14 * shot.shape[1])
sq = warp.compose(photo, shot, corners, 0.14 * shot.shape[1], corner_smoothing=0.6)
ok('corner smoothing actually changes the composite',
   not np.array_equal(flat, sq),
   f'{int(np.abs(flat.astype(int) - sq.astype(int)).sum())} total channel difference')

# ... and the default must be the old shape exactly, or every save made before
# smoothing existed re-composes to something else.
ok('smoothing defaults to the circular arc, byte for byte',
   np.array_equal(flat, warp.compose(photo, shot, corners, 0.14 * shot.shape[1],
                                     corner_smoothing=0.0)))

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
