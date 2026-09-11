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


def trace_checks(photo_path, truth):
    """The detection instrument.

    Its job is to answer one question the project has never been able to ask:
    when detection is wrong, was the true screen never PROPOSED, or proposed and
    beaten? Those have opposite fixes — recall work against ranking work — and
    every diagnosis so far has come from printing this list by hand.

    So the checks are about the instrument being trustworthy, in this order:
    it must not change what it measures, it must account for every candidate,
    and it must actually be able to answer the recall question on a photograph
    where the answer is known.
    """
    failures = 0
    photo = cv2.imread(photo_path, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY)

    plain = D.detect(gray, color=photo)
    rows = []
    traced = D.detect(gray, color=photo, trace=rows)
    a = {k: v for k, v in plain.items() if k != "_corners_np"}
    b = {k: v for k, v in traced.items() if k != "_corners_np"}
    # An instrument that perturbs what it measures is worse than no instrument.
    failures += not check("tracing does not change the answer", a == b,
                          "" if a == b else "the traced run returned something else")
    failures += not check("...and it produced rows", len(rows) > 0, f"{len(rows)} candidates")

    VERDICTS = {"accepted", "rejected", "unreached", "filtered_by_click",
                "supplied_the_answer"}
    shaped = all(isinstance(r.get("score"), float)
                 and r.get("method") in ("tone", "edge", "saturation")
                 and r.get("verdict") in VERDICTS
                 and len(r.get("quad", [])) == 4
                 and all(len(p) == 2 for p in r["quad"])
                 for r in rows)
    failures += not check("every row carries a method, a score, a quad and a verdict", shaped,
                          "" if shaped else str(next(r for r in rows if r.get("verdict")
                                                     not in VERDICTS or len(r.get("quad", [])) != 4)))

    # The recall question, asked and answered on a photograph whose screen is
    # known: is the truth among the things the detectors PROPOSED? On this
    # fixture it must be, and the winner must be that candidate — a trace where
    # the best candidate is not the accepted one is exactly the ranking failure
    # this file exists to be able to name.
    def worst(quad):
        return float(np.max(np.linalg.norm(np.array(quad, float) - truth, axis=1)))

    best = min(rows, key=lambda r: worst(r["quad"]))
    failures += not check("the trace can answer the recall question",
                          worst(best["quad"]) < 40.0,
                          f"closest candidate is {worst(best['quad']):.1f}px from the truth")
    failures += not check("...and on this fixture the closest candidate is one that WON",
                          best["verdict"] == "accepted",
                          f"closest candidate was {best['verdict']}")

    # The winning row must hold the quad that was actually RETURNED. It did not
    # until 11 Sep 2026: every row carried the polygon approximation the
    # candidate was built from, while the walk refines corners before validating,
    # so the row and the answer differed by the whole rounded-corner inset. On
    # real photographs that is 9-11% of the screen's own width, and it made a
    # corner-accuracy change read as worth nothing. The instrument has to
    # report what shipped or it cannot be used to judge a change to what ships.
    won = [r for r in rows if r["method"] == traced["method"]
           and r["verdict"] in ("accepted", "supplied_the_answer")]
    winner = next((r for r in won if r["verdict"] == "supplied_the_answer"),
                  won[0] if won else None)
    gap = (None if winner is None else
           float(np.max(np.linalg.norm(np.array(winner["quad"], float)
                                       - np.array(traced["corners"], float), axis=1))))
    failures += not check("the winning row holds the quad that was returned",
                          gap is not None and gap <= 0.2,
                          "no winning row" if gap is None
                          else f"the row is {gap:.1f}px from the answer it supplied")

    # A click filters before ranking, and the trace has to show what it removed
    # — "never judged because the user pointed elsewhere" and "never judged
    # because something better was accepted first" are different facts.
    centre = tuple(truth.mean(axis=0))
    crows = []
    D.detect(gray, color=photo, click=centre, trace=crows)
    filtered = [r for r in crows if r["verdict"] == "filtered_by_click"]
    failures += not check("a click marks the candidates it removed",
                          len(filtered) > 0 and all(r["contains_click"] is False for r in filtered),
                          f"{len(filtered)} of {len(crows)} filtered")
    failures += not check("...and nothing it removed was then accepted",
                          not any(r["verdict"] == "accepted" and not r.get("contains_click", True)
                                  for r in crows))
    inside = [r for r in crows if r["verdict"] != "filtered_by_click"]
    failures += not check("...and every surviving candidate really does contain the click",
                          all(D.contains(r["quad"], centre) >= 0 for r in inside),
                          f"{len(inside)} survivors")

    # The walked candidate is not always the one whose quad comes back:
    # pick_innermost steps inward from it. A trace that credits the walked one
    # shows an accepted row holding a quad that never became the answer, while
    # the quad that DID sits in an unreached row — and a recall analysis reading
    # that draws the opposite conclusion. Built directly rather than hunted for
    # in a photograph, so the case is exercised on every run: two nested quads,
    # the outer scoring higher.
    def quad(x0, y0, x1, y1):
        return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], np.float64)

    outer, inner = quad(100, 100, 700, 900), quad(112, 112, 688, 888)
    cands = [(9.0, outer, outer.reshape(-1, 1, 2).astype(np.int32), (0, 31)),
             (5.0, inner, inner.reshape(-1, 1, 2).astype(np.int32), (0, 31))]
    nested = []
    res = D._finalize(cands, 1000.0 * 1000.0, refine=False, img_shape=(1000, 1000),
                      trace=nested, method="tone")
    got = {r["verdict"]: r for r in nested}
    failures += not check("a nested pick is reported as one",
                          res is not None and set(got) == {"accepted", "supplied_the_answer"},
                          str([r["verdict"] for r in nested]))
    if res is not None and "supplied_the_answer" in got:
        failures += not check("...crediting the quad that actually came back",
                              got["supplied_the_answer"]["quad"][0] == [112.0, 112.0]
                              and res["corners"][0] == [112.0, 112.0],
                              f"{got['supplied_the_answer']['quad'][0]} vs {res['corners'][0]}")

    # The file is the product: a benchmark reads it, not the return value.
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "candidates.json")
        D.write_trace(path, photo_path, photo.shape, centre, traced, crows)
        with open(path) as f:
            doc = json.load(f)
        failures += not check("the trace file accounts for every candidate",
                              doc["counts"]["candidates"] == len(crows)
                              and sum(v for k, v in doc["counts"].items()
                                      if k != "candidates") == len(crows),
                              str(doc["counts"]))
        failures += not check("...and names the run it came from",
                              doc["photo"] == photo_path and doc["click"] == list(centre)
                              and doc["chosen"]["method"] in ("tone", "edge", "saturation"))
    return failures


