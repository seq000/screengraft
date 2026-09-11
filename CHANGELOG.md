# Changelog

All notable changes to screengraft.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

One convention worth knowing: entries say what was **measured**, not what was
attempted. Where a change was driven by a real photograph or a real failure, the
numbers are here.

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
