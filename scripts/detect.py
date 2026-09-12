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
# How unequal two OPPOSITE sides of the quad may be. A screen is a rectangle, and
# the image of a rectangle under perspective foreshortens one end relative to the
# other -- but not without limit at the angles anyone photographs a device from.
#
# Measured 10 Sep 2026 against seven hand-placed labels (the first real ground
# truth this project has had): every true screen sits at 1.01-1.05, the two
# usable detections at 1.04 and 1.11, and a quad returned CONFIDENTLY with one
# corner collapsed ~800px into the middle of the screen sits at 2.26. Worst
# correct 1.11 against best wrong 2.26 is a 2.0x margin.
#
# Set LOOSE at 1.9, not near the data. All seven are phones at modest angles;
# a laptop or a monitor shot from the side genuinely foreshortens more, and this
# check can only ever ADD refusals -- the cost of being wrong here is an honest
# abstention and a manual fit, never a bad composite. Re-derive it on a wider
# set of angles and device classes before tightening.
MAX_OPPOSITE_RATIO = 1.9
# Size stops being a virtue past this fraction of the frame. score_contour used
# to reward area linearly, so on a real photo (7 Sep 2026) the sunlit TABLE at
# 34% of the frame beat the phone screen at 9% by 3.6x on that term alone, and
# won outright. A screen is never the biggest thing in a photograph of a room;
# it is only ever big enough. Past this plateau extra area buys nothing, so
# candidates separate on fill and band width instead — which is what actually
# distinguishes glass from furniture.
AREA_PLATEAU = 0.15
# How many connected components each tone band offers up. See blobs_for_band:
# taking only the largest is what made a real photo undetectable, because the
# phone was the second-largest dark region in its band. Six is measured, not
# guessed — the winning component on that photo is rank 2, and nothing useful
# was found past rank 4 on any fixture; the extra two are headroom.
COMPONENTS_PER_BAND = 6
# Saturation percentile below which a region counts as "neutral". Devices are
# grey, black and white; furniture, skin, fabric and foliage are not. Measured
# 7 Sep 2026 on a photo where tone banding failed completely: the screen sits at
# saturation 1.9, the sunlit table it was being confused with at 78.6. Taking
# the image's own 25th percentile adapts to the photograph instead of fixing a
# level — a studio shot on white and a warm interior need different numbers.
# Swept, not fixed — the same reasoning the tone sweep is built on. A single
# percentile breaks whenever the neutral thing is smaller than the percentile
# (a phone occupying 15% of a colourful frame pulls p25 up into the colour and
# the mask swallows the picture). Trying several and letting the scoring decide
# costs one pass each and removes the guess.
NEUTRAL_PERCENTILES = (5, 10, 15, 25, 35)
NEUTRAL_FLOOR = 20          # never threshold below this: an all-grey photo
# A screen has rounded corners. A patch of table cut out by a threshold has
# perfectly sharp ones, and measure_corner_radius returns 0.0px for it — which
# turns out to be the cleanest way to tell a real screen from a lookalike, and
# it is a SHAPE property, not photometry (three photometric arbiters have been
# measured and rejected here; see the note above score_edge_contour).
MIN_ROUNDING_PX = 2.0
# measure_corner_radius makes FOUR independent estimates of one number. If they
# disagree by more than this, the outline is not a rounded rectangle with a
# consistent radius and the median is meaningless — so "it has rounded corners"
# is not evidence and must not be treated as any. Measured 7 Sep 2026 across
# nine real mockup photos: the seven correct detections spread 31-173%, the two
# confidently-wrong ones 247% and 464%.
#
# **This is the weakest number in the file.** 173 against 247 is a 1.4x margin
# on nine samples, where every other threshold here was set with a 4x margin or
# better. If a correct detection is ever rejected as "shape is not consistent",
# this is the line to raise, and it should be re-measured on a bigger set before
# it is trusted further.
MAX_RADIUS_SPREAD = 2.0
# A quad with a corner outside the frame is not a screen this tool can fit, and
# its handles cannot be grabbed — the user is left with a wrong quad and no way
# back (same photo: two corners at y=-50 and y=1837 on a 1792-tall image).
# Rejected at validate_quad, the one choke point every result passes through.
OOB_MARGIN = 2.0
# Gross disagreement between the two detectors, as a fraction of the image
# diagonal. Measured 7 Sep 2026: the reference photo, where detection genuinely
# works, sits at 0.033; the photo where both detectors missed the screen
# entirely sits at 0.555 — seventeen times worse. 0.15 is well clear of both.
ABSTAIN_GAP = 0.15
# A screen fills MOST of the body it sits in; content drawn on a screen is a
# small part of it. That one ratio separates "step inward to the screen" from
# "don't step into a panel", and it arbitrates between the two detectors too.
NEST_FLOOR = 0.55
# "Nested" means this much of the inner quad's area falls inside the outer.
# One number for every place that asks (arbitrate, the walk order, the
# abstention veto) so they cannot drift apart. 12 Sep 2026: on 18 labelled
# photographs the quads that are nested overlap at >= 0.95 and the ones that
# are not at 0.00 -- there is nothing in between to be careful about.
NESTED_OVERLAP = 0.90


def _odd(n: int) -> int:
    n = max(3, int(round(float(n))))
    return n if n % 2 else n + 1


def blobs_for_band(gray: np.ndarray, lo: int, hi: int, close_k: int, open_k: int,
                   keep: int = COMPONENTS_PER_BAND):
    """Mask -> morphology -> the `keep` largest connected components.

    Returns a list of contours, biggest first.

    This used to return only the single largest component, and that one line
    was why a real photo could not be detected at all. On an iPhone lying on a
    sunlit table (7 Sep 2026) the phone was the SECOND-largest dark region in
    its band — the table's shadow was bigger — so the screen was discarded
    before scoring ever saw it. No amount of re-scoring can rank a candidate
    that was never generated: measured, the best quad the old sweep could
    produce sat 693px from the true screen; keeping the runners-up brings that
    to 136px, which is a startable position.

    "Largest" is a guess about the answer dressed up as an optimisation. The
    scoring function is what decides; this function's job is only to offer.
    """
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
        return []
    return sorted(contours, key=cv2.contourArea, reverse=True)[:keep]


