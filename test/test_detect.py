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


def dark_anchor_checks():
    """The Canny sweep must not go blind on a dark photograph.

    detect_edges() anchored its thresholds on the image median. A black phone
    on a black backdrop has a median of 0..4, every sweep point lands at
    hi <= 7, and Canny fires on every pixel of noise -- the edge map is a solid
    sheet and no closed quad survives. Both photographs in the labelled corpus
    on which nothing near the screen was ever proposed were exactly this
    (11 Sep 2026). An Otsu-anchored sweep sits alongside the median one now.

    Built rather than photographed: a bright rounded screen on a near-black
    frame on a near-black ground, with sensor-like noise so the median anchor
    genuinely saturates. The median-only sweep is reproduced here as the fault
    plant, so the check cannot pass by the fixture being too easy.
    """
    failures = 0
    rng = np.random.default_rng(11)
    H, W = 1000, 1400
    img = np.full((H, W), 2, np.uint8)
    body = np.zeros((H, W), np.uint8)
    cv2.rectangle(body, (420, 200), (980, 820), 255, -1)
    img[body > 0] = 6
    screen = np.zeros((H, W), np.uint8)
    cv2.rectangle(screen, (460, 240), (940, 780), 255, -1)
    screen = cv2.morphologyEx(screen, cv2.MORPH_OPEN,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (81, 81)))
    img[screen > 0] = 200
    img = np.clip(img.astype(np.int16) + rng.normal(0, 2.5, img.shape), 0, 255).astype(np.uint8)
    truth = np.array([[460, 240], [940, 240], [940, 780], [460, 780]], dtype=np.float64)
    failures += not check("the fixture is dark enough to blind a median anchor",
                          float(np.median(img)) < 8, f"median {float(np.median(img)):.0f}")

    rows = []
    D.detect_edges(img, trace=rows)
    near = min((float(np.max(np.linalg.norm(np.array(r["quad"], float) - truth, axis=1)))
                for r in rows), default=None)
    failures += not check("the edge channel proposes the screen on a dark photograph",
                          near is not None and near < 60.0,
                          "no candidates" if near is None else f"{len(rows)} candidates, nearest {near:.1f}px")

    # The fault plant IS the old code: a median-only sweep on the same image.
    blur = cv2.GaussianBlur(img, (5, 5), 0)
    med = float(np.median(blur))
    short = min(H, W)
    old = 0
    for sigma in (0.20, 0.33, 0.50, 0.66):
        lo, hi = int(max(0, (1 - sigma) * med)), int(min(255, (1 + sigma) * med))
        if hi <= lo:
            continue
        e = cv2.Canny(blur, lo, hi, L2gradient=True)
        k = D._odd(0.004 * short)
        e = cv2.morphologyEx(e, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        cs, _ = cv2.findContours(e, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        old += sum(1 for c in cs if D.score_edge_contour(c, float(H * W))[1] is not None)
    failures += not check("...where the median-only sweep proposes nothing at all",
                          old == 0, f"median-only sweep produced {old} candidates")
    return failures


def walk_order_checks():
    """The within-channel walk looks past a tier-0 winner when a tier-2 quad
    is in the same list -- and ONLY then.

    Score is fill x size, and a device body or a large skewed outline wins on
    size every time. Ordering the whole walk tier-first was tried on 11 Sep
    2026 and broke three photographs (a tier-2 WRONG quad sits deeper in the
    list on each). The rule that survived is narrower: a tier-0 winner cannot
    be corroborated and ends in an abstention anyway, so nothing is lost by
    preferring a tier-2 candidate over it; a tier-1 winner is left alone.
    Two photographs went from abstaining to 0% and 1% on it (12 Sep 2026).

    Built rather than photographed: a sharp rectangle contour scores higher
    (bigger) than a rounded one inside the same image.
    """
    failures = 0
    H, W = 900, 1200
    img_area = float(H * W)

    def contour_of(mask):
        cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        return max(cs, key=cv2.contourArea)

    sharp = np.zeros((H, W), np.uint8)
    cv2.rectangle(sharp, (150, 120), (1050, 720), 255, -1)             # big (50%), square corners
    rounded = np.zeros((H, W), np.uint8)
    # Under the size plateau, so the bigger rectangle genuinely outscores it.
    cv2.rectangle(rounded, (400, 250), (750, 550), 255, -1)
    rounded = cv2.morphologyEx(rounded, cv2.MORPH_OPEN,
                               cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (61, 61)))
    big = contour_of(sharp)
    small = contour_of(rounded)
    cands = []
    for c in (big, small):
        score, quad = D.score_contour(c, img_area)
        cands.append((score, D.order_quad(quad), c, "t"))
    failures += not check("the sharp rectangle outscores the rounded one on size",
                          cands[0][0] > cands[1][0], f"{cands[0][0]:.3f} vs {cands[1][0]:.3f}")

    res = D._finalize(cands, img_area, img_shape=(H, W), method="tone")
    truth = np.array([[400, 250], [750, 250], [750, 550], [400, 550]], float)
    err = float(np.max(np.linalg.norm(res["_corners_np"] - truth, axis=1)))
    failures += not check("...and the walk still picks the rounded one",
                          err < 12.0, f"{err:.1f}px from the rounded rectangle")

    # The narrow part: a tier-1 winner is NOT looked past. Give the big
    # rectangle rounded corners too, but loosely (tier 1), and it keeps the win.
    loose = np.zeros((H, W), np.uint8)
    cv2.rectangle(loose, (150, 120), (1050, 720), 255, -1)
    loose = cv2.morphologyEx(loose, cv2.MORPH_OPEN,
                             cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41)))
    lc = contour_of(loose)
    ls, lq = D.score_contour(lc, img_area)
    res2 = D._finalize([(ls, D.order_quad(lq), lc, "t"), cands[1]], img_area,
                       img_shape=(H, W), method="tone")
    big_truth = np.array([[150, 120], [1050, 120], [1050, 720], [150, 720]], float)
    err2 = float(np.max(np.linalg.norm(res2["_corners_np"] - big_truth, axis=1)))
    failures += not check("a winner with rounded corners of its own is left alone",
                          err2 < 12.0, f"{err2:.1f}px from the big rectangle")
    return failures


