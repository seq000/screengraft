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
import os
import subprocess
import sys

import cv2
import numpy as np

import grade as _grade   # M2: the realism pass


MASK_SS = 4   # destination-space supersampling for the screen's edge

# How much of the device's own glass shows through under an emissive screen.
# Measured 9 Sep 2026 on an automotive render whose UI is 56% true black: at 0
# the screen is a hole, by 25% it sits in the scene, 50% reads clearly as glass,
# and past 75% the content loses contrast. 0.35 is the middle of the usable band.
DEFAULT_REFLECTION = 0.35


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


class Plan:
    """Everything about a fit that does NOT change from frame to frame.

    Built once for a still, once per clip for a video. The split exists so the
    two paths cannot drift: `compose()` is a Plan plus one frame, and
    `compose_video()` is the same Plan plus N frames, which makes "frame 0 of a
    render equals the still composite, byte for byte" a property the tests can
    assert rather than a thing we hope stays true.

    What lives here is what a fixed photo and a fixed quad make constant:

      - the prefilter's target size (the screenshot/frame is always the same
        size, and the quad never moves, so the minification factor is fixed);
      - the homography, which is derived from that rescaled size;
      - the rounded source mask;
      - the warped, antialiased destination mask, which is by far the most
        expensive thing in compose() because it supersamples MASK_SS x over the
        quad's bbox. Computing it once is most of the speed of a video render,
        and it also means the screen's EDGE is pixel-identical in every frame,
        so there is no edge crawl — the artefact that makes a composite read as
        fake. A fixed photo is the one case where that comes for free;
      - the grain sigma, measured from the photo, which does not change either.

    The grade parameters are deliberately NOT built here: they need a frame to
    measure against, so `bind_grade()` takes the fit frame and stores them.
    """

    def __init__(self, photo: np.ndarray, frame_shape, corners,
                 corner_radius: float = 0.0, grain: bool = False,
                 blend: str = "replace", reflection: float = DEFAULT_REFLECTION):
        dst_quad = np.array(corners, dtype=np.float32)
        if shoelace_area(dst_quad) < 1.0:
            raise ValueError("degenerate quad (near-zero area) — check corner order TL,TR,BR,BL")
        self.photo = photo
        self.dst_quad = dst_quad
        self.grain = grain
        self.blend = blend if blend in ("replace", "emissive") else "replace"
        self.reflection = float(np.clip(reflection, 0.0, 1.0))

        top = float(np.linalg.norm(dst_quad[1] - dst_quad[0]))
        bottom = float(np.linalg.norm(dst_quad[2] - dst_quad[3]))
        left = float(np.linalg.norm(dst_quad[3] - dst_quad[0]))
        right = float(np.linalg.norm(dst_quad[2] - dst_quad[1]))
        need_w, need_h = max(top, bottom), max(left, right)
        sh0, sw0 = frame_shape[:2]
        scale_x, scale_y = need_w / sw0, need_h / sh0
        self.prescale = max(scale_x, scale_y)
        if 0 < self.prescale < 0.95:
            self.new_w = max(1, int(round(sw0 * self.prescale)))
            self.new_h = max(1, int(round(sh0 * self.prescale)))
            self.radius = corner_radius * (self.new_w / sw0)
        else:
            self.new_w, self.new_h = sw0, sh0
            self.radius = corner_radius
            self.prescale = 1.0

        src_rect = np.array([[0, 0], [self.new_w, 0],
                             [self.new_w, self.new_h], [0, self.new_h]], dtype=np.float32)
        self.H = cv2.getPerspectiveTransform(src_rect, dst_quad)
        ph, pw = photo.shape[:2]
        self.size = (pw, ph)
        src_mask = rounded_mask(self.new_w, self.new_h, float(self.radius))
        self.warped_mask = _warp_mask_antialiased(src_mask, self.H, pw, ph, dst_quad)
        self.mask3 = cv2.merge([self.warped_mask] * 3).astype(np.float32) / 255.0
        self.grain_sigma = (_grade.measure_grain(photo, _grade.surround_ring(self.warped_mask))
                            if grain else 0.0)
        self.grade_params = None
        # Integer bbox of the quad, clamped to the canvas and padded by a pixel
        # so the antialiased edge is never clipped.
        xs, ys = dst_quad[:, 0], dst_quad[:, 1]
        bx0, by0 = max(0, int(np.floor(xs.min())) - 1), max(0, int(np.floor(ys.min())) - 1)
        bx1, by1 = min(pw, int(np.ceil(xs.max())) + 2), min(ph, int(np.ceil(ys.max())) + 2)
        self.bbox = (bx0, by0, bx1, by1) if bx1 > bx0 and by1 > by0 else None

    def _prep(self, frame: np.ndarray, bbox=None) -> np.ndarray:
        """Warp one frame. With `bbox`, warp only that window of the canvas.

        The window is an integer translation of the output grid, folded into the
        homography, so every output pixel resolves to exactly the same source
        coordinate as the full-canvas warp — byte-identical, and asserted as
        such in test_video.py. Outside the quad the mask is zero and the blend
        is the photo copied onto itself, so on a 2400x1792 photo whose screen
        occupies 9% of the frame this is most of the per-frame cost removed.
        """
        if (self.new_w, self.new_h) != (frame.shape[1], frame.shape[0]):
            frame = cv2.resize(frame, (self.new_w, self.new_h), interpolation=cv2.INTER_AREA)
        H, size = self.H, self.size
        if bbox is not None:
            x0, y0, x1, y1 = bbox
            T = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1]], dtype=np.float64)
            H, size = T @ H, (x1 - x0, y1 - y0)
        return cv2.warpPerspective(frame, H, size,
                                   flags=cv2.INTER_LANCZOS4,
                                   borderMode=cv2.BORDER_REPLICATE)

    def bind_grade(self, frame: np.ndarray, strength: float) -> None:
        """Measure the light correction once, from the frame the user fitted on."""
        self.grade_params = _grade.light_params(
            self.photo, self._prep(frame), self.warped_mask, strength) if strength > 0 else None

    def _blend(self, photo_win, warped_win):
        """Emitted light over reflected light, or a plain replace.

        `replace` treats the screenshot as paint: the device's own screen
        surface is discarded. That is right for a reflective surface and wrong
        for an emissive one — a real display shows EMISSION PLUS the room
        reflecting off its glass, which is why a switched-off phone reads dark
        grey and never black. Paint true black onto a lit dashboard and it
        reads as a hole cut in the render (reported 9 Sep 2026 from an
        automotive UI that is 56% #000).

        `emissive` composites the screenshot OVER the surface instead, with a
        screen blend so highlights cannot blow out, and `reflection` scaling how
        much of the glass survives underneath. The payoff is not only the black
        level: the specular streak running across the dashboard continues
        across the screen, and that continuity is what stops a composite
        reading as an inset panel. No amount of colour-matching can add it,
        because the surface carrying it has already been thrown away.
        """
        if self.blend != "emissive":
            return warped_win
        P = photo_win.astype(np.float32) * float(self.reflection)
        U = warped_win.astype(np.float32)
        return 255.0 - (255.0 - P) * (255.0 - U) / 255.0

    def render(self, frame: np.ndarray, screen_off: np.ndarray = None,
               specular: float = 0.75, fast: bool = False) -> np.ndarray:
        """Composite one frame onto the photo.

        `fast` confines the warp and the blend to the quad's bounding box. It is
        off for stills, where a single frame's cost is irrelevant and the
        simplest code is the one to trust, and on for video renders. Both
        produce identical bytes; test_video.py asserts it rather than assuming.
        """
        if fast and self.bbox is not None:
            x0, y0, x1, y1 = self.bbox
            warped_screen = self._prep(frame, self.bbox)
            if self.grade_params is not None:
                warped_screen = _grade.apply_light(warped_screen, self.grade_params)
            out = self.photo.copy()
            win = self.mask3[y0:y1, x0:x1]
            pw = self.photo[y0:y1, x0:x1]
            src = self._blend(pw, warped_screen)
            out[y0:y1, x0:x1] = np.clip(
                pw.astype(np.float32) * (1 - win) + src * win, 0, 255).astype(np.uint8)
        else:
            warped_screen = self._prep(frame)
            if self.grade_params is not None:
                warped_screen = _grade.apply_light(warped_screen, self.grade_params)
            src = self._blend(self.photo, warped_screen)
            out = (self.photo.astype(np.float32) * (1 - self.mask3) + src * self.mask3)
            out = np.clip(out, 0, 255).astype(np.uint8)
        if self.grain:
            # Seeded, so the grain is IDENTICAL in every frame. Over a still
            # photograph that is what it must be: the background's own noise is
            # frozen, and grain that crawled on the screen alone would read as a
            # dirty window. It also keeps the render deterministic.
            out = _grade.add_grain(out, self.warped_mask, self.grain_sigma)
        if screen_off is not None:
            out = _grade.specular_lift(out, screen_off, self.warped_mask, strength=specular)
        return out


