#!/usr/bin/env python3
"""
screengraft — M1a: no-ML screen-quad detection.

Finds the four corners of a device screen in a photo, so `warp.py` has a quad
to warp into. Deterministic and dependency-light: thresholding, morphology and
line fitting — no model, no download, no network.

The pipeline (proven on a real leaning-phone render, 3 Sep 2026):

  1. Sweep candidate tone bands over the grayscale histogram. A device screen
     is a large region whose pixels sit in a narrow tone band, distinct from
     bezel and background — so instead of guessing one threshold, try every
     band and let the scoring decide.
  2. For each band: close (fills UI text and icons back into the screen body),
     then a large open (kills speckled shadow that would otherwise bridge the
     screen to the background), then take the largest connected component.
  3. Score that blob on how much it looks like a quadrilateral — area, how
     completely it fills its own convex 4-gon, and 4-point approximability.
     Best-scoring band wins.
  4. Fit a line to the straight middle stretch of each of the four edges and
     intersect adjacent lines. This is the step that matters: rounded screen
     corners pull a naive corner estimate inward, and intersecting the straight
     edges recovers the true (virtual) corners the homography needs.

Fails honestly. When the screen's tone isn't separable from its surroundings
(a bright UI photographed against a light wall), no band scores well; the
script says so and exits non-zero rather than emitting a confident wrong quad.
That failure is the case SAM 2 (M4) is meant to earn its keep on.

Detection never warps anything. It writes corners and an overlay for a human
to confirm — `warp.py` still requires corners passed explicitly, so an
unconfirmed guess can never reach the composite.

Usage:
  python3 detect.py --photo photo.jpg --out-corners corners.json \
      [--out-overlay overlay.png] [--out-zooms DIR] [--tone LO,HI]
"""

import argparse
import json
import os
import sys

import cv2
import numpy as np

# Morphology kernel sizes are expressed as a fraction of the image's short
# side, so behaviour doesn't change with photo resolution.
CLOSE_FRAC = 0.008   # ~10px on a 1200px-short-side photo: fills UI text
OPEN_FRAC = 0.023    # ~41px on a 1792px-short-side photo: severs shadow bridges
EDGE_MIDDLE = 0.70   # fit each edge line on its straight middle 70%
MIN_AREA_FRAC = 0.01
MAX_AREA_FRAC = 0.60
MIN_FILL = 0.60      # the source blob must fill this much of the final quad
MIN_SIDE_RATIO = 0.08  # reject slivers: shortest side vs longest, after perspective
# A screen fills MOST of the body it sits in; content drawn on a screen is a
# small part of it. That one ratio separates "step inward to the screen" from
# "don't step into a panel", and it arbitrates between the two detectors too.
NEST_FLOOR = 0.55


def _odd(n: int) -> int:
    n = max(3, int(round(float(n))))
    return n if n % 2 else n + 1


def blob_for_band(gray: np.ndarray, lo: int, hi: int, close_k: int, open_k: int):
    """Mask -> morphology -> largest connected component. Returns its contour."""
    mask = cv2.inRange(gray, lo, hi)
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_k, close_k)),
    )
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_k, open_k)),
    )
    # CHAIN_APPROX_NONE, deliberately: the edge refinement fits a line to each
    # side, and SIMPLE compresses straight runs down to their endpoints, which
    # leaves fitLine with nothing to fit.
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    return max(contours, key=cv2.contourArea)


def score_contour(contour, img_area: float):
    """How much does this blob look like a flat screen? Higher is better."""
    area = cv2.contourArea(contour)
    if area < MIN_AREA_FRAC * img_area or area > MAX_AREA_FRAC * img_area:
        return 0.0, None
    quad = approx_quad(contour)
    if quad is None:
        return 0.0, None
    quad_area = cv2.contourArea(quad.astype(np.float32))
    if quad_area <= 0:
        return 0.0, None
    # Fill ratio: a real screen fills its own quad almost completely. A shadow
    # or a wall patch is ragged and fills far less.
    fill = min(area / quad_area, 1.0)
    return (fill ** 3) * (area / img_area), quad


