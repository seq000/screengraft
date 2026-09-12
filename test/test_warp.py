"""
Tests for warp.py — the compositing engine.

The important one here is minification. A UI screenshot is almost always far
larger than the screen it lands on (1206x2622 into a 226x454 quad is >5x), and
cv2.warpPerspective does not area-average at any interpolation setting: it
samples a fixed neighbourhood around one source point, so heavy minification
aliases badly and text turns to noise. That shipped in v0.5.1 and was only
caught by looking at a real save. This test fails if the prefilter is ever
removed or bypassed.

Run: ~/.screengraft/venv/bin/python test/test_warp.py
"""
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import warp as W  # noqa: E402
import dof as DOF  # noqa: E402


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    return cond


def naive_compose(photo, screenshot, corners, radius):
    """What compose() used to do: straight to warpPerspective, no prefilter."""
    dst = np.array(corners, dtype=np.float32)
    sh, sw = screenshot.shape[:2]
    H = cv2.getPerspectiveTransform(
        np.array([[0, 0], [sw, 0], [sw, sh], [0, sh]], dtype=np.float32), dst)
    ph, pw = photo.shape[:2]
    m = W.rounded_mask(sw, sh, int(radius))
    ws = cv2.warpPerspective(screenshot, H, (pw, ph), flags=cv2.INTER_LANCZOS4,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    wm = cv2.warpPerspective(m, H, (pw, ph), flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    m3 = cv2.merge([wm] * 3).astype(np.float32) / 255.0
    out = photo.astype(np.float32) * (1 - m3) + ws.astype(np.float32) * m3
    return np.clip(out, 0, 255).astype(np.uint8), wm


def text_like_screenshot(w=1206, h=2622):
    """Fine horizontal rules at body-text pitch — the pattern that aliases."""
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    for y in range(0, h, 6):                      # 6px pitch, like small type
        img[y:y + 2, :] = 20
    for x in range(0, w, 40):                     # some vertical structure too
        img[:, x:x + 2] = 60
    return img


def main():
    failures = 0
    photo = np.full((768, 1024, 3), 200, dtype=np.uint8)
    shot = text_like_screenshot()
    # The quad from the 3 Sep 2026 report: ~5.3x across, ~5.8x along.
    corners = [[232.8, 307.8], [429.7, 201.9], [797.4, 467.4], [599.5, 575.8]]
    radius = 0.14 * shot.shape[1]

    print("minification is prefiltered, not left to warpPerspective")
    new = W.compose(photo, shot, corners, radius)
    old, wm = naive_compose(photo, shot, corners, radius)
    inside = wm > 200

    def hf_energy(img):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
        return float(np.std(cv2.Laplacian(g, cv2.CV_32F)[inside]))

    e_new, e_old = hf_energy(new), hf_energy(old)
    failures += not check(
        "aliasing energy is well below the un-prefiltered path",
        e_new < 0.75 * e_old, f"prefiltered {e_new:.1f} vs naive {e_old:.1f}")

    # A correct area-average of a 50/50 black-and-white rule pattern tends to
    # mid grey; aliasing instead produces scattered extremes and moire.
    g_new = cv2.cvtColor(new, cv2.COLOR_BGR2GRAY)[inside]
    g_old = cv2.cvtColor(old, cv2.COLOR_BGR2GRAY)[inside]
    extremes_new = float(np.mean((g_new < 40) | (g_new > 230)))
    extremes_old = float(np.mean((g_old < 40) | (g_old > 230)))
    failures += not check(
        "fewer blown-out pixels than the naive path",
        extremes_new <= extremes_old,
        f"{extremes_new*100:.0f}% vs {extremes_old*100:.0f}%")

    print("the prefilter only ever downsamples")
    small = np.full((60, 40, 3), 128, dtype=np.uint8)   # smaller than the quad
    up = W.compose(photo, small, corners, 0)
    failures += not check("a small screenshot is not upscaled first", up.shape == photo.shape)

    print("the screen's edge is antialiased, not stepped")
    # A single warpPerspective of a binary mask leaves a ~1px hard transition,
    # so the screen lands on the photo with visibly stepped edges — reported
    # 4 Sep 2026 after the resampling fix, as the remaining tell.
    dst = np.array(corners, dtype=np.float32)
    small = cv2.resize(shot, (367, 972), interpolation=cv2.INTER_AREA)
    sh_, sw_ = small.shape[:2]
    Hm = cv2.getPerspectiveTransform(
        np.array([[0, 0], [sw_, 0], [sw_, sh_], [0, sh_]], dtype=np.float32), dst)
    m_src = W.rounded_mask(sw_, sh_, 51)
    aa = W._warp_mask_antialiased(m_src, Hm, 1024, 768, dst)
    hard = cv2.warpPerspective(m_src, Hm, (1024, 768), flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    partial_aa = int(((aa > 8) & (aa < 247)).sum())
    partial_hard = int(((hard > 8) & (hard < 247)).sum())
    failures += not check(
        "more genuinely partial-coverage pixels along the edge",
        partial_aa > 1.3 * partial_hard, f"{partial_aa} vs {partial_hard}")
    failures += not check("the mask still saturates inside the screen",
                          aa.max() == 255 and aa.min() == 0)

    print("no dark fringe where the mask is partial")
    # With an antialiased mask, sampling black outside the screenshot would
    # draw a dark rim exactly where the antialiasing should be blending. A
    # white screen on a white photo must not develop a dark outline.
    white_shot = np.full((2622, 1206, 3), 255, dtype=np.uint8)
    white_photo = np.full((768, 1024, 3), 255, dtype=np.uint8)
    comp = W.compose(white_photo, white_shot, corners, 0)
    failures += not check("white-on-white composites stay white",
                          int(comp.min()) >= 250, f"darkest pixel {int(comp.min())}")

    print("determinism survives the prefilter")
    a = W.compose(photo, shot, corners, radius)
    b = W.compose(photo, shot, corners, radius)
    failures += not check("two runs are byte-identical", np.array_equal(a, b))

    print("geometry is unchanged by the prefilter")
    # Compared against the un-prefiltered path, not an absolute tolerance: the
    # claim is that prefiltering changes sampling, not placement. An absolute
    # bound would really be measuring how an antialiased corner rounds off.
    flat = np.full((2622, 1206, 3), 255, dtype=np.uint8)
    black = np.zeros((768, 1024, 3), np.uint8)
    def extent(img):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        ys, xs = np.nonzero(g > 128)
        return np.array([xs.min(), xs.max(), ys.min(), ys.max()], dtype=float)
    e_pre = extent(W.compose(black, flat, corners, 0))
    e_naive = extent(naive_compose(black, flat, corners, 0)[0])
    shift = float(np.max(np.abs(e_pre - e_naive)))
    failures += not check("placement matches the un-prefiltered path",
                          shift <= 1.0, f"largest edge shift {shift:.1f}px")

    # --- the rounded mask must be symmetric on all four sides -------
    # The arcs were drawn with cv2.circle, whose integer coords are pixel
    # centres, against a screenshot box measured in edge coords. That put the
    # whole rounded rect half a pixel down-right, so the bottom and right arcs
    # were tangent one row/column outside the image and got clipped a pixel
    # early — the bottom row profile came out as the top profile shifted by
    # one. Visible on a real save as corners "cut out by a pixel or two".
    print("\nrounded mask symmetry")
    worst_v = worst_h = 0.0
    for (w_, h_, r_) in [(200, 300, 40), (1206, 2622, 180), (226, 454, 34),
                         (101, 101, 17), (64, 64, 32)]:
        m = W.rounded_mask(w_, h_, r_).astype(np.float64) / 255.0
        rows, cols = m.sum(axis=1), m.sum(axis=0)
        worst_v = max(worst_v, float(np.abs(rows - rows[::-1]).max()))
        worst_h = max(worst_h, float(np.abs(cols - cols[::-1]).max()))
    failures += not check("mask is symmetric top-to-bottom",
                          worst_v < 1e-9, f"worst row-coverage delta {worst_v:.2e}px")
    failures += not check("mask is symmetric left-to-right",
                          worst_h < 1e-9, f"worst col-coverage delta {worst_h:.2e}px")

    # Coverage must be true area, not just symmetric: r = w/2 = h/2 is a disc,
    # so the mask's total weight is pi*r^2 if the ramp is metrically honest.
    disc = W.rounded_mask(64, 64, 32).astype(np.float64) / 255.0
    err = abs(disc.sum() - np.pi * 32 * 32) / (np.pi * 32 * 32)
    failures += not check("corner coverage is metrically accurate",
                          err < 0.002, f"disc area off by {err * 100:.3f}%")

    # Straight edges must stay fully opaque — a ramp that bleeds inward would
    # feather the whole screen border, not just the corners.
    m = W.rounded_mask(200, 300, 40).astype(np.float64) / 255.0
    edges_solid = (m[150, 42:158].min() == 1.0 and m[42:258, 100].min() == 1.0
                   and m[0, 100] == 1.0 and m[299, 100] == 1.0
                   and m[150, 0] == 1.0 and m[150, 199] == 1.0)
    failures += not check("straight edges stay fully opaque", edges_solid)

    print("a true-black UI on a lit surface is a hole under replace, not under emissive")
    # The 9 Sep 2026 case: an automotive dashboard render whose UI is 56% #000.
    # `replace` treats the screenshot as paint and discards the device's own
    # glass, so true black lands as true black on a lit dashboard and reads as a
    # hole cut in the render. A real display shows emission PLUS the room
    # reflecting off it — which is why a switched-off phone is dark grey.
    lit = np.zeros((400, 700, 3), np.uint8)
    for y in range(400):                       # a lit, matte surface with a streak
        lit[y, :] = 40 + int(28 * np.exp(-((y - 150) ** 2) / 900.0))
    quad = [[120, 120], [580, 124], [578, 300], [122, 296]]
    ui = np.zeros((176, 460, 3), np.uint8)     # true black with a little content
    cv2.putText(ui, "MAP", (30, 100), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 4)
    plan = W.Plan(lit, ui.shape, quad)
    inside = plan.warped_mask > 200

    rep = W.compose(lit, ui, quad, 0.0)
    emi = W.compose(lit, ui, quad, 0.0, blend="emissive", reflection=0.35)
    g = lambda im: cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    rep_med = float(np.median(g(rep)[inside]))
    emi_med = float(np.median(g(emi)[inside]))
    sur_med = float(np.median(g(lit)[inside == False]))  # noqa: E712 - the lit surface
    failures += not check("replace leaves the screen far darker than the surface",
                          rep_med < 5, f"screen median {rep_med:.1f} vs surface {sur_med:.1f}")
    failures += not check("emissive lifts it toward the surface",
                          emi_med > rep_med + 8, f"{rep_med:.1f} -> {emi_med:.1f}")
    # The point is not the level but the STRUCTURE: the streak in the surface
    # must survive across the screen. Colour-matching can only lift uniformly.
    row_hi = float(np.median(g(emi)[150, 200:500]))
    row_lo = float(np.median(g(emi)[280, 200:500]))
    flat_hi = float(np.median(g(rep)[150, 200:500]))
    flat_lo = float(np.median(g(rep)[280, 200:500]))
    failures += not check("the surface's own gradient carries across the screen",
                          (row_hi - row_lo) > (flat_hi - flat_lo) + 5,
                          f"emissive delta {row_hi-row_lo:.1f} vs replace {flat_hi-flat_lo:.1f}")
    failures += not check("reflection=0 collapses exactly to replace",
                          np.array_equal(W.compose(lit, ui, quad, 0.0, blend="emissive",
                                                   reflection=0.0), rep))
    failures += not check("an unknown blend name falls back to replace, not an error",
                          np.array_equal(W.compose(lit, ui, quad, 0.0, blend="banana"), rep))
    failures += not check("emissive is OFF by default", np.array_equal(W.compose(lit, ui, quad, 0.0), rep))

    print("corner smoothing — Apple's squircle (Figma 0-100%, iOS = 60%)")
    # The degenerate case is the strongest available check: at smoothing 0 the
    # two cubics vanish and Figma's construction must BE a circular arc. If the
    # port of the formula is wrong anywhere, this stops being a circle.
    curve, p0 = W.squircle_corner(80.0, 0.0, 200.0)
    dev = np.hypot(curve[:, 0] - 80.0, curve[:, 1] - 80.0) - 80.0
    failures += not check("at smoothing 0 the curve IS a circular arc",
                          float(np.abs(dev).max()) < 1e-6 and abs(p0 - 80.0) < 1e-9,
                          f"worst deviation {float(np.abs(dev).max()):.2e}px from r=80")
    # ... and the whole mask must be byte-identical to the analytic path, which
    # is what lets every save made before smoothing existed reproduce exactly.
    same = all(np.array_equal(W.rounded_mask(w, h, r), W.rounded_mask(w, h, r, 0.0))
               for (w, h, r) in ((400, 300, 40), (900, 1600, 126), (200, 200, 100)))
    failures += not check("smoothing 0 leaves the mask byte-identical", same)

    # The point of a squircle: the curve leaves each edge PARALLEL to it, so
    # there is no corner where the curvature jumps. A circular arc does this too
    # at its tangent points; what a squircle adds is getting there smoothly, and
    # the endpoints are where that is checkable without differentiating twice.
    c6, p6 = W.squircle_corner(80.0, W.IOS_SMOOTHING, 200.0)
    t_in = c6[3] - c6[0]
    t_out = c6[-1] - c6[-4]
    t_in = t_in / np.linalg.norm(t_in)
    t_out = t_out / np.linalg.norm(t_out)
    # 1e-3, not 0: these are finite differences between sampled points, so they
    # carry the curve's own curvature over that step. The construction is exactly
    # parallel (the first control point is directly below P0), and 1.6e-5 is the
    # sampling error, which is still 0.001 degrees off the edge.
    failures += not check("at iOS smoothing the curve meets both edges parallel",
                          abs(t_in[0]) < 1e-3 and abs(t_out[1]) < 1e-3,
                          f"in {t_in[0]:.2e} off vertical, out {t_out[1]:.2e} off horizontal")
    failures += not check("...and it spans (0,p) to (p,0) exactly",
                          abs(c6[0][0]) < 1e-9 and abs(c6[-1][1]) < 1e-9
                          and abs(c6[0][1] - p6) < 1e-9 and abs(c6[-1][0] - p6) < 1e-9,
                          f"p={p6:.3f} for r=80 at smoothing {W.IOS_SMOOTHING}")
    # p = (1 + smoothing) * r is the one number the whole construction hangs on.
    failures += not check("...with p = (1 + smoothing) * r",
                          abs(p6 - (1.0 + W.IOS_SMOOTHING) * 80.0) < 1e-9, f"p={p6}")

    # Smoothing reaches further along the edge, so it takes MORE of the corner.
    areas = [W.rounded_mask(400, 400, 80, s).sum() for s in (0.0, 0.3, 0.6, 1.0)]
    failures += not check("more smoothing removes more of the corner",
                          all(a > b for a, b in zip(areas[:-1], areas[1:], strict=True)),
                          " > ".join(str(a) for a in areas))

    # ---- depth of field: a blur that grows in one direction, edge included ----
    # A textured photograph, so the far edge's softness is measurable against
    # the near edge's, and a screenshot with fine structure everywhere.
    rng = np.random.default_rng(3)
    tex = np.clip(rng.normal(128, 40, (768, 1024, 3)), 0, 255).astype(np.uint8)
    tex = cv2.GaussianBlur(tex, (0, 0), 1.2)
    shot = text_like_screenshot(600, 1200)
    quad = [[300, 120], [720, 130], [710, 650], [290, 640]]
    plain = W.compose(tex, shot, quad, 24)
    zero = W.compose(tex, shot, quad, 24, dof_angle=90, dof_strength=0.0)
    failures += not check("dof strength 0 is byte-identical to no dof (every old sidecar reproduces)",
                          np.array_equal(plain, zero))
    down = W.compose(tex, shot, quad, 24, dof_angle=90, dof_strength=0.6)   # blur grows toward +y

    def lap_var(img, y0, y1):
        g = cv2.cvtColor(img[y0:y1, 340:670], cv2.COLOR_BGR2GRAY).astype(np.float32)
        return float(cv2.Laplacian(g, cv2.CV_32F).var())
    # Bands at 2% and 80% of the way along the ramp: the near band is inside
    # the first blur step (sigma under 1px), the far one at four times that.
    near, far = lap_var(down, 134, 150), lap_var(down, 520, 620)
    near0, far0 = lap_var(plain, 134, 150), lap_var(plain, 520, 620)
    failures += not check("blur grows in the chosen direction: the far band is far softer than the near band",
                          near > 10 * far and near > 0.5 * near0,
                          f"near {near:.0f} (was {near0:.0f}) far {far:.0f} (was {far0:.0f})")
    up = W.compose(tex, shot, quad, 24, dof_angle=270, dof_strength=0.6)
    nearu, faru = lap_var(up, 520, 620), lap_var(up, 150, 250)
    failures += not check("...and the opposite angle blurs the opposite end",
                          nearu > 3 * faru, f"bottom {nearu:.0f} top {faru:.0f}")
    # The glass edge softens WITH the blur: below the far edge the COMPOSITE
    # departs from the photograph for many rows (the soft alpha lets screen
    # through); below the near edge, and everywhere without dof, for none.
    # Read from the composite, not from the Field -- a render that built the
    # field and then blended by the sharp mask would pass a Field-only check.
    def spill(img, y_edge, x=500):
        g = cv2.cvtColor(img[y_edge + 1:y_edge + 30, x - 3:x + 4], cv2.COLOR_BGR2GRAY).astype(np.float32)
        t = cv2.cvtColor(tex[y_edge + 1:y_edge + 30, x - 3:x + 4], cv2.COLOR_BGR2GRAY).astype(np.float32)
        return int((np.abs(g - t).mean(axis=1) > 3).sum())
    yb = int(640 + (650 - 640) * (500 - 290) / (710 - 290))        # bottom edge at x=500
    s_plain, s_far = spill(plain, yb), spill(down, yb)
    s_near = spill(up, yb)                                          # blur toward the top: bottom edge stays sharp
    failures += not check("the far glass edge softens with the blur (the mask blurs with the layer)",
                          s_plain <= 2 and s_far >= 8 and s_near <= 2,
                          f"rows of screen spilling past the edge: none {s_plain}, far {s_far}, near {s_near}")
    # A focus START: the near part of the screen stays sharp up to the start
    # line and the ramp begins there. At start 0.5 the 40% band is untouched;
    # at start 0 (the default) the same band is already softened.
    half = W.compose(tex, shot, quad, 24, dof_angle=90, dof_strength=0.6, dof_start=0.5)
    mid_default, mid_half, mid_plain = lap_var(down, 300, 340), lap_var(half, 300, 340), lap_var(plain, 300, 340)
    failures += not check("dof_start keeps the screen sharp up to the focus line",
                          mid_half > 0.85 * mid_plain and mid_default < 0.5 * mid_plain,
                          f"40% band: plain {mid_plain:.0f}, start 0 -> {mid_default:.0f}, start 0.5 -> {mid_half:.0f}")
    failures += not check("...and start 0 is what every earlier sidecar meant",
                          np.array_equal(down, W.compose(tex, shot, quad, 24, dof_angle=90, dof_strength=0.6, dof_start=0.0)))

    # The estimator: sharp all round reads flat; a planted gradient blur on the
    # PHOTO reads back with the planted direction.
    m0 = DOF.measure(plain, quad)
    failures += not check("measure: a sharp screen boundary reads flat", m0["flat"], str(m0))
    for ang in (90.0, 0.0, 225.0):
        q = np.array(quad, dtype=np.float64)
        f = DOF.Field(q, ang, 1.0, np.full(plain.shape[:2], 255, np.uint8), 0, 0)
        f.sigmas = [4.0 * k / (DOF.DOF_LEVELS - 1) for k in range(DOF.DOF_LEVELS)]
        col = plain.astype(np.float32); num = np.zeros_like(col)
        for k in range(DOF.DOF_LEVELS):
            bk = col if f.sigmas[k] <= 0 else DOF._blur(col, f.sigmas[k]); num += f.W[k][:, :, None] * bk
        m = DOF.measure(np.clip(num, 0, 255).astype(np.uint8), quad)
        err = None if m["flat"] else abs(((m["angle"] - ang) + 180) % 360 - 180)
        failures += not check(f"measure: a blur planted toward {ang:.0f}° reads back within 20°",
                              not m["flat"] and err < 20 and m["strength"] > 0.05,
                              f"angle {m.get('angle')} strength {m.get('strength')} sigma {m.get('sigma')}")

    print()
    if failures:
        print(f"{failures} check(s) failed")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