def compose(photo: np.ndarray, screenshot: np.ndarray, corners, corner_radius: float = 0.0,
            grade: float = 0.0, grain: bool = False, screen_off: np.ndarray = None,
            specular: float = 0.75, blend: str = "replace",
            reflection: float = DEFAULT_REFLECTION) -> np.ndarray:
    """Warp `screenshot` into the quad `corners` (TL,TR,BR,BL, photo pixels) on `photo`.

    Single resampling pass at the photo's resolution; deterministic. This is the
    whole engine — the CLI below and ui.py both call it.
    """
    # A Plan plus one frame. The long-form pipeline this replaced (prefilter,
    # homography, rounded mask, antialiased mask warp, grade, blend, grain,
    # specular) now lives in Plan, so the still and video paths run the SAME
    # code and cannot drift apart. See test_video.py: frame 0 of a render is
    # asserted byte-identical to this function's output.
    plan = Plan(photo, screenshot.shape, corners, corner_radius, grain=grain,
                blend=blend, reflection=reflection)
    plan.bind_grade(screenshot, grade)
    return plan.render(screenshot, screen_off=screen_off, specular=specular)


def ffmpeg_exe() -> str:
    """Path to the ffmpeg binary, or raise with something a designer can act on.

    imageio_ffmpeg ships a static binary as a wheel, so it installs into the
    same venv OpenCV already lives in and the zero-configuration constraint
    holds — no Homebrew, no PATH hunting. cv2.VideoWriter was rejected for this
    job: the headless wheels carry a limited codec set, expose no control over
    bitrate or pixel format, and behave differently per platform, none of which
    is acceptable when the output is the deliverable.
    """
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        raise RuntimeError(
            "ffmpeg is missing. Run `python3 scripts/preflight.py --install` to add it "
            "to the screengraft venv (it ships as a wheel; nothing is installed "
            "system-wide)."
        ) from e