def size_term(area: float, img_area: float) -> float:
    """Area reward that saturates at AREA_PLATEAU.

    Below the plateau, bigger is better — it separates a real region from
    speckle. At or above it, the term is 1.0 and stops discriminating, because
    beyond a plausible screen size "bigger" stops being evidence of screen-ness
    and starts being evidence of furniture.
    """
    return min(area / img_area, AREA_PLATEAU) / AREA_PLATEAU


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
    return (fill ** 3) * size_term(area, img_area), quad


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
    return fill * size_term(quad_area, img_area), quad


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


# The Canny path traces a RING -- both sides of one boundary -- and catches
# content edges drawn inside the screen along with it. Fitting a line to all of
# that lands it between the glass edge and whatever is drawn near it, which is
# the 78px failure that banned refinement from this path at v0.13.0.
#
# The fix is to pick a rail rather than to ban the fit. Of the points assigned
# to one edge, keep those within `RAIL_BAND_K` close-kernels of the outermost;
# the ring's two rails are a kernel apart by construction, and content edges are
# far deeper. Measured 11 Sep 2026 on the top-scoring edge candidate of five
# hand-labelled photographs, worst per-edge median residual over the quad's
# diagonal: 0.0673 fitting everything, 0.0052 after rail selection -- and the
# quad that refinement had pushed from 12% to 40% lands at 0.4%.
#
# 2 is the ring's own thickness rounded up, not a fitted number: one kernel
# separates the rails, the second is slack for the Canny width itself. A region
# silhouette has one rail, so this keeps every point and changes nothing.
RAIL_BAND_K = 2.0


def refine_corners(contour, quad: np.ndarray, rail_band: float = 0.0):
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
    # `outward` is the same distance signed so that positive means away from the
    # quad's own centre, which is what lets the outermost rail be picked below.
    centre = quad.mean(axis=0)
    dists, projections, outward = [], [], []
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        ab = b - a
        length = float(np.linalg.norm(ab))
        if length < 1e-6:
            return quad, False
        u = ab / length
        rel = pts - a
        cross = u[0] * rel[:, 1] - u[1] * rel[:, 0]
        rc = centre - a
        sign = -np.sign(u[0] * rc[1] - u[1] * rc[0])
        dists.append(np.abs(cross))
        projections.append((rel @ ab) / (length ** 2))
        outward.append(sign * cross)
    nearest = np.argmin(np.vstack(dists), axis=0)

    margin = (1.0 - EDGE_MIDDLE) / 2.0
    lines = []
    for i in range(4):
        t = projections[i]
        chosen = (nearest == i) & (t > margin) & (t < 1.0 - margin)
        sel = pts[chosen]
        if len(sel) < 10:
            return quad, False
        if rail_band > 0:
            # 95th percentile rather than the maximum: one stray point further
            # out than the rail would otherwise drag the window off it.
            far = outward[i][chosen]
            keep = far >= (float(np.percentile(far, 95)) - rail_band)
            if int(keep.sum()) >= 10:
                sel = sel[keep]
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


def pick_innermost(candidates, best, quad_of=None):
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
    # `quad_of` maps a candidate to the quad its nesting is judged on. The
    # walk passes the REFINED corners; the default is the raw polygon
    # approximation. Raw vertices sit on the corner arcs, not at the corners,
    # and on a phone photographed at ~45 degrees the glass's raw vertex landed
    # ON the body's raw edge line -- `quad_contains` was false, and the body
    # (tier 2, 13% off) shipped with the glass (tier 2, 1%, 87% of its area)
    # one step behind it (12 Sep 2026, a two-phone mockup). Judged on the
    # refined corners the glass is 10px inside the body all round. Replacing
    # the containment test with area overlap was tried first and stepped into
    # wrong inner quads on five photographs -- the strict test is doing work.
    if quad_of is None:
        quad_of = lambda c: c[1]  # noqa: E731
    current = best
    for _ in range(4):  # screen inside bezel inside body: a few steps is plenty
        cq = quad_of(current)
        c_area = cv2.contourArea(cq.astype(np.float32))
        inner = [
            c for c in candidates
            if c is not current
            and c[0] >= 0.25 * current[0]
            and quad_contains(cq, quad_of(c))
            and NEST_FLOOR * c_area <= cv2.contourArea(quad_of(c).astype(np.float32)) < c_area
        ]
        if not inner:
            return current
        # Largest of the nested ones: the screen, not a panel drawn on it.
        current = max(inner, key=lambda c: cv2.contourArea(quad_of(c).astype(np.float32)))
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


