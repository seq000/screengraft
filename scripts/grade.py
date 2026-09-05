"""screengraft — M2: the realism pass. Grade, don't regenerate.

An injected screenshot is a perfect, evenly-lit rectangle dropped into a
photograph that is neither. Even with the geometry exact, it reads as pasted
because three things do not match: its white balance and exposure belong to
whatever rendered it, its surface has no grain while the photo has a noise
floor, and a real screen under real light carries reflections that a clean
screenshot does not.

Three independent passes, each measurable and each defaulting to a strength a
designer can dial back:

  1. white balance + exposure -> the light in the room
  2. grain                    -> the photo's own noise floor
  3. specular lift            -> the device's REAL reflections, from a
                                 screen-off reference shot of the same photo

The one rule inherited from the build brief: this pass NEVER touches geometry
and NEVER generates pixels. Everything here is a per-channel statistic measured
off the photo itself, so a run is deterministic and reproducible.

Why Reinhard-in-Lab rather than a full histogram match: a histogram match
against the surrounding bezel would drag the screenshot's own contrast toward
the bezel's, which is wrong — the screen is a light source, not a surface, and
it is *supposed* to have its own range. Matching only the mean and spread of
the two chroma channels, plus a bounded exposure shift, moves the cast without
flattening the content.
"""
from __future__ import annotations

import cv2
import numpy as np

# The grade is deliberately weak by default. A screen is emissive: it should
# pick up the room's cast, not become the room's colour.
DEFAULT_STRENGTH = 0.35   # the UI default; the slider spans 0.10-1.00


def surround_ring(mask: np.ndarray, inner_px: int = 6, outer_px: int = 48) -> np.ndarray:
    """The band of photo just OUTSIDE the screen — the light the screen sits in.

    Sampling the whole photo would average in a wall three metres away under a
    different light. The bezel and the few centimetres around it are what a
    viewer compares the screen against, so that is what the grade matches.
    `inner_px` steps off the edge first, because those pixels are the
    antialiased blend of screen and bezel and would poison the statistic with
    the screenshot's own colour.
    """
    solid = (mask > 127).astype(np.uint8)
    k_in = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (inner_px * 2 + 1,) * 2)
    k_out = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (outer_px * 2 + 1,) * 2)
    grown = cv2.dilate(solid, k_out)
    skirt = cv2.dilate(solid, k_in)
    return ((grown > 0) & (skirt == 0)).astype(np.uint8)


def _stats(lab: np.ndarray, sel: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    px = lab[sel.astype(bool)]
    if px.size == 0:
        return np.zeros(3, np.float64), np.ones(3, np.float64)
    return px.mean(axis=0), px.std(axis=0) + 1e-6


def match_light(photo: np.ndarray, warped: np.ndarray, mask: np.ndarray,
                strength: float = DEFAULT_STRENGTH) -> np.ndarray:
    """Move the injected screen's cast and exposure toward the surrounding light.

    Chroma (a,b) is matched on mean AND spread — a cast is exactly a chroma mean
    offset, and a room with weak colour should not receive a saturated screen.
    Luminance is matched on MEAN ONLY, and bounded: a screen is emissive and is
    allowed to be brighter than its surroundings, so rescaling its L spread to
    the bezel's would crush the UI's own contrast. That asymmetry is the whole
    design of this function.
    """
    if strength <= 0:
        return warped
    ring = surround_ring(mask)
    if int(ring.sum()) < 500:          # too little context to measure honestly
        return warped

    lab_photo = cv2.cvtColor(photo, cv2.COLOR_BGR2LAB).astype(np.float64)
    lab_warp = cv2.cvtColor(warped, cv2.COLOR_BGR2LAB).astype(np.float64)
    inside = (mask > 200).astype(np.uint8)
    if int(inside.sum()) < 500:
        return warped

    m_out, s_out = _stats(lab_photo, ring)
    m_in, s_in = _stats(lab_warp, inside)

    out = lab_warp.copy()
    # a,b: full Reinhard transfer, scaled by strength.
    for c in (1, 2):
        moved = (lab_warp[:, :, c] - m_in[c]) * float(s_out[c] / s_in[c]) + m_out[c]
        out[:, :, c] = lab_warp[:, :, c] + (moved - lab_warp[:, :, c]) * strength
    # L: mean shift only, and capped at +-12 L* so a dark room cannot switch
    # the screen off. 12 is about a stop; beyond that it stops reading as the
    # same screenshot.
    dL = float(np.clip(m_out[0] - m_in[0], -12.0, 12.0)) * strength
    out[:, :, 0] = lab_warp[:, :, 0] + dL

    out[:, :, 0] = np.clip(out[:, :, 0], 0, 255)
    out[:, :, 1:] = np.clip(out[:, :, 1:], 0, 255)
    return cv2.cvtColor(out.astype(np.uint8), cv2.COLOR_LAB2BGR)


def measure_grain(photo: np.ndarray, ring: np.ndarray) -> float:
    """The photo's noise floor, in grey levels, measured where the screen isn't.

    High-pass with a 3x3 median (cheap, edge-preserving) and take the MEDIAN
    absolute deviation of the residual rather than its standard deviation: a
    bezel edge or a highlight inside the ring is a huge outlier, and a mean-based
    estimate would read the edge as noise and dump visible grain on the screen.
    0.6745 converts MAD to a sigma for a normal distribution.
    """
    g = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY)
    resid = g.astype(np.float32) - cv2.medianBlur(g, 3).astype(np.float32)
    px = resid[ring.astype(bool)]
    if px.size < 500:
        return 0.0
    return float(np.median(np.abs(px - np.median(px))) / 0.6745)


