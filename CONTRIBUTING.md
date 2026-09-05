# Contributing to screengraft

## The one rule

**Exact perspective match means geometry, not generation.** Anything that makes
the composite less deterministic, or that guesses where the screen is without
letting a human confirm, is out of scope regardless of how good it looks in one
example.

## Running it

```bash
python3 scripts/preflight.py --install   # venv at ~/.screengraft/venv
python3 scripts/ui.py --out-dir ./mockups
```

## Tests

```bash
python test/make_fixtures.py
python test/test_warp.py      # the compositing engine
python test/test_detect.py    # detectors, and that they fail honestly
python test/test_mcp.py       # the plugin's job server
python test/test_grade.py     # the realism pass
python scripts/contrast_audit.py   # UI contrast, parsed from ui/index.html
```

All of these run in CI on every push.

## UI changes need the UI audit too

`test/ui-audit.js` is run in the browser against the live page — paste it into
the console with the UI up. It checks what the Python suites structurally
cannot: accessible names, switch/section agreement, keyboard reachability,
tooltip containment, horizontal overflow, and ids the script reaches for that
don't exist. Run it with the collapsible sections both on and off, and at more
than one window width; a collapsed section is a different DOM.

It found two real defects the day it was written — a select and a slider with no
accessible name, and a native `<select>` whose chevron macOS paints *above*
positioned content, straight through a tooltip.

It deliberately does not judge appearance. That still needs a screenshot.

## If you change the engine, bring a number

Three of the worst bugs in this project's history were sampling and
coordinate-convention errors that every fixture passed: heavy minification
aliasing text into noise, a stepped screen edge, and rounded corners clipped a
pixel early. All three were found by looking at a real save.

So: a change to `warp.py` or `grade.py` should come with a measurement on a real
photograph — aliasing energy, corner placement error, contrast ratio, whatever
the change is about — and the determinism check must still pass. `test_warp.py`
and `test_grade.py` show the shape of this.

## UI changes

`ui/index.html` is one self-contained file by design: no build step, no
framework, no runtime dependencies, and it must work offline. Fonts are inlined.

The visual language and its accessibility constraints are measured, not
stylistic. `scripts/contrast_audit.py` parses the tokens straight out of the page
and fails on an unaccepted regression. Accepted shortfalls are listed *in the
script* with the reasoning, so a decision stays visible instead of being
forgotten.

Verify UI changes by looking at a screenshot. `getComputedStyle` and
`getBoundingClientRect` through a debugging bridge have both returned stale
values on this project.
