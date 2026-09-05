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

    print()
    if failures:
        print(f"{failures} check(s) failed")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
