# screengraft

**Put a UI screenshot — or a screen recording — onto a photographed screen so the perspective is exactly right.**

![The fitting workbench: photo with the screen quad on the left, live composite on the right, and a magnified strip across the edge below](docs/workbench.png)

Every device mockup is a compromise. Templates give you three angles and someone
else's lighting. Generative tools give you a screen that looks *like* your design
without being it — text reflowed, a button moved, a logo subtly wrong.

screengraft takes your photograph and your screenshot and computes the projective
transform between them. The screenshot lands on the glass because the geometry
says it must, not because a model thought it looked about right. Same inputs,
same output, every time.

Point it at a **video** instead and the same fit renders every frame: record a
prototype, then put the recording inside a real photograph.

---

## What it does

- **Any angle.** A homography handles arbitrary perspective — a phone leaning on
  a wall, a laptop half-turned, a tablet held at 40°.
- **Your pixels, unaltered.** The screenshot is resampled once and warped once.
  9px legal copy stays legible.
- **Rounded corners that actually follow the bezel**, measured from the photo or
  taken from a device preset.
- **Realism pass** *(optional)* — matches the screen's white balance and grain to
  the light in the room, and can lift the device's real reflections from a
  screen-off frame of the same shot.
- **Emissive screens** *(optional)* — a display emits light *and* reflects the
  room, which is why a switched-off phone looks dark grey rather than black.
  Paint a true-black UI on flat and it reads as a hole cut in the photo. Turn
  this on and the screenshot composites over the device's own glass, so the
  photo's highlights carry across the screen.
- **Video, not just stills.** The screen source can be an `mp4`/`mov`/`webm`.
  You match the edges on one frame and every frame gets that same geometry — the
  photograph is still, so there is nothing to track and nothing to drift. Output
  is H.264 at CRF 16 or ProRes 422 HQ.
- **You confirm every fit.** Detection is advisory and says so; you drag the four
  edges onto the glass with a magnified loupe. A silent misdetection producing a
  confident, wrong result is the one failure this tool refuses to have.

## Requirements

`python3` with **OpenCV** and **numpy**. OpenCV is the engine — nothing runs
without it. The installer provisions an isolated venv at `~/.screengraft/venv`
and never touches your system Python.

Video rendering also uses **ffmpeg**, which arrives as a wheel (`imageio-ffmpeg`)
into that same venv — nothing is installed system-wide. It is optional: without
it, stills work exactly as before.

## Install as a Claude Code / Cowork plugin

```
/plugin marketplace add seq000/screengraft
/plugin install screengraft@fraczyk-tools
```