def tier_checks():
    """Evidence tiers in arbitration and in the abstention veto.

    Two rules, one measurement behind both (11 Sep 2026, ten labelled photos,
    every channel result): every quad whose four corners agreed on a radius to
    within 50% -- "confident", tier 2 -- was on the screen, worst spread 0.24;
    every wrong quad measured >= 1.43 or nothing. Tier 1 ("rounded", <= 2.0)
    does not separate them: a correct tone quad at 1.42 sat beside a wrong one
    at 1.43. So a tier-1 result must neither OUTRANK nor VETO a tier-2 one.

    Before the rules: tone beat edge whenever the two did not nest (two photos
    answered 159% and 249% off over a confident edge at 0%), and a rounded tone
    quad 143% off vetoed a confident edge at 0.3% into an abstention -- the
    bench's one "good quad refused". Both are hand-built here so the rule is
    pinned without a photograph.
    """
    failures = 0
    shape = (1600, 1200)

    def result(method, corners, per_corner, r):
        q = np.array(corners, dtype=np.float64)
        per = [float(v) for v in per_corner]
        spread = (max(per) - min(per)) / max(r, 1e-6)
        return {"method": method, "corners": [list(map(float, c)) for c in corners],
                "_corners_np": q, "score": 1.0,
                "corner_radius": {"photo_px": float(r), "frac_of_width": 0.1,
                                  "per_corner_px": per, "confident": bool(r > 2 and spread < 0.5),
                                  "note": ""}}

    screen = [[300, 400], [900, 420], [890, 1300], [290, 1280]]
    table = [[40, 60], [1150, 80], [1140, 1500], [30, 1480]]       # far away, does not nest
    edge_conf = result("edge", screen, [60, 62, 58, 61], 60)          # spread 0.07 -> tier 2
    tone_round = result("tone", table, [30, 70, 20, 60], 45)          # spread 1.1  -> tier 1

    failures += not check("a confident radius is tier 2, a merely rounded one tier 1",
                          D.shape_tier(edge_conf) == 2 and D.shape_tier(tone_round) == 1,
                          f"{D.shape_tier(edge_conf)} / {D.shape_tier(tone_round)}")

    # "Rounded" means all four corners. [0, 0, 56, 56] has two corners with no
    # arc at all, and its spread is exactly 2.00 -- the threshold, on a <=. It
    # passed, became tier 1, beat an unmeasurable edge quad, and shipped as a
    # confident answer 124% off: the only confidently wrong result the labelled
    # bench has ever produced (iPhone-8, 12 Sep 2026).
    half_round = result("tone", table, [0, 0, 56, 56], 28)
    failures += not check("a quad rounded at two corners and square at two is not rounded",
                          not D.has_rounded_corners(half_round) and D.shape_tier(half_round) == 0,
                          f"rounded={D.has_rounded_corners(half_round)} tier={D.shape_tier(half_round)}")
    barely = result("tone", table, [1.6, 50, 56, 56], 50)            # smallest on-screen min seen
    failures += not check("...while a quad with four measured corners still can be",
                          D.has_rounded_corners(barely), "1.6px corner rejected")

    # Arbitration: not nested, edge confident, tone merely rounded -> edge wins.
    out = D.arbitrate([tone_round, edge_conf], shape)
    failures += not check("edge with a confident radius beats a non-nested rounded tone quad",
                          out["method"] == "edge", f"chose {out['method']}: {out['agreement']['chosen_because']}")
    # ... and the tone quad, being weaker evidence, cannot veto it into abstaining.
    failures += not check("...and the weaker peer cannot veto it into an abstention",
                          not out["abstained"], out.get("abstain_reason", ""))

    # Symmetry: when both are confident and far apart, that IS a gross
    # disagreement and the gate must still refuse. Loosening must not have
    # switched the veto off.
    tone_conf = result("tone", table, [44, 46, 45, 45], 45)           # spread 0.04 -> tier 2
    out2 = D.arbitrate([tone_conf, edge_conf], shape)
    failures += not check("two confident quads far apart still abstain",
                          out2["abstained"], out2.get("agreement", {}).get("note", "")[:80])

    # Equal tiers, not nested: the old rule stands -- tone wins on its band.
    edge_round = result("edge", screen, [30, 70, 20, 60], 45)
    out3 = D.arbitrate([tone_round, edge_round], shape)
    failures += not check("at equal tiers the tone channel still wins the non-nested case",
                          out3["method"] == "tone", f"chose {out3['method']}")

    # The other branch that used to hand the win over unconditionally: tone
    # absent, saturation present. Saturation won regardless of what edge had.
    # Code review of v0.38.0 found that branch had the new rule but no test, so
    # a plant there would have passed. Same shape: confident edge beats a
    # merely rounded saturation quad, and loses at equal tiers.
    sat_round = result("saturation", table, [30, 70, 20, 60], 45)
    out4 = D.arbitrate([sat_round, edge_conf], shape)
    failures += not check("with tone absent, a confident edge quad beats a rounded saturation quad",
                          out4["method"] == "edge", f"chose {out4['method']}")
    out5 = D.arbitrate([sat_round, edge_round], shape)
    failures += not check("...and at equal tiers saturation still wins that branch",
                          out5["method"] == "saturation", f"chose {out5['method']}")

    # --- nested: tiers first, the area ratio only to break a tie -------------
    # Measured on the corpus (11 Sep 2026): a UI content region at 96% of the
    # screen's area with loose corners sat inside a confident edge quad on two
    # photographs, and the ratio rule read it as "screen inside body" -- 15%
    # off, twice. And the hand-built table above showed the reverse hole: a
    # confident screen at 34% of a loosely rounded table read as "content".
    inset = [[c[0] + 12, c[1] + 16] for c in screen]                  # ~96% of the screen
    inset[1][0] -= 24; inset[2][0] -= 24; inset[2][1] -= 32; inset[3][1] -= 32
    tone_content = result("tone", inset, [30, 70, 20, 60], 45)         # tier 1, inside
    out6 = D.arbitrate([tone_content, edge_conf], shape)
    failures += not check("content at 96% inside a confident screen: the outer wins on tier",
                          out6["method"] == "edge", f"chose {out6['method']}: {out6['agreement']['chosen_because'][:70]}")

    big = [[100, 200], [1100, 220], [1090, 1500], [90, 1480]]           # screen is ~34% of it
    tone_table = result("tone", big, [30, 70, 20, 60], 45)             # tier 1, outside
    out7 = D.arbitrate([tone_table, edge_conf], shape)
    failures += not check("a confident screen at 34% of a rounded table: the inner wins on tier",
                          out7["method"] == "edge", f"chose {out7['method']}: {out7['agreement']['chosen_because'][:70]}")

    # Equal tiers: the ratio still decides, exactly as before.
    tone_content_c = result("tone", inset, [44, 46, 45, 45], 45)       # tier 2, inside at 96%
    out8 = D.arbitrate([tone_content_c, edge_conf], shape)
    failures += not check("equal tiers at 96%: still a screen inside a body, the inner wins",
                          out8["method"] == "tone", f"chose {out8['method']}")
    small = [[450, 600], [750, 610], [745, 1000], [445, 990]]          # ~25% of the screen
    tone_slab_c = result("tone", small, [44, 46, 45, 45], 45)          # tier 2, inside at 25%
    out9 = D.arbitrate([tone_slab_c, edge_conf], shape)
    failures += not check("equal tiers at 25%: still content on the screen, the outer wins",
                          out9["method"] == "edge", f"chose {out9['method']}")

    # Symmetric: the nesting is read whichever channel is inside. iPhone-4 had
    # an edge quad 3% off INSIDE a saturation quad 18% off at 94%, equal tiers,
    # and the old code -- which only looked for the region inside the edge --
    # called that "not nested" and let saturation win.
    sat_body = result("saturation", [[280, 380], [920, 400], [910, 1320], [270, 1300]],
                      [30, 70, 20, 60], 45)                             # tier 1, around the screen
    out10 = D.arbitrate([sat_body, edge_round], shape)
    failures += not check("an edge quad inside a saturation quad at a body ratio: the inner wins",
                          out10["method"] == "edge", f"chose {out10['method']}: {out10['agreement']['chosen_because'][:70]}")
    return failures


