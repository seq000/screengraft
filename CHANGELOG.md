# Changelog

All notable changes to screengraft.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

One convention worth knowing: entries say what was **measured**, not what was
attempted. Where a change was driven by a real photograph or a real failure, the
numbers are here.

## [0.61.0] - 2026-09-14

### Changed

- **The picker lists what you have used, not what is newest in two folders.**
  Every source that reaches the session — picked by path, dropped, browsed,
  imported — is recorded per role in `~/.screengraft/recents.json`, and the
  photo popover and the screenshot popover each list their own, newest-used
  first, with when and from where ("2 min ago · ~/Downloads"). Files that
  have since gone are dropped. First run seeds the list from the sessions
  that already exist. A dropped file stays recent for as long as its session
  copy does. A clip gets its first frame as a thumbnail. The Desktop/Downloads
  scan (`scan.py`) remains for the CLI.
- **Picker popover, on request:** the preview slot is as tall as the list
  beside it and no longer stroked; the drop zone is 32px taller; a list item
  at rest has no fill and no stroke — picture, name, and a second line for
  when it was used — hover raises it, the chosen one is the raised neutral
  every selected control uses.

## [0.60.0] - 2026-09-14

### Changed

- **Rails re-measured against the updated design file.** The Segment Button
  grew to 32px (from 28) with 8px side padding, a text label padded a further
  6px; the zoom rail keeps 8px between its two groups and 32px separates it
  from the corner rail; the bottom rail sits 8px off the edge. Measured in the
  page against the frame: groups 86 / 114 / 61 px against Figma's 85 / 113 /
  61 (the difference is the two half-pixel strokes), the left rail 33×97 /
  33×33 / 33×129 against 32×96 / 32×32 / 32×128. The edge-view zoom stepper
  is two Md buttons joined at a hairline (Frame 263: 66×28), not two Sm ones,
  and both carry accessible names.

## [0.59.2] - 2026-09-14

### Fixed

- A shipped comment carried a name; `check_leaks.py` caught it after the
  v0.59.1 tag was already pushed. No code change.

## [0.59.1] - 2026-09-14

### Fixed

- **The sharp line stopped at the dashed line.** `start` was held below
  `end − 0.05`, so with the far line sitting on the phone's near edge the
  plane of focus could not be dragged over the phone — it reached the dashed
  line and stayed there (a screen recording, 14 Sep). Moving the sharp line
  now moves the plane of focus and **carries both limits with it**, each
  keeping its distance, the way a tilt-shift band moves as one thing; the
  dashed lines alone change the ramp's length. A limit that reaches its own
  end of travel stops there and the ramp shortens. Three UI-audit checks.

## [0.59.0] - 2026-09-14

### Fixed

- **The depth-of-field handles could not be grabbed.** v0.54.7 made them
  hollow rings, and an unfilled SVG shape under `pointer-events:auto` is hit
  only on its stroke — the centre of every handle passed the pointer through
  to the image underneath. On a steep, flat phone, where a third of the
  screen's extent is nine pixels of mouse travel, that made the sharp line
  immovable (reported on a real fit, 14 Sep). `pointer-events:all` on the
  handles, and every handle now carries an invisible 10px-radius hit disc.
  Two UI-audit checks pin it: a probe handle must compute to `all`, and every
  painted handle must have its disc.

### Changed

- **The sharp line can sit in front of the glass.** `dof_start` reaches
  −0.5, the same distance past the screen the far line already had past the
  far edge, so the plane of focus can be on the table in front of a steep
  phone rather than pinned to its near edge; the near edge is then already
  part-way up the ramp. The gizmo labels it "sharp · in front of the screen".
  Old sidecars are unaffected (none carries a negative start). Checked in
  `test_warp.py`: start −0.5 / end 0.5 puts the near edge at exactly half
  blur, and −5 clamps to −0.5.

## [0.58.0] - 2026-09-13

### Changed

- **The fit pane is rails over the well** (Figma 7:12, Button Group 145:372,
  Segment Button 138:255, Status pill 5:10). Neither pane has a header any
  more: the photograph gets the whole pane and the two wells line up. What the
  header held now floats as Button Groups — 28px columns of 28px segment
  buttons on the raised surface, one 0.5px translucent stroke and one shadow
  around the group, so it reads on any photo tone. **Left rail:** the zoom
  group (+ / 1x / −), a lone Fit button, then the **corner rail** (TL / TR /
  BL / BR as the design's corner glyphs — the corner picked on the canvas is
  raised, kept in step from `draw()`). **Bottom rail:** Re-detect, Point at
  screen, Rotate and Reset, each its own one-button group, centred — the
  actions on the fit as a whole; corner selection left it because it is
  navigation. **Status pill** top-centre of each pane: the detection state on
  the fit, the render state on the result; hidden while empty. The zoom
  percentage readout is no longer on screen (the rail is icon-only, as
  designed) but is kept for assistive tech as a live region; the canvas
  navigation tip went with the header — the Keys section already says it.
  Rotate is not in the design frame and is kept until ruled on. UI audit
  36/36 at 1600 and at 742.

## [0.57.0] - 2026-09-13

### Changed

- **Controls re-read from the Figma component sets** (Button 4:14, Chip 5:6,
  Input chip 159:4117, Segmented 84:177, Switch 17:61, every variant) and the
  variable collection, and brought back into line where the port had drifted:
  strokes are **0.5px** throughout (they were 1px); both button sizes are
  **radius 6** (Md had been 8); the primary button's rest is the **solid
  accent** — the design's rest and hover containers are the same colour — and
  its disabled state is the solid press colour with a solid label, not three
  alpha variants; the disabled neutral label is `text/mute`, not `text/faint`;
  the segmented control's track is `surface/raise-low` in a 6px radius with a
  24px thumb at radius 4, hover lifting the thumb to `raise-hi`; the input
  chip has its own surfaces — filled is the selected chip's, empty is a
  recessed dashed pill with a `#c2c3cb` label — and gains the design's
  **Active** state: drag a file onto the chip itself and it takes the drop for
  that role (accent stroke and label on an empty chip, accent fill on a filled
  one); the switch's thumb and grip sit at the design's half-pixel insets.
  New tokens: `--bw`, `--r-xs`, `--icon`, `--inchip-ink`, `--inchip-empty`,
  `--group-edge`, `--group-shadow`, `--pill-shadow` (the last three for the
  floating rails that follow). Contrast audit: the primary label at rest now
  measures the 3.70:1 already accepted for hover — the same surface — and is
  accepted with it; nothing else moved. UI audit 36/36.

## [0.56.1] - 2026-09-13

### Fixed

- Review of v0.55–v0.56: a refused `POST` drained its body one byte per loop
  once the client had gone (a claimed 64 MB body meant 64 M empty reads);
  a garbage `Content-Length` would have raised; a non-ASCII token header
  would have reached `compare_digest` and raised instead of being refused;
  and `_grain_gain`'s docstring described a replay path that does not exist.
  Two checks added (non-ASCII token, a refused 300 KB upload answered 403).

## [0.56.0] - 2026-09-13

### Security

- **The local server now answers only its own page.** It always bound
  127.0.0.1, so nothing off the machine could reach it — but it authenticated
  nothing, and a web page the person happened to have open in the same browser
  could sweep localhost ports and fire blind `POST`s: not readable back
  (same-origin policy), but delivered, and `/api/figma` turns one into a job an
  agent then acts on. Two checks close two doors. A **per-launch token**
  (`secrets.token_urlsafe`) rides in the page's URL (`/?t=…`) and comes back on
  every request — as `X-Screengraft-Token` from the page's fetches, as `t` on
  `<img>`/`<video>` sources, which cannot set headers; constant-time compare.
  And **`Sec-Fetch-Site`**, which the browser stamps and a page cannot forge:
  anything but `same-origin` / `none` is refused even with the token in hand,
  so a token that leaks into a screenshot is still not a way in. `/api/ping`
  is the one open route — liveness and version, nothing else; `launch.sh` and
  the skill probe that instead of `/api/state`. The launch line now carries
  `url` (with the token — the thing to open), `base` and `token`. A bare
  `http://127.0.0.1:<port>/` gets a one-sentence page saying to use the
  launcher's link; since the port was already random per launch, no working
  bookmark existed to break. Nine checks in `test_render_api.py`; a planted
  `return True` in `_authorised` turns eight red.

## [0.55.0] - 2026-09-13

### Changed

- **The grain on the screen is 0.7× the photo's measured noise floor.** The
  floor is measured on the ring around the screen — bezel and body, usually the
  darkest thing near it — but a lit screen is usually the brightest thing in
  the frame, and after the sRGB curve a highlight carries less noise in grey
  levels than a shadow does. Measured across the 38-photo corpus: the 192–255
  band's floor is a median **0.67×** the 0–63 band's. On the first judgement of
  a full-resolution save by eye, the verdict was "a bit smaller"; this is the
  derived version of that. `compose()` / `compose_video()` take `grain_gain`
  (default **1.0**, the old behaviour), fresh renders from the UI pass
  `grade.SCREEN_GRAIN_GAIN` = 0.7, and both sidecars record it — so a sidecar
  written before the gain existed replays byte for byte, and one written now
  reproduces the lighter grain. Verified on real fits: laid sigma 2.07 → 1.46,
  1.82 → 1.29, ratio 0.71 on every photo with a measurable floor. A planted
  ignore of the gain in `Plan` is caught by `test_grade.py`.
- `dof.py`: an unused unpacked variable renamed for a lint rule the local ruff
  now enforces. No behaviour change.

## [0.54.8] - 2026-09-13

### Added

- **A corner under the pointer gets a magnified view in the edge strip.**
  Hover, pick or drag a corner handle and the strip below the canvas shows an
  unrotated crop centred on that corner at the strip's own magnification, with
  both adjoining edges drawn through it and the corner named. Edges keep the
  rectified band, which is the strip's real job; the corner view is for the
  moment the two edges meet and neither band can show it.

## [0.54.7] - 2026-09-13

### Changed

- **Handles are hollow rings.** 8px circle, 2px stroke, nothing inside, so
  the pixel under the handle stays visible; the casing sits outside the ring.
  Every line breaks 1px short of the ring — the quad's edges at the corners,
  the depth-of-field lines at their handles — so it reads as a handle beside
  a line, not a bead on it. Pivot pips stay small and filled.

## [0.54.6] - 2026-09-13

### Changed

- Overlay strokes 0.9px (was 0.8) on a +2px casing at 35% black (was +1.6
  at 45%) — quad, guide and the depth-of-field gizmo alike. The gizmo no
  longer fades when the pointer leaves the result pane.

## [0.54.5] - 2026-09-13

### Fixed

- The depth-of-field gizmo's dashes now match the fit overlay's at every
  zoom. SVG dash lengths are in the viewBox's units — the photo's pixels —
  and `non-scaling-stroke` does not cover them, so 6/5 rendered as 3/2.5 at
  half zoom; they are now set in screen pixels through the zoom factor. The
  casing under a dashed line is dashed with it, instead of a solid dark line
  with orange dashes on top.

## [0.54.4] - 2026-09-13

### Changed

- Guide dashes 6/5 (10/7 was too long). The depth-of-field gizmo follows the
  fit overlay's rules: 1px focus line, 0.8px limits, casing +1.6px at 45%
  black, dashes 6/5, move cursor on handles, rotate cursor on the pips, a
  resize cursor on the strength thumb.

