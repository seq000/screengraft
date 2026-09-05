#!/usr/bin/env python3
"""
screengraft — M0: manual four-point perspective warp.

Takes a photo of a device and a UI screenshot, and warps the screenshot into
a given quadrilateral (the four screen corners in the photo) so the
perspective matches exactly. Geometry, not generation: a single
cv2.getPerspectiveTransform + cv2.warpPerspective call, deterministic
end to end.

Design constraints this script exists to satisfy (see the project's design notes):
  - Warp once, at the photo's full resolution — never warp-then-scale
    (double resampling blurs text).
  - Fully deterministic: same inputs -> byte-identical output PNG.
  - No AI, no guessing: corners are supplied by the caller (a human, via the
    drag-picker UI, or hardcoded for a test) — this script only does the
    textbook part.

Usage:
  python3 warp.py --photo photo.jpg --screenshot ui.png \
      --corners '[[120,80],[860,140],[840,900],[100,840]]' \
      --output out.png [--corner-radius 40]

Corners are [x, y] pixel coordinates in the PHOTO, in order
TL, TR, BR, BL (top-left, top-right, bottom-right, bottom-left of the
screen as it appears in the photo — order matters, it defines the mapping).
"""

import argparse
import json
import sys

import cv2
import numpy as np

import grade as _grade   # M2: the realism pass


MASK_SS = 4   # destination-space supersampling for the screen's edge


def rounded_mask(w: int, h: int, radius: float) -> np.ndarray:
    """White-on-black mask, full frame minus rounded corners cut to black.

    Computed analytically rather than drawn, for two reasons.

    Geometry. The screenshot occupies the edge-coordinate box [0,w]x[0,h] --
    the box `compose` hands to getPerspectiveTransform -- so pixel *centres*
    sit at i+0.5 and the four arc centres belong at (r, r) and (w-r, h-r) in
    that same edge space. The previous version drew the arcs with cv2.circle,
    whose integer coordinates are pixel *centres*, which placed the whole
    rounded rectangle half a pixel down and to the right. The top and left
    arcs still came out tangent to the frame, but the bottom and right arcs
    were tangent to y=h and x=w -- one row/column outside the image -- so each
    was clipped a pixel early and met its straight edge at a slope
    discontinuity instead of flattening into it. Reported from a real save, 4 Sep 2026
    as the bottom corners looking "cut out by a pixel or two"; the row
    coverage profile confirmed it, the bottom being exactly the top shifted
    by one row (the tangent row missing entirely).

    Antialiasing. Coverage is a 1px linear ramp on the distance to the
    rounded rectangle, symmetric on all four sides by construction. LINE_AA's
    own ramp is not, and cannot be nudged sub-pixel without the fixed-point
    `shift` dance.
    """
    if radius <= 0:
        return np.full((h, w), 255, dtype=np.uint8)
    r = float(max(0.0, min(float(radius), w / 2.0, h / 2.0)))
    xs = np.arange(w, dtype=np.float64) + 0.5      # pixel centres, edge coords
    ys = np.arange(h, dtype=np.float64) + 0.5
    # Per-axis distance past the arc-centre rail: zero everywhere except the
    # four corner squares, so `dist` is the true distance to the rounded
    # rectangle's boundary there and the straight edges stay exactly full.
    dx = np.maximum(np.maximum(r - xs, xs - (w - r)), 0.0)
    dy = np.maximum(np.maximum(r - ys, ys - (h - r)), 0.0)
    dist = np.hypot(dx[None, :], dy[:, None])
    coverage = np.clip(r + 0.5 - dist, 0.0, 1.0)
    return np.rint(coverage * 255.0).astype(np.uint8)


