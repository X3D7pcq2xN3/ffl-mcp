/* fflDraft content script — runs inside the ESPN draft room.
 *
 * Two ways a pick reaches the sheet, by design:
 *
 *   1. AUTO — a MutationObserver watches the live pick feed and fires on each
 *      new pick. ESPN's markup is not documented and changes between seasons,
 *      so the selectors in SEL are a STARTING POINT you confirm against a mock
 *      draft (ESPN runs mocks year-round): right-click a completed pick in the
 *      feed > Inspect, then set PICK_NAME to the element holding the player's
 *      name. Until it's confirmed, auto may catch nothing — that's expected.
 *
 *   2. MANUAL — a small panel (bottom-right) with a text box and a hotkey.
 *      Type or paste a name and Enter, or select a name anywhere on the page
 *      and press Alt+D. This works on day one regardless of ESPN's markup, and
 *      is the reliable fallback if auto needs tuning mid-draft.
 *
 * The panel is a PASSIVE sidecar. It never touches ESPN's own draft controls,
 * so if this script breaks, your draft is unaffected — you just lose the
 * auto-marking, not a pick. The sheet is the source of truth; a page refresh
 * re-injects this script and already-marked players stay marked. */

const api = (typeof browser !== 'undefined') ? browser : chrome;

/* ---- ESPN selectors — CONFIRM ON A MOCK DRAFT --------------------------- */
const SEL = {
  // An element that wraps the player name inside one completed pick. The
  // defaults are broad guesses; narrow them once you inspect the real feed.
  PICK_NAME: 'a[href*="/player/"], [class*="playerName"], [class*="PlayerName"], [class*="athleteName"]',
  // Optional: a container to scan on a timer as a reconcile safety net. Leave
  // as document.body if unsure.
  FEED: 'body'
};
const RECONCILE_MS = 4000;   // periodic re-scan to self-heal missed mutations

/* ---- de-dupe: a player is drafted once ---------------------------------- */
const seen = new Set();
function normKey(s) {
  return String(s || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
    .toLowerCase().replace(/[^a-z ]/g, ' ').replace(/\s+/g, ' ').trim();
}

function send(name, info) {
  const key = normKey(name);
  if (!key || seen.has(key)) return;
  seen.add(key);
  setStatus(`sending: ${name}`);
  api.runtime.sendMessage({ type: 'PICK', name: name, info: info || '' }).then((r) => {
    if (!r)                 setStatus(`? ${name} — no reply`, 'warn');
    else if (r.ok)          { bump(); setStatus(`✓ ${name} (row ${r.row}, ${r.match})`, 'ok'); }
    else                    { seen.delete(key); setStatus(`✗ ${name} — ${r.error}`, 'err'); }
  });
}

/* ---- auto detection ----------------------------------------------------- */
function textFrom(el) {
  const hit = el.matches && el.matches(SEL.PICK_NAME) ? el
            : (el.querySelector ? el.querySelector(SEL.PICK_NAME) : null);
  const t = hit && (hit.textContent || '').trim();
  return t && t.length >= 3 ? t : null;
}
function scan(root) {
  if (!root || !root.querySelectorAll) return;
  root.querySelectorAll(SEL.PICK_NAME).forEach((el) => {
    const t = (el.textContent || '').trim();
    if (t && t.length >= 3) send(t);
  });
}
function startAuto() {
  const obs = new MutationObserver((muts) => {
    for (const m of muts) m.addedNodes.forEach((n) => {
      if (n.nodeType === 1) { const t = textFrom(n); if (t) send(t); }
    });
  });
  obs.observe(document.body, { childList: true, subtree: true });
  const feed = document.querySelector(SEL.FEED) || document.body;
  setInterval(() => scan(feed), RECONCILE_MS);   // reconcile safety net
}

/* ---- passive sidecar panel ---------------------------------------------- */
let elStatus, elCount, count = 0;
function bump() { count++; if (elCount) elCount.textContent = String(count); }
function setStatus(msg, kind) {
  if (!elStatus) return;
  elStatus.textContent = msg;
  elStatus.style.color = kind === 'ok' ? '#137333' : kind === 'err' ? '#c5221f'
                      : kind === 'warn' ? '#b06000' : '#3c4043';
}
function panel() {
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;right:14px;bottom:14px;z-index:2147483647;width:250px;'
    + 'font:12px/1.4 system-ui,sans-serif;background:#fff;color:#202124;border:1px solid #dadce0;'
    + 'border-radius:10px;box-shadow:0 4px 16px rgba(0,0,0,.18);padding:10px;';
  box.innerHTML =
      '<div style="font-weight:600;margin-bottom:6px">fflDraft <span style="font-weight:400;color:#5f6368">· ESPN → Sheet</span></div>'
    + '<div id="ffld-status" style="min-height:16px;margin-bottom:6px">idle</div>'
    + '<div style="display:flex;gap:6px;margin-bottom:6px">'
    + '  <input id="ffld-name" placeholder="mark a name…" style="flex:1;min-width:0;padding:4px 6px;border:1px solid #dadce0;border-radius:6px">'
    + '  <button id="ffld-mark" style="padding:4px 8px;border:0;border-radius:6px;background:#1a73e8;color:#fff;cursor:pointer">Mark</button>'
    + '</div>'
    + '<div style="display:flex;justify-content:space-between;align-items:center;color:#5f6368">'
    + '  <span>drafted: <b id="ffld-count">0</b></span>'
    + '  <span><a id="ffld-reset" href="#" style="color:#c5221f;text-decoration:none">reset board</a></span>'
    + '</div>'
    + '<div style="margin-top:6px;color:#9aa0a6;font-size:11px">Alt+D marks selected text</div>';
  document.body.appendChild(box);
  elStatus = box.querySelector('#ffld-status');
  elCount  = box.querySelector('#ffld-count');
  const input = box.querySelector('#ffld-name');
  const mark = () => { const v = input.value.trim(); if (v) { send(v); input.value = ''; } };
  box.querySelector('#ffld-mark').addEventListener('click', mark);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') mark(); });
  box.querySelector('#ffld-reset').addEventListener('click', (e) => {
    e.preventDefault();
    if (!confirm('Clear all drafted marks on the board?')) return;
    api.runtime.sendMessage({ type: 'RESET' }).then((r) => {
      if (r && r.ok) { seen.clear(); count = 0; elCount.textContent = '0'; setStatus(`reset ${r.reset} rows`, 'ok'); }
      else setStatus('reset failed: ' + ((r && r.error) || '?'), 'err');
    });
  });

  // Confirm the web app is reachable on load.
  api.runtime.sendMessage({ type: 'PING' }).then((r) => {
    if (r && r.ok) setStatus('connected', 'ok');
    else setStatus((r && r.error) || 'not connected — see options', 'warn');
  });
}

/* ---- Alt+D: mark the current text selection ----------------------------- */
document.addEventListener('keydown', (e) => {
  if (e.altKey && (e.key === 'd' || e.key === 'D')) {
    const sel = String(window.getSelection());
    if (sel && sel.trim()) { send(sel.trim()); e.preventDefault(); }
  }
});

if (document.body) { panel(); startAuto(); }