def validate_quad(corners: np.ndarray, contour, img_area: float, img_shape=None):
    """Is this *final* quad plausibly a screen? Returns (ok, reason).

    The area gate in score_contour() runs against the CONTOUR, before
    approxPolyDP and refine_corners() reshape it — so a contour that scrapes
    past the floor can still yield a final quad far below it. That is exactly
    how a 0.72%-of-image sliver around a watermark was once returned as a
    confident detection (3 Sep 2026, an earlier finding). Everything returned to a caller
    goes through here.
    """
    if img_shape is not None:
        h, w = float(img_shape[0]), float(img_shape[1])
        for (x, y), label in zip(corners, ["TL", "TR", "BR", "BL"], strict=True):
            if not (-OOB_MARGIN <= x <= w + OOB_MARGIN
                    and -OOB_MARGIN <= y <= h + OOB_MARGIN):
                return False, ("%s lands outside the photo at (%.0f, %.0f) on a "
                               "%.0fx%.0f image — a screen this tool can fit is "
                               "inside the frame, and an off-canvas handle can't "
                               "be dragged back" % (label, x, y, w, h))
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
    # A collapsed corner passes every check above: the quad stays convex, no side
    # is a sliver, the area is in range and the blob still fills it. What gives it
    # away is that one PAIR of opposite sides is wildly unequal while the other is
    # not -- which is what a rectangle cannot do, at any angle a device is
    # photographed from. Found on a real photograph where three corners sat on the
    # glass and the fourth was in the middle of the screen, returned with no
    # abstention: the one failure this tool says it does not have.
    opposite = max(max(sides[0], sides[2]) / max(min(sides[0], sides[2]), 1e-6),
                   max(sides[1], sides[3]) / max(min(sides[1], sides[3]), 1e-6))
    if opposite > MAX_OPPOSITE_RATIO:
        return False, ("opposite sides of the final quad differ by %.1fx (ceiling "
                       "%.1fx) — a rectangle in perspective does not do that, so a "
                       "corner has been pulled off the screen"
                       % (opposite, MAX_OPPOSITE_RATIO))
    if contour is not None:
        fill = float(cv2.contourArea(contour)) / max(area, 1e-6)
        if fill < MIN_FILL:
            return False, ("source blob fills only %.0f%% of the final quad "
                           "(floor %.0f%%) — ragged, not a screen"
                           % (fill * 100, MIN_FILL * 100))
    return True, ""


def contains(quad, point) -> bool:
    """Is `point` inside this quad? The whole of the click feature, in one line.

    A click cannot make a bad candidate good, and it is not asked to. It answers
    the one question the pixels cannot: WHICH of the regions we already found is
    the screen. Measured on the two photos that defeated every detector, the
    correct quad was already in the candidate list both times -- 23 of 93
    candidates contained the click on one, 16 of 118 on the other -- so the
    failure was never detection, it was selection.
    """
    return cv2.pointPolygonTest(np.asarray(quad, np.float32),
                                (float(point[0]), float(point[1])), False) >= 0


def _tag_json(tag):
    """Whatever a detector used to label a candidate: a tone band, a threshold."""
    if isinstance(tag, (tuple, list)):
        return [int(t) for t in tag]
    return int(tag) if isinstance(tag, (int, float, np.integer, np.floating)) else tag


def _trace_row(method, score, quad, tag, verdict, why=""):
    return {"method": method,
            "score": round(float(score), 5),
            "tag": _tag_json(tag),
            "quad": [[round(float(x), 1), round(float(y), 1)] for x, y in quad],
            "verdict": verdict,
            "why": why}