That route tracks versions and updates itself. If you would rather not add a
marketplace, download `screengraft-<version>.plugin` from
[the latest release](https://github.com/seq000/screengraft/releases/latest) and
open it, or clone this repo and point Claude Code at the folder.

Then ask Claude to inject a screenshot onto a photo. It opens a local page in
your browser, you fit the edges, press Save, and the composite lands in your
project folder. Nothing is uploaded anywhere; the page is served from
`127.0.0.1`.

## Or use it without Claude

```bash
npx screengraft --out-dir ./mockups
```

npm is a delivery mechanism here, not a claim about the language: the tool is
Python and OpenCV, and `cli/screengraft.js` is a launcher. It installs nothing
behind your back — if the engine is missing it prints the one command that
builds it (`npx screengraft --install`) and exits.

From a clone:

```bash
python3 scripts/preflight.py --install        # one-time: creates the venv
python3 scripts/ui.py --out-dir ./mockups     # opens the fitting page
```

Headless, if you already know the corners:

```bash
python3 scripts/warp.py --photo shot.jpg --screenshot ui.png \
  --corners "945,504 1310,475 1501,1408 1135,1459" \
  --radius-frac 0.14 --out composite.png
```

Corners are `TL TR BR BL` in photo pixels.

## Why not just use AI

A diffusion model cannot guarantee the screenshot lands on the screen's four
corners, because nothing in it is solving for that. A projective transform can,
by construction — it is the same maths a document scanner uses to flatten a page.
So the pipeline is computer vision and projective geometry end to end, and it is
deterministic: re-run it and you get a byte-identical file.

Generative AI has exactly one optional job in the design, and it is strictly
outside the screen mask. It never touches the pixels you designed.

## How it works

1. **Corner acquisition** — an advisory detector proposes a quad; you correct it
   by dragging *edges* (a rounded corner has no point to aim at; the straight
   edges either side are unambiguous), with a rectified strip loupe at ~5×.
2. **Warp** — the screenshot is area-averaged down to its destination footprint,
   then warped once at the photo's resolution. Prefiltering matters: OpenCV's
   warp never area-averages, so warping a 1206×2622 screenshot into a 226×454
   quad without it turns body text into noise.
3. **Realism pass** *(optional)* — white balance and exposure toward the
   surrounding light, grain matched to the photo's own noise floor, real
   speculars lifted from a screen-off reference.
4. **Video**, when the source is a clip — everything a fixed photo and a fixed
   quad make constant is computed once, and only the frame changes. Three
   consequences worth naming, because each is a way video normally goes wrong:
   the light match is measured **once** from the frame you fitted on, so the
   screen cannot pulse as your UI scrolls from dark to light; the grain stays
   frozen, because the photograph's own noise does not move; and the screen's
   antialiased **edge is pixel-identical in every frame**, so there is no edge
   crawl. Frame 0 of a render is byte-identical to the still composite — the
   test suite asserts it, because that is what stops the two paths drifting.

## Where screengraft keeps things

**Your output** goes to the folder you launched with (`--out-dir`), which the
Claude skill points at your project. That is the only place anything is kept for
you, and nothing below ever touches it.

**Working files** live in `~/.screengraft/sessions/<timestamp>/` — one directory
per run. A source you pick by path is never copied: screengraft reads it where it
is, and screengraft never deletes a file of yours. A source you drag in or browse
to has to be copied, because a browser hands over bytes and will not say where
they came from.

What happens to that copy depends on whether the run produced anything:

- **A run that saved a mockup keeps its source.** The `result.json` sidecar names
  it, and a recipe naming a file that no longer exists is not a recipe.
- **A run that produced nothing keeps nothing.** That is the common case and
  where the disk goes — previews, thumbnails, poster frames and abandoned
  uploads are all swept when the run ends, or at the next launch after a crash.

What survives either way is the `result.json` sidecar: a few hundred bytes
recording the corners, radius, grade and blend of that fit. It reproduces a
composite exactly, and it is the first thing a bug report should include.

Sidecars written by v0.23.0–v0.25.1 may name a dragged-in source that release
deleted. Those cannot be repaired — the bytes are gone — but screengraft now
marks them `"source_retained": false` rather than leaving them looking valid.


## Roadmap

Done: manual warp, advisory detectors, the fitting workbench, the realism pass,
video into a still photo.

Open: **camera-motion tracking** — the photograph itself must currently be a
still, so a clip of a moving phone is out of scope; **SAM 2 auto-detect** (built
and measured in a separate repo; it segments the phone body rather than the
glass, so it is not shipped); **occluder matte**, so a finger in front of the
screen stays in front.

Known limits worth stating plainly: detection abstains rather than guessing when
the background is itself neutral (a pale tiled floor, a plain wall) — you place
the edges by hand there. And a prototype recording has no motion blur, so a very
fast scroll will strobe; that is a property of the source, not of the composite.

## Changelog

Every release is described in [CHANGELOG.md](CHANGELOG.md), with the
measurements that drove it.

## Support

Bugs and photographs that defeat the detector belong in
[Issues](https://github.com/seq000/screengraft/issues) — the bug template asks
first for the `result.json` sidecar, because it reproduces any composite
exactly. Ideas and "can it do X" go in
[Discussions](https://github.com/seq000/screengraft/discussions).

If the photograph or the UI is confidential — a client shot, something
unreleased — email **screengraft@fraczyk.design** instead of posting it.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version: there are tests, they
run in CI, and a change to the compositing engine needs a measurement, not an
opinion.

## Licence

MIT. The bundled Mona Sans subset is SIL OFL — see `ui/fonts/OFL.txt`.
