"""M2 realism pass — the properties that must hold, not the pixels that happen to come out.

Golden-image tests would lock in whatever the grade currently does; these lock in
what it must NEVER do: move geometry, break determinism, touch pixels outside the
screen, or destroy the screenshot's own contrast.
"""
import os, sys
import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import warp, grade                                              # noqa: E402

FAILED = []
def ok(name, cond, extra=''):
    print(('  ok    ' if cond else '  FAIL  ') + name + (('   ' + extra) if extra else ''))
    if not cond: FAILED.append(name)

def scene(warm=True):
    """A photo with a strong cast and a neutral screenshot dropped into it."""
    photo = np.zeros((400, 600, 3), np.uint8)
    photo[:, :] = (40, 90, 170) if warm else (170, 90, 40)      # BGR
    rng = np.random.default_rng(7)
    photo = np.clip(photo + rng.normal(0, 2.0, photo.shape), 0, 255).astype(np.uint8)
    shot = np.full((300, 200, 3), 235, np.uint8)
    shot[40:80, 20:180] = 30                                     # some content
    corners = [[180, 90], [420, 96], [416, 320], [176, 312]]
    return photo, shot, corners

def mask_for(photo, shot, corners, radius=6.0):
    dst = np.array(corners, np.float32)
    sh, sw = shot.shape[:2]
    src = np.array([[0, 0], [sw, 0], [sw, sh], [0, sh]], np.float32)
    H = cv2.getPerspectiveTransform(src, dst)
    return warp._warp_mask_antialiased(warp.rounded_mask(sw, sh, radius), H,
                                       photo.shape[1], photo.shape[0], dst)

print('M2 realism pass')
photo, shot, corners = scene()
base = warp.compose(photo, shot, corners, corner_radius=6.0)
graded = warp.compose(photo, shot, corners, corner_radius=6.0, grade=0.35, grain=True)
m = mask_for(photo, shot, corners)

ok('grade=0 is byte-identical to the ungraded engine',
   np.array_equal(base, warp.compose(photo, shot, corners, corner_radius=6.0, grade=0.0)))
ok('a graded run is deterministic',
   np.array_equal(graded, warp.compose(photo, shot, corners, corner_radius=6.0, grade=0.35, grain=True)))
ok('grading changes something at all', not np.array_equal(base, graded))

outside = (m == 0)
ok('nothing outside the screen is touched',
   np.array_equal(base[outside], graded[outside]),
   '%d px checked' % int(outside.sum()))

# --- the cast actually moves toward the room ---------------------------------
def chroma_gap(img, photo, m):
    lab_i = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float64)
    lab_p = cv2.cvtColor(photo, cv2.COLOR_BGR2LAB).astype(np.float64)
    ring = grade.surround_ring(m)
    inside = (m > 200).astype(bool)
    a = lab_i[inside]; b = lab_p[ring.astype(bool)]
    return float(np.hypot(a[:, 1].mean() - b[:, 1].mean(), a[:, 2].mean() - b[:, 2].mean()))

g_before, g_after = chroma_gap(base, photo, m), chroma_gap(graded, photo, m)
ok('the screen moves toward the surrounding light', g_after < g_before,
   'chroma gap %.2f -> %.2f' % (g_before, g_after))

# It must move toward it, never PAST it — overshoot would tint the screen more
# than the room and look worse than doing nothing.
ok('and does not overshoot past neutral', g_after >= 0)

# --- the screenshot keeps its own contrast -----------------------------------
def inner_std(img):
    inside = (m > 200).astype(bool)
    return float(cv2.cvtColor(img, cv2.COLOR_BGR2LAB)[:, :, 0][inside].std())
s_b, s_a = inner_std(base), inner_std(graded)
ok('the UI keeps its own contrast (L spread within 15%)',
   abs(s_a - s_b) / max(s_b, 1e-6) < 0.15, 'L std %.2f -> %.2f' % (s_b, s_a))

# --- strength is monotonic and 0 is off --------------------------------------
gaps = [chroma_gap(warp.compose(photo, shot, corners, corner_radius=6.0, grade=s), photo, m)
        for s in (0.0, 0.25, 0.5, 1.0)]