def _finalize(candidates, img_area: float, refine: bool = True, img_shape=None,
              click=None, trace=None, method=None, rail_band: float = 0.0):
    """Best candidate that survives refinement AND validation.

    Walks candidates best-score-first rather than trusting the top one: a
    high-scoring blob whose refined quad fails the plausibility gate is a
    miss, not a result, and the next candidate deserves a look before the
    detector gives up.

    `refine` used to be off for the Canny path, and `rail_band` is why it no
    longer is. refine_corners() assumes the contour is a filled region's
    silhouette, where each side has one long straight run to fit; a Canny
    contour is a ring tracing both sides of an edge, with content edges caught
    inside it, so the per-edge line fits picked up the wrong points -- measured
    on the gradient-screen mockup at v0.13.0, 78px off an otherwise correct
    quad.

    The claim that came with that ban -- "the polygon approximation of a Canny
    boundary is already on the edge, so there is nothing to recover" -- was
    wrong, and it cost this project the largest single bucket of detection
    error for eighteen releases. approxPolyDP puts its vertices ON the rounded
    corner arcs, inside the true corners, and on real photographs that is
    **9-11% of the screen's own width** lost from every side.

    `rail_band` fixes the fit instead of banning it: of the points assigned to
    one edge, only those within a couple of close-kernels of the outermost are
    fitted, which is the ring's own outer rail and excludes content edges by
    construction. Measured over the top-scoring edge candidate on five
    hand-labelled photographs: 12% -> 0.4%, 11% -> 0.5%, 8% -> 3.4%, 9% -> 6.8%.
    A region silhouette has one rail, so passing 0 there changes nothing.
    """
    generated = candidates
    if click is not None:
        # Before ranking, not after: the point of the click is to shrink the
        # field to the things the user actually pointed at, and let the existing
        # score decide among those. Ranking first and filtering after would just
        # re-confirm whichever candidate already won.
        candidates = [c for c in candidates if contains(c[1], click)]
    rejected = []
    # The instrument. Every diagnosis this project has made about
    # detection began by printing this list by hand, and TWICE it changed what
    # the fix was: the 7 Sep rescoring that was the obvious answer and was
    # wrong, because the true screen was never generated at all (693px away);
    # and the click feature, where the correct quad turned out to be the top-scoring
    # candidate containing the click, which deleted most of the planned work.
    #
    # What it exists to separate is RECALL from RANKING -- was the screen never
    # proposed, or proposed and beaten? Those have opposite fixes and this
    # project has never had the number. Off unless asked for, and it must not
    # change the answer: it observes the same lists the walk below uses.
    walked = {}
    # Walk order: by score -- EXCEPT when the best-scoring candidate is not
    # itself confident (tier < 2) while a tier-2 candidate exists in the same
    # list. Two cases, and they are different:
    #
    # * Top is tier 0 (sharp, unmeasurable, or inconsistent corners): it cannot
    #   be corroborated and ends in an abstention or a refusal, so nothing is
    #   lost by looking past it to ANY tier-2 candidate.
    # * Top is tier 1 (rounded, but the four radii disagree): it is a real
    #   finding, and only a tier-2 candidate NESTED INSIDE it may move ahead --
    #   the same finding narrowed to the part whose four corners agree, which
    #   is how arbitrate() already reads a confident quad inside a loosely
    #   rounded one (tiers before area ratio). A tier-2 candidate somewhere
    #   ELSE is a different finding and does not displace a rounded top on
    #   tier alone. Measured 12 Sep 2026 on 18 labelled photographs: every
    #   tier-2 that should jump a tier-1 top lies inside it at >= 0.95
    #   overlap; every one that must not (tone's patches on two photographs,
    #   an edge quad on a third) overlaps it at 0.00. Without the nesting
    #   condition the tone channel promoted a disjoint tier-2 patch 202% off
    #   on two photographs and the answer was lost to abstention. The case
    #   that needed this is a front-and-back mockup: the edge channel's top
    #   candidate is the bounding box of BOTH phones (tier 1, 105% off), and
    #   the screen sits inside it at 48% of its area -- under NEST_FLOOR, so
    #   pick_innermost cannot step to it on the ratio.
    #
    # Deliberately NOT tier-first ordering of the whole list: that was tried
    # on 11 Sep 2026 and broke three photographs, because a tier-2 WRONG
    # candidate sits deeper in the list on each.
    # Refined corners, once per candidate: the walk order reads tiers off them
    # and pick_innermost judges nesting on them (raw polygon vertices sit on
    # the arcs and can land on a neighbouring quad's edge line -- see there).
    shapes = {}

    def _shape_of(cand):
        if id(cand) not in shapes:
            _score, quad, contour, _tag = cand
            q = order_quad(refine_corners(contour, quad, rail_band)[0]) if refine else quad
            shapes[id(cand)] = (q, shape_tier({"corner_radius": measure_corner_radius(contour, q)}))
        return shapes[id(cand)]

    def _refined(cand):
        return _shape_of(cand)[0]

    order = sorted(candidates, key=lambda c: c[0], reverse=True)
    if order:
        top_q, top_tier = _shape_of(order[0])
        if top_tier < 2:
            strong = []
            for c in order[1:]:
                q, tier = _shape_of(c)
                if tier == 2 and (top_tier == 0
                                  or overlap_frac(q, top_q) >= NESTED_OVERLAP):
                    strong.append(c)
            if strong:
                # Identity, not equality: candidates hold numpy arrays.
                strong_ids = {id(c) for c in strong}
                order = strong + [c for c in order if id(c) not in strong_ids]
    for cand in order:
        # NOT necessarily `cand`: pick_innermost steps inward from it while a
        # comparably screen-like quad nests inside, so the quad that gets
        # validated -- and returned -- can belong to a different candidate.
        picked = pick_innermost(candidates, cand, quad_of=_refined)
        score, quad, contour, tag = picked
        if refine:
            refined, did_refine = refine_corners(contour, quad, rail_band)
        else:
            refined, did_refine = quad, False
        corners = order_quad(refined)
        ok, why = validate_quad(corners, contour, img_area, img_shape)
        if trace is not None:
            # "accepted" by its own CHANNEL, which is not the same as winning:
            # each of tone, edge and saturation accepts one, and detect() then
            # arbitrates between them. The file's top-level `chosen` says which
            # channel actually won, so a trace with three accepted rows and one
            # chosen method is right, not a contradiction.
            #
            # And the walked candidate is not always the one whose quad came
            # back. Measured on five real photographs: pick_innermost stepped
            # inward on one of them, so a trace that credited `cand` would show
            # the accepted row holding a quad that never became the answer,
            # while the quad that DID sat in an `unreached` row. An instrument
            # that misattributes the win is worse than no instrument -- a recall
            # analysis reading it would draw the opposite conclusion.
            if not ok:
                walked[id(cand)] = ("rejected", why)
            elif picked is cand:
                walked[id(cand)] = ("accepted", "")
            else:
                walked[id(cand)] = ("accepted", "this candidate won the walk, but the "
                                                "quad returned came from the nested "
                                                "candidate marked supplied_the_answer")
                walked[id(picked)] = ("supplied_the_answer",
                                      "nested inside the accepted candidate; "
                                      "pick_innermost stepped inward to it")
        if ok:
            if trace is not None:
                trace.extend(_walk_rows(generated, candidates, walked, method, click,
                                        refine, rail_band))
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
    if trace is not None:
        trace.extend(_walk_rows(generated, candidates, walked, method, click, refine,
                                rail_band))
    return None


def _walk_rows(generated, survived, walked, method, click, refine=True,
               rail_band: float = 0.0):
    """One row per candidate the detector GENERATED, with what became of it.

    Four verdicts, and the distinction between the last two is the whole point:
    `filtered_by_click` and `unreached` both mean "never judged", but one is the
    user narrowing the field and the other is a higher-scoring candidate winning
    first. A recall analysis needs to see quads in all four states, so nothing
    is dropped from this list -- it is written to a file, not to a page.

    Each row carries the REFINED quad, not the polygon approximation the
    candidate was built from. The walk refines before it validates, so a row
    holding the raw quad describes a proposal the detector never actually
    considered -- and the two differ by the whole rounded-corner inset, which on
    real photographs is 9-11% of the screen's own width. That defect cost a day
    on 11 Sep 2026: the recall column said the best proposal was 9% off
    when refining it put it at 0.4%, so a corner-accuracy change looked like it
    had bought nothing. An instrument that understates what a candidate is worth
    is as wrong as one that misattributes the win, which this function already
    goes to some trouble to avoid.
    """
    # Identity, not equality: two candidates can hold equal numbers and be
    # different proposals. `survived` is a filtered view of `generated`, so the
    # objects are shared and `is` holds -- but only while nobody rebuilds the
    # list, which is why `click is None` is checked explicitly below rather than
    # inferred from the sets matching. A future `[transform(c) for c in ...]`
    # would otherwise relabel every row `filtered_by_click` in silence.
    kept = {id(c) for c in survived}
    rows = []
    for cand in generated:
        score, quad, contour, tag = cand
        if refine:
            quad = order_quad(refine_corners(contour, quad, rail_band)[0])
        if click is not None and id(cand) not in kept:
            verdict, why = "filtered_by_click", "the click was not inside this quad"
        else:
            verdict, why = walked.get(id(cand), ("unreached",
                                                 "a higher-scoring candidate was accepted first"))
        row = _trace_row(method, score, quad, tag, verdict, why)
        # The shape tier of every proposal, not only the winner's: the walk
        # order rule in _finalize reads tiers, so a bench reading this file
        # has to be able to see what the walk saw (added 12 Sep 2026 while
        # tracing a 105% edge win with a 5% tier-2 candidate right behind it).
        row["tier"] = shape_tier({"corner_radius": measure_corner_radius(contour, quad)})
        rows.append(row)
    if click is not None:
        for r in rows:
            r["contains_click"] = r["verdict"] != "filtered_by_click"
    return rows


