/* fflDraft content script — runs inside the ESPN draft room.
 *
 * Two ways a pick reaches the sheet, by design:
 *
 *   1. AUTO — reads ESPN directly: the player table marks who's taken (→ ☑)
 *      and the "My Team" roster panel marks your own picks (→ ★). See SEL
 *      below. ESPN's markup can change between seasons; if auto goes quiet,
 *      re-inspect and update the selectors in SEL.
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

/* ---- ESPN selectors (confirmed against ESPN's live draft room) ----------
 * TWO signals, because "taken" and "mine" are different questions:
 *   TAKEN (anyone) -- a player's draft button flips to the disabled "Drafted"
 *     state (Button--drafted). These become ☑ on the board.
 *   MINE -- the "My Team" roster panel lists the players YOU drafted as
 *     Table__TR rows; .player-column carries the full name in its `title`
 *     (the link text is abbreviated, e.g. "J. Dart"). These become ★, which
 *     is what the My Team + Byes tab filters on.
 * A player you drafted appears in both, so ★ wins over ☑ -- push() upgrades.
 *
 * Two usage caveats:
 *   - Keep ESPN's list on "All", not "Available only", or drafted rows leave
 *     the table and can't be read as taken.
 *   - Keep the roster panel showing YOUR team, not an opponent's, or their
 *     players get tagged ★ as yours. */
const SEL = {
  DRAFTED_BTN: 'button.Button--drafted',                       // a taken player's button
  ROW: '.fixedDataTableCellGroupLayout_cellGroupWrapper',      // its row (holds button + name)
  NAME: '.playerinfo__playername',                             // holds ONLY the name
  MINE_ROW: 'tr.Table__TR',                                    // a "My Team" roster row
  MINE_NAME: '.player-column[title]'                           // full name in its title attr
};
const RECONCILE_MS = 2500;   // periodic re-scan catches button flips + virtualized rows

function normKey(s) {
  return String(s || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
    .toLowerCase().replace(/[^a-z ]/g, ' ').replace(/\s+/g, ' ').trim();
}

/* Push a mark, de-duped, with ★ (mine) allowed to upgrade ☑ (taken). A player
 * you drafted appears in both the table (taken) and your roster (mine). */
const sent = new Map();   // normKey -> 'mine' | 'taken'
function push(name, mine) {
  const key = normKey(name);
  if (!key) return;
  const cur = sent.get(key);
  if (cur === 'mine') return;               // already the best state
  if (cur === 'taken' && !mine) return;     // no change
  sent.set(key, mine ? 'mine' : 'taken');
  api.runtime.sendMessage({ type: 'PICK', name: name, mine: !!mine }).then((r) => {
    if (!r)        setStatus(`? ${name} — no reply`, 'warn');
    else if (r.ok) { if (cur === undefined) bump(); setStatus(`${mine ? '★' : '☑'} ${name} (row ${r.row})`, 'ok'); }
    else           { sent.delete(key); setStatus(`✗ ${name} — ${r.error}`, 'err'); }
  });
}

/* ---- auto detection ----------------------------------------------------- */
// From a drafted button, the player name in its row. The name lives in
// .playerinfo__playername (a sibling span holds the news-icon link, so we
// don't read that by mistake).
function nameForDraftedButton(btn) {
  const row = btn.closest(SEL.ROW) || btn.closest('[role="row"]');
  const el = row && row.querySelector(SEL.NAME);
  const t = el && (el.textContent || '').trim();
  return t && t.length >= 3 ? t : null;
}
function scanDrafted() {
  document.querySelectorAll(SEL.DRAFTED_BTN).forEach((btn) => {
    const name = nameForDraftedButton(btn);
    if (name) push(name, false);            // ☑ taken; upgrades to ★ if also mine
  });
  // MINE: roster-panel rows -- read the full name from the title attribute.
  document.querySelectorAll(`${SEL.MINE_ROW} ${SEL.MINE_NAME}`).forEach((el) => {
    const name = (el.getAttribute('title') || '').trim();
    if (name.length >= 3) push(name, true); // ★ mine (wins over ☑)
  });
}
function startAuto() {
  // Rows re-render as the table virtualizes and buttons/rosters change; a
  // childList observer catches re-renders, the interval catches pure class
  // flips. push()'s state map means repeats cost nothing.
  new MutationObserver(scanDrafted).observe(document.body, { childList: true, subtree: true });
  setInterval(scanDrafted, RECONCILE_MS);
  scanDrafted();   // catch up on everyone already taken / rostered at load
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
    + '  <input id="ffld-name" placeholder="mark MY pick…" style="flex:1;min-width:0;padding:4px 6px;border:1px solid #dadce0;border-radius:6px">'
    + '  <button id="ffld-mark" style="padding:4px 8px;border:0;border-radius:6px;background:#1a73e8;color:#fff;cursor:pointer">★ Mine</button>'
    + '</div>'
    + '<div style="display:flex;justify-content:space-between;align-items:center;color:#5f6368">'
    + '  <span>marked: <b id="ffld-count">0</b></span>'
    + '  <span><a id="ffld-reset" href="#" style="color:#c5221f;text-decoration:none">reset board</a></span>'
    + '</div>'
    + '<div style="margin-top:6px;color:#9aa0a6;font-size:11px">Alt+D marks selected text as ★ mine</div>';
  document.body.appendChild(box);
  elStatus = box.querySelector('#ffld-status');
  elCount  = box.querySelector('#ffld-count');
  const input = box.querySelector('#ffld-name');
  const mark = () => { const v = input.value.trim(); if (v) { push(v, true); input.value = ''; } };
  box.querySelector('#ffld-mark').addEventListener('click', mark);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') mark(); });
  box.querySelector('#ffld-reset').addEventListener('click', (e) => {
    e.preventDefault();
    if (!confirm('Clear all drafted marks on the board?')) return;
    api.runtime.sendMessage({ type: 'RESET' }).then((r) => {
      if (r && r.ok) { sent.clear(); count = 0; elCount.textContent = '0'; setStatus(`reset ${r.reset} rows`, 'ok'); }
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
    if (sel && sel.trim()) { push(sel.trim(), true); e.preventDefault(); }
  }
});

if (document.body) { panel(); startAuto(); }