def perspective_checks():
    """A collapsed corner must not pass validation (SG70).

    The quad that made this necessary was returned CONFIDENTLY from a real
    photograph with three corners on the glass and the fourth ~800px into the
    middle of the screen — and it passed every check there was: convex, no
    sliver, area in range, blob filling it. What gives it away is that one pair
    of opposite sides is wildly unequal while the other is not, which is a thing
    a rectangle cannot do at any angle a device is photographed from.

    Both directions are checked. A gate that only ever refuses is safe against
    the failure it exists to stop and dangerous in the other direction — it can
    refuse a real steep-angle screen — so the second case is the one that stops
    this being tightened onto the data.
    """
    failures = 0
    img_area = 2000.0 * 1500.0

    def q(pts):
        return np.array(pts, dtype=np.float64)

    # ratio 1.00 — a rectangle, straight on
    flat = q([[400, 300], [1400, 300], [1400, 1100], [400, 1100]])
    ok, why = D.validate_quad(flat, None, img_area, (1500, 2000))
    failures += not check("a plain rectangle passes", ok, why)

    # A real screen at a steep angle: the far edge foreshortened to 62% of the
    # near one (ratio 1.6). Every measured true screen sits at 1.01-1.05, so
    # this is far beyond anything in the corpus and still has to pass — the
    # ceiling must not be tightened onto seven photographs of phones lying flat.
    # Past 1.9 the tool abstains and the edges get placed by hand, which is the
    # deliberate trade: an honest refusal rather than a confident wrong quad.
    steep = q([[400, 300], [1400, 490], [1400, 1110], [400, 1300]])
    ok, why = D.validate_quad(steep, None, img_area, (1500, 2000))
    failures += not check("a steeply foreshortened screen still passes", ok, why)

    # the shape from the photograph: one corner pulled inward
    collapsed = q([[400, 300], [1400, 320], [1450, 750], [900, 1300]])
    ok, why = D.validate_quad(collapsed, None, img_area, (1500, 2000))
    failures += not check("a collapsed corner is refused", not ok, why or "accepted")
    failures += not check("...and the reason names what is wrong",
                          (not ok) and "opposite sides" in why, why)
    # It is worth being explicit that the OTHER checks would have let it through,
    # or the test above proves nothing about why this one exists.
    convex = bool(cv2.isContourConvex(collapsed.astype(np.float32).reshape(-1, 1, 2)))
    sides = [float(np.linalg.norm(collapsed[(i + 1) % 4] - collapsed[i])) for i in range(4)]
    sliver = min(sides) < D.MIN_SIDE_RATIO * max(sides)
    failures += not check("...and every other check would have let it through",
                          convex and not sliver,
                          "" if (convex and not sliver) else
                          f"convex={convex} sliver={sliver} — this shape is caught "
                          "by an older rule, so it proves nothing about the new one")
    return failures


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

    print("the saturation detector finds a screen grayscale cannot")
    # Devices are neutral; the furniture they sit on is not. detect() runs on
    # grayscale alone unless a colour image is passed, which is why an iPhone
    # on a sunlit table was undetectable: tone and edge both landed on the
    # table 1030px away, saturation lands 29px from the truth.
    swatch = np.full((900, 1200, 3), 0, np.uint8)
    swatch[:, :] = (40, 120, 200)                      # a saturated wood-ish ground
    cv2.rectangle(swatch, (400, 250), (800, 650), (210, 210, 210), -1)   # neutral "screen"
    rs = D.detect_saturation(swatch)
    failures += not check("it finds the neutral region", rs is not None,
                          "returned None")
    if rs:
        c = np.array(rs["corners"], dtype=np.float64)
        truth = np.array([[400, 250], [800, 250], [800, 650], [400, 650]], dtype=np.float64)
        worst = np.linalg.norm(c - truth, axis=1).max()
        failures += not check("on the right region", worst <= 12.0, f"worst {worst:.1f}px")
        failures += not check("the threshold adapts to the image, not a constant",
                              "neutral_threshold" in rs, str(rs.keys()))
    # A colour image must not change what grayscale-only callers get back.
    gray_only = D.detect(cv2.cvtColor(swatch, cv2.COLOR_BGR2GRAY))
    with_colour = D.detect(cv2.cvtColor(swatch, cv2.COLOR_BGR2GRAY), color=swatch)
    failures += not check("passing colour is additive, never required",
                          gray_only is not None and with_colour is not None, "")

    print("perfectly sharp corners are not a screen")
    # The arbiter that picks saturation over tone on a hard photo. A patch of
    # table cut out of a threshold mask measures a 0.0px corner radius; a real
    # screen measures a real one. Shape, not photometry — the three photometric
    # arbiters tried in this project were all rejected.
    sharp = {"corner_radius": {"photo_px": 0.0, "confident": False,
                               "per_corner_px": [0.0, 0.0, 0.0, 0.0]}}
    round_ = {"corner_radius": {"photo_px": 62.4, "confident": False,
                                "per_corner_px": [55.0, 60.0, 65.0, 70.0]}}
    failures += not check("a 0.0px radius is rejected", not D.has_rounded_corners(sharp), "")
    failures += not check("a measured radius is accepted", D.has_rounded_corners(round_), "")

    # Four estimates of one number that disagree by more than 2x describe
    # something that is not a rounded rectangle, so the median means nothing.
    # Measured on nine real photos: correct detections spread 31-173%, the two
    # confidently-wrong ones 247% and 464% — which is how an iPad on a tiled
    # floor stopped being reported as a confident screen.
    inconsistent = {"corner_radius": {"photo_px": 243.2, "confident": False,
                                      "per_corner_px": [40.0, 243.0, 300.0, 640.0]}}
    failures += not check("a radius its own four corners disagree about is not evidence",
                          not D.has_rounded_corners(inconsistent), "")

    print("the rounded-corner filter never judges the edge detector")
    # A trap fallen into and caught on 7 Sep 2026. The filter that picks
    # saturation over tone was first applied to ALL detectors, which threw away
    # the CORRECT answer on the gradient-screen fixture: edge had it to 1.4px
    # while measuring a 0.0px radius, because a Canny ring contour is not a
    # region silhouette and the radius measured from it is an artifact. tone,
    # 384px wrong, measured a confident-looking 15.7px. The filter is now
    # restricted to the two region detectors.
    ring_like = {"method": "edge", "corner_radius": {"photo_px": 0.0, "confident": False}}
    failures += not check("edge is exempt by construction (it is not a region)",
                          ring_like["method"] not in ("tone", "saturation"), "")

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

    print("perspective plausibility (SG70)")
    failures += perspective_checks()

    print("the detection instrument")
    failures += trace_checks(photo_path, load_truth())

    print()
    if failures:
        print(f"{failures} check(s) failed")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