def detect_tone(gray: np.ndarray, tone=None, click=None, trace=None):
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
        for contour in blobs_for_band(gray, lo, hi, close_k, open_k):
            score, quad = score_contour(contour, img_area)
            if score <= 0 or quad is None:
                continue
            # Prefer a narrow band. A screen is tonally uniform; a band wide
            # enough to also swallow the phone's shadowed body scores well on
            # area but produces edges that follow the body, not the glass.
            # Measured on the reference photo: this alone cut the worst-corner
            # error from 110px to 66px.
            score *= (16.0 / (hi - lo + 1)) ** 0.25
            candidates.append((score, order_quad(quad), contour, (lo, hi)))

    res = _finalize(candidates, img_area, img_shape=gray.shape[:2], click=click,
                    trace=trace, method="tone")
    if res is None:
        return None
    band = res.pop("_tag")
    res["method"] = "tone"
    res["band"] = [int(band[0]), int(band[1])]
    return res


def detect_edges(gray: np.ndarray, click=None, trace=None):
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
    #
    # ... and ALSO off Otsu's threshold, because the median anchor has a hole
    # the median cannot see: a dark photograph. A black phone on a black
    # backdrop has a median of 0..4, so every sweep point lands at hi <= 7 and
    # Canny fires on every pixel of noise -- the edge map is a solid sheet and
    # no closed quad survives it. Both photographs in the labelled corpus on
    # which nothing near the screen was EVER proposed (11 Sep 2026) are exactly
    # this, and edge returned zero candidates on them. Otsu splits the two
    # modes that are actually there -- 97 and 127 on those two -- and the same
    # sweep then proposes the screen at 9% and 12% unrefined, which is where
    # every other photograph's nearest candidate sits. On the other seven the
    # nearest candidate is unchanged. The saturation channel already anchors
    # on Otsu for the same reason (one percentile fails when the thing sought
    # is smaller than the percentile).
    med = float(np.median(blur))
    otsu, _ = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    sweep = [((1.0 - s) * med, (1.0 + s) * med) for s in (0.20, 0.33, 0.50, 0.66)]
    sweep += [(otsu * f / 2.0, otsu * f) for f in (0.5, 1.0, 1.5)]
    seen = set()
    for lo_f, hi_f in sweep:
        lo = int(max(0, lo_f))
        hi = int(min(255, hi_f))
        if hi <= lo or (lo, hi) in seen:
            continue
        seen.add((lo, hi))
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

    res = _finalize(candidates, img_area, img_shape=gray.shape[:2],
                    rail_band=RAIL_BAND_K * _odd(0.004 * short),
                    click=click, trace=trace, method="edge")
    if res is None:
        return None
    thr = res.pop("_tag")
    res["method"] = "edge"
    res["canny"] = [int(thr[0]), int(thr[1])]
    return res


