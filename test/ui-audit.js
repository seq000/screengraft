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
  const hiddenButFocusable = $$('button, input, select, a[href]')
    .filter(el => !vis(el) && !el.disabled && el.tabIndex >= 0 && !el.closest('[hidden]'))
    .filter(el => !el.closest('.pop') && !el.closest('.sect[data-on="0"]') && !el.closest('.toasts'));
  ok('nothing invisible is left in the tab order', hiddenButFocusable.length === 0,
     hiddenButFocusable.map(e => e.id || e.className).join(', '));

  // --- 4. tooltips ----------------------------------------------------------
  // Tips are moved to <body> at boot, so they are found there, not under .info.
  const tips = $$('body > .tip');
  const infos = $$('.info');
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

  // --- 8. motion ------------------------------------------------------------
  const noTrans = $$('.rail button, .chip, .switch').filter(vis)
    .filter(el => getComputedStyle(el).transitionDuration === '0s');
  ok('rail controls animate their state change', noTrans.length === 0,
     noTrans.map(e => e.id || e.className).join(', '));

  const fail = R.filter(r => !r.pass);
  return { pass: R.length - fail.length, fail: fail.length,
           failures: fail, checks: R.map(r => (r.pass ? '  ok   ' : '  FAIL ') + r.name + (r.extra ? '   ' + r.extra : '')) };
})();
