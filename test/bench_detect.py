#!/usr/bin/env python3
"""Measure detection against corners a human placed.

Not a pass/fail suite and deliberately not in CI: it needs photographs, and
photographs are not in this repository. It is the thing to run when a detection
change needs judging, and the thing to run again afterwards.

The labels come from the fit store — every composite saved through the workbench
records its four corners keyed by the photograph's own decoded pixels, so a
directory of photographs plus a history of ordinary use IS the corpus. Nothing
has to be labelled twice.

    python3 test/bench_detect.py ~/photos
    python3 test/bench_detect.py ~/photos --json > before.json

What it separates, because these have opposite fixes and looked identical
before the trace existed (v0.27.0):

    recall   was the true screen ever PROPOSED?   nearest candidate to the label
    ranking  did the proposed one WIN?            returned quad vs the label
    gate     was a correct answer then refused?   abstained with a good quad

Errors are reported as a percentage of the screen's own width, not in pixels: a
30px error means something different on a 4000px photograph than on a 900px one,
and the thing being found is the screen.
"""
import argparse
import glob
import json
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import detect as D  # noqa: E402
import fits as FIT  # noqa: E402

EXTS = ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.heic")
# A fit is "good" when it is close enough to drag from in a few seconds, and
# "wrong" when it is not the screen at all. Nothing in between is claimed.
GOOD = 0.10
WRONG = 0.30


def worst(quad, ref):
    return float(np.max(np.linalg.norm(np.array(quad, float) - ref, axis=1)))


def measure(path):
    im = cv2.imread(path)
    if im is None:
        return None
    label = FIT.recall(FIT.key_for(im))
    if not label:
        return {"photo": os.path.basename(path), "labelled": False}
    ref = np.array(label["corners"], float)
    width = float(np.linalg.norm(ref[1] - ref[0])) or 1.0
    gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)

    cands = []
    res = D.detect(gray, color=im, trace=cands)
    clicked = D.detect(gray, color=im, click=tuple(ref.mean(axis=0)))
    best = min(cands, key=lambda c: worst(c["quad"], ref)) if cands else None

    return {
        "photo": os.path.basename(path), "labelled": True,
        "size": [int(im.shape[1]), int(im.shape[0])],
        "state": ("none" if res is None
                  else "abstained" if res.get("abstained") else "answered"),
        "method": None if res is None else res.get("method"),
        # The returned quad, including one kept only for inspection after an
        # abstention: "the gate refused a correct answer" is a real outcome and
        # it cannot be seen without this.
        "answer": None if res is None else worst(res["corners"], ref) / width,
        "recall": None if best is None else worst(best["quad"], ref) / width,
        "recall_from": None if best is None else f"{best['method']}/{best['verdict']}",
        "clicked": (None if (clicked is None or clicked.get("abstained"))
                    else worst(clicked["corners"], ref) / width),
        "candidates": len(cands),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photos", help="Directory of photographs")
    ap.add_argument("--json", action="store_true", help="Machine-readable, for diffing runs")
    args = ap.parse_args()

    files = sorted(sum((glob.glob(os.path.join(args.photos, e)) for e in EXTS), []))
    rows = [r for r in (measure(p) for p in files) if r]
    lab = [r for r in rows if r["labelled"]]

    if args.json:
        json.dump({"labelled": len(lab), "seen": len(rows), "rows": rows},
                  sys.stdout, indent=1)
        print()
        return 0

    if not lab:
        print(f"no labelled photographs in {args.photos}")
        print("Fit one in the workbench and save it — every save records its corners.")
        return 0

    pct = lambda v: "  —  " if v is None else f"{100 * v:4.0f}%"   # noqa: E731
    print(f"\n{'photo':24}{'unaided':>11}{'answer':>8}{'best cand':>11}"
          f"{'  from':18}{'w/ click':>9}")
    for r in lab:
        print(f"{r['photo'][:24]:24}{r['state']:>11}{pct(r['answer'])}{pct(r['recall'])}"
              f"  {str(r['recall_from'] or ''):16}{pct(r['clicked'])}")

    answered = [r for r in lab if r["state"] == "answered"]
    good = [r for r in answered if r["answer"] <= GOOD]
    conf_wrong = [r for r in answered if r["answer"] > WRONG]
    abst = [r for r in lab if r["state"] == "abstained"]
    refused = [r for r in abst if r["answer"] is not None and r["answer"] <= GOOD]
    no_recall = [r for r in lab if r["recall"] is not None and r["recall"] > WRONG]
    clicked_ok = [r for r in lab if r["clicked"] is not None and r["clicked"] <= GOOD]

    n = len(lab)
    print(f"\n{n} labelled photographs — error as a percentage of the screen's own width\n")
    print(f"  good unaided (<={GOOD:.0%})              {len(good)}/{n}")
    print(f"  CONFIDENTLY WRONG (>{WRONG:.0%})          {len(conf_wrong)}/{n}"
          "   <- the failure this tool refuses to have")
    print(f"  abstained                          {len(abst)}/{n}")
    print(f"    of those, a good quad refused     {len(refused)}"
          "   <- the gate costing you an answer")
    print(f"  never proposed at all (>{WRONG:.0%})       {len(no_recall)}/{n}"
          "   <- recall; ranking cannot reach these")
    print(f"  good with one click                {len(clicked_ok)}/{n}")
    if conf_wrong:
        print("\n  confidently wrong: "
              + ", ".join(f"{r['photo']} ({100 * r['answer']:.0f}%)" for r in conf_wrong))
    if no_recall:
        print("  never proposed:    "
              + ", ".join(f"{r['photo']} (closest {100 * r['recall']:.0f}%)"
                          for r in no_recall))
    unl = len(rows) - n
    if unl:
        print(f"\n  {unl} photograph(s) here have no saved fit and were skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
