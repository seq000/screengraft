---
name: inject-screenshot
description: Injects a UI screenshot onto a photographed device screen (phone/tablet/laptop) at any angle, matching the perspective exactly via homography — geometry, not AI generation. Use when the user wants to composite a screen design into a real device photo for a portfolio, case study, or mockup, and needs the result to look like a genuine photo rather than a template. Opens a local browser UI for picking files, correcting corners and saving.
---

# Inject a screenshot onto a photographed device

**What ships (v0.13.1):** a local browser UI (`scripts/ui.py`) that walks the designer through the whole job — pick the photo and the screenshot (recent Desktop/Downloads images, drag-drop, browse, path, or a **Figma frame link**), auto-detect the screen as a starting position, then **match the four edges** (drag an edge's middle to slide it, near an end to pivot; corners still draggable) with canvas zoom/pan and a rectified strip loupe, Preview (in a popup, or continuously in the compare pane), an on-by-default realism pass that colour-matches the screenshot to the photo's light, Save into the project folder (`--out-dir`), and a **Send to Claude** button that reaches you through the plugin's own MCP server. The UI is a hand port of the project's Figma design file — dark only.

The geometry is exact (`warp.py`); the detection is advisory (`detect.py`) and the human corrects it.

**The realism pass ships and is ON by default** (`grade.py`, M2): it matches the injected screen's white balance and grain to the light around it, at a strength the designer sets in the rail. It can also lift the device's real specular highlights from a screen-off reference frame, though the UI cannot supply one yet. Off is a first-class choice and keeps the screenshot's colour exactly — say so if the user is reviewing brand colour.

Still missing: **no ML detection** (M4 — measured, and it segments the phone body rather than the glass, so it is not shipped), **no occluder handling** — a finger or glare in front of the screen gets painted over (M5) — and **no video** (M3). Say so if it matters for the photo.

**Runs on the user's Mac shell** (Desktop Commander `start_process` or equivalent). The sandboxed Linux shell can't open a browser or reach `~/Desktop`. Paths below are relative to the plugin root — two levels up from this file.

## Workflow

### 0. Preflight — every time, before promising anything

```bash
python3 scripts/preflight.py
```

Read the JSON. If `ready` is true, note `python` — **use that interpreter for every command below** (it's the venv at `~/.screengraft/venv`, not system Python). If `ready` is false:

- Tell the user plainly what's missing and that **OpenCV is the engine: without it nothing runs — not worse results, no results.**
- Ask with `AskUserQuestion` whether to run the install: `python3 scripts/preflight.py --install` (creates `~/.screengraft/venv`, pip-installs `opencv-python-headless` + `numpy`, ~60 MB, touches nothing else). Run it only after a yes. This is the **only** interview question this skill asks in chat — everything else happens in the UI.

### 1. Launch the UI — with the project folder as the output directory

```bash
scripts/launch.sh --out-dir "<the user's current project folder>/mockups"
```

**Always pass `--out-dir`** when you know the folder the user is working in. Two reasons, and the second is not optional: saves land where the designer actually is rather than on the Desktop, and `present_files` **refuses any path outside a connected folder** — so with the default Desktop output, the "Import to Claude" button cannot work at all. If you genuinely have no project folder, omit the flag and tell the user that Import will be unavailable.

**Do not launch `ui.py` directly with `nohup ... &` from your own shell.** That was tried on 3 Sep 2026 and the server died silently between turns, twice, losing whatever the user had already entered — the shell session that launches it can be torn down out from under a merely-backgrounded child. `launch.sh` starts it with `--daemon`, which double-forks and calls `setsid`, putting the server in its own session with no controlling terminal; it survives the launching shell and opens no window. It self-checks (waits for startup output, then confirms the server responds) before returning.

A Terminal.app window was the previous fix for the same problem. It worked but left a dead "[Process completed]" window behind after every session, and closing those from AppleScript proved unreliable — Terminal reports stale ttys for dead windows and leaves zero-tab husks that `close` reports success on. The daemon removes the window entirely, so there is nothing to clean up.

It prints one JSON line — `url`, `session`, `job`, `result`, `out_dir` — and opens the browser tab itself. If it exits non-zero, read the error and the log path it names before telling the user anything is ready.

**Verify liveness again right before telling the user to interact with it** — `curl -sf <url>api/state` — especially if any time has passed since launch. If that fails, the server died; say so, relaunch, and have the user redo their last action rather than assuming it's still there.

**Then explain the job in chat.** The page deliberately carries no onboarding — the explanation belongs here, where the user already is. Say this, in your own words but keeping all of it:

> **What this does** — it computes the perspective between your photo and your screenshot, so the screenshot lands on the glass exactly. Geometry, not AI: nothing is invented and your pixels are unchanged.
>
> **1 · Choose a photo, then a screenshot.** Recent images from Desktop and Downloads are listed for you — or drag a file in, browse, paste a path, or paste a Figma frame link and I'll export it.
>
> **2 · Match the four edges to the screen.** Drag an edge's middle to slide it, or near an end to pivot — only that edge moves. The magnified strip below shows the boundary straightened, so aligned reads as flat. Arrow keys nudge 1px, Shift+arrow 10px, Tab moves to the next edge.
>
> **3 · Preview, then Save**, then **Send to Claude** and I'll check the result and show it here. Saves go to `<out-dir>`.
>
> A detector proposes a starting quad, but it's only a guess — you confirm all four edges. That's deliberate: a confident-looking wrong result is the one failure this tool won't risk.

Adapt it: name the real output folder, and mention the realism pass only if it matters (it is on by default and changes the screenshot's colour, which is worth flagging if they are reviewing brand colour). Say it once, on launch — not again on every re-arm.

Do not build a chat *interview* — the page collects every input, and duplicating its questions is what the one-interview-surface rule forbids. Explaining the workflow is not an interview. The page scans `~/Desktop` and `~/Downloads` for recent images itself, every launch.

### 2. Park in `wait_for_job` — this is the main loop, not an optional extra

**You cannot poll.** You run in turns; between them nothing of you is executing. An earlier version of this file told you to "poll `job.json` every few seconds" and the page told the user "(it watches this job)" — both false, and the user sat waiting for an agent that was not running. Do not reproduce that in chat: never tell the user you are watching, monitoring, or keeping an eye on anything.

What you *can* do is block. Immediately after launching the UI, call:

```
wait_for_job(timeout_s=90)
```

It parks until the user presses a button and returns within ~150 ms of the press. Handle what comes back, then **call it again**. That loop is how the page reaches you.

| result | what to do |
|---|---|
| `status=job`, `job.type="figma_export"` | Extract `fileKey` and `nodeId` from `job.url` (`1-2` → `1:2`), export via the Figma MCP (`download_assets`, PNG, scale 3), save to `job.save_to`, then `complete_job(status="done", path=<saved file>)`. Re-arm. |
| `status=job`, `job.type="present"` | `present_files` on `job.paths`, report what you checked in the composite (§3), then `complete_job(status="done")`. Re-arm. |
| `status=timeout` | Nothing pressed yet. Call again to keep waiting. Re-arm two or three times, then stop and say you've stopped waiting — do not loop forever burning turns. |
| `status=ui_closed` | The UI exited. Stop; say so. |
| `status=no_ui` | Nothing is running — launch it first. |

Pass the job's `id` back as `job_id` when you complete it. If the user gave up and started something else while you were working, that stops your late answer from marking their new request done and stranding them on a spinner.

**Always `complete_job`, including on failure.** The page is polling for it and will sit on a spinner until it arrives. If the Figma MCP isn't available, `complete_job(status="error", message="…")` with a sentence the designer can act on — the page shows it and offers the manual route.

While you are blocked you cannot do anything else, which is correct during a fit but means the user's own chat messages wait for the call to return. That is why the default is 90 s rather than the 150 s maximum: it bounds how long a message can sit behind the wait.

**Don't raise `timeout_s` past the default hoping to park longer.** The host kills an MCP tool call at around 180 s — measured on 4 Sep 2026, when a `wait_for_job(300)` was killed at exactly 180 s. Nothing is lost when that happens (an unanswered job stays pending and the next wait picks it up), but you miss the wake you were parked for, which is the whole point. The server clamps to 150 s; re-arming is the way to wait longer, not a bigger number.

### 3. When `<session>/result.json` appears: verify, then hand over

The user pressed Save. Read the output image back (you can see images). Check:

- The injected screen sits on the bezel edge all the way round — no sliver of the original screen showing, no UI poking past the glass. Zoom a corner if unsure.
- Text in the injected area is sharp. Soft means double resampling — that's a bug, not a setting.
- Nothing that was in front of the screen in the photo has been painted over (if it has, say so — M5).

Then `present_files` the output. Report what you checked, not "done".

If the user is unhappy, the UI is still open — they nudge and Save again; a new file is written (`-2`, `-3`, …), never overwritten.

### 4. Finish

The server is a detached daemon with no window. **Stop it with `scripts/stop.sh`, never a bare `pkill -9`.** stop.sh sends SIGTERM, which ui.py catches so its atexit clears the session pointer the MCP server reads; a hard kill leaves that pointer stale and the next `wait_for_job` then blocks a full timeout against a session nobody is in. Sessions live in `~/.screengraft/sessions/<timestamp>/` — leave them, they're small.

## Rules

- **Preflight first, install only on a yes.** OpenCV is required, full stop — never describe its absence as "reduced quality".
- **One interview surface, but explain the job in chat.** The browser page collects every *input*; `AskUserQuestion` is for install consent only, and you must not re-ask in chat what the page already asks. Explaining what the tool does and what the three steps are is not an interview — it is the onboarding, it belongs in chat, and §1 gives the words.
- **Never claim a composite is right without reading the output back.** Correct-looking code is not evidence; neither is the user clicking Save.
- **Detection is advisory and is only a starting position; the warp is exact — keep the two claims apart.** No-ML detection was measured to its ceiling (see the design notes): it cannot tell a screen from a bezel from a body, because that is a semantic question. The edge-matching UI exists so a human fixes it in seconds, and the page shows green ONLY when both detectors corroborate each other.
- **Testing the plugin ≠ doing the task.** If the user is testing screengraft and it can't do something, say what it can't do and propose the change. Don't reach past the plugin with ad-hoc scripts to make the result better.
- **Never claim to be watching, monitoring, or waiting on something you aren't.** You have exactly one way to be reached from the page — being blocked inside `wait_for_job`. If you are not in that call, you are not reachable, and saying otherwise leaves the user waiting on nothing. This is the specific failure v0.7 was built to fix; don't reintroduce it in prose.

## Scripts

| File | What it does |
|---|---|
| `mcp/server.py` | The plugin's MCP server: `wait_for_job` / `complete_job`. Stdlib only on system `python3`, deliberately — it must load before preflight has built the venv, or the tools would silently be missing on a fresh install. |
| `scripts/preflight.py` | Dependency report; `--install` builds the venv |
| `scripts/launch.sh` | Starts `ui.py` as a detached daemon (no window) and verifies it's alive — use this, not `ui.py` directly |
| `scripts/stop.sh` | Stops the UI with SIGTERM so the session pointer is cleared — use this instead of `pkill` |
| `scripts/ui.py` | Local server + browser UI; calls the two below |
| `scripts/detect.py` | Advisory screen-quad + corner-radius detection (no ML) |
| `scripts/warp.py` | The engine: `compose()` and a CLI for scripted use |
| `scripts/scan.py` | Recent images on Desktop/Downloads, thumbnails |
| `ui/index.html` | The page |

Design rationale and the roadmap live with the project's own notes, not in the plugin.