# Output presets. The last stage of the pipeline is the only one that can undo
# the care taken in all the others: H.264's 4:2:0 chroma subsampling softens
# exactly the coloured text edges the INTER_AREA prefilter exists to protect.
# So "web" runs at CRF 16, which is near-visually-lossless rather than
# delivery-sized, and anything destined for a case study should use prores.
# BT.709 is tagged explicitly on both so players do not guess at the primaries
# and shift the colour we just matched to the room.
PRESETS = {
    "web": ["-c:v", "libx264", "-preset", "slow", "-crf", "16",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart"],
    "prores": ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"],
}


def probe_video(path: str):
    """(frame_count, fps, width, height) — read, never trusted blindly."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError(f"could not open video: {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS)) or 0.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    # CAP_PROP_FRAME_COUNT is a container hint and is wrong often enough that
    # the render loop counts frames as it reads them instead. It is reported
    # here only to drive a progress bar.
    if not (0.1 <= fps <= 240):
        fps = 30.0
    return n, fps, w, h


def read_frame_at(path: str, index: int = 0):
    """One frame, for fitting and for the poster image."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError(f"could not open video: {path}")
    if index > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = cap.read()
    if not ok and index > 0:
        # Seeking is unreliable on some containers; fall back to reading
        # forward, which is slow and always right.
        cap.release()
        cap = cv2.VideoCapture(path)
        for _ in range(index + 1):
            ok, frame = cap.read()
            if not ok:
                break
    cap.release()
    if not ok or frame is None:
        raise RuntimeError(f"could not read frame {index} of {path}")
    return frame


def compose_video(photo: np.ndarray, video_path: str, corners, output: str,
                  corner_radius: float = 0.0, grade: float = 0.0, grain: bool = False,
                  preset: str = "web", fit_frame: int = 0, audio: bool = True,
                  frames_dir: str = None, progress=None, blend: str = "replace",
                  reflection: float = DEFAULT_REFLECTION,
                  start_frame: int = 0, max_frames: int = None) -> dict:
    """Inject a VIDEO into a still photo. The photo does not move, so there is
    exactly one homography and the whole of Plan is computed once.

    Frames are piped to ffmpeg as raw BGR24 rather than written out as a PNG
    sequence: a ten-second clip is several hundred frames and several GB of
    intermediate PNGs, for no benefit. `frames_dir` still dumps them when a
    test or a human needs to look at individual frames.

    `start_frame` and `max_frames` render a SEGMENT rather than the whole clip.
    They exist for the preview: compositing a 2460-frame recording to look at it
    takes about as long as the render it is meant to save you from, and a
    preview you wait a minute for is a render with a worse output. Nothing else
    passes them, so the full-clip contract -- frame 0 of a render equals the
    still composite, byte for byte -- is untouched.

    Time is deliberately NOT resampled. The output runs at the source's own
    frame rate; converting fps by dropping or duplicating frames is judder, and
    doing it properly means blending, which is a different feature. Note also
    that a prototype recording has no motion blur — it renders discrete frames
    — so a fast scroll will strobe. That is a property of the input, the same
    way the source resolution is, not something this stage should paper over.
    """
    n_hint, fps, vw, vh = probe_video(video_path)
    first = read_frame_at(video_path, fit_frame)
    plan = Plan(photo, first.shape, corners, corner_radius, grain=grain,
                blend=blend, reflection=reflection)
    plan.bind_grade(first, grade)

    ph, pw = photo.shape[:2]
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{pw}x{ph}",
           "-r", f"{fps}", "-i", "-"]
    if audio:
        # Optional by construction: `?` on the map means a source with no audio
        # track (which a prototype recording usually is) is not an error.
        cmd += ["-i", video_path, "-map", "0:v", "-map", "1:a?", "-c:a", "aac", "-shortest"]
    cmd += PRESETS.get(preset, PRESETS["web"])
    cmd += ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            output]

    if frames_dir:
        os.makedirs(frames_dir, exist_ok=True)
    cap = cv2.VideoCapture(video_path)
    if start_frame > 0:
        # Same fallback read_frame_at uses: seeking is unreliable on some
        # containers, and a segment that silently began somewhere else would be
        # a preview of the wrong moment.
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        if not cap.grab():
            cap.release()
            cap = cv2.VideoCapture(video_path)
            for _ in range(start_frame):
                if not cap.grab():
                    break
        else:
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    count = 0
    total_hint = n_hint if max_frames is None else min(n_hint or max_frames, max_frames)
    try:
        while True:
            if max_frames is not None and count >= max_frames:
                break
            ok, frame = cap.read()
            if not ok:
                break
            out = plan.render(frame, fast=True)
            if frames_dir:
                cv2.imwrite(os.path.join(frames_dir, f"{count:06d}.png"), out,
                            [cv2.IMWRITE_PNG_COMPRESSION, 1])
            proc.stdin.write(out.tobytes())
            count += 1
            if progress and count % 10 == 0:
                progress(count, total_hint)
    finally:
        cap.release()
        try:
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        err = proc.stderr.read().decode("utf-8", "replace")
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {err.strip()[:400]}")
    if count == 0:
        raise RuntimeError(f"no frames could be read from {video_path}")
    return {"frames": count, "fps": fps, "source_size": [vw, vh],
            "output_size": [pw, ph], "preset": preset, "fit_frame": fit_frame,
            "blend": blend, "reflection": plan.reflection,
            "start_frame": start_frame}


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