def detect_saturation(bgr: np.ndarray, click=None, trace=None):
    """Neutral-region segmentation — the third detector, and the only one that
    looks at colour.

    tone and edge both run on grayscale, which throws away the single most
    useful cue a photograph of a device offers: **devices are neutral.** A
    phone is grey, black or white; the table, sofa, hand or plant it is lying
    on almost never is. On the 7 Sep 2026 photo the screen measured saturation
    1.9 against the sunlit table's 78.6, and this detector lands 29px from the
    true quad where tone lands 1030px away.

    The threshold is the image's own 25th saturation percentile rather than a
    fixed level, so a studio shot on white and a warm interior both work.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    h, w = sat.shape[:2]
    img_area = float(h * w)
    short = min(h, w)
    close_k = _odd(CLOSE_FRAC * short)
    open_k = _odd(OPEN_FRAC * short)

    thresholds = {int(max(NEUTRAL_FLOOR, np.percentile(sat, p)))
                  for p in NEUTRAL_PERCENTILES}
    otsu, _ = cv2.threshold(sat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    thresholds.add(int(max(NEUTRAL_FLOOR, otsu)))
    candidates = []
    for thr in sorted(thresholds):
        for contour in blobs_for_band(sat, 0, thr, close_k, open_k):
            score, quad = score_contour(contour, img_area)
            if score > 0 and quad is not None:
                # Prefer a tighter neutral threshold, for the same reason the
                # tone sweep prefers a narrow band: a loose one swallows the
                # device body and the wall behind it along with the screen.
                candidates.append((score * (32.0 / max(thr, 1)) ** 0.25,
                                   order_quad(quad), contour, thr))

    res = _finalize(candidates, img_area, img_shape=sat.shape[:2], click=click,
                    trace=trace, method="saturation")
    if res is None:
        return None
    res.pop("_tag")
    res["method"] = "saturation"
    res["neutral_threshold"] = thr
    return res


def shape_tier(result) -> int:
    """How strongly a result's own SHAPE says "this is a screen": 0, 1 or 2.

        2  confident radius -- four per-corner estimates agree within 50%
        1  rounded          -- they agree within MAX_RADIUS_SPREAD (2x)
        0  nothing          -- sharp, unmeasurable, or wildly inconsistent

    Both thresholds already existed (measure_corner_radius's `confident`, and
    has_rounded_corners); this only ranks them. Measured 11 Sep 2026 on ten
    hand-labelled photographs, every channel result: **every tier-2 quad was on
    the screen** (worst spread 0.24) and **every wrong quad was >= 1.43 or
    unmeasurable** -- a 6x margin. Tier 1 alone does not separate them (a
    correct tone quad at 1.42 against a wrong one at 1.43), which is exactly why
    a tier-1 result must not outrank or veto a tier-2 one. It was doing both.
    """
    if (result.get("corner_radius") or {}).get("confident"):
        return 2
    return 1 if has_rounded_corners(result) else 0


def has_rounded_corners(result) -> bool:
    """Did this quad's own outline actually curve at the corners?

    A device screen is a rounded rectangle. A patch of table cut out of a
    threshold mask is a polygon with sharp corners, and measure_corner_radius
    reports 0.0px for it. That single number separated the right answer from
    three wrong ones on the photo this was built for, and unlike edge strength
    or ring contrast it is a property of the shape rather than of the light.
    """
    cr = result["corner_radius"]
    if float(cr["photo_px"]) <= MIN_ROUNDING_PX:
        return False
    per = [float(v) for v in cr["per_corner_px"]]
    # ALL FOUR corners, not most of them. A per-corner estimate of exactly 0.0
    # is the estimator saying "no arc here", and a rounded rectangle does not
    # have corners with no arc. The spread test alone let [0, 0, 56, 56]
    # through -- a quad rounded at two corners and square at the other two,
    # a shape no screen has -- because its spread lands at exactly 2.00 and the
    # comparison is <=. That quad shipped as a CONFIDENT answer 124% off
    # (iPhone-8, 12 Sep 2026): the only confidently wrong result the labelled
    # bench has ever produced. Categorical rather than a threshold: on the 14
    # labelled photographs every on-screen quad this accepts has all four
    # corners measured (smallest 1.6px); the wrong one had two at 0.0.
    if min(per) <= 0.0:
        return False
    r = float(cr["photo_px"])
    spread = (max(per) - min(per)) / max(r, 1e-6)
    return spread <= MAX_RADIUS_SPREAD


def detect(gray: np.ndarray, tone=None, method="auto", color=None, click=None,
           trace=None):
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
    since its assumptions being met is itself evidence: a screen that lands
    inside one narrow tone band is a screen.

    Disagreement is reported, never silently resolved — the human confirms
    the corners either way.
    """
    # `trace`, when given, is a list this fills with one row per candidate every
    # channel generated. It is an OBSERVER: nothing downstream reads it,
    # and the answer is identical with and without -- which is asserted, because
    # an instrument that perturbs what it measures is worse than none.
    results = []
    if method in ("auto", "tone"):
        r = detect_tone(gray, tone, click=click, trace=trace)
        if r:
            results.append(r)
    if method in ("auto", "edge") and tone is None:
        r = detect_edges(gray, click=click, trace=trace)
        if r:
            results.append(r)
    if method in ("auto", "saturation") and tone is None and color is not None:
        r = detect_saturation(color, click=click, trace=trace)
        if r:
            results.append(r)

    if not results:
        return None
    return arbitrate(results, gray.shape[:2], click)


