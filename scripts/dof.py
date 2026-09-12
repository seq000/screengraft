"""Depth of field across the screen — a blur that grows in one direction.

A phone photographed at an angle is a plane receding from the camera, so
focus falls off *linearly across the quad*: sharp at the near edge, softer
toward the far one. Two numbers describe it — the direction the blur grows in
(`angle`, degrees, photo space, 0 = toward +x, 90 = toward +y) and how fast
(`strength`, 0..1) — and both can be read off the photograph, because the
bezel around the screen already carries the camera's own defocus.

Blur is applied in PHOTO space, after the warp, to the premultiplied screen
layer and its mask together (`blur_layer`). Blurring the layer alone would
pull the black outside the quad into its edge and leave a sharp alpha edge
inside a soft bezel — the tell in a bad mockup. Premultiplied, the edge
softens exactly as the colour does.

Spatially varying Gaussian: DOF_LEVELS blur levels, per pixel a linear blend
of the two nearest. Standard, cheap (five separable blurs on the quad's
window), and byte-identical to no blur at strength 0.
"""
import math

import cv2
import numpy as np

DOF_LEVELS = 5          # sigma steps between 0 and sigma_max (0 is the identity)
DOF_MAX_FRAC = 0.02     # strength 1.0 = sigma of 2% of the quad's longer side (16px on an 800px screen)


def sigma_max(corners, strength: float) -> float:
    """Blur at the far edge, in photo pixels, for a given strength."""
    q = np.asarray(corners, dtype=np.float64)
    side = max(np.linalg.norm(q[1] - q[0]), np.linalg.norm(q[2] - q[1]),
               np.linalg.norm(q[3] - q[2]), np.linalg.norm(q[0] - q[3]))
    return float(np.clip(strength, 0.0, 1.0)) * DOF_MAX_FRAC * float(side)


def ramp(corners, angle_deg: float, x0: int, y0: int, w: int, h: int) -> np.ndarray:
    """Per-pixel 0..1 distance along `angle` across the quad, over a window.

    0 at the quad's nearest extent in that direction, 1 at its farthest; pixels
    outside the quad clamp. The window is (x0, y0, w, h) in photo pixels.
    """
    a = math.radians(angle_deg)
    d = np.array([math.cos(a), math.sin(a)], dtype=np.float64)
    q = np.asarray(corners, dtype=np.float64)
    proj = q @ d
    lo, hi = float(proj.min()), float(proj.max())
    if hi - lo < 1e-6:
        return np.zeros((h, w), dtype=np.float32)
    xs = np.arange(x0, x0 + w, dtype=np.float64)[None, :]
    ys = np.arange(y0, y0 + h, dtype=np.float64)[:, None]
    t = (xs * d[0] + ys * d[1] - lo) / (hi - lo)
    return np.clip(t, 0.0, 1.0).astype(np.float32)


def level_weights(t: np.ndarray, levels: int = DOF_LEVELS):
    """Blend weights (levels, h, w): each pixel splits between its two nearest
    sigma steps. Sums to 1 everywhere."""
    pos = t * (levels - 1)
    lo = np.floor(pos).astype(np.int32)
    lo = np.clip(lo, 0, levels - 2)
    f = (pos - lo).astype(np.float32)
    W = np.zeros((levels,) + t.shape, dtype=np.float32)
    rows, cols = np.indices(t.shape)
    W[lo, rows, cols] = 1.0 - f
    W[lo + 1, rows, cols] = f
    return W


