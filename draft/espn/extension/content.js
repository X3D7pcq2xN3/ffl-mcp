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
const FFLD_VERSION = 'v5-feed';   // bump on each change; shown on the panel + logged on load

/* ---- ESPN selectors (confirmed against ESPN's live draft room) ----------
 * TWO signals, because "taken" and "mine" are different questions:
 *   TAKEN (anyone) -- a player's draft button flips to the disabled "Drafted"
 *     state (Button--drafted). These become ☑ on the board.
 *   MINE -- ESPN tags YOUR picks with a `.player-column.my-pick` class that
 *     opponents' rows don't have (in the draft log / pick feed, and on the
 *     drafted row itself). These become ★, which the My Team + Byes tab filters
 *     on. Reading ESPN's own marker means no roster-panel dependency and no
 *     lag: a pick goes ★ the instant it lands, wherever my-pick renders.
 * A player you drafted is both taken and mine, so ★ wins over ☑ -- push()
 * upgrades and the web app never downgrades ★ to ☑.
 *
 * One usage caveat: keep ESPN's list on "All", not "Available only", or drafted
 * rows leave the table and can't be read as taken. */
const SEL = {
  DRAFTED_BTN: 'button.Button--drafted',                       // a taken player's button
  ROW: '.fixedDataTableCellGroupLayout_cellGroupWrapper',      // its row (holds button + name)
  NAME: '.playerinfo__playername',                             // holds ONLY the name
  MINE: '.player-column.my-pick'                               // ESPN's own marker on YOUR picks
};

/* The Roster sidebar ("your team" panel). This is the reliable "mine" source:
 * unlike the pool table it is NOT virtualized -- your ~15 players are always in
 * the DOM -- so it still marks ★ for a player you had to SEARCH to draft, whose
 * pool row scrolls out of the page the moment you clear the search box.
 *   Row:  tr.Table__TR  (also used by other panels, so we filter by POS)
 *   Name: .player-column[title="Full Name"]  (full name in the title attr; the
 *         visible <a> text is abbreviated, e.g. "J. Gibbs")
 *   Pos:  a [title="Position"] cell (QB/RB/.../BE) is on EVERY roster row --
 *         starters and bench alike -- but not on the Pick Queue panel, so it
 *         both excludes QUEUED (undrafted) players and, unlike a Bye-Week cell,
 *         still matches bench (BE) picks whose bye may not render.
 * Caveat: keep the roster panel's team dropdown on YOUR team (the default). If
 * you switch it to view an opponent, their players would read as yours. */
const ROSTER = {
  ROW: 'tr.Table__TR',
  NAME: '.player-column',
  POS: '[title="Position"]'
};

/* The pick feed / draft log. Every team's pick posts here the instant it's made
 * (newest at the bottom), so this catches OPPONENTS' picks with no scrolling --
 * unlike the virtualized player pool, where a "Drafted" button only exists for
 * rows you've scrolled into view. Feed entries are marked ☑ (taken); the roster
 * scan still upgrades your own picks to ★, so we don't need to read the drafting
 * team name here.
 *   Item: li.pick-message__container  (one per pick)
 *   Name: .playerinfo__playername     (e.g. "Steelers D/ST") */
const FEED = {
  ITEM: 'li.pick-message__container',
  NAME: '.playerinfo__playername'
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
  console.log('[fflDraft] send', mine ? '★' : '☑', name);
  api.runtime.sendMessage({ type: 'PICK', name: name, mine: !!mine }).then((r) => {
    if (!r)        setStatus(`? ${name} — no reply`, 'warn');
    else if (r.ok) { if (cur === undefined) bump(); setStatus(`${mine ? '★' : '☑'} ${name} (row ${r.row})`, 'ok'); }
    else           { sent.delete(key); setStatus(`✗ ${name} — ${r.error}`, 'err'); }
  });
}

/* ---- auto detection ----------------------------------------------------- */
// The player name inside a container (.playerinfo__playername; a sibling span
// holds the news-icon link and the injury tag, so we don't read those).
function nameIn(el) {
  const n = el && el.querySelector(SEL.NAME);
  const t = n && (n.textContent || '').trim();
  return t && t.length >= 3 ? t : null;
}
function scanDrafted() {
  // TAKEN: a drafted button means the player is off the board. Its row carries
  // ESPN's .my-pick marker when the player is yours, so we can tag ☑-vs-★ right
  // here on the pool tab -- no waiting to see a roster panel.
  document.querySelectorAll(SEL.DRAFTED_BTN).forEach((btn) => {
    const row = btn.closest(SEL.ROW) || btn.closest('[role="row"]');
    const name = nameIn(row);
    if (name) push(name, !!(row && row.querySelector(SEL.MINE)));
  });
  // MINE: anywhere ESPN marks a pick as yours (the always-visible draft log /
  // pick feed uses .player-column.my-pick). Lag-free -- ★ the moment it lands.
  document.querySelectorAll(SEL.MINE).forEach((pc) => {
    const name = nameIn(pc);
    if (name) push(name, true);             // ★ mine (wins over ☑)
  });
  scanFeed();
  scanRoster();
}

