#!/usr/bin/env python3
"""
Tests for the video path — injecting a moving screen into a still photo.

The point of this file is one contract above all others:

    **frame 0 of a video render must equal the still composite, byte for byte.**

The still and video paths share `Plan`, and that sharing is the whole design —
it is what stops the two drifting apart so that a fix lands in one and not the
other. A test that asserts the shared result is the only thing keeping the
sharing honest, because a refactor that broke it would still pass every other
suite in this directory.

Run: ~/.screengraft/venv/bin/python test/test_video.py
"""
import os
import subprocess
import sys
import tempfile

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import warp as W  # noqa: E402

FAILED = []


def ok(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)
    return cond


def synth_photo(w=900, h=700):
    """A 'photo': a textured ground with a dark device body sitting on it."""
    ph = np.zeros((h, w, 3), np.uint8)
    for y in range(h):                      # a gradient ground, so grade has context
        ph[y, :] = (90 + y // 12, 120 + y // 14, 150 + y // 16)
    cv2.rectangle(ph, (250, 150), (650, 550), (30, 30, 32), -1)   # body
    # Real photographic noise, and NOT decoration. Without it measure_grain()
    # returns sigma 0.0 on this fixture, add_grain becomes a no-op, and the
    # determinism check silently stops testing grain at all — which is exactly
    # what happened: unseeding the generator was planted as a fault and the
    # suite stayed green. A fixture too clean to exercise the code is a test
    # that passes for the wrong reason.
    rng = np.random.default_rng(7)
    return np.clip(ph.astype(np.float32) + rng.normal(0, 3.5, ph.shape),
                   0, 255).astype(np.uint8)


CORNERS = [[270, 170], [630, 175], [628, 530], [272, 528]]


def synth_clip(path, n=12, w=300, h=300):
    """A clip whose content changes a lot — dark to light, plus a moving band.

    Deliberately harsh: a per-frame light match would visibly pulse on this.
    """
    exe = W.ffmpeg_exe()
    p = subprocess.Popen(
        [exe, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{w}x{h}", "-r", "15", "-i", "-", "-c:v", "libx264", "-crf", "10",
         "-pix_fmt", "yuv420p", path], stdin=subprocess.PIPE)
    for i in range(n):
        f = np.full((h, w, 3), int(20 + 200 * i / max(n - 1, 1)), np.uint8)
        cv2.rectangle(f, (0, int(h * i / n)), (w, int(h * i / n) + 20), (0, 0, 220), -1)
        cv2.putText(f, "UI", (30, 150), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 3)
        p.stdin.write(f.tobytes())
    p.stdin.close()
    p.wait()
    return p.returncode == 0


def main():
    try:
        W.ffmpeg_exe()
    except RuntimeError as e:
        # Skipping is right on a machine that only ever does stills. It is NOT
        # right in CI, where requirements.txt guarantees the wheel: a suite that
        # quietly passes because it did not run is the exact failure mode this
        # project keeps catching. CI sets SCREENGRAFT_REQUIRE_FFMPEG=1 so a
        # missing binary is a red build rather than a green non-event.
        if os.environ.get("SCREENGRAFT_REQUIRE_FFMPEG") == "1":
            print("FAIL  ffmpeg is required here and is missing")
            print(f"  ({e})")
            sys.exit(1)
        print("video tests skipped — ffmpeg not installed in the venv")
        print(f"  ({e})")
        return

    photo = synth_photo()

    print("the bbox fast path is an optimisation, not a different renderer")
    # The per-frame warp and blend are confined to the quad's bounding box, with
    # the window folded into the homography as an integer translation. If that
    # is ever not byte-identical, the optimisation is a bug.
    frame = np.full((300, 300, 3), 200, np.uint8)
    cv2.putText(frame, "AA", (20, 160), cv2.FONT_HERSHEY_SIMPLEX, 2, (10, 10, 10), 3)
    plan = W.Plan(photo, frame.shape, CORNERS, corner_radius=24.0, grain=True)
    plan.bind_grade(frame, 0.35)
    slow, fast = plan.render(frame), plan.render(frame, fast=True)
    ok("fast render is byte-identical to the full-canvas one", np.array_equal(slow, fast),
       "" if np.array_equal(slow, fast) else
       f"max delta {np.abs(slow.astype(int) - fast.astype(int)).max()}")

    # The emissive blend reads the PHOTO under the screen, so the bbox window has
    # to be sliced out of it as well as out of the mask. Getting that wrong shows
    # up only on the video path, and only as a subtly wrong screen.
    pe = W.Plan(photo, frame.shape, CORNERS, corner_radius=24.0, grain=True,
                blend="emissive", reflection=0.35)
    pe.bind_grade(frame, 0.35)
    es, ef = pe.render(frame), pe.render(frame, fast=True)
    ok("...and with the emissive blend too", np.array_equal(es, ef),
       "" if np.array_equal(es, ef) else
       f"max delta {np.abs(es.astype(int) - ef.astype(int)).max()}")
    ok("the emissive blend actually changes the frame", not np.array_equal(es, slow))

    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "src.mp4")
        if not ok("a test clip could be encoded", synth_clip(src)):
            print("\n" + f"FAILURES: {', '.join(FAILED)}")
            sys.exit(1)

        print("\nframe 0 of a render equals the still composite")
        out = os.path.join(td, "out.mp4")
        fdir = os.path.join(td, "frames")
        info = W.compose_video(photo, src, CORNERS, out, corner_radius=24.0,
                               grade=0.35, grain=True, frames_dir=fdir)
        f0 = W.read_frame_at(src, 0)
        still = W.compose(photo, f0, CORNERS, 24.0, grade=0.35, grain=True)
        rendered = cv2.imread(os.path.join(fdir, "000000.png"))
        same = np.array_equal(still, rendered)
        ok("THE contract: still and video paths agree exactly", same,
           "" if same else f"max delta {np.abs(still.astype(int) - rendered.astype(int)).max()}")
        ok("every source frame was rendered", info["frames"] == 12, str(info["frames"]))
        ok("an encoded file was produced", os.path.getsize(out) > 1000,
           f"{os.path.getsize(out)} bytes")

        print("\nthe photo outside the screen is untouched")
        # Not "close to" untouched — identical. The mask's antialiased edge is
        # legitimately part screen and is excluded; everything the blend does not
        # reach must survive the render bit for bit.
        m = plan.warped_mask
        outside = m == 0
        a = cv2.imread(os.path.join(fdir, "000000.png"))
        b = cv2.imread(os.path.join(fdir, "000011.png"))
        ok("outside is identical to the original photo",
           np.array_equal(a[outside], photo[outside]))
        ok("outside does not move across frames", np.array_equal(a[outside], b[outside]))
        ok("the antialiased edge DOES vary (it is part screen)",
           not np.array_equal(a[(m > 0) & (m <= 200)], b[(m > 0) & (m <= 200)]))

        print("\nthe light match is bound once, so the screen cannot pulse")
        # match_light measures the correction from the screen's OWN content, so
        # running it per frame makes it drift as the UI goes dark to light and the
        # injected screen visibly pulses. Parameters are derived once from the
        # fitted frame and applied unchanged to every frame.
        p2 = W.Plan(photo, f0.shape, CORNERS, 24.0)
        p2.bind_grade(f0, 0.35)
        before = dict(p2.grade_params)
        last = W.read_frame_at(src, 11)
        p2.render(last, fast=True)
        ok("rendering a very different frame does not change the parameters",
           all(np.allclose(before[k], p2.grade_params[k]) for k in ("m_in", "s_in", "dL")))
        # And the applied correction really is the same transform.
        grey = np.full_like(f0, 128)
        one = W._grade.apply_light(grey, before)
        two = W._grade.apply_light(grey, p2.grade_params)
        ok("the same transform is applied throughout", np.array_equal(one, two))

        print("\na render is deterministic")
        f2 = os.path.join(td, "frames2")
        W.compose_video(photo, src, CORNERS, os.path.join(td, "out2.mp4"),
                        corner_radius=24.0, grade=0.35, grain=True, frames_dir=f2)
        same_all = all(
            np.array_equal(cv2.imread(os.path.join(fdir, f"{i:06d}.png")),
                           cv2.imread(os.path.join(f2, f"{i:06d}.png")))
            for i in range(12))
        # Frames, not the .mp4: encoded bytes depend on the ffmpeg build, so that
        # is not a promise this project can make. The frames are.
        ok("two renders produce identical frames", same_all)
        ok("...and grain was actually exercised (a clean fixture would not)",
           plan.grain_sigma > 0.5, f"sigma {plan.grain_sigma:.3f}")

        print("\nthe scrubbed frame reaches the compositor")
        # It did not, and the scrubber looked decorative: /api/frame updated the
        # thumbnail while _read_source still read frame 0, so Preview and Save
        # always composited the first frame whatever the slider said (reported
        # 9 Sep 2026). Parsed from the source, like the sidecar contract, because
        # the failure is "this function forgot to ask" — invisible to any test
        # that only exercises the engine.
        import re as _re
        ui_src = open(os.path.join(ROOT, "scripts", "ui.py"), encoding="utf-8").read()
        body = _re.search(r"def _read_source\(.*?\n(?=def )", ui_src, _re.DOTALL)
        ok("_read_source asks for the fitted frame, not frame 0",
           bool(body) and "_fit_frame()" in body.group(0),
           "" if body else "could not find _read_source")
        # This used to count TWO resets, one per route -- which pinned the
        # shape of the code, not what it does: /api/use and /api/upload now
        # share one _adopt(), and collapsing the duplication turned a correct
        # refactor red. What is worth pinning is that the one place a source is
        # adopted still resets the frame; that it actually HAPPENS is proved
        # over HTTP in test_render_api.py, where a stale index would show.
        adopt = _re.search(r"def _adopt\(.*?\n(?=def )", ui_src, _re.DOTALL)
        ok("adopting a new screen source resets the fitted frame",
           bool(adopt) and "SESSION.update(fit_frame=0)" in adopt.group(0),
           "" if adopt else "could not find _adopt")
        ok("/api/frame records the frame it was asked for",
           "SESSION.update(fit_frame=idx)" in ui_src)
        # And the frames really are different, or none of the above would matter.
        a, b = W.read_frame_at(src, 0), W.read_frame_at(src, 11)
        ok("frames of the test clip actually differ", not np.array_equal(a, b))

        print("\npresets and metadata")
        ok("both presets are defined", set(W.PRESETS) == {"web", "prores"}, str(list(W.PRESETS)))
        ok("web is tagged for compatibility and quality",
           "yuv420p" in W.PRESETS["web"] and "16" in W.PRESETS["web"])
        ok("the render info carries what a re-render needs",
           {"frames", "fps", "source_size", "output_size", "preset", "fit_frame",
            "blend", "reflection"} <= set(info), str(sorted(info)))

    print()
    if FAILED:
        print(f"FAILURES: {', '.join(FAILED)}")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