def _blur(img: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0.0:
        return img
    k = int(2 * math.ceil(3 * sigma) + 1)
    return cv2.GaussianBlur(img, (k, k), sigma, borderType=cv2.BORDER_REPLICATE)


class Field:
    """Everything that does not change per frame: the ramp, the weights, the
    blurred masks. `blur_layer` then costs `levels - 1` blurs of the colour."""

    def __init__(self, corners, angle_deg: float, strength: float, mask: np.ndarray,
                 x0: int, y0: int):
        h, w = mask.shape[:2]
        self.x0, self.y0 = x0, y0
        self.smax = sigma_max(corners, strength)
        self.sigmas = [self.smax * k / (DOF_LEVELS - 1) for k in range(DOF_LEVELS)]
        t = ramp(corners, angle_deg, x0, y0, w, h)
        self.W = level_weights(t)                       # (L, h, w)
        m = mask.astype(np.float32) / 255.0
        self.masks = [_blur(m, s) for s in self.sigmas]  # each (h, w)
        self.alpha = np.zeros_like(m)
        for k in range(DOF_LEVELS):
            self.alpha += self.W[k] * self.masks[k]
        self.alpha3 = np.repeat(self.alpha[:, :, None], 3, axis=2)

    @property
    def pad(self) -> int:
        """How far the soft edge reaches outside the sharp mask."""
        return int(math.ceil(3 * self.smax))

    def blur_layer(self, colour: np.ndarray) -> np.ndarray:
        """Blur a warped screen window (float32 BGR, h×w×3) by the field.

        Premultiplied by the sharp mask, blurred per level, blended by the
        weights, then un-premultiplied by the blended mask — so the colour at
        a soft edge is the screen's own, not the screen mixed with whatever
        the warp put outside the quad. (The warp replicates the edge outward,
        so in practice that is nearly the screen's own colour already; the
        premultiplication is what keeps it exact rather than nearly.)
        """
        m0 = self.masks[0][:, :, None]
        pm = colour * m0
        num = np.zeros_like(colour)
        for k in range(DOF_LEVELS):
            bk = pm if self.sigmas[k] <= 0.0 else _blur(pm, self.sigmas[k])
            num += self.W[k][:, :, None] * bk
        den = np.maximum(self.alpha3, 1e-4)
        out = num / den
        return np.where(self.alpha3 > 1e-4, out, colour)


# ---------------------------------------------------------------- measure --

DOF_PROFILE_HALF = 14   # px either side of the screen boundary to fit the step
DOF_MIN_SPREAD = 1.6    # far-edge sigma / near-edge sigma below this = flat
DOF_MIN_SIGMA = 0.9     # a step narrower than this is the render's own antialiasing


def _edge_profiles(gray: np.ndarray, A, B, n, half: int, trim: float = 0.12):
    """Intensity profiles ACROSS edge A→B, one column per sample point along
    it, from `half` px inside the screen to `half` px outside, along the
    outward unit normal `n`. Rectified with remap, so a tilted edge reads as
    a straight step."""
    A = np.asarray(A, dtype=np.float64); B = np.asarray(B, dtype=np.float64)
    u = B - A
    L = float(np.linalg.norm(u))
    if L < 8:
        return None
    u /= L
    s = np.linspace(trim * L, (1 - trim) * L, max(8, int((1 - 2 * trim) * L / 2)))
    d = np.arange(-half, half + 1, dtype=np.float64)
    xs = A[0] + s[None, :] * u[0] + d[:, None] * n[0]
    ys = A[1] + s[None, :] * u[1] + d[:, None] * n[1]
    return cv2.remap(gray.astype(np.float32), xs.astype(np.float32), ys.astype(np.float32),
                     cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def step_sigma(profiles: np.ndarray) -> float:
    """Blur of a step edge, in pixels, from profiles across it (rows = across,
    columns = samples along the edge).

    A step of amplitude A blurred by a Gaussian of sigma has a peak derivative
    of A / (sigma * sqrt(2*pi)), so sigma = A / (sqrt(2*pi) * peak). Only the
    DOMINANT transition in each column is read: the strongest gradient near
    the boundary, with A taken between the plateaus 3 sigma-ish either side of
    it. The second-moment estimate was tried first and saturated at ~5px on
    sharp renders, because a ±14px profile crosses glass edge, bezel and body
    and its derivative is spread over all three. Reduced by the median across
    columns so a corner arc or a reflection on a few samples does not move it;
    columns with no real step are left out.
    """
    smooth = cv2.GaussianBlur(profiles, (1, 3), 0.6)      # tame sensor noise along the profile
    g = np.diff(smooth, axis=0)                            # (2*half, N)
    ag = np.abs(g)
    n_across, N = ag.shape
    half = n_across // 2
    lo_i, hi_i = max(1, half - 6), min(n_across - 1, half + 6)   # the boundary is near the centre
    peak = lo_i + ag[lo_i:hi_i].argmax(axis=0)
    out = []
    for j in range(N):
        pk = int(peak[j]); gm = float(ag[pk, j])
        if gm < 1.5:
            continue
        # plateaus: 4..9 px either side of the peak, clamped to the profile
        a0, a1 = max(0, pk - 9), max(0, pk - 4)
        b0, b1 = min(n_across, pk + 5), min(n_across, pk + 10)
        if a1 <= a0 or b1 <= b0:
            continue
        A = abs(float(smooth[b0:b1, j].mean()) - float(smooth[a0:a1, j].mean()))
        if A < 12.0:                                      # no step worth reading
            continue
        out.append(A / (math.sqrt(2 * math.pi) * gm))
    if len(out) < 4:
        return 0.0
    return float(np.median(out))


def measure(photo: np.ndarray, corners) -> dict:
    """Direction and strength of defocus from the screen's own boundary.

    Four blur widths, one per edge (sigma in pixels, `step_sigma`), the
    edge midpoints as positions → a plane sigma(x, y) = a·x + b·y + c by least
    squares. The blur grows along the plane's gradient: angle = atan2(b, a).
    Strength is the far edge's sigma against DOF_MAX_FRAC of the longer side,
    which is what the blur uses, so a measured strength reproduces the measured
    blur. Below DOF_MIN_SPREAD between the softest and sharpest edge the photo
    is in focus across the screen (or uniformly soft, which is not depth of
    field) and the answer is `flat`.
    """
    gray = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY) if photo.ndim == 3 else photo
    q = np.asarray(corners, dtype=np.float64)
    centre = q.mean(axis=0)
    sig, mids = [], []
    for i in range(4):
        A, B = q[i], q[(i + 1) % 4]
        u = B - A
        n = np.array([-u[1], u[0]]) / max(np.linalg.norm(u), 1e-6)
        mid = (A + B) / 2
        if np.dot(n, centre - mid) > 0:     # pointing in: flip to outward
            n = -n
        prof = _edge_profiles(gray, A, B, n, DOF_PROFILE_HALF)
        if prof is None:
            continue
        sg = step_sigma(prof)
        if sg > 0.0:
            sig.append(sg); mids.append(mid)
    if len(sig) < 3:
        return {"angle": 0.0, "strength": 0.0, "flat": True, "sigma": [round(v, 2) for v in sig]}
    sig = np.array(sig); mids = np.array(mids)
    lo = max(float(sig.min()), DOF_MIN_SIGMA)
    spread = float(sig.max() / lo)
    out = {"sigma": sig.round(2).tolist(), "spread": round(spread, 2)}
    if spread < DOF_MIN_SPREAD:
        out.update({"angle": 0.0, "strength": 0.0, "flat": True})
        return out
    Amat = np.column_stack([mids[:, 0], mids[:, 1], np.ones(len(mids))])
    (a, b, c), *_ = np.linalg.lstsq(Amat, sig, rcond=None)
    angle = math.degrees(math.atan2(b, a)) % 360.0
    strength = float(np.clip((sig.max() - lo) / max(sigma_max(q, 1.0), 1e-6), 0.0, 1.0))
    out.update({"angle": round(angle, 1), "strength": round(strength, 3), "flat": False})
    return out