// TAKEN (scroll-proof): the pick feed lists every pick as it's made, so we catch
// opponents' picks here without scrolling the pool. Mark ☑; scanRoster upgrades
// any of these that are yours to ★.
function scanFeed() {
  document.querySelectorAll(FEED.ITEM).forEach((li) => {
    const n = li.querySelector(FEED.NAME);
    const name = n && (n.textContent || '').trim();
    if (name && name.length >= 3) push(name, false);
  });
}

// MINE (search-proof): read the Roster sidebar. It's never virtualized, so a
// player you searched-and-drafted is still listed here after their pool row
// scrolls away -- which is exactly the case where the pool my-pick marker
// vanishes before it can upgrade ☑ to ★.
function scanRoster() {
  document.querySelectorAll(ROSTER.ROW).forEach((tr) => {
    if (!tr.querySelector(ROSTER.POS)) return;          // not a roster row (skip Pick Queue etc.)
    const pc = tr.querySelector(ROSTER.NAME);
    const name = pc && (pc.getAttribute('title') || '').trim();
    if (!name || /^empty$/i.test(name)) return;         // empty bench slot
    push(name, true);                                    // ★ mine
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
  // Default to the LEFT so it never covers ESPN's picks pane / pick history
  // (both on the right, with new picks at the bottom). Drag it anywhere by the
  // title bar, or collapse it to just the title with the ⌄ button.
  box.style.cssText = 'position:fixed;left:14px;bottom:14px;z-index:2147483647;width:250px;'
    + 'font:12px/1.4 system-ui,sans-serif;background:#fff;color:#202124;border:1px solid #dadce0;'
    + 'border-radius:10px;box-shadow:0 4px 16px rgba(0,0,0,.18);padding:10px;';
  box.innerHTML =
      '<div id="ffld-title" style="font-weight:600;margin-bottom:6px;cursor:move;display:flex;justify-content:space-between;align-items:center;user-select:none">'
    + '  <span>fflDraft <span style="font-weight:400;color:#5f6368">· ' + FFLD_VERSION + '</span></span>'
    + '  <span id="ffld-collapse" title="collapse / expand" style="color:#5f6368;cursor:pointer;padding:0 4px">⌄</span>'
    + '</div>'
    + '<div id="ffld-body">'
    + '<div id="ffld-status" style="min-height:16px;margin-bottom:6px">idle</div>'
    + '<div style="display:flex;gap:6px;margin-bottom:6px">'
    + '  <input id="ffld-name" placeholder="mark MY pick…" style="flex:1;min-width:0;padding:4px 6px;border:1px solid #dadce0;border-radius:6px">'
    + '  <button id="ffld-mark" style="padding:4px 8px;border:0;border-radius:6px;background:#1a73e8;color:#fff;cursor:pointer">★ Mine</button>'
    + '</div>'
    + '<div style="display:flex;justify-content:space-between;align-items:center;color:#5f6368">'
    + '  <span>marked: <b id="ffld-count">0</b></span>'
    + '  <span><a id="ffld-reset" href="#" style="color:#c5221f;text-decoration:none">reset board</a></span>'
    + '</div>'
    + '<div style="margin-top:6px;color:#9aa0a6;font-size:11px">Alt+D marks selected text as ★ mine</div>'
    + '</div>';
  document.body.appendChild(box);

  // Drag by the title bar (switches anchoring to left/top on first move).
  const title = box.querySelector('#ffld-title');
  let drag = null;
  title.addEventListener('pointerdown', (e) => {
    if (e.target.id === 'ffld-collapse') return;
    const r = box.getBoundingClientRect();
    drag = { dx: e.clientX - r.left, dy: e.clientY - r.top };
    box.style.right = box.style.bottom = 'auto';
    box.style.left = r.left + 'px'; box.style.top = r.top + 'px';
    title.setPointerCapture(e.pointerId);
  });
  title.addEventListener('pointermove', (e) => {
    if (!drag) return;
    box.style.left = (e.clientX - drag.dx) + 'px';
    box.style.top  = (e.clientY - drag.dy) + 'px';
  });
  title.addEventListener('pointerup', (e) => { drag = null; title.releasePointerCapture(e.pointerId); });

  // Collapse to just the title bar.
  const body = box.querySelector('#ffld-body');
  box.querySelector('#ffld-collapse').addEventListener('click', () => { body.hidden = !body.hidden; });

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

if (document.body) {
  console.log('[fflDraft] content ' + FFLD_VERSION + ' loaded — roster scan active');
  panel();
  startAuto();
}
