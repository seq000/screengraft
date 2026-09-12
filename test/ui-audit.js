/* Repeatable UI audit for ui/index.html.
 *
 * Paste into the page's console (or run it through a browser-driving tool) while
 * the UI is up. It checks the things that break silently and that neither the
 * Python suites nor the contrast audit can see: accessible names, switch/section
 * agreement, keyboard reachability, overflow, and dangling references.
 *
 * It does NOT judge how anything looks. That still needs a screenshot and an eye
 * — three of this project's UI defects were invisible to measurement and obvious
 * in a picture.
 *
 * Returns {pass, fail, checks}. Run before every publish.
 */
(() => {
  const R = [];
  const ok = (name, cond, extra = '') => R.push({ name, pass: !!cond, extra: String(extra || '') });
  const $$ = s => [...document.querySelectorAll(s)];
  const vis = el => {
    const c = getComputedStyle(el);
    if (c.display === 'none' || c.visibility === 'hidden' || +c.opacity === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const nameOf = el =>
    (el.getAttribute('aria-label') || el.getAttribute('title') ||
     (el.labels && el.labels[0] && el.labels[0].textContent) || el.textContent || '').trim();

  // --- 1. every visible control can be named by a screen reader --------------
  const controls = $$('button, [role="switch"], input, select, a[href]').filter(vis);
  const unnamed = controls.filter(el => !nameOf(el));
  ok('every visible control has an accessible name', unnamed.length === 0,
     unnamed.map(e => e.id || e.className || e.tagName).join(', '));

  // --- 2. switches agree with the section they govern ------------------------
  $$('.sect').forEach(sec => {
    const sw = sec.querySelector('[role="switch"]');
    if (!sw) return;
    const on = sw.getAttribute('aria-checked') === 'true';
    ok(`${sec.id}: section state matches its switch`, sec.dataset.on === (on ? '1' : '0'),
       `data-on=${sec.dataset.on} aria-checked=${sw.getAttribute('aria-checked')}`);
    const body = sec.querySelector('.sect-body');
    // A hidden document suspends CSS transitions, so a body that is closing
    // never reaches 0 and this reads as a failure that isn't one. Check the
    // inline style instead, which is set synchronously either way.
    if (body) {
      const settled = (Math.round(body.getBoundingClientRect().height) > 0) === on;
      const intent = on ? body.style.maxHeight !== '0px' : body.style.maxHeight === '0px';
      ok(`${sec.id}: body ${on ? 'shown' : 'collapsed'} to match`,
         document.hidden ? intent : settled,
         document.hidden ? '(document hidden — checked intent, not painted height)' : '');
    }
  });

  // --- 3. a control that is visible must be reachable, and vice versa --------
  const focusable = controls.filter(el => !el.disabled && el.tabIndex >= 0);
  ok('every enabled visible control is keyboard-reachable',
     focusable.length === controls.filter(el => !el.disabled).length,
     `${focusable.length} of ${controls.filter(el => !el.disabled).length}`);
  // `tabIndex >= 0` is what the element CLAIMS, not what the browser will do:
  // a button inside a display:none ancestor still reports tabIndex 0 and is
  // nonetheless unfocusable, so inferring reachability from it produces false
  // positives — the strip loupe's zoom steppers, invisible inside the docked
  // loupe whenever the loupe is floating, were reported as a tab trap they
  // could not be. Ask the browser instead: focus it and see if focus landed.
  // Restores the previous activeElement, so running the audit does not move
  // the user's focus.
  const reallyFocusable = el => {
    const prev = document.activeElement;
    try { el.focus(); } catch (e) { return false; }
    const got = document.activeElement === el;
    if (prev && prev.focus) prev.focus();
    return got;
  };
  const hiddenButFocusable = $$('button, input, select, a[href]')
    .filter(el => !vis(el) && !el.disabled && el.tabIndex >= 0 && !el.closest('[hidden]'))
    // Accepted by decision, not by measurement: a collapsed section and a
    // closed popover are known to keep their contents reachable.
    .filter(el => !el.closest('.pop') && !el.closest('.sect[data-on="0"]') && !el.closest('.toasts'))
    .filter(reallyFocusable);
  ok('nothing invisible is left in the tab order', hiddenButFocusable.length === 0,
     hiddenButFocusable.map(e => e.id || e.className).join(', '));

  // --- 4. tooltips ----------------------------------------------------------
  // Tips are moved to <body> at boot, so they are found there, not under .info.
  const tips = $$('body > .tip');
  // `button.info`, not `.info`: a status toast is `.toast.info` and matches the
  // bare class while it is on screen, which reported "5 tips / 6 icons" every
  // time the audit ran within a few seconds of loading a source. Reported
  // twice on 11 Sep 2026 and blamed on a debug probe the first time.
  const infos = $$('button.info');
  ok('every info icon carries a tooltip with real text',
     tips.length === infos.length && tips.every(t => t.textContent.trim().length > 40),
     `${tips.length} tips / ${infos.length} icons`);
  ok('tooltips are hidden at rest', tips.every(t => getComputedStyle(t).visibility === 'hidden'));
  ok('every info icon points at its tooltip for assistive tech',
     infos.every(b => { const id = b.getAttribute('aria-describedby');
                        return id && document.getElementById(id); }));
  // A tip must escape every ancestor stacking context, or a later section's
  // switch paints over it — which is exactly what happened when they lived
  // inside .sect-top. Being a direct child of <body> is the guarantee.
  ok('tooltips sit at body level, outside any stacking context',
     tips.every(t => t.parentElement === document.body));
  ok('tooltips are position:fixed so the rail cannot clip them',
     tips.every(t => getComputedStyle(t).position === 'fixed'));

  // --- 5. layout ------------------------------------------------------------
  ok('the page does not scroll horizontally',
     document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
     `${document.documentElement.scrollWidth} vs ${document.documentElement.clientWidth}`);
  const chips = $$('#types .chip').map(c => Math.round(c.getBoundingClientRect().width));
  ok('device chips are equal width', new Set(chips).size <= 1, chips.join('/'));
  const overflowing = $$('.rail button, .rail select, .rail h4')
    .filter(vis).filter(el => el.scrollWidth > el.clientWidth + 1);
  ok('no rail control clips its own label', overflowing.length === 0,
     overflowing.map(e => e.id || e.textContent.trim().slice(0, 18)).join(', '));

  // --- 6. dangling references ----------------------------------------------
  const ids = new Set($$('[id]').map(e => e.id));
  const src = [...document.scripts].map(s => s.textContent).join('\n');
  const referenced = [...new Set([...src.matchAll(/\$\('#([\w-]+)'\)/g)].map(m => m[1]))];
  const missing = referenced.filter(id => !ids.has(id));
  ok('every id the script reaches for exists', missing.length === 0, missing.join(', '));

  // --- 7. the script actually ran -------------------------------------------
  // A temporal-dead-zone error kills the whole script and leaves a page that
  // looks fine but does nothing. Cheap to detect: the globals the page defines
  // are simply missing.
  // Top-level `const`/`let` do NOT become window properties, so probing
  // window[name] could only ever fail. Evaluate the name in scope instead.
  const defined = n => { try { return eval('typeof ' + n) !== 'undefined'; } catch (e) { return false; } };
  const NEEDED = ['st', 'setSectionOpen', 'toast', 'compose' in window ? 'toast' : 'drawStrip'];
  ok('the page script ran to completion', NEEDED.every(defined),
     NEEDED.filter(n => !defined(n)).join(', '));

  // --- 7b. no @property name is also used as a plain custom property --------
  // `@property` is a PAGE-WIDE type declaration, not a scoped one: it applies to
  // every element, and a registered property always has a value, so `var(--x, 0)`
  // silently stops using its fallback. Registering a name somebody else already
  // writes with a different type breaks them at a distance.
  //
  // That shipped in v0.33.0. The render progress bar registered `--p` as a
  // <percentage>; the range sliders had been setting `--p` to a unitless
  // fraction for months and reading it as `calc(var(--p,0) * 100%)`. The unitless
  // value became invalid, fell back to the registered initial `0%`, and
  // `calc(0% * 100%)` is invalid — so every slider lost its accent fill. Nothing
  // could see it: the Python suites never open a browser, the contrast audit
  // reads tokens rather than computed styles, and a dropped gradient leaves a
  // track that still looks like a track.
  //
  // Reading the track's computed style is not the check — `::-webkit-slider-
  // runnable-track` is not reliably queryable through getComputedStyle, and a
  // check that cannot fail honestly is worse than none. The COLLISION is what is
  // checkable, and it is the actual defect.
  // From the stylesheet TEXT, not from cssRules: WebKit does not expose
  // @property as a CSSRule, so a cssRules scan finds nothing and the check can
  // never fail — which is the failure mode this whole section exists to reject.
  // Verified by planting the collision: the scan must report --p.
  const cssText = [...document.querySelectorAll('style')]
                    .map(el => el.textContent).join('\n');
  const registered = new Set(
    [...cssText.matchAll(/@property\s+(--[\w-]+)/g)].map(m => m[1]));
  const inlineNames = new Set();
  for (const el of $$('*')) {
    const st = el.getAttribute('style');
    if (!st) continue;
    for (const m of st.matchAll(/(--[\w-]+)\s*:/g)) inlineNames.add(m[1]);
  }
  const collided = [...registered].filter(n => inlineNames.has(n));
  ok('no @property name is also set as a plain custom property',
     collided.length === 0,
     collided.length ? collided.join(', ') + ' — registering a name types it for the WHOLE page'
       : `${registered.size} registered, ${inlineNames.size} set inline`);

  // --- 8. motion ------------------------------------------------------------
  const noTrans = $$('.rail button, .chip, .switch').filter(vis)
    .filter(el => getComputedStyle(el).transitionDuration === '0s');
  ok('rail controls animate their state change', noTrans.length === 0,
     noTrans.map(e => e.id || e.className).join(', '));

  // --- 9. orientation -------------------------------------------------------
  // orientQuad() turns a DETECTED quad so its top edge suits the screenshot's
  // aspect (portrait -> a short edge, landscape -> a long one). Exercised on
  // synthetic state and restored, so it runs whether or not a photo is loaded.
  // Both directions, because the first version of this rule lived in
  // detect.py and was right for phones and wrong for every landscape screen.
  if (typeof orientQuad === 'function' && typeof st === 'object') {
    const keep = { corners: st.corners, shotSize: st.shotSize, quadFrom: st.quadFrom };
    const tilted = [[490, 439], [1157, 92], [1350, 344], [687, 695]];   // a phone at 45°, image-order start
    st.corners = tilted.map(c => c.slice()); st.shotSize = [1080, 2280];
    const turnedP = orientQuad();
    const topLenP = Math.hypot(st.corners[1][0] - st.corners[0][0], st.corners[1][1] - st.corners[0][1]);
    ok('a portrait screenshot on a tilted phone gets a short top edge',
       turnedP && topLenP < 400 && st.corners[0][0] === 1157, `turned=${turnedP} top=${topLenP.toFixed(0)}px first=${st.corners[0]}`);
    st.corners = tilted.map(c => c.slice()); st.shotSize = [2280, 1080];
    const turnedL = orientQuad();
    const topLenL = Math.hypot(st.corners[1][0] - st.corners[0][0], st.corners[1][1] - st.corners[0][1]);
    ok('a landscape screenshot on the same phone gets a long top edge',
       !turnedL && topLenL > 600, `turned=${turnedL} top=${topLenL.toFixed(0)}px`);
    st.corners = [[100, 100], [700, 100], [700, 600], [100, 600]]; st.shotSize = [1080, 2280];
    const turnedSq = orientQuad();
    ok('a near-square quad is left alone', !turnedSq, `turned=${turnedSq}`);
    // Rotate steps to the NEXT orientation the screenshot fits. On a
    // phone a portrait screenshot fits only two ways, so one press is a half
    // turn: corner 0 lands two places on, never on a long edge. Near-square:
    // a quarter turn. Landscape screenshot on the phone: the top must stay a
    // long edge, so again a half turn. autoPreview/draw are stubbed out —
    // this exercises the order rule, not the pipeline.
    if (typeof rotateQuad === 'function') {
      const stubs = { draw, drawStrip, autoPreview, toast };
      draw = () => {}; drawStrip = () => {}; autoPreview = () => {}; toast = () => null;
      st.corners = [[490, 439], [1157, 92], [1350, 344], [687, 695]]; st.shotSize = [1080, 2280];
      orientQuad();                         // now corner 0 = [1157,92], top short
      const before = st.corners.map(c => c.slice());
      rotateQuad();
      const topLen = Math.hypot(st.corners[1][0] - st.corners[0][0], st.corners[1][1] - st.corners[0][1]);
      ok('Rotate on a phone is a half turn — the top stays a short edge',
         st.corners[0][0] === before[2][0] && topLen < 400, `first=${st.corners[0]} top=${topLen.toFixed(0)}px`);
      st.corners = [[100, 100], [700, 100], [700, 600], [100, 600]]; st.shotSize = [1080, 2280];
      rotateQuad();
      ok('Rotate on a near-square screen is a quarter turn',
         st.corners[0][0] === 700 && st.corners[0][1] === 100, `first=${st.corners[0]}`);
      st.corners = [[490, 439], [1157, 92], [1350, 344], [687, 695]]; st.shotSize = [2280, 1080];
      rotateQuad();
      const topLenL2 = Math.hypot(st.corners[1][0] - st.corners[0][0], st.corners[1][1] - st.corners[0][1]);
      ok('Rotate with a landscape screenshot keeps a long top edge', topLenL2 > 600, `top=${topLenL2.toFixed(0)}px`);
      Object.assign(window, stubs);
    } else {
      ok('rotateQuad is present', false, 'not defined');
    }
    Object.assign(st, keep);
  } else {
    ok('orientQuad is present', false, 'not defined');
  }

  // --- 10. the edge strip ---------------------------------------------------
  // Contrast: a strip whose whole tonal range is 8..20 (a dark screen on a
  // dark body) must come out spanning most of 0..255, and a flat strip must
  // be left alone. On a scratch canvas, so the real strip is untouched.
  if (typeof stretchContrast === 'function') {
    const sc = document.createElement('canvas'); sc.width = 64; sc.height = 8;
    const g = sc.getContext('2d');
    g.fillStyle = 'rgb(8,8,8)'; g.fillRect(0, 0, 32, 8);
    g.fillStyle = 'rgb(20,20,20)'; g.fillRect(32, 0, 32, 8);
    stretchContrast(g, 64, 8);
    const px = g.getImageData(0, 0, 64, 8).data;
    const row4 = 4*64*4;
    const spread = px[row4 + 32*4] - px[row4];   // row 4: x=32 vs x=0
    ok('strip contrast stretches an 8..20 boundary to most of the range', spread > 200, `spread=${spread}`);
    g.fillStyle = 'rgb(40,40,40)'; g.fillRect(0, 0, 64, 8);
    stretchContrast(g, 64, 8);
    ok('strip contrast leaves a flat strip alone', g.getImageData(0, 0, 1, 1).data[0] === 40,
       `value=${g.getImageData(0, 0, 1, 1).data[0]}`);
    const hc = document.getElementById('stripHC');
    ok('the Contrast toggle states its pressed state', hc && hc.hasAttribute('aria-pressed'));
  } else {
    ok('stretchContrast is present', false, 'not defined');
  }
  // Which end swings: the caption names it, one way per pivot mode.
  if (typeof swingText === 'function') {
    ok('rotA caption: right end swings, pivot left', /right end swings/.test(swingText('rotA')) && /pivot on the left/.test(swingText('rotA')), swingText('rotA'));
    ok('rotB caption: left end swings, pivot right', /left end swings/.test(swingText('rotB')) && /pivot on the right/.test(swingText('rotB')), swingText('rotB'));
  } else {
    ok('swingText is present', false, 'not defined');
  }

  const fail = R.filter(r => !r.pass);
  return { pass: R.length - fail.length, fail: fail.length,
           failures: fail, checks: R.map(r => (r.pass ? '  ok   ' : '  FAIL ') + r.name + (r.extra ? '   ' + r.extra : '')) };
})();
