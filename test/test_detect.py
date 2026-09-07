#!/usr/bin/env python3
"""
Tests for detect.py — the no-ML screen-quad finder.

Checks three things, in order of what would actually hurt if it broke:
  1. Accuracy: on a fixture with a hand-authored ground-truth quad, every
     detected corner lands within TOL pixels of the truth.
  2. Determinism: the same photo detected twice gives identical numbers.
     (The whole tool's promise is geometry, not guessing.)
  3. Honest failure: on a photo with no separable screen, it returns nothing
     rather than a confident wrong quad.

Run: .venv/bin/python test/test_detect.py
"""
import json
import os
import subprocess
import sys
import tempfile

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import detect as D  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")
TOL = 4.0  # pixels


def load_truth():
    with open(os.path.join(FIXTURES, "meta.json")) as f:
        return np.array(json.load(f)["ground_truth_quad_TL_TR_BR_BL"], dtype=np.float64)


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    return cond


def main():
    failures = 0
    photo_path = os.path.join(FIXTURES, "photo.png")
    gray = cv2.cvtColor(cv2.imread(photo_path, cv2.IMREAD_COLOR), cv2.COLOR_BGR2GRAY)

    print("accuracy against the ground-truth quad")
    res = D.detect(gray)
    if res is None:
        failures += 1
        print("  FAIL  detection returned nothing on the fixture")
    else:
        truth = load_truth()
        got = np.array(res["corners"], dtype=np.float64)
        dists = np.linalg.norm(got - truth, axis=1)
        for label, d in zip(["TL", "TR", "BR", "BL"], dists, strict=True):
            failures += not check(f"{label} within {TOL}px", d <= TOL, f"off by {d:.2f}px")
        failures += not check("corner order is TL,TR,BR,BL",
                              got[0][0] < got[1][0] and got[2][1] > got[1][1])

    print("determinism")
    a = D.detect(gray)
    b = D.detect(cv2.cvtColor(cv2.imread(photo_path, cv2.IMREAD_COLOR), cv2.COLOR_BGR2GRAY))
    failures += not check("two runs agree exactly", a["corners"] == b["corners"])

    print("honest failure on an unseparable photo")
    flat = np.full((900, 1200, 3), 200, dtype=np.uint8)
    noise_rng = np.random.default_rng(0)
    flat = np.clip(flat.astype(np.int16) + noise_rng.integers(-6, 7, flat.shape), 0, 255).astype(np.uint8)
    got = D.detect(cv2.cvtColor(flat, cv2.COLOR_BGR2GRAY))
    failures += not check("no quad invented from noise", got is None,
                          "" if got is None else f"invented {got['corners']}")

    print("rounded corners: the edge refinement actually runs")
    # The fixture above has square corners, so the polygon corners are already
    # exact and refinement changes nothing — which means it passes whether the
    # refinement runs or silently bails. This case exists because it did
    # silently bail once (CHAIN_APPROX_SIMPLE left fitLine nothing to fit) and
    # nothing caught it.
    quad = np.array([[420, 260], [1180, 330], [1120, 1010], [380, 940]], dtype=np.float64)
    rounded = np.full((1300, 1600, 3), 210, dtype=np.uint8)
    cv2.fillConvexPoly(rounded, quad.astype(np.int32), (30, 30, 32))
    # Round the corners off, the way a real screen is rounded.
    for (x, y) in quad:
        cv2.circle(rounded, (int(x), int(y)), 46, (210, 210, 210), -1, cv2.LINE_AA)
    cv2.fillConvexPoly(
        rounded,
        (quad.mean(axis=0) + (quad - quad.mean(axis=0)) * 0.90).astype(np.int32),
        (30, 30, 32),
    )
    res_r = D.detect(cv2.cvtColor(rounded, cv2.COLOR_BGR2GRAY))
    if res_r is None:
        failures += 1
        print("  FAIL  no quad found on the rounded fixture")
    else:
        failures += not check("refinement ran (did not silently bail)", res_r["edge_refined"])
        got_r = np.array(res_r["corners"], dtype=np.float64)
        worst = np.linalg.norm(got_r - quad, axis=1).max()
        failures += not check("recovers the virtual corners rounding hides",
                              worst <= 12.0, f"worst {worst:.1f}px")

    print("a sliver is rejected, not returned as a confident quad")
    # This is the shape of the 3 Sep 2026 failure: a contour that scrapes past
    # the 1% floor whose FINAL quad collapses below it. The gate used to run
    # only on the contour, so a 0.72%-of-image sliver around a watermark was
    # returned as a green "Detected".
    img_area = 1024.0 * 768.0
    sliver = np.array([[482, 426], [613, 459], [613, 501], [552, 511]], dtype=np.float64)
    ok, why = D.validate_quad(sliver, None, img_area)
    failures += not check("the actual 0.72% quad from the bug report is rejected",
                          not ok, why)
    thin = np.array([[100, 400], [900, 400], [900, 412], [100, 412]], dtype=np.float64)
    ok2, why2 = D.validate_quad(thin, None, img_area)
    failures += not check("a thin sliver is rejected", not ok2, why2)
    good = np.array([[300, 200], [800, 220], [790, 700], [290, 680]], dtype=np.float64)
    ok3, why3 = D.validate_quad(good, None, img_area)
    failures += not check("a plausible screen quad still passes", ok3, why3)

    print("a screen with CONTENT on it is found (tone banding can't)")
    # Models the 3 Sep 2026 failure: a rendered mockup whose screen shows a
    # gradient wallpaper. No tone band contains such a screen, so the tone
    # sweep finds nothing and the whole detector used to return a watermark
    # sliver instead. The bezel is shaded rather than flat — a flat one is
    # itself a perfect tone blob, which no real render or photo offers and
    # which would let the tone path "win" on the device body.
    gq = np.array([[380, 240], [1160, 300], [1100, 1000], [340, 930]], dtype=np.float64)
    H, W = 1300, 1600
    grad = np.full((H, W, 3), 235, dtype=np.uint8)
    body = (gq.mean(axis=0) + (gq - gq.mean(axis=0)) * 1.07).astype(np.int32)
    shade = np.zeros((H, W, 3), dtype=np.uint8)
    for x in range(W):  # shaded body: 14 -> 62 across the frame
        shade[:, x] = 14 + int(48 * x / W)
    bmask = np.zeros((H, W), dtype=np.uint8)
    cv2.fillConvexPoly(bmask, body, 255)
    grad[bmask > 0] = shade[bmask > 0]
    ramp = np.zeros((H, W, 3), dtype=np.uint8)
    for y in range(H):  # wallpaper-ish gradient across most of the tonal range
        ramp[y, :] = (30 + int(200 * y / H), 90 + int(120 * y / H), 200 - int(60 * y / H))
    smask = np.zeros((H, W), dtype=np.uint8)
    cv2.fillConvexPoly(smask, gq.astype(np.int32), 255)
    grad[smask > 0] = ramp[smask > 0]
    ggray = cv2.cvtColor(grad, cv2.COLOR_BGR2GRAY)
    res_g = D.detect(ggray)
    if res_g is None:
        failures += 1
        print("  FAIL  no quad found on the gradient-screen fixture")
    else:
        worst_g = np.linalg.norm(np.array(res_g["corners"], dtype=np.float64) - gq, axis=1).max()
        failures += not check("finds the screen, not the body or a content band",
                              worst_g <= 45.0, f"worst {worst_g:.1f}px via {res_g['method']}")

    print("CLI writes the artefacts a human confirms with")
    with tempfile.TemporaryDirectory() as td:
        cj = os.path.join(td, "corners.json")
        ov = os.path.join(td, "overlay.png")
        zd = os.path.join(td, "zooms")
        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "detect.py"),
             "--photo", photo_path, "--out-corners", cj, "--out-overlay", ov, "--out-zooms", zd],
            capture_output=True, text=True)
        failures += not check("exit 0", r.returncode == 0, r.stderr.strip()[:200])
        failures += not check("corners.json written", os.path.exists(cj))
        failures += not check("overlay written", os.path.exists(ov))
        failures += not check("four corner zooms written",
                              os.path.isdir(zd) and len(os.listdir(zd)) == 4)

    print("a quad with a corner off the image is rejected")
    # The 7 Sep 2026 failure, exactly: the tone detector returned the sunlit
    # TABLE, with TR at y=-50 and BR at y=1837 on a 1792-tall image. Off-canvas
    # handles cannot be dragged back, so the user was stuck with a wrong quad
    # and no way to fix it. Bounds are checked in validate_quad, which every
    # result passes through.
    shape = (1792, 2400)
    area = float(shape[0] * shape[1])
    oob = np.array([[1627.1, 143.5], [2399.0, -50.1],
                    [2399.0, 1836.7], [1463.7, 1709.4]], dtype=np.float64)
    ok, why = D.validate_quad(oob, None, area, shape)
    failures += not check("the actual off-canvas quad from the bug report is rejected",
                          not ok, why)
    failures += not check("...and names the offending corner", "TR" in why, why)
    inside = np.array([[986.6, 431.0], [1419.8, 430.8],
                       [1424.1, 1355.6], [985.4, 1357.3]], dtype=np.float64)
    ok2, why2 = D.validate_quad(inside, None, area, shape)
    failures += not check("the true screen quad from the same photo still passes",
                          ok2, why2)
    # Without a shape the check cannot run — that must not silently pass a
    # caller who forgot it into thinking bounds were verified.
    ok3, _ = D.validate_quad(oob, None, area)
    failures += not check("bounds are only claimed when a shape is supplied", ok3, "")

    print("every tone band offers its runners-up, not just its biggest blob")
    # The 7 Sep 2026 failure's real cause. blob_for_band used to return only the
    # LARGEST component per band, so on a photo where the phone was the second-
    # largest dark region (the table's shadow was bigger) the screen was never a
    # candidate — no scoring change could have ranked what was never generated.
    # Measured: best achievable quad went from 693px off the true screen to
    # 136px purely by keeping the runners-up.
    band_blobs = D.blobs_for_band(gray, 0, 90, 15, 41)
    failures += not check("blobs_for_band returns a list", isinstance(band_blobs, list),
                          type(band_blobs).__name__)
    failures += not check("it is capped at COMPONENTS_PER_BAND",
                          len(band_blobs) <= D.COMPONENTS_PER_BAND, str(len(band_blobs)))
    if len(band_blobs) > 1:
        areas = [cv2.contourArea(c) for c in band_blobs]
        failures += not check("biggest first", areas == sorted(areas, reverse=True), str(areas[:3]))

    print("size stops being rewarded past the plateau")
    # The table beat the screen 3.6x on the old linear area term alone. Past
    # AREA_PLATEAU the term saturates, so furniture stops outscoring glass by
    # being furniture-sized.
    big = D.size_term(0.34 * area, area)
    huge = D.size_term(0.55 * area, area)
    small = D.size_term(0.05 * area, area)
    failures += not check("the term saturates at 1.0", big == 1.0 and huge == 1.0,
                          f"{big} / {huge}")
    failures += not check("a 34% region no longer outscores a 15% one on size",
                          big == D.size_term(D.AREA_PLATEAU * area, area), "")
    failures += not check("below the plateau, bigger is still better",
                          small < big, f"{small:.3f} vs {big:.3f}")

    real = os.environ.get("SCREENGRAFT_REAL_PHOTO")
    real_corners = os.environ.get("SCREENGRAFT_REAL_CORNERS")
    if real and real_corners and os.path.exists(real):
        print("real photo, measured (advisory accuracy — see README)")
        g = cv2.cvtColor(cv2.imread(real, cv2.IMREAD_COLOR), cv2.COLOR_BGR2GRAY)
        r = D.detect(g)
        truth = np.array(json.load(open(real_corners)), dtype=np.float64)
        worst = np.linalg.norm(np.array(r["corners"], dtype=np.float64) - truth, axis=1).max()
        # Not a quality bar — a tripwire. Auto-detect is documented as ~66px
        # out on this photo; this fails if that silently gets worse.
        failures += not check("within the documented 80px envelope", worst <= 80.0,
                              f"worst {worst:.1f}px")
    else:
        print("real photo: skipped (set SCREENGRAFT_REAL_PHOTO + SCREENGRAFT_REAL_CORNERS)")

    real_bad = os.environ.get("SCREENGRAFT_ABSTAIN_PHOTO")
    if real_bad and os.path.exists(real_bad):
        print("a photo where both detectors miss is abstained on, not guessed at")
        g = cv2.cvtColor(cv2.imread(real_bad, cv2.IMREAD_COLOR), cv2.COLOR_BGR2GRAY)
        r = D.detect(g)
        failures += not check("detect() abstains", bool(r and r.get("abstained")),
                              (r or {}).get("abstain_reason", "returned a quad"))
    else:
        print("abstention photo: skipped (set SCREENGRAFT_ABSTAIN_PHOTO)")

    print("the fixture, where detection genuinely works, does NOT abstain")
    # The gate has to be sharp enough to catch a real miss without switching
    # off a real hit. Measured 7 Sep 2026: this fixture disagrees by 3.3% of
    # the diagonal with a confident radius; the miss was 55% with no radius.
    rf = D.detect(cv2.cvtColor(cv2.imread(photo_path, cv2.IMREAD_COLOR),
                               cv2.COLOR_BGR2GRAY))
    failures += not check("fixture detection survives the abstention gate",
                          bool(rf) and not rf.get("abstained"),
                          (rf or {}).get("abstain_reason", ""))

    print()
    if failures:
        print(f"{failures} check(s) failed")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
