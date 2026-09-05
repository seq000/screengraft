#!/usr/bin/env python3
"""
Generates synthetic test fixtures for warp.py when no real photo/screenshot
are available yet: a "device photo" with a known, hand-authored screen quad
(so the warp can be verified against ground truth) and a sample UI
screenshot with fine detail (thin text-like strokes, a grid) so blur from
double-resampling would be visible.

Not part of the shipped plugin. The fixtures are synthetic on purpose: the
quad below is the ground truth, so detector accuracy is measurable rather
than eyeballed. Run: python3 make_fixtures.py
"""
import json
import os

import cv2
import numpy as np

OUT_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
os.makedirs(OUT_DIR, exist_ok=True)

# --- Ground-truth screen quad in the synthetic photo, TL,TR,BR,BL ---
QUAD = [[520, 150], [1200, 230], [1150, 1050], [480, 970]]


def make_photo():
    w, h = 1600, 1200
    img = np.zeros((h, w, 3), dtype=np.uint8)
    # desk background: a soft vertical gradient, wood-ish tone
    for y in range(h):
        t = y / h
        color = (
            int(60 + 40 * t),   # B
            int(90 + 50 * t),   # G
            int(120 + 60 * t),  # R
        )
        img[y, :, :] = color
    # phone body: bezel = quad expanded outward by a fixed margin, dark
    quad = np.array(QUAD, dtype=np.float32)
    center = quad.mean(axis=0)
    bezel = center + (quad - center) * 1.12
    cv2.fillConvexPoly(img, bezel.astype(np.int32), (18, 18, 20))
    # screen-off placeholder: near-black fill in the exact quad, so an
    # unwarped run is visibly obviously wrong (pure black rectangle)
    cv2.fillConvexPoly(img, quad.astype(np.int32), (8, 8, 10))
    # a soft specular highlight streak across the bezel, cosmetic only
    cv2.line(img, tuple(bezel[0].astype(int)), tuple(bezel[2].astype(int)), (70, 70, 75), 2, cv2.LINE_AA)
    path = os.path.join(OUT_DIR, "photo.png")
    cv2.imwrite(path, img, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    return path


def make_screenshot():
    w, h = 1080, 2280  # phone-ish UI resolution
    img = np.full((h, w, 3), (245, 244, 240), dtype=np.uint8)  # light BG (BGR)
    # header bar
    cv2.rectangle(img, (0, 0), (w, 180), (60, 40, 210), -1)  # BGR -> reddish header
    # thin 1px grid lines across the body — the sharpest test of double-resampling blur
    for x in range(0, w, 40):
        cv2.line(img, (x, 220), (x, h - 40), (210, 210, 205), 1, cv2.LINE_AA)
    for y in range(220, h - 40, 40):
        cv2.line(img, (0, y), (w, y), (210, 210, 205), 1, cv2.LINE_AA)
    # a few "cards" with thin borders and fine "text" strokes
    for i, cy in enumerate(range(320, h - 200, 260)):
        cv2.rectangle(img, (60, cy), (w - 60, cy + 200), (255, 255, 255), -1)
        cv2.rectangle(img, (60, cy), (w - 60, cy + 200), (200, 200, 195), 2, cv2.LINE_AA)
        # fake text lines: thin 2px strokes
        for j in range(4):
            ty = cy + 40 + j * 30
            cv2.line(img, (100, ty), (100 + 500 - j * 60, ty), (90, 80, 70), 2, cv2.LINE_AA)
    # bottom nav
    cv2.rectangle(img, (0, h - 140), (w, h), (235, 232, 225), -1)
    cv2.line(img, (0, h - 140), (w, h - 140), (200, 200, 195), 2, cv2.LINE_AA)
    for i in range(4):
        cx = w // 8 + i * (w // 4)
        cv2.circle(img, (cx, h - 70), 24, (60, 40, 210), -1, cv2.LINE_AA)
    path = os.path.join(OUT_DIR, "screenshot.png")
    cv2.imwrite(path, img, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    return path


if __name__ == "__main__":
    photo = make_photo()
    shot = make_screenshot()
    # Basenames, not absolute paths: this file is committed, and an absolute
    # path here would publish whoever generated it. Nothing reads these
    # fields — the fixtures are found relative to this directory.
    meta = {
        "photo": os.path.basename(photo),
        "screenshot": os.path.basename(shot),
        "ground_truth_quad_TL_TR_BR_BL": QUAD,
    }
    meta_path = os.path.join(OUT_DIR, "meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(json.dumps(meta, indent=2))