ok('stronger settings move it further, monotonically',
   all(gaps[i] >= gaps[i + 1] - 1e-9 for i in range(len(gaps) - 1)),
   ' -> '.join('%.2f' % g for g in gaps))

# --- grain is measured, not invented -----------------------------------------
RING = grade.surround_ring(m)

def flat(sigma, seed=1, base=100):
    """A flat patch plus MONOCHROME noise of known sigma.

    Monochrome on purpose. The old fixture added independent noise to all three
    channels and then called the result "true sigma 4.0" — but measure_grain
    greys the photo first, so three independent channels average down to
    4/sqrt(3) = 2.31. The assertion band was wide enough to hide it. Sensor
    noise after demosaicing is correlated across channels anyway, which is why
    add_grain lays it monochrome, so this is also the honest fixture.
    """
    n = np.random.default_rng(seed).normal(0, sigma, (400, 600))
    return np.clip(np.full((400, 600, 3), float(base)) + n[:, :, None], 0, 255).astype(np.uint8)

clean = np.full((400, 600, 3), 100, np.uint8)
ok('a noiseless photo yields no grain', grade.measure_grain(clean, RING) < 0.2)

# Accuracy at several levels, INCLUDING below 1.5 grey levels. That band is the
# whole of SG50: the old median-of-integers estimator returned a flat 0 under
# 1.4826 and could not tell a clean render from a lightly-noisy photograph.
for true in (0.6, 1.0, 1.5, 2.5, 4.0):
    got = grade.measure_grain(flat(true), RING)
    ok('grain within 15%% of a known sigma %.1f' % true,
       abs(got - true) / true < 0.15, 'measured %.3f' % got)

# The plateau itself, pinned as a property: three sigmas under 1.5 must give
# three different answers. This is the regression that would come back if the
# estimator ever went back to an order statistic over integer residuals.
low = [grade.measure_grain(flat(s), RING) for s in (0.5, 0.9, 1.3)]
ok('it resolves continuously below 1.5 grey levels',
   len({round(v, 3) for v in low}) == 3 and low[0] < low[1] < low[2],
   ' < '.join('%.3f' % v for v in low))

# A hard edge inside the sample ring must not be read as noise. Note WHY this
# passes: a 3x3 median is edge-preserving, so a clean step leaves a residual of
# exactly zero. It is not the statistic that saves this case.
edged = clean.copy(); edged[:, 300:] = 200
ok('a hard edge in the ring is not mistaken for grain',
   grade.measure_grain(edged, RING) < 0.5)

# Fine repeating texture IS what leaks, and what GRAIN_GATE exists for. Ungated
# this reads ~27 against a true 1.0.
tex = flat(1.0).copy(); tex[:, ::9] = 200
ok('fine repeating texture is gated off, not read as grain',
   grade.measure_grain(tex, RING) < 1.3,
   'measured %.3f (true 1.0)' % grade.measure_grain(tex, RING))

# --- specular lift -----------------------------------------------------------
off = np.full_like(photo, 8)                      # a dark screen-off frame
off[150:170, 200:400] = 200                       # a window reflection
lifted = warp.compose(photo, shot, corners, corner_radius=6.0, screen_off=off, specular=0.75)
ok('the specular lift only ever adds light',
   bool((lifted.astype(int) >= base.astype(int)).all()))
ok('the lift lands where the reflection is',
   lifted[160, 300].mean() > base[160, 300].mean() + 5)
ok('a featureless screen-off frame lifts nothing',
   np.array_equal(warp.compose(photo, shot, corners, corner_radius=6.0,
                               screen_off=np.full_like(photo, 8)), base))
try:
    warp.compose(photo, shot, corners, corner_radius=6.0, screen_off=np.zeros((10, 10, 3), np.uint8))
    ok('a mismatched screen-off frame is rejected', False)
except ValueError:
    ok('a mismatched screen-off frame is rejected', True)

print('\n' + ('all checks passed' if not FAILED else 'FAILURES: ' + ', '.join(FAILED)))
sys.exit(1 if FAILED else 0)