# Two "edge support" arbiters — score each candidate quad by how much of its
# perimeter sits on a Canny edge, then by whether the gradient forms a local
# ridge across it — were built and measured here on 3 Sep 2026, and both
# dropped. Numbers, correct answer first:
#
#   case                    Canny support      ridge support
#   synthetic fixture       0.023 vs 1.000     0.927 vs 0.999   (both prefer wrong)
#   gradient screen         --                 0.932 correct    (works)
#   real phone photo        0.728 vs 0.339     0.082 vs 0.172   (ridge prefers wrong)
#   real mockup             0.215 correct      0.062 correct    (below any usable floor)
#
# Edge strength is not a usable arbiter in this domain, for the reason an earlier finding
# already found from the other direction: a screen's own boundary (glass
# against a dark bezel) is routinely WEAKER than the device silhouette beside
# it, and on real photographs both are soft enough that any credibility floor
# strict enough to reject a wrong quad also rejects the right one. Geometry
# generalised; photometry did not. detect() arbitrates on nesting instead —
# the same rule pick_innermost() already uses.


def score_edge_contour(contour, img_area: float):
    """Scoring for the Canny path, where score_contour()'s assumptions break.

    Two differences that matter. Canny traces a closed *ring* around each
    edge, so the contour's own area is an artifact of the ring, not of the
    region — score the QUAD's area instead, which is what gets returned.
    And the fill ratio is correspondingly noisy (it can exceed 1), so it
    weighs in linearly rather than cubed; cubing it once cost the real screen
    the win against a wave-shaped gradient boundary drawn inside that screen
    (fill 0.86 vs a ring artifact's 1.0).
    """
    quad = approx_quad(contour)
    if quad is None:
        return 0.0, None
    quad_area = float(cv2.contourArea(order_quad(quad).astype(np.float32)))
    if quad_area < MIN_AREA_FRAC * img_area or quad_area > MAX_AREA_FRAC * img_area:
        return 0.0, None
    fill = min(float(cv2.contourArea(contour)) / max(quad_area, 1e-6), 1.0)
    return fill * (quad_area / img_area), quad