def arbitrate(results, shape, click=None):
    """Choose among the channels' accepted results and decide whether to abstain.

    Split out of detect() on 11 Sep 2026 so the rules here can be tested on
    hand-built results, the way _finalize's nested pick already is. `shape` is
    the photograph's (h, w); the only thing this needs it for is the diagonal.
    """
    # tone and saturation are the same algorithm on different channels, so they
    # are compared to each other before anything else, on whether the region
    # each found actually has rounded corners. A patch of table cut out of a
    # threshold mask measures 0.0px; a screen measures a real radius. On the
    # 7 Sep photo that is the whole ball game — tone 0.0px against saturation's
    # 62.4px, so the channel that found the phone is the one that goes forward.
    #
    # **Only these two.** The edge detector is deliberately exempt: its contour
    # is a Canny ring tracing both sides of a boundary, not a filled region's
    # silhouette, so measure_corner_radius reports an artifact for it — 0.0px
    # even when its quad is the correct one to 1.4px (measured on the
    # gradient-screen fixture, where an earlier version of this filter threw
    # away the right answer). Corner REFINEMENT is no longer skipped there --
    # rail selection made the line fits safe on a ring, see refine_corners() --
    # but measuring a RADIUS from a ring is a separate claim and still is.
    region = [r for r in results if r["method"] in ("tone", "saturation")]
    if len(region) == 2:
        rounded = [r for r in region if has_rounded_corners(r)]
        if len(rounded) == 1:
            loser = next(r for r in region if r is not rounded[0])
            results = [r for r in results if r is not loser]

    t = next((r for r in results if r["method"] == "tone"), None)
    e = next((r for r in results if r["method"] == "edge"), None)
    sat = next((r for r in results if r["method"] == "saturation"), None)
    why = "it was the only detector left after the rounded-corner filter" \
        if len(results) == 1 else "its tone band assumption held, which is itself evidence"
    # ONE region-vs-edge arbitration, for whichever region channel survived the
    # rounded-corner filter above. Until 11 Sep 2026 only tone got the nesting
    # rules; saturation-vs-edge fell through to "saturation wins". On iPhone-4
    # that returned a saturation quad 18% off, nested around an edge quad 3%
    # off at 94% of its area -- exactly the "screen inside a body" shape the
    # tone branch already knew how to read.
    region = t if t is not None else sat
    rname = "tone" if t is not None else "saturation"
    if region is not None and e is not None:
        rq, eq = region["_corners_np"], e["_corners_np"]
        ra = float(cv2.contourArea(rq.astype(np.float32)))
        ea = float(cv2.contourArea(eq.astype(np.float32)))
        # Nesting is read on whichever quad is inside the other. It used to be
        # read only with the region quad inside the edge quad, so an edge quad
        # sitting inside a region quad (iPhone-4: edge 3% off inside a
        # saturation quad 18% off at 94%) was "not nested" and fell through to
        # the region winning by default.
        inner, outer = (region, e) if ra < ea else (e, region)
        iname, oname = (rname, "edge") if ra < ea else ("edge", rname)
        nested = overlap_frac(inner["_corners_np"], outer["_corners_np"]) >= NESTED_OVERLAP
        ratio = min(ra, ea) / max(ra, ea) if max(ra, ea) > 0 else 0.0
        ti, to = shape_tier(inner), shape_tier(outer)
        tr, te = shape_tier(region), shape_tier(e)
        # Nested: shape evidence first, the area ratio only to break a tie.
        #
        # The ratio alone reads "small inside big" as content-inside-screen and
        # "large inside big" as screen-inside-body, and it is right on the
        # gradient-screen fixture (41%: a slab on the screen) and on most
        # photographs. It is wrong exactly when the quads' own corners say the
        # opposite: a UI content region at 96% of the screen with loose corners
        # (two of ten labelled photographs, 15% off) is not a screen inside a
        # body, and a confident phone screen at 34% of a loosely-rounded table
        # (the hand-built case in test_detect) is not content on it. Tiers
        # decide those; at equal tiers the ratio still does, unchanged.
        if nested and to > ti:
            best, why = outer, ("the %s quad sits inside the %s quad at %.0f%% of its "
                                "area, but the outer quad's corners agree on a radius "
                                "(tier %d) and the inner's do not (tier %d) — content "
                                "inside a screen, not a screen inside a body"
                                % (iname, oname, ratio * 100, to, ti))
        elif nested and ti > to:
            best, why = inner, ("the %s quad sits inside the %s quad at %.0f%% of its "
                                "area, and the inner quad's corners agree on a radius "
                                "(tier %d) where the outer's do not (tier %d) — a "
                                "screen on something larger"
                                % (iname, oname, ratio * 100, ti, to))
        elif nested and ratio < NEST_FLOOR:
            best, why = outer, ("the %s quad is only %.0f%% of the %s quad it sits "
                                "inside — that's content drawn on the screen, not the "
                                "screen" % (iname, ratio * 100, oname))
        elif nested:
            best, why = inner, ("the %s quad sits inside the %s quad at %.0f%% of "
                                "its area — a screen inside a device body"
                                % (iname, oname, ratio * 100))
        elif te > tr:
            # Not nested, and the edge quad's own shape says "screen" more
            # strongly than the region's does. Before 11 Sep 2026 tone won here
            # unconditionally, on the argument that its band assumption holding
            # was itself evidence -- and on two of ten labelled photographs that
            # handed the answer to a tone quad 159% and 249% off, with corner
            # spreads of 3.4 and 19.9, over an edge quad at 0% with a confident
            # radius. A band assumption is weaker evidence than four agreeing
            # corners; the tiers say so and this reads them.
            best, why = e, ("the two quads aren't nested and the edge quad's "
                            "corners agree on a radius (tier %d) where %s's do "
                            "not (tier %d)" % (te, rname, tr))
        else:
            best, why = region, ("the two quads aren't nested; %s's assumption "
                                 "holding is itself evidence that it found a screen"
                                 % rname)
    else:
        best = t or e or sat
    if best is None:
        best = results[0]

    if len(results) > 1:
        # Agreement is measured against the CLOSEST other detector, not against
        # "the other one" — there are three now, and a third opinion that lands
        # somewhere else entirely should not erase the fact that two of them
        # landed together. Corroboration by any one independent method is the
        # evidence worth reporting.
        diag = float(np.hypot(*shape))
        others = [r for r in results if r is not best]
        gaps = [(float(np.max(np.linalg.norm(best["_corners_np"]
                                             - r["_corners_np"], axis=1))) / diag, r)
                for r in others]
        spread, nearest = min(gaps, key=lambda g: g[0])
        agree = bool(spread < 0.02)
        best["agreement"] = {
            "both_found": True,
            "max_corner_gap_frac_of_diagonal": round(spread, 4),
            "agree": agree,
            "agrees_with": nearest["method"] if agree else None,
            "note": ("The %s and %s detectors independently landed on the same "
                     "quad — that is real evidence, not one algorithm's opinion."
                     % (best["method"], nearest["method"])
                     if agree else
                     "No two detectors agree; the closest other (%s) is %.0f%% of "
                     "the image diagonal away. Showing the %s one because %s — "
                     "but check all four corners."
                     % (nearest["method"], spread * 100, best["method"], why)),
        }
        best["agreement"]["chosen_because"] = why
        best["other"] = [{"method": r["method"], "corners": r["corners"]}
                         for r in others]
    else:
        best["agreement"] = {
            "both_found": False,
            "agree": False,
            "note": ("Only the %s detector found anything — a first guess to "
                     "correct, not a measurement." % best["method"]),
        }

    # Abstention. detect.py has always PROMISED to fail honestly rather than
    # emit a confident wrong quad, but nothing enforced it: on 7 Sep 2026 a real
    # photo produced a quad on the table, with `agree` false, the two detectors
    # 55% of the diagonal apart, the radius spread at 104%, and two corners off
    # the image — every indicator of failure present, and a result returned
    # anyway, exit 0. The evidence was already being computed; it just wasn't
    # gating. Two conditions, either of which means "we do not know":
    ag = best["agreement"]
    # Disagreement only counts against a CREDIBLE peer. Measured 7 Sep 2026 on
    # eight real mockup photos: where saturation correctly found a phone that
    # tone and edge had both missed, the winner was of course miles from the two
    # that failed — and this gate then threw the right answer away as
    # "disagreement". A detector that found a sharp-cornered patch of floor does
    # not get a vote on whether the rounded thing is a screen. So the gap is
    # re-measured against peers that also found something screen-shaped; when
    # there are none, being alone is not evidence of being wrong.
    # ... and a peer may only veto a result whose shape evidence it at least
    # matches. On iPhone-2 (11 Sep 2026) a tone quad 143% off, "rounded" at a
    # spread of 1.43, vetoed a confident edge quad 0.3% off -- the bench's one
    # "good quad refused". A veto from weaker evidence is not a disagreement
    # between peers; it is noise outvoting a measurement.
    # ... and a peer sitting INSIDE the winner is not disagreeing about where
    # the screen is. On iPhone-15 (12 Sep 2026) arbitration had just ruled a
    # tone quad to be content drawn on the edge quad's screen -- nested at 9%
    # of its area, a rounded card -- and this gate then read that same card as
    # a credible second opinion 32% of the diagonal away and abstained, holding
    # a quad 0% from the label. A veto is for two screen-shaped findings in
    # two PLACES; a card on the screen is one place. The nested case has
    # already been decided above, on tiers and ratio, by the time this runs.
    peers = [r for r in results if r is not best and has_rounded_corners(r)
             and shape_tier(r) >= shape_tier(best)
             and overlap_frac(r["_corners_np"], best["_corners_np"]) < NESTED_OVERLAP]
    if peers:
        diag = float(np.hypot(*shape))
        peer_gap = min(float(np.max(np.linalg.norm(best["_corners_np"]
                                                   - r["_corners_np"], axis=1))) / diag
                       for r in peers)
    else:
        peer_gap = None
    gross = bool(peer_gap is not None and peer_gap > ABSTAIN_GAP)
    if peer_gap is not None:
        ag["credible_peer_gap"] = round(peer_gap, 4)
    # A measurable corner radius counts as evidence in its own right: it says
    # the thing found is shaped like a screen, which is what abstention exists
    # to doubt. Without this a good saturation result on a hard photo would be
    # thrown away for want of a second opinion.
    # A click IS corroboration, and the strongest kind available: a person
    # looked at the photograph and said "the screen is here". Abstaining for
    # want of a second algorithm after that would be refusing the only evidence
    # that outranks the algorithms. Gross disagreement between two credible
    # peers still counts -- that says the click landed somewhere ambiguous, and
    # is worth reporting -- but being alone no longer does.
    uncorroborated = bool(click is None
                          and not ag.get("agree")
                          and not best["corner_radius"]["confident"]
                          and not has_rounded_corners(best))
    if gross or uncorroborated:
        why = []
        if gross:
            why.append("two detectors that each found something screen-shaped are "
                       "%.0f%% of the image diagonal apart" % (peer_gap * 100))
        if uncorroborated:
            why.append("nothing corroborates the quad (the detectors don't agree "
                       "and the corner radius isn't measurable)")
        best["abstained"] = True
        best["abstain_reason"] = (
            "Detection abstained: " + " and ".join(why) + ". The quad below is "
            "kept for inspection but is not offered as a starting position — "
            "place the four edges by hand."
        )
    else:
        best["abstained"] = False
    return best