def _warp_mask_antialiased(src_mask, H, pw, ph, dst_quad):
    """Warp the screen mask into photo space with coverage antialiasing.

    A single warpPerspective of a binary mask gives a ~1px hard transition,
    so the screen's edge lands on the photo stepped — obvious on a slanted
    edge, which is every interesting photo (reported 4 Sep 2026).

    Instead the mask is rasterised at MASK_SS x the output scale and then
    INTER_AREA'd down, so each output pixel gets the *fraction* of itself the
    screen actually covers — the same thing multisampling does. Only the
    quad's bounding box is supersampled, so the cost is a few megapixels
    rather than MASK_SS^2 x the whole photo.
    """
    x0 = max(0, int(np.floor(dst_quad[:, 0].min())) - 2)
    y0 = max(0, int(np.floor(dst_quad[:, 1].min())) - 2)
    x1 = min(pw, int(np.ceil(dst_quad[:, 0].max())) + 2)
    y1 = min(ph, int(np.ceil(dst_quad[:, 1].max())) + 2)
    out = np.zeros((ph, pw), dtype=np.uint8)
    if x1 <= x0 or y1 <= y0:
        return out
    bw, bh = x1 - x0, y1 - y0
    # photo space -> supersampled bbox-local space
    T = np.array([[MASK_SS, 0, -MASK_SS * x0],
                  [0, MASK_SS, -MASK_SS * y0],
                  [0, 0, 1]], dtype=np.float64)
    big = cv2.warpPerspective(
        src_mask, T @ H, (bw * MASK_SS, bh * MASK_SS),
        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    out[y0:y1, x0:x1] = cv2.resize(big, (bw, bh), interpolation=cv2.INTER_AREA)
    return out


def shoelace_area(pts: np.ndarray) -> float:
    x = pts[:, 0]
    y = pts[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))