## [0.54.3] - 2026-09-13

### Changed

- **The fit overlay is thinner and its casing lighter.** Quad 0.8px (was
  1), active edge 1.5 (was 2), the dark casing under every stroke +1.6px at
  45% black (was +2.5 at 62%). The casing stays — it is what keeps the
  overlay readable over any photograph — just quieter. The guide's dashes
  are longer (10/7, was 2/6) so it reads as a line, not a dotted one.

- **Cursors say what a drag will do.** A corner handle shows *move*; the
  pivot zones near an edge's ends show a rotate cursor (a drawn one — the
  platform has none); the middle of an edge keeps *move*.

## [0.54.2] - 2026-09-13

### Fixed

- **Turning the depth-of-field lines no longer slides them.** The lines are
  stored as fractions of the screen's extent along the direction, and that
  extent changes with the angle — so turning on the fractions alone moved
  every line as it turned, and the centre handle crept along the line. The
  sharp line's handle is now the pivot: it stays put to the pixel through a
  turn, and both limits keep their distance from it in screen pixels.

- **Magnetic to the screen's axes.** Within 4° of 0/90/180/270 the lines snap
  to run exactly along the screen's edges — which, once the perspective is
  applied, is what "along the phone" looks like. A family of lines turned a
  few degrees off is physically consistent but runs along nothing, which is
  how it read. ⇧ still snaps to 15°.

## [0.54.1] - 2026-09-13

### Changed

- The switch track is 20px tall, as the Figma component draws it (17:61);
  the 48×28 hit area is unchanged. Was 22px.

## [0.54.0] - 2026-09-13

### Added

- **Depth of field on both sides of the focus line.** A phone whose middle
  is sharp and both ends soft has its plane of focus *inside* the screen:
  blur grows toward the camera as well as away from it — the depth of
  field's near and far limits, the band Photoshop's tilt-shift draws.
  **Both sides** adds the near limit as a second dashed line behind the focus
  line, with its own centre handle; strength is shared, as it is in a lens.
  Turning it on with the focus line at an edge puts the sharp band across the
  middle with both limits at the screen's edges. `dof_end2` in the sidecar;
  null (and every earlier sidecar) means one-sided.

### Changed

- The rotation pips are on the sharp line: the plane of focus is what turns.

## [0.53.0] - 2026-09-13

### Changed

- **The depth-of-field ramp lives in the screen's plane, not the photo's.**
  The plane of focus cuts the screen along a line and blur grows with depth
  *along the screen*, so iso-blur lines are parallel on the screen — and
  parallel lines on a receding plane converge in the photograph, like the
  phone's own edges. v0.51–v0.52 ramped linearly in photo pixels, which is
  only right for a screen seen square-on; on a steep fit the gizmo's two
  lines stayed parallel on the picture while the phone's edges did not. The
  ramp is now built in screenshot coordinates and projected through the
  fit's homography (`dof_space: "screen"` in the sidecar); sidecars without
  the key replay the old model, so v0.51–v0.52 saves reproduce.

- **The gizmo's far line is where the ramp ends, and strength is a thumb on
  it.** The dashed line used to mark a fixed reference blur, which put it off
  the photograph at ordinary strengths. Now it marks where the blur reaches
  its full amount — anywhere on the screen or a little past it (`dof_end`,
  recorded) — with the spacing between the lines as the ramp's length, a
  diamond sliding along the dashed line for how much blur, and the end pips
  on the dashed line to turn both. Nothing is ever out of reach.

## [0.52.0] - 2026-09-13

### Added