def write_trace(path, photo_path, shape, click, result, rows):
    """The candidate list as a file, which is the form a benchmark can read.

    Deliberately not folded into the sidecar: `result.json` is the recipe for
    reproducing a composite and is contract-tested against compose()'s
    signature, so hanging diagnostics off it would couple two things that
    change for different reasons. This is a separate artefact of a separate
    run.
    """
    by_verdict = {}
    for r in rows:
        by_verdict[r["verdict"]] = by_verdict.get(r["verdict"], 0) + 1
    with open(path, "w") as f:
        json.dump({
            "photo": photo_path,
            "size": [int(shape[1]), int(shape[0])],
            "click": list(click) if click else None,
            "chosen": None if result is None else {
                "method": result.get("method"),
                "corners": result.get("corners"),
                "abstained": bool(result.get("abstained")),
            },
            "counts": {"candidates": len(rows), **by_verdict},
            "candidates": rows,
        }, f, indent=1)
    return by_verdict


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--photo", required=True)
    ap.add_argument("--out-corners", required=True, help="Where to write the corners JSON")
    ap.add_argument("--out-overlay", help="Optional PNG showing the detected quad on the photo")
    ap.add_argument("--out-zooms", help="Optional directory for 2x corner close-ups")
    ap.add_argument("--tone", help="Skip the sweep and force one band, e.g. --tone 20,40")
    ap.add_argument("--click", help="A point inside the screen, X,Y in photo pixels")
    ap.add_argument("--trace", help="Write every candidate quad, with its score and "
                                    "what became of it, to this JSON file")
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

    click = None
    if args.click:
        try:
            click = tuple(float(v) for v in args.click.split(","))
            if len(click) != 2:
                raise ValueError
        except ValueError:
            sys.exit("error: --click must be X,Y (e.g. --click 850,637)")

    trace = [] if args.trace else None
    result = detect(gray, tone, color=photo, click=click, trace=trace)
    if trace is not None:
        # Written whether or not anything was found: a run that found NOTHING is
        # the most interesting one to inspect, and it is exactly the run that
        # would otherwise leave no trace at all.
        write_trace(args.trace, args.photo, photo.shape, click, result, trace)
        print(f"trace: {len(trace)} candidates -> {args.trace}", file=sys.stderr)
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

    if result.get("abstained"):
        print(result["abstain_reason"], file=sys.stderr)
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

    # The docstring's promise, finally enforced: an uncorroborated guess exits
    # non-zero. The JSON is still printed above so a caller can inspect what was
    # rejected and why.
    if result.get("abstained"):
        sys.exit(2)


if __name__ == "__main__":
    main()
