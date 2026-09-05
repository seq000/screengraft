#!/usr/bin/env python3
"""
screengraft — recent images a designer is likely to want.

Scans ~/Desktop and ~/Downloads (the two places people actually save to) for
image files modified in the last N days, newest first, and prints JSON. The
UI shows these as pick-one thumbnails so nobody has to type a path.

  python3 scripts/scan.py [--days 14] [--limit 40] [--thumbs DIR]

HEIC (iPhone photos) is converted to JPEG for the thumbnail via `sips` on
macOS; OpenCV can't read HEIC. Run every time the skill starts — new photos
appear between sessions.
"""
import argparse
import json
import os
import subprocess
import sys
import time

EXTS = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".tif", ".tiff"}
FOLDERS = ["~/Desktop", "~/Downloads"]


def scan(days: int, limit: int):
    cutoff = time.time() - days * 86400
    items = []
    for f in FOLDERS:
        d = os.path.expanduser(f)
        if not os.path.isdir(d):
            continue
        try:
            names = os.listdir(d)
        except PermissionError:
            continue
        for n in names:
            if n.startswith("."):
                continue
            p = os.path.join(d, n)
            ext = os.path.splitext(n)[1].lower()
            if ext not in EXTS or not os.path.isfile(p):
                continue
            st = os.stat(p)
            if st.st_mtime < cutoff:
                continue
            items.append({"path": p, "name": n, "folder": f, "mtime": st.st_mtime, "bytes": st.st_size, "ext": ext})
    items.sort(key=lambda x: -x["mtime"])
    return items[:limit]


def thumb(item, out_dir: str, size: int = 320):
    """Write a small JPEG thumbnail; returns its path or None."""
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(item["name"])[0]
    out = os.path.join(out_dir, f"{abs(hash(item['path']))}_{base[:40]}.jpg")
    if os.path.exists(out):
        return out
    if sys.platform == "darwin":
        # sips handles HEIC and everything else natively; no OpenCV needed here.
        r = subprocess.run(["sips", "-s", "format", "jpeg", "-Z", str(size), item["path"], "--out", out],
                           capture_output=True, text=True)
        return out if r.returncode == 0 and os.path.exists(out) else None
    try:
        import cv2
        im = cv2.imread(item["path"])
        if im is None:
            return None
        h, w = im.shape[:2]
        s = size / max(h, w)
        im = cv2.resize(im, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
        cv2.imwrite(out, im, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return out
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--thumbs", help="Directory to write thumbnails into (optional)")
    args = ap.parse_args()
    items = scan(args.days, args.limit)
    if args.thumbs:
        for it in items:
            it["thumb"] = thumb(it, args.thumbs)
    print(json.dumps({"folders": FOLDERS, "days": args.days, "count": len(items), "items": items}, indent=1))


if __name__ == "__main__":
    main()
