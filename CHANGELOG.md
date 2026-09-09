# Changelog

All notable changes to screengraft.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

One convention worth knowing: entries say what was **measured**, not what was
attempted. Where a change was driven by a real photograph or a real failure, the
numbers are here.

## [0.21.2] - 2026-09-09

### Fixed

- **The contrast audit never measured the text drawn on the photograph.** Section
  4b covered overlay *strokes*; the corner tags and the strip loupe's `screen` /
  `outside` labels are cased by a halo stroked around the glyph, at their own
  alpha, and nothing looked at them. A new **4c** measures them on the same
  better-of-the-two rule (fill or halo, minimised over every photo grey) against
  the same 2.0:1 floor. All three pass with no accepted shortfall: corner tags
  **3.95:1**, `screen` **3.95:1**, `outside` **3.20:1**.
- **Two overlays were being skipped in silence.** 4b matched two `const CORE_*`
  declarations, so the strip's tick marks — `rgba(255,255,255,.7)`, drawn by the
  *audited* `cased()` helper — were measured by nothing (**3.09:1**), and
  `CORE_IDLE`, which shares a declaration line with `CASE_A`, was dropped from
  the sweep with no output saying so. Call sites are now parsed paren-balanced
  rather than by regex, which truncates on the inline arrow body's own
  semicolons, and a name that stops resolving **fails** instead of going quiet.
- `CORE_IDLE` had been approximated by compositing white .92 over *black*, the
  darkest possible backing rather than the tone it is drawn on. Measured
  properly it is **3.44:1**, not 3.31.
- **`test/ui-audit.js` reported a tab trap that could not exist.** `tabIndex >= 0`
  is what an element claims, not what the browser will do: the strip loupe's zoom
  steppers sit inside a `display:none` dock whenever the loupe is floating, still
  report tabIndex 0, and are nonetheless unfocusable. The check now asks the
  browser — focus it, see if focus landed, restore the previous element — so it
  measures reachability instead of inferring it. A planted `opacity:0` control is
  still caught.

### Changed

- The Realism tooltip now says that grain is judged at the preview's scale.
  Measured on a real 2400px fit: the preview's 1.50× downscale averages the
  injected grain from sigma **1.501 to 0.871**, so the preview shows **58%** of
  what the save carries. Across every source photo on hand the factor spans
  1.07×–1.72×, i.e. 68%–52%. No engine change — a mockup is nearly always viewed
  scaled, so the preview is honest about how the file will actually be seen, and
  the discrepancy only bites at 100%.

## [Unreleased]

### Added

- A support address, **screengraft@fraczyk.design**, for the case the issue
  tracker cannot serve: a photograph or a UI that is confidential. It is offered
  in the README, as a contact link on the new-issue chooser, and as the author
  and `bugs` email in `package.json`, `plugin.json` and the marketplace catalog,
  so `npm bugs` and the plugin listing both resolve to a person.

## [0.21.1] — 2026-09-09

### Fixed

- **The "fit on frame" scrubber only moved the thumbnail.** The compositor went
  on reading frame 0 whatever the slider said, so Preview, Save and the fit you
  were judging all used the first frame of the clip. The chosen frame is now
  session state, and picking a new clip resets it.
- **Clip thumbnails had been blank since video shipped.** The picker was handed
  the video's path directly, and an `<img>` cannot render a video. Clips now get
  a poster frame written once when chosen. The poster stays on frame 0
  deliberately — at that size one frame looks like any other, so following the
  scrubber would be movement without information.
- **The web/ProRes control showed no selection.** Its `sel` class was only ever
  styled for the file picker's thumbnails, so a segmented control was styling
  nothing. It now matches the device chips and is a proper `radiogroup`.
- `POST /api/frame` no longer writes a PNG per scrub step.

## [0.21.0] — 2026-09-09

### Added

- **Emissive screens** *(off by default)*. A real display shows its own light
  **plus** the room reflecting off its glass, which is why a switched-off phone
  reads dark grey and never black. The default composite treats the screenshot
  as paint and discards the device's own screen surface, so a true-black
  interface lands as a hole cut in the photograph. Turn this on and the
  screenshot is composited *over* the glass, with a strength setting how much
  surface shows through.

  Measured on the reporting case — an automotive dashboard render whose UI is
  56% pure black — the screen's median luminance went **2 → 29**, against a
  surrounding dashboard at **62**. Colour-matching alone reached only 17 and
  stayed flat, because it can lift uniformly but cannot restore a gradient that
  has already been discarded. **25–50% is the usable band**; past 75% the
  content loses contrast. The default is 35%.

  The larger effect is not the black level: a specular streak running across the
  photograph used to stop dead at the screen edge, and now carries across it.
  That continuity is what stops a composite reading as an inset panel.

  Mathematically this is a Screen blend with the backdrop scaled by the
  strength, so 0% collapses exactly to the previous behaviour and 100% is a
  plain Screen. Off is byte-identical to earlier releases.