def approx_quad(contour):
    """Reduce a contour to 4 convex points, or None."""
    hull = cv2.convexHull(contour)
    peri = cv2.arcLength(hull, True)
    for eps in np.arange(0.01, 0.12, 0.005):
        approx = cv2.approxPolyDP(hull, eps * peri, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            return approx.reshape(4, 2).astype(np.float64)
    return None


def order_quad(pts: np.ndarray) -> np.ndarray:
    """Order 4 points TL, TR, BR, BL as they appear in the image."""
    c = pts.mean(axis=0)
    ang = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    pts = pts[np.argsort(ang)]           # counter-clockwise in image coords
    start = int(np.argmin(pts.sum(axis=1)))  # closest to the image's top-left
    return np.roll(pts, -start, axis=0)


def refine_corners(contour, quad: np.ndarray):
    """
    Re-derive corners by intersecting fitted edge lines.

    Rounded screen corners bend the contour inward, so the polygon's own
    vertices sit inside the true corner. Each edge's straight middle stretch,
    extended, meets its neighbour at the corner the homography actually wants.

    Every contour point is assigned to whichever of the four edges it lies
    nearest, then only the middle stretch of each edge is fitted — which drops
    the rounded corners without needing a distance threshold to tune. The fit
    is Huber rather than least-squares so a bump in the silhouette (a shadow
    nick, a finger) pulls the line far less than it otherwise would.

    Returns (corners, refined) — `refined` False means it declined and handed
    back the polygon's own corners, which the caller should surface rather
    than quietly present as a refined result.
    """
    pts = contour.reshape(-1, 2).astype(np.float64)
    if len(pts) < 40:
        return quad, False

    # Distance from every point to every edge; nearest edge wins the point.
    dists, projections = [], []
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        ab = b - a
        length = float(np.linalg.norm(ab))
        if length < 1e-6:
            return quad, False
        u = ab / length
        rel = pts - a
        dists.append(np.abs(u[0] * rel[:, 1] - u[1] * rel[:, 0]))
        projections.append((rel @ ab) / (length ** 2))
    nearest = np.argmin(np.vstack(dists), axis=0)

    margin = (1.0 - EDGE_MIDDLE) / 2.0
    lines = []
    for i in range(4):
        t = projections[i]
        sel = pts[(nearest == i) & (t > margin) & (t < 1.0 - margin)]
        if len(sel) < 10:
            return quad, False
        vx, vy, x0, y0 = cv2.fitLine(
            sel.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01
        ).ravel()
        lines.append((float(vx), float(vy), float(x0), float(y0)))

    corners = []
    for i in range(4):
        # Corner i is where edge (i-1) meets edge i.
        vx1, vy1, x1, y1 = lines[(i - 1) % 4]
        vx2, vy2, x2, y2 = lines[i]
        denom = vx1 * vy2 - vy1 * vx2
        if abs(denom) < 1e-9:
            return quad, False  # parallel edges: refinement is meaningless
        t = ((x2 - x1) * vy2 - (y2 - y1) * vx2) / denom
        corners.append([x1 + t * vx1, y1 + t * vy1])
    corners = np.array(corners, dtype=np.float64)

    # A refinement that moves a corner further than a quarter of the quad's
    # size is not a refinement; something upstream was wrong.
    span = float(np.linalg.norm(quad[2] - quad[0]))
    if np.max(np.linalg.norm(corners - quad, axis=1)) > 0.25 * span:
        return quad, False
    return corners, True


def draw_overlay(photo: np.ndarray, corners: np.ndarray) -> np.ndarray:
    out = photo.copy()
    poly = corners.astype(np.int32)
    cv2.polylines(out, [poly], True, (0, 255, 0), 2, cv2.LINE_AA)
    for (x, y), label in zip(corners, ["TL", "TR", "BR", "BL"], strict=True):
        p = (int(round(x)), int(round(y)))
        cv2.circle(out, p, 9, (0, 0, 255), 2, cv2.LINE_AA)
        cv2.circle(out, p, 2, (0, 0, 255), -1, cv2.LINE_AA)
        cv2.putText(out, label, (p[0] + 12, p[1] - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)
    return out


def write_zooms(photo: np.ndarray, corners: np.ndarray, out_dir: str, box: int = 140):
    """Corner close-ups — what a human needs to actually confirm a quad."""
    os.makedirs(out_dir, exist_ok=True)
    h, w = photo.shape[:2]
    paths = []
    overlaid = draw_overlay(photo, corners)
    for (x, y), label in zip(corners, ["TL", "TR", "BR", "BL"], strict=True):
        cx, cy = int(round(x)), int(round(y))
        x0, y0 = max(0, cx - box), max(0, cy - box)
        x1, y1 = min(w, cx + box), min(h, cy + box)
        crop = overlaid[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
        path = os.path.join(out_dir, f"zoom_{label}.png")
        cv2.imwrite(path, crop, [cv2.IMWRITE_PNG_COMPRESSION, 9])
        paths.append(path)
    return paths


def quad_contains(outer: np.ndarray, inner: np.ndarray, margin: float = 2.0) -> bool:
    """Is `inner` wholly inside `outer`?"""
    poly = outer.astype(np.float32)
    return all(
        cv2.pointPolygonTest(poly, (float(x), float(y)), True) > margin
        for x, y in inner
    )


def overlap_frac(inner: np.ndarray, outer: np.ndarray) -> float:
    """How much of `inner`'s area falls inside `outer` (0..1)."""
    a = float(cv2.contourArea(inner.astype(np.float32)))
    if a <= 0:
        return 0.0
    # The first return is the intersection area, deliberately discarded: it is
    # recomputed from `region` below so this function has exactly one notion of
    # area, measured the same way as `a`.
    _, region = cv2.intersectConvexConvex(inner.astype(np.float32),
                                          outer.astype(np.float32))
    if region is None or len(region) < 3:
        return 0.0
    return float(cv2.contourArea(region.astype(np.float32))) / a


def pick_innermost(candidates, best):
    """
    A device photo offers more than one screen-shaped region: the glass screen,
    and the bezel or body it sits in. They nest, and the outer one wins on
    area alone — so once a best candidate is found, step inward while a
    comparably screen-like quad sits wholly inside it. The innermost such
    region is the screen; that's the one the UI has to be warped into.

    The nesting floor is deliberately high. A screen fills most of the body
    it sits in, so a genuine step inward barely shrinks. Content *drawn on*
    the screen — a panel, a card, a gradient band — is much smaller relative
    to its parent, and stepping into it is a miss, not a refinement. At the
    old 0.35 floor a wave-shaped gradient at 49% of its screen was eligible;
    at 0.55 it isn't (an earlier finding, 3 Sep 2026).
    """
    current = best
    for _ in range(4):  # screen inside bezel inside body: a few steps is plenty
        c_area = cv2.contourArea(current[1].astype(np.float32))
        inner = [
            c for c in candidates
            if c is not current
            and c[0] >= 0.25 * current[0]
            and quad_contains(current[1], c[1])
            and NEST_FLOOR * c_area <= cv2.contourArea(c[1].astype(np.float32)) < c_area
        ]
        if not inner:
            return current
        # Largest of the nested ones: the screen, not a panel drawn on it.
        current = max(inner, key=lambda c: cv2.contourArea(c[1].astype(np.float32)))
    return current


def measure_corner_radius(contour, corners: np.ndarray):
    """Estimate the screen's corner radius from the mask outline.

    For a rounded corner of radius r, the outline's nearest point to the
    virtual (sharp) corner lies on the bisector at distance r*(sqrt(2)-1).
    So r ~= d / 0.4142 per corner. Perspective skews this a little, so we
    report the median over the four corners, express it as a fraction of
    the screen's width (so warp.py can turn it into screenshot pixels), and
    flag confidence from how well the four corners agree.
    """
    pts = contour.reshape(-1, 2).astype(np.float64)
    top = np.linalg.norm(corners[1] - corners[0])
    bottom = np.linalg.norm(corners[2] - corners[3])
    width = float((top + bottom) / 2.0)
    per = []
    for c in corners:
        d = float(np.min(np.linalg.norm(pts - c, axis=1)))
        per.append(d / (np.sqrt(2.0) - 1.0))
    per = np.array(per)
    r = float(np.median(per))
    spread = float((per.max() - per.min()) / max(r, 1e-6))
    confident = bool(r > 2.0 and spread < 0.5)
    return {
        "photo_px": round(r, 1),
        "frac_of_width": round(r / width, 4) if width > 0 else 0.0,
        "per_corner_px": [round(float(v), 1) for v in per],
        "confident": confident,
        "note": ("Median of four per-corner estimates; spread %.0f%%." % (spread * 100))
                + (" Good agreement." if confident else
                   " Poor agreement or near-square corners: offer device presets instead."),
    }


# A local, per-handle version of refine_corners() below — "snap this one
# corner to its nearest edge on release" — was prototyped and measured
# against the real reference photo (see build-brief.md, "an earlier finding" section): mean
# error did not improve over the rough dragged position (19.6px unrefined vs
# 21.5px refined), because the true bezel/screen edge is often LOWER local
# contrast than a nearby wrong edge (e.g. bezel against a bright background),
# so "strongest/nearest gradient" reliably locks onto the wrong one. Dropped
# rather than wired into the UI. detect()'s global refine_corners() below is
# a different, more reliable case — it fits all four edges from one already-
# segmented contour, so it isn't picking between competing nearby edges.


def validate_quad(corners: np.ndarray, contour, img_area: float):
    """Is this *final* quad plausibly a screen? Returns (ok, reason).

    The area gate in score_contour() runs against the CONTOUR, before
    approxPolyDP and refine_corners() reshape it — so a contour that scrapes
    past the floor can still yield a final quad far below it. That is exactly
    how a 0.72%-of-image sliver around a watermark was once returned as a
    confident detection (3 Sep 2026, an earlier finding). Everything returned to a caller
    goes through here.
    """
    area = float(cv2.contourArea(corners.astype(np.float32)))
    frac = area / img_area
    if frac < MIN_AREA_FRAC:
        return False, ("final quad covers only %.2f%% of the photo (floor %.0f%%) "
                       "— too small to be the screen" % (frac * 100, MIN_AREA_FRAC * 100))
    if frac > MAX_AREA_FRAC:
        return False, ("final quad covers %.0f%% of the photo (ceiling %.0f%%) "
                       "— that's the scene, not a screen" % (frac * 100, MAX_AREA_FRAC * 100))
    if not cv2.isContourConvex(corners.astype(np.float32).reshape(-1, 1, 2)):
        return False, "final quad is not convex — a plane in perspective always is"
    sides = [float(np.linalg.norm(corners[(i + 1) % 4] - corners[i])) for i in range(4)]
    if min(sides) < MIN_SIDE_RATIO * max(sides):
        return False, ("final quad is a sliver (shortest side %.0f%% of the longest) "
                       % (100 * min(sides) / max(sides)))
    if contour is not None:
        fill = float(cv2.contourArea(contour)) / max(area, 1e-6)
        if fill < MIN_FILL:
            return False, ("source blob fills only %.0f%% of the final quad "
                           "(floor %.0f%%) — ragged, not a screen"
                           % (fill * 100, MIN_FILL * 100))
    return True, ""


def _finalize(candidates, img_area: float, refine: bool = True):
    """Best candidate that survives refinement AND validation.

    Walks candidates best-score-first rather than trusting the top one: a
    high-scoring blob whose refined quad fails the plausibility gate is a
    miss, not a result, and the next candidate deserves a look before the
    detector gives up.

    `refine` is off for the Canny path. refine_corners() assumes the contour
    is a filled region's silhouette, where each side has one long straight
    run to fit. A Canny contour is a ring tracing both sides of an edge, with
    content edges caught inside it, so the per-edge line fits pick up the
    wrong points: measured on the gradient-screen mockup it pushed one corner
    78px off an otherwise correct quad . The polygon approximation of a
    Canny boundary is already on the edge, so there is nothing to recover.
    """
    rejected = []
    for cand in sorted(candidates, key=lambda c: c[0], reverse=True):
        score, quad, contour, tag = pick_innermost(candidates, cand)
        if refine:
            refined, did_refine = refine_corners(contour, quad)
        else:
            refined, did_refine = quad, False
        corners = order_quad(refined)
        ok, why = validate_quad(corners, contour, img_area)
        if ok:
            return {
                "corners": [[round(float(x), 1), round(float(y), 1)] for x, y in corners],
                "score": round(float(score), 5),
                "edge_refined": did_refine,
                "corner_radius": measure_corner_radius(contour, corners),
                "_corners_np": corners,
                "_tag": tag,
                "rejected": rejected,
            }
        rejected.append({"score": round(float(score), 5), "tag": tag, "why": why})
    return None


def detect_tone(gray: np.ndarray, tone=None):
    """Tone-band segmentation. Assumes the screen sits in a narrow tone band."""
    h, w = gray.shape[:2]
    img_area = float(h * w)
    short = min(h, w)
    close_k = _odd(CLOSE_FRAC * short)
    open_k = _odd(OPEN_FRAC * short)

    if tone is not None:
        bands = [tone]
    else:
        # 32 bins over the 0-255 range; try each bin, and each adjacent pair
        # (a screen showing a gradient can straddle two bins).
        edges = [int(round(i * 256 / 32)) for i in range(33)]
        bands = [(edges[i], edges[i + 1] - 1) for i in range(32)]
        bands += [(edges[i], edges[i + 2] - 1) for i in range(31)]

    candidates = []
    for lo, hi in bands:
        contour = blob_for_band(gray, lo, hi, close_k, open_k)
        if contour is None:
            continue
        score, quad = score_contour(contour, img_area)
        if score > 0 and quad is not None:
            # Prefer a narrow band. A screen is tonally uniform; a band wide
            # enough to also swallow the phone's shadowed body scores well on
            # area but produces edges that follow the body, not the glass.
            # Measured on the reference photo: this alone cut the worst-corner
            # error from 110px to 66px.
            score *= (16.0 / (hi - lo + 1)) ** 0.25
            candidates.append((score, order_quad(quad), contour, (lo, hi)))

    res = _finalize(candidates, img_area)
    if res is None:
        return None
    band = res.pop("_tag")
    res["method"] = "tone"
    res["band"] = [int(band[0]), int(band[1])]
    return res


def detect_edges(gray: np.ndarray):
    """Canny-and-quad detection — the document-scanner path.

    Tone banding assumes a near-uniform screen, which breaks the moment the
    screen shows real UI: a gradient wallpaper never lands inside one band,
    so the sweep finds nothing (or worse, something else — an earlier finding, 3 Sep 2026).
    This keys on the *boundary* instead of the fill, so screen content is
    irrelevant; all it needs is contrast between glass and bezel, which a
    device photo has by construction.
    """
    h, w = gray.shape[:2]
    img_area = float(h * w)
    short = min(h, w)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)

    candidates = []
    # Sweep the Canny thresholds off the image's own median rather than fixed
    # numbers, then a few sigmas around it — one exposure doesn't suit both a
    # bright render and a dim photo.
    med = float(np.median(blur))
    for sigma in (0.20, 0.33, 0.50, 0.66):
        lo = int(max(0, (1.0 - sigma) * med))
        hi = int(min(255, (1.0 + sigma) * med))
        if hi <= lo:
            continue
        edges = cv2.Canny(blur, lo, hi, L2gradient=True)
        # Close small gaps so a bezel outline broken by a notch or a glare
        # spot still forms one closed contour.
        k = _odd(0.004 * short)
        edges = cv2.morphologyEx(
            edges, cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)),
        )
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        for c in contours:
            score, quad = score_edge_contour(c, img_area)
            if score > 0 and quad is not None:
                candidates.append((score, order_quad(quad), c, (lo, hi)))

    res = _finalize(candidates, img_area, refine=False)
    if res is None:
        return None
    thr = res.pop("_tag")
    res["method"] = "edge"
    res["canny"] = [int(thr[0]), int(thr[1])]
    return res