def compose(photo: np.ndarray, screenshot: np.ndarray, corners, corner_radius: float = 0.0,
            grade: float = 0.0, grain: bool = False, screen_off: np.ndarray = None,
            specular: float = 0.75) -> np.ndarray:
    """Warp `screenshot` into the quad `corners` (TL,TR,BR,BL, photo pixels) on `photo`.

    Single resampling pass at the photo's resolution; deterministic. This is the
    whole engine — the CLI below and ui.py both call it.
    """
    dst_quad = np.array(corners, dtype=np.float32)
    if shoelace_area(dst_quad) < 1.0:
        raise ValueError("degenerate quad (near-zero area) — check corner order TL,TR,BR,BL")

    # --- prefilter for minification -------------------------------------
    # A UI screenshot is almost always far larger than the screen it lands
    # on: 1206x2622 into a 226x454 quad is 5.3x across and 5.8x along, so
    # each output pixel is the average of ~31 source pixels. warpPerspective
    # (like remap) does NOT area-average — INTER_LANCZOS4 samples a fixed 8x8
    # window around one source point no matter the scale, and Lanczos is a
    # sharpening kernel, so heavy minification came out aliased and crunchy
    # with text turned to noise (3 Sep 2026, reported from a real save).
    #
    # The fix is the mipmap principle: area-average DOWN to roughly the
    # destination footprint first, then warp at ~1:1. This is not the
    # "warp-then-scale" the build brief warns against — that's resampling an
    # already-warped result, which blurs. This is resampling the source with
    # the right filter before the only geometric pass, which is how you avoid
    # aliasing when minifying.
    top = float(np.linalg.norm(dst_quad[1] - dst_quad[0]))
    bottom = float(np.linalg.norm(dst_quad[2] - dst_quad[3]))
    left = float(np.linalg.norm(dst_quad[3] - dst_quad[0]))
    right = float(np.linalg.norm(dst_quad[2] - dst_quad[1]))
    # Use the LONGER opposing edge of each pair: under perspective the near
    # edge carries the most detail, and that's the resolution to preserve.
    need_w = max(top, bottom)
    need_h = max(left, right)
    sh0, sw0 = screenshot.shape[:2]
    scale_x, scale_y = need_w / sw0, need_h / sh0
    if 0 < max(scale_x, scale_y) < 0.95:          # only ever downsample
        new_w = max(1, int(round(sw0 * max(scale_x, scale_y))))
        new_h = max(1, int(round(sh0 * max(scale_x, scale_y))))
        screenshot = cv2.resize(screenshot, (new_w, new_h), interpolation=cv2.INTER_AREA)
        corner_radius = corner_radius * (new_w / sw0)   # radius is in source px
    # --------------------------------------------------------------------

    sh, sw = screenshot.shape[:2]
    src_rect = np.array([[0, 0], [sw, 0], [sw, sh], [0, sh]], dtype=np.float32)
    H = cv2.getPerspectiveTransform(src_rect, dst_quad)
    ph, pw = photo.shape[:2]
    # Radius stays fractional: rounded_mask is analytic, and after the
    # prefilter rescale above a truncation here is up to a whole pixel of
    # radius thrown away at exactly the scale the viewer is looking at.
    src_mask = rounded_mask(sw, sh, float(corner_radius))
    # BORDER_REPLICATE, not BORDER_CONSTANT black: with an antialiased mask
    # the edge pixels are a genuine blend of screen and photo, and sampling
    # black just outside the screenshot would draw a dark fringe right where
    # the antialiasing is supposed to be doing its work. Replicating the edge
    # pixel means a half-covered pixel blends real screen colour instead.
    warped_screen = cv2.warpPerspective(
        screenshot, H, (pw, ph), flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REPLICATE)
    warped_mask = _warp_mask_antialiased(src_mask, H, pw, ph, dst_quad)

    # --- M2: the realism pass -------------------------------------------
    # Order is not arbitrary. The light match runs on the warped screen BEFORE
    # compositing, so it measures and moves only screen pixels — grading after
    # the blend would drag the bezel with it. Grain and the specular lift run
    # AFTER, because both are things that happen to the finished surface, and
    # both are confined to the screen by the same mask.
    if grade > 0:
        warped_screen = _grade.match_light(photo, warped_screen, warped_mask, strength=grade)

    mask3 = cv2.merge([warped_mask] * 3).astype(np.float32) / 255.0
    out = photo.astype(np.float32) * (1 - mask3) + warped_screen.astype(np.float32) * mask3
    out = np.clip(out, 0, 255).astype(np.uint8)

    if grain:
        sigma = _grade.measure_grain(photo, _grade.surround_ring(warped_mask))
        out = _grade.add_grain(out, warped_mask, sigma)
    if screen_off is not None:
        out = _grade.specular_lift(out, screen_off, warped_mask, strength=specular)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--photo", required=True, help="Path to the device photo")
    ap.add_argument("--screenshot", required=True, help="Path to the UI screenshot to inject")
    ap.add_argument("--corners", required=True, help="JSON [[x,y]x4] in the photo, order TL,TR,BR,BL")
    ap.add_argument("--output", required=True, help="Output PNG path")
    ap.add_argument("--corner-radius", type=float, default=0.0,
                     help="Corner radius in SCREENSHOT source pixels (0 = square corners, M0 default)")
    args = ap.parse_args()

    photo = cv2.imread(args.photo, cv2.IMREAD_COLOR)
    if photo is None:
        sys.exit(f"error: could not read photo: {args.photo}")
    screenshot = cv2.imread(args.screenshot, cv2.IMREAD_COLOR)
    if screenshot is None:
        sys.exit(f"error: could not read screenshot: {args.screenshot}")

    try:
        corners = json.loads(args.corners)
    except json.JSONDecodeError as e:
        sys.exit(f"error: --corners is not valid JSON: {e}")
    if len(corners) != 4 or any(len(c) != 2 for c in corners):
        sys.exit("error: --corners must be a JSON list of exactly 4 [x, y] pairs")

    try:
        composite = compose(photo, screenshot, corners, args.corner_radius)
    except ValueError as e:
        sys.exit(f"error: {e}")
    sh, sw = screenshot.shape[:2]
    ph, pw = photo.shape[:2]

    ok = cv2.imwrite(args.output, composite, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    if not ok:
        sys.exit(f"error: could not write output: {args.output}")

    print(json.dumps({
        "output": args.output,
        "photo_size": [pw, ph],
        "screenshot_size": [sw, sh],
        "dst_quad": corners,
        "corner_radius": args.corner_radius,
    }))


if __name__ == "__main__":
    main()