## [0.20.4] — 2026-09-08

### Changed

- New README hero, captured from the running tool. The previous one predated the
  layout change and showed controls that no longer existed.

## [0.20.3] — 2026-09-08

### Changed

- A version bump can no longer land without updating the skill definition.
  `check_package.py` compares the version the skill claims against the version
  being packaged, and fails the release when they drift. Documentation trailing
  the code is a nuisance; the skill's description trailing the code makes a
  feature *invisible*, because that description is how the tool gets found.

## [0.20.2] — 2026-09-08

### Fixed

- **The skill described only screenshots, three versions after video shipped**,
  so a request phrased around a screen recording would not have reached the tool
  built for exactly that. Also removed a promise of a preview popup that had
  been deleted two versions earlier.

## [0.20.0] – [0.20.1] — 2026-09-08

### Changed

- **ffmpeg is offered when the tool starts, not discovered when a render fails.**
  Anyone who installed before video existed has a working environment without
  it, and nothing warned them until the end of a job. `preflight.py
  --install-ffmpeg` adds the single wheel to an existing environment.
- The offer happens before the browser opens — the last moment the user is still
  in the conversation that can ask.

## [0.19.1] — 2026-09-08

### Changed

- Documentation now says the tool handles video: README, package descriptions,
  keywords and catalogue tags. Doing this uncovered that CI had never run the
  video test suite, and that the suite could pass by not running at all when
  ffmpeg was absent. Both fixed.

## [0.19.0] — 2026-09-08

### Changed

- **The fit and the composite are now side by side permanently.** Judging a
  corner means seeing the same corner in both at the same zoom, so making that
  optional made the check optional. The toggle, its settings section, and the
  preview popup that existed only to serve the "off" state are gone.
- Below ~1100px the two panes stack rather than one being dropped.

## [0.18.0] — 2026-09-08

### Added

- **Inject a video, not just a screenshot.** Record a prototype, then put the
  recording inside a real photograph. The photograph is still, so there is one
  perspective solve and no tracking: match the four edges on one frame, and
  every frame gets that geometry.

  Three things video usually gets wrong, and does not here: the light match is
  measured **once**, from the frame you fitted on, so the screen cannot pulse as
  the interface scrolls; grain stays frozen, because a photograph's own noise
  does not move; and the screen's antialiased edge is pixel-identical in every
  frame, so there is no edge crawl.

  Output is H.264 at CRF 16 or ProRes 422 HQ. Time is never resampled.

### Changed

- The still and video paths share one implementation, and the test suite asserts
  that frame 0 of a render equals the still composite byte for byte.

## [0.17.0] — 2026-09-07

### Changed

- **Detection rebuilt against real photographs.** Measured across nine real
  mockup photos: seven detect correctly, two abstain, none produce a confident
  wrong result.
- A third detector that looks at **colour** — devices are neutral, the furniture
  they sit on is not. On one photograph the screen measured a saturation of 1.9
  against the table's 78.6, and the previous detectors discarded that by working
  in greyscale.
- Every tone band now offers its runners-up rather than only its largest region.
  A phone that was the *second*-largest dark area in its band was being
  discarded before scoring ever saw it.

### Fixed

- **Detection abstains when nothing corroborates the result**, rather than
  emitting a confident wrong quadrilateral — a promise the code had made in a
  comment for four milestones without enforcing anywhere.
- A result with a corner outside the photograph is rejected: such a corner
  cannot be dragged back, and a wrong result you cannot correct is worse than no
  result. A **Reset** control restores a sane starting rectangle.

## [0.13.0] – [0.13.1] — 2026-09-05

### Added

- First public release: manual four-point warp, advisory detectors, the fitting
  workbench with a rectified edge loupe, and the realism pass.

[0.21.1]: https://github.com/seq000/screengraft/releases/tag/v0.21.1
[0.21.0]: https://github.com/seq000/screengraft/releases/tag/v0.21.0
[0.20.4]: https://github.com/seq000/screengraft/releases/tag/v0.20.4
[0.17.0]: https://github.com/seq000/screengraft/releases/tag/v0.17.0
[0.13.1]: https://github.com/seq000/screengraft/releases/tag/v0.13.1