def add_grain(img: np.ndarray, mask: np.ndarray, sigma: float, seed: int = 0) -> np.ndarray:
    """Lay the measured noise floor over the injected screen only.

    Seeded, so a re-run is byte-identical — determinism is a stated verification
    rule for this tool, and unseeded noise would break it silently. Monochrome
    rather than per-channel: sensor noise after demosaicing is strongly
    correlated across channels, and independent RGB noise reads as colour
    speckle, which is worse than no grain at all.
    """
    if sigma <= 0.05:
        return img
    sigma = float(min(sigma, 6.0))          # beyond this it stops being grain
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, sigma, img.shape[:2]).astype(np.float32)
    a = (mask.astype(np.float32) / 255.0)[:, :, None]
    return np.clip(img.astype(np.float32) + noise[:, :, None] * a, 0, 255).astype(np.uint8)


def specular_lift(composite: np.ndarray, screen_off: np.ndarray, mask: np.ndarray,
                  strength: float = 0.75) -> np.ndarray:
    """Re-composite the device's REAL reflections over the injected screen.

    Needs a second photograph of the same scene with the screen off. A dark
    screen is nearly a mirror, so that frame contains the true specular
    highlights — window, lamp, the photographer — in exactly the right places
    with the right shape. Lifting them beats any attempt to invent them, which
    is the single thing every AI mockup tool gets visibly wrong.

    The highlight layer is what the off-screen has ABOVE its own dark floor, so
    the floor is subtracted first; screen-space SCREEN blend, because
    reflections add light and never subtract it.
    """
    if screen_off is None or strength <= 0:
        return composite
    if screen_off.shape[:2] != composite.shape[:2]:
        raise ValueError("screen-off reference must be the same size as the photo — "
                         "it has to be the same shot, tripod-locked, not a re-frame")
    sel = mask > 0
    if not sel.any():
        return composite

    off_l = cv2.cvtColor(screen_off, cv2.COLOR_BGR2GRAY).astype(np.float32)
    floor = float(np.percentile(off_l[sel], 20))     # the glass at its darkest
    hi = np.clip(off_l - floor, 0, None)
    peak = float(np.percentile(hi[sel], 99.5))
    if peak < 2.0:                                    # nothing specular to lift
        return composite
    hi = np.clip(hi / peak, 0, 1) * (mask.astype(np.float32) / 255.0) * float(strength)

    base = composite.astype(np.float32) / 255.0
    lifted = 1.0 - (1.0 - base) * (1.0 - hi[:, :, None])   # screen blend
    out = np.clip(lifted * 255.0, 0, 255).astype(np.uint8)
    # A screen blend cannot darken, but the /255 -> *255 round trip quantises:
    # measured 41% of pixels coming back exactly ONE level below the input where
    # the highlight contributes nothing. Clamping to the input enforces the
    # property the maths already has, instead of dimming the whole composite by
    # a level for no reason.
    return np.maximum(out, composite)