- **Depth of field is set on the result itself.** Two lines over the
  composite, the graduated-filter idiom: a solid line where focus ends (drag
  its centre to move it, either end pip to turn both lines), a dashed line
  where the blur reaches 30% of full — about 6px on a phone, where text stops
  being readable — dragged closer for a steeper falloff, further for a
  gentler one, out over the photograph if need be. Drawn in the photo's own
  pixels (the SVG's viewBox is the photo), so it stays aligned at every zoom;
  faint until the pointer is over the pane, solid while dragging; ⇧ snaps
  the angle to 15°. The sliders and the gizmo are one model.

- **A focus start.** The gizmo exposes what the sliders could not: where the
  blur *begins*. `dof_start` (0–0.95 of the screen's extent along the
  direction) keeps the screen sharp up to the line and ramps from there; 0
  is the whole-screen ramp every earlier sidecar meant, byte-identical.
  Both sidecars record it.

## [0.51.0] - 2026-09-13

### Added

- **Depth of field.** A blur that grows across the screen in one direction —
  a phone shot at an angle is a plane receding from the camera, so its far
  end is softer than its near end, and a pin-sharp screenshot across all of
  it gives the fake away. Two controls, direction and strength, off by
  default. Applied in photo space after the warp, to the premultiplied
  screen layer *and its mask* together, so the glass edge softens exactly as
  the bezel does — a sharp alpha edge inside a soft bezel is the tell in bad
  mockups. Spatially varying Gaussian, five levels blended per pixel; a
  still costs ~0.1 s, a 6 s video preview ~30% more than before. Strength 0
  is byte-identical to no blur, so every earlier sidecar reproduces; both
  sidecars record `dof_angle` and `dof_strength`. The live in-place playback
  cannot show it and says so.

- **Measure from photo** reads the direction and a starting strength off the
  photograph's own screen boundary: the blur width of each edge from the
  peak derivative of the step (σ = A / (√2π · peak)), a plane through the
  four, its gradient is the direction. Measured: sharp renders read 0.7–1.05
  px on every edge and answer *flat* (4/4, no false positives); blur planted
  toward 0°, 90° and 225° reads back within 20°. The estimator saturates
  around 5 px, so the strength it proposes is a floor, and the caption says
  so. On mockup *templates* the device is usually rendered sharp with the
  blur only on the background, so Measure answers flat there — set it by
  eye. The contrast-normalised Laplacian estimator was tried first and
  rejected: not monotonic with blur, angle errors to 87°, a sharp render
  measured 0.55.

- **Import from Figma can be cancelled.** The button reads Cancel while a job
  is pending; the job is marked cancelled (kept, not deleted) so an agent
  still exporting is told "already cancelled" instead of landing a file on a
  request nobody is waiting for. A non-Figma link is refused before it
  becomes a job. Relabelled from Export.

### Fixed

- **A source overwritten on disk loads its new bytes.** Import, clear,
  overwrite the file, import again showed the old picture in every place the
  browser had cached by URL — chip swatch, popover preview, recent-rail
  thumbnail, the canvas itself — while the composite was already new. Source
  URLs carry the file's mtime now, and recent thumbnails are keyed on it.

- The picker no longer gets a toast repeating the line under its own field.

## [0.50.0] - 2026-09-12

Two edge-strip improvements from use.

### Added

- **Contrast, a toggle on the edge strip.** A dark screen on a dark frame
  puts the boundary a few levels apart — on a hand-held black phone the left
  edge's strip spanned luminance 0–22 — and no zoom adds contrast. The strip's
  own 1st–99th percentile is stretched to 0–255 with the same gain on every
  channel, so hue is kept; flat strips are left alone. Viewing aid only: the
  composite, the fit and the saved file never see it. Remembered.

- **The strip shows which end of the edge will swing.** Grabbing an edge near
  one end pivots on the other; the canvas marked this with pips but the eye
  is on the strip while placing. The strip now draws the pivot pip and a
  double arrow at the swinging end, at the same 0.16/0.84 positions as the
  canvas, and the caption says it in words ("the left end swings, pivot on
  the right").

## [0.49.0] - 2026-09-12

### Added

- **`scripts/dev-root.sh` — test a checkout without reinstalling the plugin.**
  The desktop app snapshots an installed plugin per session and refreshes it
  only after *Check for updates*, so trying a change meant release → check →
  new session, and things went untested for want of the loop. With
  `~/.screengraft/dev-root` pointing at a tree, every session's `launch.sh`
  runs the UI from there instead; the badge reads `dev <sha>+` so it can never
  pass for a release; a stale path is ignored with a warning. `off` restores
  the installed copy. Opt-in by the file's existence — nothing changes for
  anyone who never creates it.

## [0.48.0] - 2026-09-12

Four defects from the first real use of v0.38–v0.47, all in the workbench.

### Fixed

- **Rotate no longer squashes the screenshot.** It was a quarter turn of the
  corner order, and a portrait screenshot on a phone fits only two ways: one
  press mapped 804px across the phone's long edge and 1748px down its short
  one — a 4:1 squash that also flattened the 107px corner rounding into a
  107×27 ellipse, which read as "square corners that don't fit the frame".
  Rotate now steps to the next orientation the screenshot fits without
  stretching: a half turn on a phone, a quarter turn on a near-square screen
  or where the screenshot's aspect suits the other edges. The button says
  which turn it made. Three audit checks pin the rule.

- **Swapping a source refreshes the Result pane.** Replacing a clip with a
  screenshot (or one photo with another while a fit was in hand) left the
  previous composite on screen, and the live layer kept playing the previous
  clip: choosing a source only redrew the canvas, and the still render will
  not take the pane away from a playing clip. Any change of file in either
  role now stops the clip, empties the pane, un-lights Save, and re-renders
  once the fit is ready. Reproduced on v0.47.0 before the fix, verified after.

- **The output-format control no longer moves when you switch it.** The
  selected label is weight 600, which is wider than 400, so choosing ProRes
  grew that segment and shifted the whole control. Each segment now reserves
  its label's bold width; measured identical left edge and widths in both
  states.

- **The chip's clear × is centred.** It was the × character at 15px, which
  carries its own ascent and sat above centre in the 22px disc. Drawn as a
  10px SVG in a flex centre: 0.00px off on both axes, measured.

## [0.47.0] - 2026-09-12

### Changed

- **The clear control sits inside the source chip, and you can see it.** It
  was a faint × beside the chip and read as a stray character. Still its own
  button in the markup (a button inside a button is invalid HTML), drawn
  inside the pill's right end on a raised surface with a border. Same
  keyboard stop, same name ("Remove photo" / "Remove screenshot").

- **A chip shows the file's own name and nothing else.** The size — and for
  a clip, the frame count — followed the name in the same 12px, and an
  upload's session copy is named `photo-<epoch>-<name>`, so a chip read
  "photo-1789204531-IMG… · 1800×1395": the one thing that identifies the
  file was the part cut off. The server returns the original name for
  uploads; the size and frame count moved to the chip's hover title with the
  full path. Chips are 220px at most, down from 300 — the name alone can
  afford it — which is most of the way to the corner bar clipping at 742px
  (the status pill is still queued).

- Removed `prettyDir()`, unused since v0.42.0 gave paths their own line.

## [0.46.0] - 2026-09-12

### Added

- **The screenshot lands the right way up on a tilted phone.** Detection
  orders corners by where they sit in the photograph — nearest the image's
  top-left first — and on a phone lying at ~45° that corner is the screen's
  physical bottom-left, so a quad right to 1% put the screenshot a quarter
  turn out, and the only fix was dragging all four corners to their
  neighbours' places. Which edge is the top depends on the *screenshot's*
  aspect, which detection cannot know; so the workbench decides: after a
  detection, if the screenshot is portrait and the quad's top edge is a long
  one (or landscape and short), the order is turned until they agree, taking
  the higher of the two candidate top edges so an upright photo is unchanged.
  Near-square quads (under 1.25) are left alone. Remembered and hand-placed
  fits are never touched — those are somebody's decision. The same rule was
  first written into `detect.py` and was wrong for every landscape screen;
  it lives in the page because the page is where both facts are.

- **Rotate 90°** beside Reset in the corner bar: the same four edges, the
  screenshot a quarter turn round inside them. Four presses is a full turn.
  The saved fit and the sidecar already carry corners in order, so a rotated
  fit comes back rotated.

- `ui-audit.js` exercises the orientation rule in both directions and on a
  near-square quad, on synthetic state, so it runs with no photo loaded.

## [0.45.0] - 2026-09-12

Eight mockup-grade photographs labelled (26 in all): steep shelf, low
angle, hard shadow, rock and quilted-leather textures, a phone on a stand,
two two-phone scenes. Seven answered at 0–5% unchanged. The eighth found a
geometry defect and a bench defect, both fixed. **25/26 good unaided, 0/26
confidently wrong, 0 good quads refused.**

### Fixed

- **`pick_innermost` judges nesting on refined corners, not raw polygon
  vertices.** On a phone photographed at ~45° the glass's raw vertex landed
  exactly on the body's raw edge line; `quad_contains` (every vertex 2px
  inside) said "not nested" and the body shipped 13% off with the glass —
  tier 2, 1% off, 87% of the body's area — one step behind it. Raw vertices
  sit on the corner arcs; refined corners are where the corners are, and the
  walk already computes them for the tier rule. They are cached once per
  candidate and handed to `pick_innermost` as `quad_of`. Replacing the
  containment test with area overlap was tried first and stepped into wrong
  inner quads on five photographs — the strict test is doing work, it was
  being fed the wrong quads. Two-phone mockup: 13% → 1%.

- **The bench scores a quad order-invariantly.** The label's corners start at
  the *screen's* top-left (where the person put the handle); the detector's
  start at the corner nearest the *image's* top-left. On an upright phone
  those agree; on one at 45° they are one position apart, and a candidate
  sitting exactly on the label scored **179%** — reported as "never proposed"
  and "confidently wrong" on a photograph detection had at 0%. `worst()` now
  takes the best of the four cyclic rotations, and a new line reports
  photographs whose quad is right but whose first corner is not the screen's
  top-left. One of 26 today; the workbench has no control for it (SG86).

## [0.44.0] - 2026-09-12

Four more labelled photographs (18 in all) found one confidently-wrong answer
and one good quad refused. Both fixed; the bench is **17/18 good unaided,
0/18 confidently wrong, 0 good quads refused**, every answered photograph
within 5% of its label. The one abstention (iPhone-8) is honest.

### Fixed

- **A front-and-back mockup answered 105% off with confidence.** The edge
  channel's top-scoring candidate was the bounding box of *both* phones
  (score 1.0; tier 1, because one of its corners is the back phone's rounded
  body), and the screen sat inside it at 48% of its area — under
  `NEST_FLOOR`, so `pick_innermost` could not step to it on the ratio. The
  walk-order rule from v0.43.0 now has a second case: past a **tier-1** top,
  a tier-2 candidate may move ahead only when it is **nested inside** that
  top — the same finding narrowed to the part whose four corners agree, which
  is how `arbitrate()` already reads a confident quad inside a loosely rounded
  one. The form without the nesting condition was measured and rejected the
  same afternoon: the tone channel promoted a disjoint tier-2 patch 202% off
  on two photographs and lost both answers to abstention. On 18 photographs
  every tier-2 that should jump a tier-1 top overlaps it at ≥ 0.95 and every
  one that must not overlaps it at 0.00; `NESTED_OVERLAP = 0.90` is now one
  shared constant for arbitration, the walk and the veto. iPhone-17: 105% →
  5%. iPhone-9_16-pro, the 15% from v0.43.0: → 1%.

- **A card on the screen no longer vetoes the screen.** On iPhone-15
  arbitration ruled a confident tone quad to be content drawn on the edge
  quad's screen (9% of its area), and the abstention veto then read that same
  card as a credible peer 32% of the diagonal away and abstained holding a
  quad 0% from the label — the bench's "good quad refused". A veto is for two
  screen-shaped findings in two *places*; a quad nested inside the winner is
  one place. What this gives up: the veto used to also rescue an
  outer-wins-on-ratio ruling when a confident screen sat inside a confident
  larger rounded object at under 55% of its area. No photograph has shown
  that shape; the test fixture that did was `table` containing `screen`, and
  it now sits beside it as its name always claimed.

### Changed

- **Every trace row carries `tier`.** The walk reads tiers; the bench could
  not see them. Now it can.

- **`MAX_RADIUS_SPREAD` re-derived on clean geometry and left at 2.0** (the
  third time). Over 206 tier-1 candidates on 18 photographs, correct ones
  spread from 0.51 to 1.93 and wrong ones from 0.53 to 2.00 — no margin
  anywhere. The threshold is not what separates them.

## [0.43.0] - 2026-09-12

### Fixed

- **A corner with no arc at all no longer counts as rounded.** Five new
  labelled photographs (14 in all) surfaced the first confidently-wrong answer
  since the bench existed: on iPhone-8 the tone channel accepted a quad whose
  per-corner radii were `[0, 0, 56, 56]` — two real arcs and two corners that
  were not rounded at all. The spread test (`max − min ≤ 2.0`) is a similarity
  test, and two zeros and two 56s happen to fall inside it once the radius is
  normalised. The quad won as tier 1 against the correct tier-0 edge quad and
  shipped **124% off**. `has_rounded_corners` now refuses any quad whose
  smallest corner radius is exactly zero: a radius of zero means no arc was
  measured, and a screen corner without an arc is not evidence of a screen.
  iPhone-8 abstains honestly now (the 1% candidate is not reachable — see
  below). Pinned both ways in `tier_checks`, fault-planted.

### Changed

- **Within a channel, the walk looks past a sharp winner when a rounded one
  exists.** `_finalize` walks candidates by score, and score is fill × size —
  a device body is bigger than its screen and just as well filled, so on two
  photographs the body outscored the screen inside it. The rule is narrow on
  purpose: only when the top-scoring candidate has **no** rounded corners
  (tier 0) do tier-2 candidates move ahead of it; a winner with rounded corners
  of its own is left alone. The whole-walk tier-first order was measured and
  rejected in v0.40.0 (a tier-2 *wrong* candidate sits deeper in the list on
  three photographs); this narrower form fixes iPhone-11 and iPhone-3 without
  touching those. `walk_order_checks` pins the rule with a big sharp rectangle
  around a smaller rounded one; the plant (`if False:`) puts the answer 345px
  off.

- **Bench, 14 labelled photographs:** good unaided **12/14** (was 10/14 the
  moment the new labels landed), confidently wrong **0/14** (was 1), abstained
  1 (iPhone-8, holding a quad 103% off — an honest "I don't know"), never
  proposed 0. iPhone-9_16-pro answers at 15%: the 1% candidate ranks eighth
  and the accepted quad is tier 1, so the rule above does not fire. Still
  waiting on within-channel ranking, which remains score alone.

- **`iPhone-12_15-pro.webp` cannot be read by OpenCV** (an animated or
  lossless WebP variant the build does not decode) and is skipped by the
  bench; it needs a PNG or JPEG export to become a label.

## [0.42.0] - 2026-09-11

### Changed

- **Notifications are readable.** Four things, all reported from use:
  - **13px, not 12** — the same size as the rest of the page.
  - **A path is in the message's own typeface.** It was `<code>` at the
    browser's monospace default: a second face for no reason.
  - **A path has its own line.** The sentence ends, then the path — complete,
    with `~` for home, no longer elided to its last two segments — wrapping at
    its slashes rather than mid-filename.
  - **The error glyph is not the Close glyph any more.** It was the `×`
    character, the same character as the Dismiss button beside it. Each kind
    has a silhouette nothing else on the page uses: circle-tick, triangle-bang,
    octagon-bang, circle-i. The one × left in a toast is the control that
    closes it.

- **`scripts/build-plugin.sh` refuses to build a version whose release tag
  already exists when the tree has moved since it.** A version is a promise
  about bytes; `check_package.py` catches the three version fields drifting
  from each other but cannot see the same number being reused for different
  contents, which is how v0.23.1 came to exist. Tags are fetched first (they
  live on GitHub — `gh release` creates them there); offline means no tag and
  no refusal. `SCREENGRAFT_REBUILD=1` rebuilds the tagged bytes on purpose.
  Not packaged, so no release carries it; it applies from the next one.

### Investigated and not changed

- **The one remaining labelled photograph that abstains (iPhone-7).** The
  edge channel accepts a badly skewed quad — raw corners `[724,290] [978,283]
  [1060,1274] [460,944]` — that rail refinement straightens into a plausible
  rectangle 59% off, and the true screen (0.6% off, ranked fourth) is only 43%
  of its area, below `NEST_FLOOR`, so `pick_innermost` cannot step to it.
  Contour fill was the candidate discriminator (0.70 against the screen's
  0.99) and it does not hold across the corpus: wrong candidates reach 1.00 on
  most photographs and correct ones dip to 0.02. No principled gate; it stays
  an honest abstention, resolved by one click.

## [0.41.1] - 2026-09-11

### Fixed

- **Clearing a source while a render is in flight is refused (409).** The
  worker would otherwise finish and publish an output and sidecar from a
  source that is no longer loaded — the stale artefact `/api/clear` exists to
  prevent. Found in the v0.41.0 code review; route-tested mid-render.
- Clearing the photo also clears the edge-view strip, and moves focus to the
  now-empty chip rather than dropping it on `<body>`.

## [0.41.0] - 2026-09-11

### Added

- **A filled source chip has a clear control.** There was no way to start
  over: picking a different file was the only exit, and a reload restores the
  session's fit, so "start again" was not reachable from the page. A small
  round × sits beside each chip once it is filled — beside, not inside: the
  chip is one `<button>`, and a button inside a button is invalid HTML that
  browsers repair unpredictably. It is its own keyboard stop, named *Remove
  photo* / *Remove screenshot*, which is also what keeps it distinct from the
  fit bar's **Reset** (that resets the quad; this un-chooses a source).

  What goes with a source is decided by what the source *is*: the photo owns
  the corners (a fit you saved comes back on re-pick — v0.26.0 — and the
  status line says so); the screenshot owns the video state and the fitted
  frame, and the corners stay because they are on the photo; either owns the
  session output, which is dropped so **Send to Claude cannot hand over a
  composite made from a source that is no longer loaded**.

  `POST /api/clear {role}` is the mirror of `/api/use`, guarded by the same
  role whitelist. Route-tested over HTTP: each thing kept or dropped is
  asserted from the session file, not the response.

### Fixed

- **`test/ui-audit.js` was counting status toasts as info icons.** Its
  selector was `.info`; a toast is `.toast.info`, so any audit run within a
  few seconds of loading a source reported "5 tips / 6 icons". Reported twice
  on 11 Sep and blamed on a debug probe the first time. `button.info` now.

## [0.40.0] - 2026-09-11

### Changed

- **The Canny sweep no longer goes blind on a dark photograph. Never-proposed
  went from 2/9 to 0/9 on the labelled bench; good unaided is 8/9;
  confidently-wrong stayed 0/9.**

  `detect_edges()` anchored its thresholds on the image median — the standard
  "auto Canny". A black phone on a black backdrop has a median of 0..4, so
  every sweep point landed at `hi ≤ 7` and Canny fired on every pixel of
  noise: the edge map was a solid sheet and no closed quad survived it. Both
  photographs on which nothing near the screen had *ever* been proposed were
  exactly this — grayscale renders, surround median 1 and 4 — and the edge
  channel returned **zero** candidates on them at every scale and in every
  colour view tried.

  An Otsu-anchored sweep now runs alongside the median one (the saturation
  channel already anchors on Otsu for the same reason). On the two dark
  photographs the screen is proposed at 9% and 12% unrefined — the same range
  every other photograph's nearest candidate sits in — and on the other seven
  the nearest candidate is unchanged. One resolves at 5%; the other still
  abstains (see below).

  Pinned by a built fixture: a bright rounded screen on a near-black frame on
  a near-black ground with sensor-like noise, median 3. The fault plant is the
  old code itself — the median-only sweep, reproduced in the test, produces
  zero candidates on it.

### Investigated and not changed

- **Ordering the within-channel walk by shape tier before score.** It fixed
  the one remaining abstention (a 59%-off body outscoring a 0.6%-off screen
  ranked fifth) and took *good with one click* to 9/9 — and it dropped three
  other photographs to honest abstentions, because a **tier-2 wrong
  candidate exists deeper in the list** on each of them. The 6× margin behind
  the tiers was measured on channel-*accepted* results, and it does not hold
  for every candidate a channel generates. Reverted. The remaining case is a
  within-channel ranking problem and is recorded as such.

## [0.39.0] - 2026-09-11

### Changed

- **One region-vs-edge arbitration, read both ways, tiers before ratio. Good
  unaided is 7/9 on the labelled bench (from 4/9); every answered photograph
  is within 5% of its label; confidently-wrong stayed 0/9.**

  Three things were wrong with how the surviving region channel (tone or
  saturation) was weighed against the edge channel, each found by reading the
  candidate list against the labels rather than guessing:

  - **Saturation never got the nesting rules.** Only tone did; saturation vs
    edge fell through to "saturation wins". On iPhone-4 that returned a
    saturation quad 18% off wrapped around an edge quad 3% off at 94% of its
    area — the exact screen-in-body shape the tone branch already read.
  - **Nesting was only read with the region quad inside the edge quad.** An
    edge quad inside a region quad was "not nested". Read on whichever is
    inside now.
  - **The area ratio cannot tell content-in-screen from screen-in-body on its
    own.** A UI content region at 96% of the screen with loose corners sat
    inside a confident edge quad on two photographs and was called "a screen
    inside a body" — 15% off, twice. And the reverse: a confident screen at 34%
    of a loosely rounded table would have been called content on it. Evidence
    tiers decide those; at equal tiers the ratio still does, unchanged, which
    is what keeps the gradient-screen fixture (41%, both tier 2) resolving to
    the edge quad as before.

  Six new hand-built arbitration cases in `test_detect.py`, two fault plants.

## [0.38.0] - 2026-09-11

### Changed

- **Evidence tiers in detection: a weaker result can no longer outrank or
  veto a stronger one. Good unaided went from 1/9 to 4/9 on the labelled
  bench; confidently-wrong stayed 0/9.**

  Every channel result already carried two shape signals — a *confident*
  corner radius (four per-corner estimates agree within 50%) and a *rounded*
  one (within 2×). Measured over ten labelled photographs, every channel
  result: **every confident quad was on the screen** (worst spread 0.24) and
  **every wrong quad was ≥ 1.43 or unmeasurable** — a 6× margin. The rounded
  tier alone does not separate them (a correct 1.42 beside a wrong 1.43).

  Two rules were letting tier 1 beat tier 2:
  - **Arbitration.** When tone and edge did not nest, tone won unconditionally
    on the argument that its band assumption holding was itself evidence. On
    two photographs that handed the answer to a tone quad **159% and 249%**
    off — with corner spreads of 3.4 and 19.9 — over an edge quad at **0%**
    with a confident radius. Now the higher tier wins; at equal tiers the old
    rule stands, and the nesting rules are untouched (the gradient-screen
    fixture still resolves the same way).
  - **The abstention veto.** A peer could force an abstention by disagreeing
    grossly if it merely had rounded corners. On iPhone-2 a tone quad **143%**
    off at spread 1.43 vetoed a confident edge quad at **0.3%** — the bench's
    one "good quad refused". A peer must now match the result's tier to veto.
    Two confident quads far apart still abstain; that veto is pinned.

  No new thresholds. `shape_tier()` ranks the two that existed; the
  arbitration and gate are now `arbitrate()`, testable on hand-built results.
  Both rules fault-planted.

  `validate_quad`, `MAX_RADIUS_SPREAD` and `NEST_FLOOR` were reviewed against
  the same bench and **left alone**: nothing in it indicts them — no good quad
  is refused and nothing is confidently wrong — and moving a threshold without
  an indictment is tuning.

## [0.37.0] - 2026-09-11

### Added

- **Apple's corners are squircles, and now so are ours.** A rounded corner used
  to be a circular arc, where curvature jumps from zero to 1/r at the tangent
  point and leaves a seam you can see. Apple's displays use a continuous curve
  instead; Figma exposes the same control as **corner smoothing**, 0-100%, and
  labels 60% "iOS".

  `compose()` and `compose_video()` take `corner_smoothing` (0-1). The
  construction is Figma's own — cubic, circular arc, cubic per corner, from
  their write-up and MartinRGB's derivation — not a superellipse approximation.

  **It is automatic, from the device preset.** Every Apple preset carries 0.6;
  Android and the square entries carry nothing. A photograph of an iPhone does
  not have a smoothing preference, it has a shape — which is why this is not a
  control. It follows the selected preset even when the radius was *measured*
  from the photograph, because a measured radius is still a radius on that
  device.

  Verified rather than asserted: at smoothing 0 the construction collapses to a
  circular arc to **1.4e-14px** over r=80, and the whole mask comes out
  **byte-identical** to the analytic path. At 60% the curve meets both edges
  parallel to within 0.001°, spans exactly (0,p) to (p,0), and p is exactly
  (1 + smoothing) x r.

### Changed

- **Old saves keep their shape.** `corner_smoothing` defaults to 0 everywhere,
  and a sidecar written before this release has no such field — so it
  re-composes to the pixels it always did. That is the sidecar's contract and it
  outranks making old saves consistent with new ones.

### Fixed

- **`test_sidecar.py`'s contract check could not fail, and had not been able to
  for three releases.** It found the sidecar dicts with
  `re.search(r'result = \{(.*?)\n\s*_write_json_atomic', src, re.S)`, which was
  wrong twice over: `re.search` takes the FIRST match and the video dict comes
  first in `ui.py`, so the **still** contract was being checked against the
  **video** sidecar; and `.*?` still spans everything between, so the key set it
  compared against included route response keys (`started`, `running`, `saved`)
  that are not sidecar keys at all. Both faults made the check pass by looking
  at a superset.

  Planting the removal of `corner_smoothing` from the still sidecar changed
  nothing at all — which is how this was found. The dicts are located by
  **parsing `ui.py` with `ast`** now. Three faults planted, three caught: key
  missing from the still sidecar, key missing from the video sidecar, and the
  route recording the value but not applying it (a new round-trip case, because
  recording and applying are different contracts).

- **~20 lines of prose were sitting in the stylesheet as invalid CSS.** A
  comment added in v0.35.1 was appended *after* its block had already closed,
  leaving a stray `*/`. Browsers dropped it silently. Found by `deadcode.py`
  reporting a phantom `.js` class — it was reading the text "ui-audit.js" out of
  what it correctly believed was a selector.

## [0.36.0] - 2026-09-11

### Changed

- **The iPhone corner-radius presets are now derived per model, not estimated,
  and there are eleven of them instead of two.** Darek asked whether all iPhones
  share a radius. They do not, and the spread is large enough to matter: 39pt on
  an iPhone X against 62pt on a 17 Pro.

  Radius in points comes from Apple's private `UIScreen._displayCornerRadius`
  (collected by [kylebshr/ScreenCorners](https://github.com/kylebshr/ScreenCorners));
  width in points from the logical screen size. Both are exact, so the fraction
  is too.

  | group | radius | width | frac |
  |---|---|---|---|
  | iPhone 17 Pro / 17 / 16 Pro | 62.0 | 402 | **15.4%** |
  | iPhone Air | 62.0 | 420 | **14.8%** |
  | iPhone 17 Pro Max / 16 Pro Max | 62.0 | 440 | **14.1%** |
  | iPhone 16 / 15 / 15 Pro / 14 Pro | 55.0 | 393 | **14.0%** |
  | iPhone 16 Plus / 15 Plus / 15 Pro Max / 14 Pro Max | 55.0 | 430 | **12.8%** |
  | iPhone 14 Plus / 13 Pro Max / 12 Pro Max | 53.33 | 428 | **12.5%** |
  | iPhone 16e / 14 / 13 / 13 Pro / 12 / 12 Pro | 47.33 | 390 | **12.1%** |
  | iPhone 13 mini / 12 mini | 44.0 | 375 | **11.7%** |
  | iPhone 11 Pro / XS / X | 39.0 | 375 | **10.4%** |
  | iPhone 11 / XR | 41.5 | 414 | **10.0%** |
  | iPhone 11 Pro Max / XS Max | 39.0 | 414 | **9.4%** |
  | iPhone SE / 8 / 7 | — | — | **0%** (square) |

  Note that **width changes too**, so two models with the same radius land on
  different fractions: 55pt is 14.0% of a 393pt iPhone 16 and 12.8% of a 430pt
  16 Plus. A single "iPhone" preset could never have covered this — the old two
  entries were 14.0% and 12.8%, i.e. only the middle of the range.

  Preset ids `phone-iphone` and `phone-iphone-max` keep their meaning, so an
  existing choice still resolves.

### Added

- The radius caption now names the **full** model list and the numbers behind
  it — "12.8% of screen width — preset: iPhone 16 Plus, 15 Plus, 15 Pro Max,
  14 Pro Max — 55pt over 430pt". The dropdown label is cut to what a closed
  `<select>` can show (measured: ~254px at 13px), and a `title` on an `<option>`
  is not reliably rendered by a native macOS popup — so the caption is the only
  place the exact membership can actually be read. A preset is a claim about a
  device; it should show its working.

### Known limits

- **Apple's display corners are a continuous curve, not a circular arc**, and
  `compose()` applies a circular radius. Matched by number they are not matched
  by shape — a continuous corner reads slightly tighter at the diagonal. The
  preset is a starting position; a measured radius beats it when the photograph
  offers one.
- The plain **iPhone 13** is not listed by ScreenCorners while the 13 Pro is.
  It shares the 390×844 display, so 47.33pt is an inference here — the only
  entry in the table that is not directly attested.

## [0.35.1] - 2026-09-11

### Fixed

- **The Realism and Corner radius sliders lost their orange fill in v0.33.0.**
  Reported by eye; nothing in the project could have caught it.

  `@property` is a **page-wide type declaration**, not a scoped one. The render
  progress bar registered `--p` as a `<percentage>`, and the range sliders had
  been setting `--p` to a unitless fraction for months and reading it back as
  `calc(var(--p, 0) * 100%)`. Registering the name typed it everywhere at once:
  the unitless `0.35` became invalid, fell back to the registered initial value
  `0%` — and the `0` fallback in `var(--p, 0)` never fired either, because a
  registered property always has a value. `calc(0% * 100%)` is invalid, so the
  whole gradient was dropped and the track rendered empty.

  The progress bar's property is `--fill` now. Confirmed by planting the
  collision back at runtime: every slider loses its accent the instant `--p` is
  registered.

  **The rule: before registering a name with `@property`, check who else already
  writes it.** Second time a page-wide fix in this file has caught unrelated
  components, after `[hidden]{display:none !important}`.

- `test/ui-audit.js` gained the check that would have caught it: no name
  declared with `@property` may also be set as a plain custom property. It reads
  the stylesheet **text**, because WebKit does not expose `@property` through
  `cssRules` and a scan of those finds nothing — a check that cannot fail is
  worse than no check. Fault-planted: restoring the collision names `--p` and
  turns it red. 22/22 otherwise.

## [0.35.0] - 2026-09-11

### Added

- **A real segmented control (Figma 84:177), and the output format now uses it.**
  Web/ProRes had been a *stepper* — ordinary buttons butted together, which is
  right for `-`/`+` and wrong for a choice: two adjacent buttons read as two
  actions, and the pair had been borrowing the device chip's selected step to
  say which one was on. The component the design file specifies is a **recessed
  track with one raised thumb**, so the selected option is the only thing at
  button elevation and the control reads as a switch with a position.

  The drawn thumb is 24px, which with 2px of track padding and a 1px border
  makes the control 30px against 28px neighbours in the top bar — a 2px mismatch
  in that row has already shipped once as a bug (v0.32.0). The thumb is **22px**
  here so the track lands on 28px exactly; padding, gap, border and both radii
  are as drawn.

  The contrast audit gained two checks for it. The thumb against its track is
  **1.31:1** and accepted: the label is the channel, not the surface — selected
  reads 11.89:1 on the thumb against 5.97:1 for unselected on the track, a
  2.60:1 step between the two labels, plus 400 → 600 weight.

### Changed

- **Button tokens re-picked against the polished Figma matrix (4:14).**
  - **Md is radius 8, Sm is radius 6** — one rule, both variants. Md had been
    6px here while Primary/Md was 8px, so the neutral and accent buttons sitting
    beside each other in the top bar were not the same shape.
  - **Hover's border is `border/edge-mid`** (`#494a50`, was `#3f4045`).
  - **Pressed keeps `border/edge`** (`#3a3b41`, was `#2b2c31`) — pressing a
    control must not make it look unavailable.
  - **Default/Disabled recesses**: `surface/raise-low` with a `border/edge-low`
    border, where it used to keep the raised surface and dim only the label. A
    control you cannot press should not sit at the same elevation as one you
    can.

  New base tokens `--raise-low` and `--edge-low`; `button.primary.sm`'s radius
  override and three restatements of `--r-md` are gone, so `.sm` now wins on
  size by the cascade instead of by luck.

### Not applied, deliberately

- The Figma layer for Default/Disabled puts the **label at 50% on top of
  `text/faint`**, while the Button component's own description says *"Disabled
  keeps its label readable rather than using opacity."* The two disagree.
  Measured, the description is also the better outcome: `text/faint` on the
  recessed surface is **3.37:1**, the same label with the multiplier is
  **1.80:1**, and what shipped before was 3.01:1 — so the new surface makes the
  label *more* readable than it was, and the multiplier would have made it the
  dimmest text in the tool. The description wins pending a ruling; the contrast
  audit now measures this label every run.

## [0.34.0] - 2026-09-11

### Changed

- **The Canny path recovers its corners now, and that was the largest fixable
  bucket of detection error in the tool.** `approxPolyDP` cannot place a vertex
  on a rounded corner — there isn't one — so it settles for a point on the arc,
  inside where the two sides would meet, and every side comes up short. On real
  photographs that is **9-11% of the screen's own width**. `refine_corners()`
  already cures it by intersecting the fitted sides, and the Canny path had been
  banned from calling it since v0.13.0 on the grounds that a ring contour
  corrupts the line fits. The ring was a real problem; the ban was the wrong
  answer to it.

  **Rail selection** fixes the fit instead: of the points assigned to one edge,
  only those within a couple of close-kernels of the outermost are fitted. That
  is the ring's own outer rail, and content edges drawn inside the screen are
  excluded by construction rather than by a threshold on how bad the result
  turned out. A filled region has one rail, so nothing changes there.

  Measured over eight hand-labelled photographs — the error of the closest quad
  any channel proposed, as a percentage of the screen's own width:

  | photo | before | after |
  |---|---|---|
  | iPhone-2 | 9% | **0%** |
  | iPhone-3 | 9% | **0%** |
  | iPhone-5 | 9% | **0%** |
  | iPhone-4 | 8% | **2%** |

  **Good with one click went from 1/8 to 4/8.** Confidently wrong stayed at
  **0/8**, which was the constraint throughout. Unaided answers are unchanged at
  1/8: on the photographs that still fail, the screen is now proposed almost
  exactly and loses the ranking, or is never proposed at all — both of which are
  now clean problems rather than problems measured through a geometry defect.

  The three photographs where nothing near the screen is ever proposed are
  untouched by this and need recall work.

### Added

- `test/test_detect.py` builds a two-rail ring with a content edge carrying as
  many points as the screen edge beside it — what a UI card border actually
  produces in a Canny image. Fitting the whole ring lands **39.6px** out; rail
  selection holds **8.5px**, against **13.0px** for the polygon approximation it
  started from. A one-rail silhouette moves 0.00px, so the region channels are
  provably undisturbed.

## [0.33.3] - 2026-09-11

### Fixed

- **The detection trace reported a quad the detector never returned.** Every
  row carried the polygon approximation its candidate was built from, but the
  walk refines corners before it validates, so the row and the answer differed
  by the whole rounded-corner inset — 6.4px on the synthetic fixture, 9% of the
  screen's own width on real photographs. `test/bench_detect.py` reads those
  rows, so its "best candidate" column understated every candidate by that
  amount: a corner-accuracy change that took the nearest proposal from 10.7% to
  0.4% read as having bought nothing. Rows now hold the refined quad, and a new
  check asserts the winning row equals the answer it supplied (fault-planted:
  restoring the old behaviour fails it at 6.4px).

### Investigated and not changed

- **Why candidates sit ~9% of the screen's width inside the true screen.** The
  mask is not the cause: the tone contour straddles the label, median 8px
  *outside* it. `approxPolyDP` is — it puts its vertices on the rounded corner
  arcs, and `refine_corners()` exists to undo exactly that, but the Canny path
  refuses refinement by construction. Refining it recovers most of the loss on
  the nearest candidate (11.5% -> 4.7%, 10.7% -> 0.4%, 9.5% -> 6.7%).

  **It still ships unrefined.** The pipeline returns the highest-*scoring*
  candidate, not the nearest one, and refining moves the ranking and the
  abstention evidence with it: end to end the change cost one answer
  (18% -> abstained at 57%) and one click-assisted answer, and a variant that
  gated refinement on the per-edge fit residual produced a **confidently wrong**
  answer at 129% — the one failure this tool refuses to have. Reverted whole.
  Corner accuracy is downstream of ranking; ranking is the next piece of work.

## [0.33.2] - 2026-09-11

### Added

- **`test/bench_detect.py` — detection measured against corners a human placed.**
  Not in CI and deliberately so: it needs photographs, and photographs are not in
  this repository. It is the thing to run when a detection change needs judging,
  and again afterwards. **The labels come from the fit store** — every composite
  saved through the workbench records its four corners keyed by the photo's own
  pixels, so a folder of photographs plus ordinary use *is* the corpus, and
  nothing is labelled twice. It separates the three outcomes that looked
  identical before the trace existed: **recall** (was the screen ever proposed),
  **ranking** (did the proposed one win) and **the gate** (was a correct answer
  then refused). Errors are a percentage of the screen's own width, because 30px
  means different things on a 4000px photograph and a 900px one.

  On the eight labelled photographs today: **1 good unaided, 0 confidently
  wrong, 6 abstained with none of them refusing a good quad, 3 never proposed at
  all.**

## [0.33.1] - 2026-09-11

### Fixed

- **The Web/ProRes control was on screen for a still**, where there is no format
  to choose. It carries the `hidden` attribute and the attribute did nothing:
  **any author rule that sets `display` beats the browser's own
  `[hidden]{display:none}`**, whatever its specificity, because author styles win
  over the UA stylesheet by cascade origin. `.stepper{display:inline-flex}` was
  quietly switching the attribute off.

  This is the **third** component to need it — the clip bar and the result
  video were each patched one at a time, the video one after shipping as a black
  panel under the composite (v0.30.1). One rule now covers every case and the
  two hand-patched ones are gone: `[hidden]{display:none !important}`, with the
  `!important` there deliberately, because it is the only thing that survives the
  next component that styles `display` without thinking about it.

  Found by the code review of v0.32.0/v0.33.0, one release after writing the
  comment that explains the same mistake thirty lines further down.

## [0.33.0] - 2026-09-11

### Changed

- **The Render button is the progress bar (SG71).** Darek's design: the track is
  the disabled accent the button already wears while it is busy, the fill is the
  lighter rest accent — the same colour one step apart, so nothing new enters the
  palette — and the fill is the height of the button minus its strokes. The label
  carries the number: *Rendering 42%*.

  Two background layers rather than a child element, because the label on this
  button is written by several different code paths and a required child span
  would mean every one of them had to maintain it. `background-clip: padding-box,
  border-box` is what puts the fill inside the strokes and the track behind them.
  `role="progressbar"` and `aria-valuenow` come with it: a colour change is not
  information a screen reader can reach.

- **The spinner is gone, and the reason it was there does not survive reading.**
  v0.19.0 replaced a determinate percentage with a spinner because the number
  "read as busier than the work felt". That judgement was made against a
  percentage that never moved — the poll feeding it had been broken since
  v0.18.0, found only yesterday. A number that never updates does read as noise;
  so would any number. **A decision made against a broken measurement is not a
  decision**, and the comment in the stylesheet now says so where the spinner
  used to be.

## [0.32.0] - 2026-09-11

### Changed

- **The output format moved out of the Result pane and up beside Render.** It
  was the fifth control in the clip bar — after the label, the scrubber, the
  frame count, Play and Preview — and it is not a thing you judge a fit with. It
  is a render setting, so it sits with Render.

  The top bar now reads **Format · Render · Send to Claude**, which is the order
  of the work: choose how it will be written, render it, then send it. *Send to
  Claude* moved to the end for that reason; it was first.

  It stays a **segmented control**. Two mutually exclusive options of equal
  weight is what one is for, both stay readable without a click, and it carries
  no accent — so the one-accent-on-screen rule is untouched. It is absent
  entirely for a still, the same rule the clip bar already follows. Explored
  against four alternatives first (split button, rail section, cycling chip,
  settings menu) in `wireframe/1109-render-format-control/`; the three that
  saved more space all did it by hiding which format is selected.

### Fixed

- **The frame scrubber has a floor.** Removing the format control stopped the
  clip bar overflowing at 742px — and the space it freed went to the other
  controls while the slider collapsed to **four pixels**, measured. The bar is
  allowed to scroll; the one control that is useless when small is not allowed
  to be the one that gives way. `min-width: 140px`, verified at 742px and
  1600px.
- The top-bar segmented control is 28px, matching its neighbours. In the clip
  bar everything was 24px so it matched by default; beside a 28px button that
  reads as a misalignment rather than as hierarchy.

## [0.31.1] - 2026-09-11

### Changed

- **The clip bar reads as a player.** Play is an icon that becomes a **stop**
  icon while the clip runs — one control, because "is it running" is one
  question and two buttons would leave one of them meaningless at all times. The
  icon follows the video's own `play`/`pause` events, not the button press, so
  it stays honest if playback stops by itself. Icon-only, so the accessible name
  changes with the state too: a screen reader on a square still saying "Play"
  is being told the opposite of what is happening.
- **Stopping returns to the fitted frame** rather than leaving playback wherever
  it landed. That frame is the one the edges were matched against and the one
  the light match is bound from, so it is the only frame the fit is a statement
  about. The frame scrubber also moves the paused clip now — the number and the
  picture were able to disagree.
- **"Render preview" is "Preview"**, and both controls moved after the frame
  scrubber, Play first. Viewing controls sit with the other viewing control; the
  format stepper is about the output and stays at the end.

### Fixed

- **`/file` answers Range requests.** A browser cannot seek in a video the
  server will only hand over whole: it plays from the start and every jump snaps
  back to zero. Measured in the live page before the fix — setting `currentTime`
  to 9.0s read back as **0.0** — which made "stop returns to the fitted frame"
  quietly impossible and broke the video element's own scrubber with it. Single
  ranges answer 206 with `Content-Range`; `Accept-Ranges` is what tells the
  player it may seek at all; anything unparseable falls back to the whole file,
  as the spec asks.
- **The icon button was 13px wide at 742px.** A `width` on a flex item in a
  nowrap row that overflows shrinks to its content — the glyph and its border.
  `flex:none` and a `min-width`; measured back at 28px.

## [0.31.0] - 2026-09-11

### Added

- **Play runs the clip on the photo, live, with no wait.** The fit is a
  homography, and a homography is precisely what CSS `matrix3d` applies — so the
  browser can put the moving video on the device's screen itself. Press Play and
  it is there: **1.5 seconds to first frame against 10** for the composited
  version, and it keeps up while you drag a corner or change the zoom.

  What it is faithful about, and what it is not, because the page says both:
  the **geometry is exact** — the same four corners, verified against the fit at
  four zoom levels and after a drag, **0px** difference in every case — and the
  **corner radius** is applied in the video's own pixel space, which is where
  `compose()` applies it. **Emissive is approximated** with `screen` blending:
  the same idea as the real blend (the screen's own light plus the glass beneath
  it, which is why a true-black UI stops reading as a hole), not the same
  arithmetic. **The colour grade and the grain are not in this view at all** —
  they are per-frame Python, and they are what the rendered preview costs its
  seconds on.

### Changed

- The composited preview is now **Render preview**, a second control. It is the
  only view that shows the true look over time, so it stays; Play is what you
  reach for to judge placement and motion.
- The status line describes **what the pane is showing**. The still keeps
  re-rendering behind a playing clip — deliberately, so switching back is
  instant — but it no longer narrates over it.

## [0.30.1] - 2026-09-11

### Fixed

- **An empty video box sat below the result the whole time.** `#outImg,#outVid
  {display:block}` is an ID selector, so it beat the browser's own
  `[hidden]{display:none}` — which switched the `hidden` attribute off for both
  elements. Invisible on the `<img>` (no source, no height) and glaring on the
  `<video>`, which renders a black panel with a play button. The clip is meant
  to **replace the still in the same frame**, not appear under it, and now does.
  Reported from a screenshot: *"there is some video layer at the bottom below
  result"*.
- **A preview is six seconds, not the whole clip.** Compositing a 2460-frame
  recording took about as long as the render it exists to save you from, which
  makes it a render with a worse output. It now composites `PREVIEW_SECONDS`
  from the frame you fitted on — measured on a 21s clip: **10s against 18s for
  the full length**, and far more on a longer one. Move the scrubber to preview
  a different moment. The pane says how long the segment is and where it starts,
  because a preview that silently showed six seconds of a forty-second clip
  would look like a broken render.

### Changed

- `compose_video()` takes `start_frame` and `max_frames`. Only the preview passes
  them, so the full-clip contract — frame 0 of a render equals the still
  composite, byte for byte — is untouched.

## [0.30.0] - 2026-09-11

### Added

- **Play the composite before rendering it (SG73).** The Result pane composited
  a single frame, so every judgement about a clip was made on a still — and the
  two settings most likely to misbehave over time are exactly the two a still
  cannot show. The **light match is bound once**, from the fitted frame
  (deliberately: measuring per frame makes the screen pulse as the UI scrolls),
  so a badly chosen frame is wrong for the whole clip. The **emissive blend**
  mixes the screenshot with the glass beneath it, so its effect moves with the
  content's own brightness. Press **Play**, in the Result pane before the frame
  scrubber, and the clip is composited and played there.

  It is a **proxy through the same pipeline**, not a shortcut: the photo is
  downscaled to 720px and the quad scaled with it, so grade, grain and emissive
  are all applied and what you watch is what will render. The obvious cheap
  version — a `<video>` under a CSS perspective transform — would show the
  geometry moving and none of those three, which is to say none of what this is
  for. Measured on a 21s clip: **18s at 720px against 57s full size**.

  A preview **publishes nothing**: no sidecar, no fit file, and above all not the
  session output, so *Send to Claude* can never be handed a proxy instead of the
  mockup. It lands in the session as `preview.mp4`, which the sweep already
  treats as residue.

### Fixed

- **A finished render left the page saying "Rendering…" for ever.** The status
  poll called `api('/api/render_status', null, {method:'GET'})` — but `api`'s
  third argument is `raw` (headers and body for an upload), not options, so this
  was a **POST with a null body** to a GET-only route. Every poll threw *no such
  route* into a `catch` that swallows it. The encode finished correctly and the
  page never noticed: no toast, no re-enabled button, and *Send to Claude* never
  offered. Shipped since v0.18.0, and it is why the symptom was reported as "no
  progress" rather than as a broken poll. Found by watching the first preview
  complete on the server while the button sat still.
- **The frame counter is no longer wiped by a preview nobody asked for.**
  Dragging an edge during a build re-renders the still, and that path owns the
  same status line — so the count vanished mid-wait.

### Changed

- Even dimensions are forced on the proxy. H.264 with `yuv420p` refuses an odd
  width or height, and refuses by killing ffmpeg mid-stream — which arrives in
  Python as a broken pipe with the real complaint nowhere in sight. 720 x
  1536/2752 rounds to 401, and the whole preview vanished. The quad is scaled by
  what the resize *actually did*, not by the ratio asked for.

## [0.29.0] - 2026-09-11

### Added

- **A fit is a file you can keep, and dropping it back on the page restores the
  corners (SG72).** Matching the four edges is the only part of this job that
  costs real attention, and the scene gets reused — the same photograph with next
  week's UI. 0.26.0 already remembered a fit automatically, keyed by the
  photograph's decoded pixels, and that covers "same photo, same machine, later"
  and nothing else. It has no artefact to find, name, keep beside the project or
  send to anyone; it **misses a re-export**, because saving the same scene again
  at another quality changes the pixels and therefore the key; and it does not
  travel.

  So every save and render now writes `<mockup>.fit.json` **beside the output**,
  in the folder you already chose. Four corners, the radius fraction, the device,
  and which photograph it was made for. Drag it back onto the page — the way a
  photograph already arrives — and the quad comes back. **No file dialog is
  involved and none is needed:** the file lands where the work is, Finder finds
  it, drag-and-drop carries it.

  **It never applies silently**, because corners are meaningless on the wrong
  image and *plausible but wrong* on a crop of the right one. Four answers, each
  stated in the page: the **same photograph** (applied as saved); **the same size
  with different pixels** — the re-export this exists for — applied as saved and
  named as such; a **scaled** photograph, corners scaled and worth a check; and a
  **differently shaped** one, which means a crop, where the corners are stretched
  and every one of them needs correcting.

  A fit carries geometry only. Grade, blend and grain describe a *composite* and
  stay in `result.json`, which reproduces one exactly — keeping the two apart
  stops either file quietly becoming a worse copy of the other. Anything can be
  dropped on a page, so a file that is not a fit is refused with a sentence
  rather than applied as four numbers that happen to parse.

### Changed

- The save toast names the fit file. It is written silently beside the mockup,
  and a file nobody knows about is a file nobody drags back in.

## [0.28.0] - 2026-09-10

### Fixed

- **A quad with one corner collapsed into the middle of the screen was being
  returned as a confident answer (SG70).** Found on a real photograph, with the
  first hand-placed labels this project has had: three corners sat on the glass
  and the fourth ~800px inside it, and detection reported it without abstaining
  — the single failure this tool says it does not have.

  Nothing caught it because nothing measured the right property. The quad is
  **convex**, no side is a **sliver**, its **area** is in range and the source
  blob **fills** it — every existing check passes. What is wrong is that one
  pair of opposite sides differs by **2.26×** while the other pair does not, and
  a rectangle photographed from any angle a device is photographed from cannot
  do that.

  Measured against seven hand-fitted photographs: **every true screen sits at
  1.01–1.05**, the two usable detections at 1.04 and 1.11, the confident miss at
  2.26. Worst correct 1.11 against best wrong 2.26 is a **2.0× margin** — better
  than every threshold in `detect.py` except those set at 4×.

  `MAX_OPPOSITE_RATIO` is deliberately **loose at 1.9**, not near the data: all
  seven photographs are phones at modest angles, and a laptop or monitor shot
  from the side genuinely foreshortens more. The check can only ever *add*
  refusals, so its failure mode is an honest abstention and a manual fit, never
  a bad composite.

  On that photograph the outcome changes from a confident 154%-of-screen-width
  error to an abstention — and a single click now resolves it to 11%, because
  the collapsed quad no longer wins the walk. No other photograph's outcome
  changed.

## [0.27.1] - 2026-09-10

### Fixed

- **The detection trace could credit the wrong candidate.** `_finalize()` walks
  candidates best-score-first, and `pick_innermost()` then steps *inward* from
  the one it is looking at while a comparably screen-like quad nests inside — so
  the quad that gets validated and returned can belong to a **different**
  candidate. The trace recorded the verdict against the walked one, which meant
  an `accepted` row could hold a quad that never became the answer while the
  quad that did sat in an `unreached` row. A recall analysis reading that would
  reach the opposite conclusion, which is the one failure an instrument must not
  have. Measured across five real photographs: `pick_innermost` stepped inward
  on one of them.

  The nested candidate now gets its own verdict, `supplied_the_answer`, and the
  walked one says so. Pinned by a hand-built pair of nested quads rather than by
  hunting for a photograph that triggers it, so the case runs every time.
- **`filtered_by_click` is only reachable when there was a click.** It was
  inferred from object identity between the generated and surviving lists, which
  holds today and would break in silence the moment anything rebuilt that list —
  relabelling every row as filtered by a click nobody made.

## [0.27.0] - 2026-09-10

### Added

- **The candidate list is an output now, not something to print by hand (SG66).**
  `detect()` generates candidate quads across three channels and returns one;
  the rest were discarded. Every diagnosis this project has made about detection
  began by instrumenting that list by hand, and **twice it changed what the fix
  was**: the rescore that was the obvious answer on 7 Sep and was wrong, because
  the true screen was never generated at all (693px away); and SG46, where the
  correct quad turned out to be the top-scoring candidate containing the click,
  which deleted most of the planned work.

  What it exists to separate is **recall from ranking** — was the screen never
  proposed, or proposed and beaten? Those have opposite fixes, and this project
  has never had the number.

  `detect(..., trace=[])` fills a list with one row per candidate: method,
  score, the band or threshold that produced it, the quad, and what became of it
  — `accepted` by its channel, `rejected` (with the validator's reason),
  `unreached` because a higher-scoring candidate was accepted first, or
  `filtered_by_click`. Those last two both mean "never judged", and telling them
  apart is the point. Two ways in: `scripts/detect.py --trace FILE`, which also
  takes `--click X,Y`, and `POST /api/detect {"trace": true}`, which writes
  `<session>/candidates.json` and answers with the counts and the path rather
  than several hundred quads the page would not render.

  **It is an observer.** The answer is identical with and without it, asserted
  rather than assumed — planting a trace that drops one candidate turns that
  check red. Off unless asked for, no new dependency, and the file is a `.json`
  beside the session, so the sweep leaves it alone. It is kept out of
  `result.json` deliberately: the sidecar is the recipe for reproducing a
  composite and is contract-tested against `compose()`'s signature, and hanging
  diagnostics off it would couple two things that change for different reasons.

  On the fixture the instrument already answers its own question: the closest of
  36 candidates is **6.4px** from ground truth, and it is the one that won.

### Fixed

- **`/api/use` and `/api/upload` accepted any `role` (SG67).** The role names a
  session-state key and the handler writes it, so an unchecked role was a write
  primitive: `role="output"` sets the pointer `/api/import` reads, and the agent
  is then asked to show whatever file that names — any readable file under
  `$HOME`. Nothing on this port authenticates, so the caller is not necessarily
  the page. Two roles exist; anything else is now a 400 that changes no state.
  Pre-existing in both routes, surfaced by the refactor that merged them.
- **The remembered-fits store holds a lock now (SG67).** `_load` → mutate → `_save`
  is read-modify-write, and `os.replace` keeps the file from tearing while
  saying nothing about lost updates. Measured with the lock removed: **40
  concurrent writes leave 5 entries.**

### Changed

- The bug template asks for `candidates.json` when the report is about
  detection, next to where it asks for the sidecar.

## [0.26.0] - 2026-09-10

### Added

- **A photograph you have fitted before comes back fitted (SG51).** Matching the
  four edges is the only part of this job that costs real attention, and it is a
  property of the **photograph**, not of the screenshot — put a second screenshot
  into the same shot and the corners are identical. Until now they were thrown
  away when the run ended, so the second screenshot meant doing the whole
  interview again. Save a composite and those corners, the radius fraction and
  the device are kept; pick that photograph again and they are the starting
  position, in place of a detection.

  **The key is the photograph's decoded pixels, not its path.** A photo gets
  re-exported, renamed and downloaded twice constantly, and a path key would miss
  every one of those — including the case screengraft creates itself, where a
  drag-drop is copied into the session under a name invented from the clock and
  no original path exists at all. Hashing what the file decodes to costs **4ms on
  a 12MP photo and 18ms on 48MP**, measured, against the read that produced the
  array. Each route has its own test for this, because a path key passes a naive
  one; planting the path key turns four checks red, including *"a remembered fit
  reproduces the composite it came from, pixel for pixel"* (max |diff| = 0).

  **A fit is remembered when it produced an output, not while it is being
  dragged.** A quad on the canvas is a work in progress; a quad that made a file
  is one you looked at and kept. That also keeps the store trivial — an entry is
  a couple of hundred bytes, capped at 500, in `~/.screengraft/fits.json`, which
  sits outside every session so the sweep cannot take it. Numbers and a basename
  for display; no image data, no absolute paths.

  The page **says where the quad came from**, because a remembered fit is a much
  stronger claim than a detection and this tool does not present a guess as a
  fact: *"Your saved fit for this photo — saved 3 days ago"*, with the age
  relative so nobody does arithmetic against today. It is named one step earlier
  too, on the photo-only step, since a feature nobody notices is a feature that
  does not exist (the lesson of 0.24.1).

### Fixed

- **A reload no longer re-detects over hand-placed edges.** The session restore
  assigned the saved corners *before* re-adopting the photo — and choosing a
  photo clears the quad, correctly, because in every other case a new photo has
  nothing to do with the old corners. On the restore path it is the same photo,
  so the assignment was wiped by the call it preceded and `maybeStart()` ran a
  fresh detection over work the designer had already done. Found while reading
  the same code for the feature above.

### Changed

- **`/api/use` and `/api/upload` share one `_adopt()`.** They differed only in
  where the bytes came from, and everything after that — the video probe, the
  session state, and now the remembered fit — has to be identical or a feature
  works when you browse and not when you drag. The duplication was already
  written twice; the fit lookup would have made it three.
- **The scrubber-reset check moved from parsing source to speaking HTTP.** It
  counted two `fit_frame=0` resets, one per route, so collapsing that duplication
  turned a correct refactor red — pinning the shape of the code rather than what
  it does. What is parsed now is that the one place a source is adopted still
  resets; that it *happens* is asserted against a live server, where a stale
  index would show. Verified by planting the removal: the HTTP check reports
  `fit_frame = 11`.

## [0.25.2] - 2026-09-10

### Fixed

- **A run that saved a mockup now keeps the source its sidecar names (SG63).**
  0.23.0 swept every copied source, and said in three places that what survived
  was *"the recipe, referencing your originals by path"*. That was true only for
  a source picked by **path** — which was never copied in the first place. A
  dragged-in or browsed source has no original to reference: the browser hands
  over bytes without an origin, so the copy in the session **was** the original
  as far as the sidecar was concerned, and the sweep deleted it. Measured after
  the first sweep: **9 of 9 such sidecars named a file that no longer existed.**

  The rule is now conditional on output, which is where reproducibility actually
  matters: a session with a `result.json` keeps exactly the sources that sidecar
  names; a session that produced nothing keeps nothing. Derived media — previews,
  thumbnails, poster frames, re-fetchable Figma exports — is still swept from
  both, so the common case, which is where the volume was, is unchanged.

  Nothing of the user's own was ever at risk: a path-picked source lives in their
  own folders and screengraft does not delete their files.

- **Sidecars already broken by 0.23.0 now say so.** They cannot be repaired — the
  bytes are gone — but a sidecar naming a deleted file reads exactly like a
  working one, and the difference only surfaces when someone tries to re-run it.
  They are marked `"source_retained": false` at the next launch.

### Added

- `test/test_sweep.py`, in CI. It pins the **rule** rather than the
  implementation: nothing kept without output, exactly the named sources kept
  with it, derived media swept either way, a source outside the session never
  touched, and an unreadable sidecar protecting *nothing* rather than everything
  — failing open there would quietly restore the unbounded growth 0.23.0 existed
  to stop. Verified by planting the 0.23.0 behaviour back and watching three
  checks go red.

  `test_sidecar.py` checks the contents of the recipe; this checks the
  ingredients are still there. The first passed throughout SG63.

## [0.25.1] - 2026-09-10

### Fixed

- **The marketplace could not sync, and the message said to check the URL.**
  Adding `seq000/screengraft` as a marketplace failed with *"Marketplace sync
  failed. Check the repository URL and try again."* The URL was fine. So was
  everything else on the GitHub side: the repo is public, `main` was current,
  `.claude-plugin/marketplace.json` fetched anonymously and validated against
  the published marketplace schema, and an anonymous clone produced the
  manifest. The sync reached the repository, read it, and rejected its
  **contents** — which the dialog does not say. The real error existed only in
  the desktop app's log:

  ```
  marketplace_sync_bin_directory_not_allowed
  Plugin contains a top-level bin/ directory ('bin/screengraft.js').
  ```

  The catalog declares `"source": "./"`, so the repository root *is* the
  plugin — and the root also held `bin/screengraft.js`, the launcher that makes
  `npx screengraft` work. One directory serving two distribution channels with
  contradictory rules: npm wants a `bin`, the hosted marketplace forbids one,
  because a `bin/` is added to PATH by the CLI but never shown on the admin
  approval surface.

  The launcher now lives in `cli/`. npm does not care where the file sits — only
  the directory *name* trips the rule — so `npx screengraft` is unchanged, and
  the packaged `.plugin` is unaffected because it never included the launcher in
  the first place.

  `check_marketplace.py` now fails on a top-level `bin/` under any relative
  source, verified by putting the directory back and watching it go red. Worth
  noting why nothing local caught this: the built `.plugin` never contained
  `bin/`, so unpacking the artefact — this project's standing answer to "never
  trust the config that produces it" — could not have found it. **The
  marketplace validates the repository tree, not the package.**

## [0.25.0] - 2026-09-10

### Fixed

- **The grain estimator could only ever return multiples of 1.4826, and under
  one grey level it returned nothing at all.** `measure_grain` high-passed with
  a 3x3 median and took the median absolute deviation of the residual — but the
  photo and the median blur are both uint8, so that residual is integer-valued,
  and a median of integers is an integer or a half. The estimator had a handful
  of possible outputs, not a range.

  What it cost was not coarseness, it was silence: below 1.4826 the only
  available answer was **0**, and a sigma of 0 means `add_grain` returns the
  image untouched. Of the three reference photographs still on disk, **two
  measured exactly 0.0 and received no grain whatsoever**. They carry 0.39 and
  1.46.

  The median high-pass stays. The value now comes from the **mean** absolute
  deviation of the gated residual, which over the same integers resolves
  continuously, calibrated by 0.909 for the noise the median filter itself
  absorbs (measured, 5 seeds x sigma 1-5, spread under 0.3%). Measured against
  synthetic noise of known sigma, the reported value is now within 0.1% at every
  level from 1.0 up, where the old estimator reported 1.4826 for a true 1.0 and
  2.97 for a true 4.0.

  Robustness moved from the statistic to a **gate**. A 3x3 median is
  edge-preserving, so a clean step edge leaves a residual of exactly zero — the
  hard-edge case the old docstring claimed the MAD was protecting against was
  never in danger. What does leak is fine repeating texture: a 9px-pitch line
  pattern over true sigma 1.0 reads **27.0** with no gate. Discarding residuals
  above 20 grey levels drops it to 1.11 and leaves the noise floor untouched;
  any gate from 8 to 40 behaves identically.

  Grain will be stronger on photographs that previously received none. That is
  the fix, not a side effect.

- **The page scrolled sideways at 742px once a photo was loaded, and Save was
  off-screen.** One omission, made twice: `.app` and `.pane` both give their
  rows `minmax(0,1fr)` and leave the column implicit, which means `auto` — and
  an auto track is floored at its content's min-content width. The app grew to
  896px inside a 742px viewport; the pane's own track grew to 798px inside a
  398px column. Stating the 0 minimum on the column fixes both.

  The worse half was the topbar: a nowrap flex row whose children keep
  `min-width:auto` cannot shrink below their content, so **Save and Send to
  Claude sat at x=750-885 — outside the viewport and unclickable**. The chips
  carry a filename and are the part that gives; the actions are fixed-size and
  now say so.

  Verified with `test/ui-audit.js` at 742px **with a photo and a screenshot
  loaded**, sections both expanded and collapsed — 21 of 21 — and again at
  1600px, where the three-column layout is unchanged, and at 560px.

### Changed

- The grain test fixture asserted the wrong ground truth. It added independent
  noise to three channels and called the result "true sigma 4.0", but the
  estimator greys the photo first, so three independent channels average down to
  4/sqrt(3) = 2.31 — and the assertion band was wide enough to hide it. The
  fixture is monochrome now, which is also what sensor noise after demosaicing
  actually is, and what `add_grain` lays.

## [0.24.1] - 2026-09-10

### Fixed

- **Nobody could find Point at screen.** Reported within minutes of 0.24.0
  shipping — *"I haven't noticed new button"* — and the tool had no excuse: it
  knows the exact moment that button is worth pressing, because it just
  abstained. It said "place the edges by hand" instead, which sent people to
  the slowest remaining option without mentioning the fast one.

  The status now names the control — "Detector abstained — try **Point at
  screen**, or place the edges by hand" — and the button lifts on the surface
  ladder while the suggestion stands. It drops back as soon as the suggestion
  stops being true: you arm it, or you grab a corner and start fitting by hand.

  A first attempt gave the button the **accent**, and measuring caught it: Save
  is already accent-filled by then, and the visual language allows exactly one
  accent-filled control on screen — the accent means "the next action", so two
  of them means neither does. Emphasis without colour is what the raise ladder
  is for, and it is the same treatment a selected chip gets. Measured across the
  three states: rest `#2b2b30`, suggested `#3a3a40`, armed `#46464e`, with one
  accent-filled button on screen throughout.

## [0.24.0] - 2026-09-10

### Added

- **Point at screen.** When detection cannot tell which region is a screen, click
  once inside it and it will.

  Measured first, and the measurement chose the design. Of eleven real mockup
  photographs, nine detect correctly and two abstain — an iPad on a pale tiled
  floor and an iPhone against a pale wall, the cases where the background is as
  neutral as the device. Instrumenting the candidate list showed **the correct
  quad was already there both times**: 23 of 93 candidates contained the click
  on one photo, 16 of 118 on the other, and in each case the right one was the
  top-scoring candidate that contained it.

  So the failure was never detection — it was **selection**, and which region is
  a screen is the one question a person answers instantly. The click filters the
  candidate list before ranking; the existing score decides among what is left.
  No new segmentation, and every existing guard — validation, corner refinement,
  the radius measurement, the abstention — still applies to whatever wins.

  A click also counts as corroboration, so a result the user pointed at is no
  longer withheld for want of a second algorithm agreeing. Gross disagreement
  between two credible detectors still abstains: that means the click landed
  somewhere genuinely ambiguous, which is worth saying.

  **A GrabCut prototype was built first and rejected on measurement.** Seeded at
  the same click it solved the iPhone exactly, and failed on the iPad — that
  screen shows a large photograph, and a colour model segments the screen along
  its own content boundary rather than its edge. Reusing the detectors' own
  candidates is both simpler and better: it fixed both.

  The no-click path is **byte-identical on all eleven photographs**, and on the
  fixture a click inside a screen detection had already found moves the answer
  by **0.0px** — where detection works the click is a no-op.

## [0.23.1] - 2026-09-10

### Added

- **The workbench shows its version, bottom right — and where that code came
  from.** `v0.23.1` from an installed plugin; `v0.23.1 · dev a1b2c3d+` from a
  working tree.

  The version is read from `plugin.json` and served through `/api/state`, never
  written into the page: a second place to write a version is a second place for
  it to go stale, which is why `check_package.py` exists at all. If the manifest
  cannot be read the badge stays empty, because no version beats a wrong one
  once it is in a bug report.

  The provenance half matters more than the number. A session materialises its
  own private copy of every installed plugin when it starts and keeps that
  snapshot for its whole life, so an installed copy and the tree being edited
  drift apart within minutes. The symptom is a feature that is simply "not
  there" — which reads exactly like a bug in the feature, and has cost two
  debugging sessions: once testing the installed plugin while editing the tree,
  and once the reverse. `.git` is the discriminator, since the packager excludes
  it. The commit is shown because on a day with four releases "dev" does not say
  *which* dev, and the `+` because a sha with uncommitted work behind it would
  be a confident lie — the failure the badge exists to prevent.

  Bottom-right, `pointer-events:none` so it can never take a click, and never
  the accent: that means "the next action", and this is a fact about what you
  are running rather than something to do. It sits in the dock's own padding
  band, not over the rectified strip — the work surface keeps zero decoration.

### Note on the number

This release exists to *be* 0.23.1. The badge was built at Darek's instruction
not to bump the version, which left an unreleased build claiming to be the
published `v0.23.0` — the release-consistency problem raised in the 9 Sep review,
in a new instance. Re-cutting 0.23.0 would have entrenched it. A metadata-only
commit still changes the package, so it still needs a version.

## [0.23.0] - 2026-09-09

### Changed

- **Copied and derived media no longer outlives the run that needed it.**
  Measured first: `~/.screengraft/sessions/` held **492 MB across 90 directories**
  after six days, **64% of it duplicates of files the user already had**, and
  nothing had ever deleted any of it. A source picked by path was never copied —
  screengraft reads it where it is — but a drag-drop or a browse has to be,
  because a browser hands over bytes and will not say where they came from.

  So the copy is now session-scoped: swept when the run ends, and swept at the
  next launch for anything a crash left behind. **What survives is the
  `result.json` sidecar** — a few hundred bytes recording corners, radius, grade
  and blend, referencing the originals by path — so a composite stays
  reproducible without keeping a copy of everything it was made from. Keep the
  recipe, not the ingredients.

  > **Correction, added in 0.25.2.** That claim held only for a source picked by
  > path. A dragged-in or browsed source has no original to reference: the copy
  > in the session *was* the original as far as the sidecar was concerned, and
  > this release deleted it. Measured afterwards: 9 of 9 such sidecars named a
  > file that no longer existed. Fixed in 0.25.2 — a run that produced output now
  > keeps the source its sidecar names. Sidecars broken in the interval cannot be
  > repaired and are marked `"source_retained": false` instead.

  Run against a copy of the real 492 MB tree: **475.6 MB reclaimed (97%)**, all
  23 sidecars and 90 state files intact, the live session untouched.

### Fixed

- **The primary button's label disagreed with what clicking it would do.**
  Six places set it and they did not agree: one derived it from the source, one
  upgraded "Save" to "Render" with no inverse, and the save handler reset it to
  "Save" unconditionally — so a video source could leave the button reading
  either word. It is one function now, derived from the source, and the labels
  that mean something else ("Preview first", "Saving…", render progress) survive
  a source change untouched.

### Added

- The **Keys** section lists the canvas gestures: ⌘+scroll, Space+drag, and that
  plain scrolling pans.
- **A scrubber test that looks at pixels.** The existing one parses `ui.py` for
  the string `_fit_frame()`, which pins the shape of the code and not what it
  does. Demonstrated: force `_fit_frame()` to return 0 — the original v0.21.1
  bug, with the string still present — and the source-parsing test still reports
  **ok** and its whole suite passes, while the new test fails with
  `mean |diff| to frame 11 = 37.24, to frame 0 = 0.00`.

## [0.22.1] - 2026-09-09

Five defects in the render **route**. `test_video.py` proves the engine — same
geometry, identical frames, frame 0 of a render equal to the still composite —
and touches none of this. Every fault below would have passed it, and three of
them broke a shipped feature. There is a `test/test_render_api.py` now that
drives the real server over HTTP, and it is in CI.

### Fixed

- **A finished video render was never recorded as the session output.** The
  worker set it on the render's own state; `/api/import` — Send to Claude —
  reads the *session's*. So after a successful render it either answered
  "nothing saved yet", or, if a still had been saved earlier in the session,
  **silently handed over that still instead of the video**. The second is the
  bad one: it failed quietly and passed on the wrong artefact.
- **A validation failure locked rendering for the rest of the session.** The
  "running" flag was set before corners, radius, fit frame and output directory
  were checked, so anything that threw afterwards left it stuck on with no
  worker to clear it, and every later attempt answered `409 a render is already
  running`. The only recovery was restarting the server, and nothing said so.
  The flag now means what it says — a thread is running — and is set
  immediately before the thread exists.
- **`result.json` claimed a video was saved before the encode had run.** The
  sidecar is the first thing the bug template asks for, so a misleading one
  sends the next investigation the wrong way. It is published by the worker
  now, with the session output, and only on success — both before the state
  flips to "done", so a page that polls and immediately asks to send the file
  cannot race the worker.
- **A request with no photo chosen killed the handler thread.** `None` reached
  `os.path.expanduser`, raising a `TypeError` nobody had enumerated, and the
  browser saw the connection drop with no status and no message —
  indistinguishable from the server being gone. Missing sources are now named
  in a 400, and any unhandled error returns a 500 **with the exception in it**
  rather than hanging up.
- **A malformed quad was accepted, started, and failed somewhere invisible.**
  `corners` went to the engine unchecked, so a one-point "quad" produced an
  accepted render that died on a worker thread. Shape is the route's business:
  four points, two finite numbers each, or a 400 naming the problem.

### Verification

Each fix was watched to fail on the fault it claims to catch — the fix reverted,
the suite run, the red assertion checked against the original symptom. Plant the
first and Send to Claude answers "nothing saved yet"; plant the second and a
good request after three bad ones answers 409.

## [0.22.0] - 2026-09-09

### Added

- **Canvas navigation now follows the conventions every graphics tool uses.**
  Hold **⌘ and scroll** to zoom, and the pixel under the pointer stays under the
  pointer — which is what lets you magnify a corner without losing it off the
  edge. Hold **space and drag** to pan. Plain scrolling still pans, and the
  Result pane keeps up with both for free, because panning here *is* scrolling
  the element it already mirrors.

  The zoom anchor is measured rather than computed: after the resize, the page
  asks the DOM where the pinned image point actually landed and scrolls by the
  difference. The canvas is `margin:auto` in a grid, so while it is smaller than
  the pane it sits centred with a margin that changes as it grows, and
  arithmetic that predicts the scroll offset has to model that margin. Measured
  drift over zoom in, zoom out and a 2.2× jump is **under 0.25 image pixels**;
  the centre-anchored path it replaces drifts **63px** at the same cursor point.

  Two things the gesture must not break, both verified: a space-drag **cannot
  grab a corner** (the pan is caught in the capture phase on the scroller, so it
  never reaches the hit test), and **space still activates a focused control**
  for anyone using the keyboard. The second needed the canvas to take focus when
  you click it — `tabindex="-1"`, so it is not a tab stop — because focus
  otherwise stays on whichever rail button you last pressed, and holding space
  over the picture would re-press it instead of panning.

## [0.21.2] - 2026-09-09

### Added

- A support address, **screengraft@fraczyk.design**, for the case the issue
  tracker cannot serve: a photograph or a UI that is confidential. It is offered
  in the README, as a contact link on the new-issue chooser, and as the author
  and `bugs` email in `package.json`, `plugin.json` and the marketplace catalog,
  so `npm bugs` and the plugin listing both resolve to a person.

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