def detect(gray: np.ndarray, tone=None, method="auto"):
    """Run both detectors; arbitrate on how the two quads nest.

    The two fail on opposite things. Tone banding needs a tonally uniform
    screen: it finds nothing when the screen shows real UI, or — worse — a
    horizontal slab of a gradient wallpaper, which looks like a perfectly
    good screen. Edge detection needs only a visible boundary, so it handles
    content-filled screens, but with nothing to tell glass from bezel it will
    return the device's outer silhouette instead.

    Ranking by score is meaningless (the two are computed differently), and
    two photometric arbiters were built, measured and rejected — see the note
    above score_edge_contour(). What does separate the cases is the same
    geometry pick_innermost() already relies on: a screen fills MOST of the
    body it sits in, while content drawn on a screen is a small part of it.
    So when tone's quad sits inside edge's, the area ratio says which is
    which — 0.79 on the fixture (screen in body: take the inner, tone), 0.41
    on a gradient screen (slab on screen: take the outer, edge). When they
    don't nest at all, neither is a subregion of the other and tone wins,
    since its assumptions being met is itself evidence and it refines corners.

    Disagreement is reported, never silently resolved — the human confirms
    the corners either way.
    """
    results = []
    if method in ("auto", "tone"):
        r = detect_tone(gray, tone)
        if r:
            results.append(r)
    if method in ("auto", "edge") and tone is None:
        r = detect_edges(gray)
        if r:
            results.append(r)

    if not results:
        return None

    t = next((r for r in results if r["method"] == "tone"), None)
    e = next((r for r in results if r["method"] == "edge"), None)
    why = ""
    if t and e:
        tq, eq = t["_corners_np"], e["_corners_np"]
        ta = float(cv2.contourArea(tq.astype(np.float32)))
        ea = float(cv2.contourArea(eq.astype(np.float32)))
        nested = overlap_frac(tq, eq) >= 0.90 and ta < ea
        ratio = ta / ea if ea > 0 else 0.0
        if nested and ratio < NEST_FLOOR:
            best, why = e, ("the tone quad is only %.0f%% of the edge quad it sits "
                            "inside — that's content drawn on the screen, not the "
                            "screen" % (ratio * 100))
        elif nested:
            best, why = t, ("the tone quad sits inside the edge quad at %.0f%% of "
                            "its area — a screen inside a device body" % (ratio * 100))
        else:
            best, why = t, "the two quads aren't nested; the tone detector refines corners"
    else:
        best = t or e

    if len(results) == 2:
        a, b = (r["_corners_np"] for r in results)
        diag = float(np.hypot(*gray.shape[:2]))
        spread = float(np.max(np.linalg.norm(a - b, axis=1))) / diag
        agree = bool(spread < 0.02)
        best["agreement"] = {
            "both_found": True,
            "max_corner_gap_frac_of_diagonal": round(spread, 4),
            "agree": agree,
            "note": ("Both detectors independently landed on the same quad — "
                     "that is real evidence, not one algorithm's opinion."
                     if agree else
                     "The two detectors disagree by %.0f%% of the image diagonal. "
                     "Showing the %s one because %s — but check all four corners."
                     % (spread * 100, best["method"], why)),
        }
        best["agreement"]["chosen_because"] = why
        other = next(r for r in results if r is not best)
        best["other"] = {"method": other["method"], "corners": other["corners"]}
    else:
        best["agreement"] = {
            "both_found": False,
            "agree": False,
            "note": ("Only the %s detector found anything — a first guess to "
                     "correct, not a measurement." % best["method"]),
        }
    return best


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--photo", required=True)
    ap.add_argument("--out-corners", required=True, help="Where to write the corners JSON")
    ap.add_argument("--out-overlay", help="Optional PNG showing the detected quad on the photo")
    ap.add_argument("--out-zooms", help="Optional directory for 2x corner close-ups")
    ap.add_argument("--tone", help="Skip the sweep and force one band, e.g. --tone 20,40")
    args = ap.parse_args()

    photo = cv2.imread(args.photo, cv2.IMREAD_COLOR)
    if photo is None:
        sys.exit(f"error: could not read photo: {args.photo}")
    gray = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY)

    tone = None
    if args.tone:
        try:
            lo, hi = (int(v) for v in args.tone.split(","))
            tone = (lo, hi)
        except ValueError:
            sys.exit("error: --tone must be LO,HI (e.g. 20,40)")

    result = detect(gray, tone)
    if result is None:
        sys.exit(
            "error: no screen-like quad found. The screen's tone probably isn't "
            "separable from its surroundings (a bright UI on a light wall is the "
            "usual case). Try --tone LO,HI with a band read off the screen, or "
            "supply corners by hand to warp.py."
        )

    corners = result.pop("_corners_np")
    with open(args.out_corners, "w") as f:
        json.dump(result["corners"], f)
    written = {"corners_json": args.out_corners}

    if args.out_overlay:
        cv2.imwrite(args.out_overlay, draw_overlay(photo, corners), [cv2.IMWRITE_PNG_COMPRESSION, 9])
        written["overlay"] = args.out_overlay
    if args.out_zooms:
        written["zooms"] = write_zooms(photo, corners, args.out_zooms)

    print(json.dumps({
        **result,
        "photo_size": [photo.shape[1], photo.shape[0]],
        "written": written,
        "advisory": True,
        "accuracy": "First guess, not a measurement. On the reference photo the "
                    "worst corner landed ~66px out on a 2400x1792 image — close "
                    "enough to aim a human's eye at, not close enough to warp "
                    "blind. Auto-detection degrades whenever the screen's tone "
                    "runs into a shadowed phone body or a dark background.",
        "next": "Show the overlay and the four zooms to the human and get an "
                "explicit yes. If the quad is off, re-run with --tone LO,HI "
                "(read a band off the screen itself) or hand-correct the "
                "corners. warp.py takes corners explicitly and never calls "
                "this script, so an unconfirmed guess cannot reach a composite.",
    }, indent=1))


if __name__ == "__main__":
    main()