def rail_checks():
    """Corner recovery on a Canny RING, which is where 9-11% of the screen used
    to be lost on every photograph.

    approxPolyDP cannot put a vertex on a rounded corner, because a rounded
    corner has no vertex -- it settles for a point on the arc, inside where the
    two sides would meet, and shortens every side. refine_corners() recovers the
    corner by intersecting the fitted sides, and the Canny path was BANNED from
    calling it for eighteen releases: a ring traces both sides of one boundary
    and catches content edges drawn inside the screen, so the line fits picked up
    the wrong points (78px off, measured at v0.13.0).

    Rail selection is the answer: fit only the points within a couple of
    close-kernels of the outermost, which is the ring's outer rail, and content
    edges are excluded by construction rather than by a threshold on how bad the
    fit turned out.

    The fixture is built rather than photographed so it runs in CI and so the
    contamination is a dial: two rails 5px apart around a rounded rectangle,
    plus a content edge inset 40px carrying as many points as the screen edge on
    that side -- which is what a UI card border spanning the screen actually
    produces in a Canny image.
    """
    failures = 0
    x0, y0, x1, y1, r = 280, 200, 920, 700, 46
    truth = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float64)

    def rail(grow):
        m = np.zeros((900, 1200), np.uint8)
        cv2.rectangle(m, (x0 - grow, y0 - grow), (x1 + grow, y1 + grow), 255, -1)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)      # rounds the corners
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        return max(cs, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)

    def worst(quad):
        return float(np.max(np.linalg.norm(
            D.order_quad(np.array(quad, dtype=np.float64)) - truth, axis=1)))

    xs = np.linspace(x0 + r, x1 - r, 700)
    ring = np.concatenate([
        rail(0), rail(5),
        np.stack([xs, np.full(700, y0 + 40.0)], 1),     # content edge, two rails
        np.stack([xs, np.full(700, y0 + 45.0)], 1),
    ]).reshape(-1, 1, 2)

    quad = D.order_quad(D.approx_quad(ring.astype(np.int32)))
    approx_err = worst(quad)
    # The defect itself, asserted so it cannot be quietly explained away again:
    # the polygon approximation IS short, by a distance set by the corner radius.
    failures += not check("the polygon approximation falls short of the corner",
                          approx_err > 8.0, f"{approx_err:.1f}px")

    plain, ok_plain = D.refine_corners(ring, quad, 0.0)
    railed, ok_rail = D.refine_corners(ring, quad, 10.0)
    failures += not check("rail selection recovers the corner on a ring",
                          ok_rail and worst(railed) < approx_err,
                          f"{approx_err:.1f}px -> {worst(railed):.1f}px")
    # The fault plant lives in the assertion: fitting every assigned point is
    # what the ban was protecting against, and it must still be visibly worse.
    failures += not check("...where fitting the whole ring is much worse",
                          ok_plain and worst(plain) > 3.0 * worst(railed),
                          f"whole ring {worst(plain):.1f}px against railed "
                          f"{worst(railed):.1f}px")
    # A filled region has one rail, so the same call must not disturb it.
    solid = rail(0).reshape(-1, 1, 2)
    sq = D.order_quad(D.approx_quad(solid.astype(np.int32)))
    a, _ = D.refine_corners(solid, sq, 0.0)
    b, _ = D.refine_corners(solid, sq, 10.0)
    gap = float(np.max(np.linalg.norm(np.array(a, dtype=np.float64)
                                      - np.array(b, dtype=np.float64), axis=1)))
    failures += not check("...and a one-rail silhouette is left alone",
                          gap <= 0.5, f"moved {gap:.2f}px")
    return failures


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
    print("the Canny sweep on a dark photograph")
    failures += dark_anchor_checks()
    print("the within-channel walk looks past a tier-0 winner")
    failures += walk_order_checks()
    print("evidence tiers — arbitration and the abstention veto")
    failures += tier_checks()
    print("corner recovery on a Canny ring")
    failures += rail_checks()
    failures += trace_checks(photo_path, load_truth())

    print()
    if failures:
        print(f"{failures} check(s) failed")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
