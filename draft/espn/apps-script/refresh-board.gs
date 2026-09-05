/**
 * Draft Board — live Status + ADP refresh (Google Sheets, browser, in place).
 *
 * Two menu buttons that pull from free public APIs and write live columns to the
 * RIGHT of the board, so nothing re-uploads the file and no existing column,
 * ranking or format is touched:
 *
 *   Draft Board ↻ > Refresh Status  — Sleeper players feed -> injury / team into
 *                                     a "Live Status" column, red = OUT-type,
 *                                     amber = questionable.
 *   Draft Board ↻ > Refresh ADP     — Fantasy Football Calculator full-PPR ADP
 *                                     into "Live ADP", plus a 7-day delta and a
 *                                     rising/falling arrow. Each run also appends
 *                                     a dated snapshot to a hidden ADPHistory tab
 *                                     so the delta has something to diff against.
 *
 * WHY THIS AND NOT THE PYTHON: draft/espn/draft-board/sleeper_status_refresh.py
 * writes a *copy* of a downloaded .xlsx. This edits the live Sheet itself, the
 * same design choice as mark-drafted.gs — the board you're reading stays current.
 *
 * ANNOTATION, NOT RE-RANKING: the ADP delta is a "the market moved" flag beside
 * your ranking, never a re-sort of the board. Your Exp Rk (col J) stays the
 * ranking. This mirrors the stance in the repo's trending.py: a soft signal
 * annotates, it does not become the score.
 *
 * NEWS/ECR: Sleeper gives status, not ranks; FFC gives ADP, not ECR. There is no
 * free expert-consensus-rank API worth depending on, so ECR stays your board's
 * hand-built col J. Only Status and ADP are live here.
 *
 * MANUAL BY DESIGN: nothing runs on a timer. The 7-day trend is only as complete
 * as the days you clicked Refresh ADP — run it a few times in the week before the
 * draft and the delta fills in; until there's history ≥7 days old the delta shows
 * the real gap it found (e.g. "ADP Δ (3d)") or "—".
 *
 * SETUP: open the workbook as a native Google Sheet -> Extensions > Apps Script,
 * paste this file alongside the others (mark-drafted.gs, autofit-rows.gs, the
 * fuzzy-search onEdit — they coexist), Save, and reload the Sheet. The project's
 * single onOpen (in autofit-rows.gs) calls addRefreshMenu(), so the "Draft Board
 * ↻" menu appears on reload; first run of each button authorizes (external fetch
 * + edit) once. See docs/SETUP.md.
 *
 * This file is self-contained: it carries its own name-folding helper (_nm)
 * rather than sharing mark-drafted.gs's _norm, so it can't collide as a second
 * top-level definition in the same project and still works if pasted on its own.
 * The folding is the same idea (accents / punctuation / Jr-Sr-III suffixes).
 */

var RB = {
  SHEET: 'Draft Board',
  FIRST_ROW: 3,          // first player row (matches mark-drafted / fuzzy-search)
  LAST_ROW: 252,         // last player row (expandBoard() grew the list to 252)
  HEADER_ROW: 2,         // the board's header row (row 1 is the fuzzy-search box)
  NAME_COL: 4,           // column D = Player

  // New live columns, placed right of the board's used range (A–O = 15). These
  // are deliberately separate from the board's own static ADP (col I) and Exp Rk
  // (col J) — those are your curated numbers and are never written here.
  STATUS_COL: 16,        // P — Live Status (Sleeper)
  ADP_COL:    17,        // Q — Live ADP (FFC full PPR)
  DELTA_COL:  18,        // R — ADP Δ vs ~7 days ago
  TREND_COL:  19,        // S — rising / falling arrow

  HISTORY_SHEET: 'ADPHistory',   // hidden; one dated column per snapshot
  TREND_DAYS: 7,                 // target look-back for the delta
  MOVE_MIN: 3.0,                 // spots of ADP movement before an arrow shows

  // FFC full-PPR ADP. teams=12 matches the league (16×12 draft); year is the
  // current season. No key required.
  FFC_URL: 'https://fantasyfootballcalculator.com/api/v1/adp/ppr?teams=12&year=2026',
  SLEEPER_URL: 'https://api.sleeper.app/v1/players/nfl',

  DARK: '#1F2937', WHITE: '#FFFFFF',
  RED: '#FCA5A5', AMBER: '#FDE68A'
};

// OUT-type injury/status tokens (shade red); "questionable" shades amber.
var RB_OUT_LIKE = ['out', 'ir', 'pup', 'sus', 'susp', 'doubtful', 'dnr', 'nfi'];

// ---- menu ------------------------------------------------------------------

// This project already defines onOpen (autofit-rows.gs), and Apps Script runs
// only ONE onOpen. So this file does NOT declare its own -- it exposes the menu
// builder instead, and the shared onOpen calls it (see autofit-rows.gs and
// docs/SETUP.md). Run this once from the editor if you want the menu before the
// next reload.
function addRefreshMenu() {
  SpreadsheetApp.getUi()
    .createMenu('Draft Board ↻')
    .addItem('Refresh Status (Sleeper)', 'refreshStatus')
    .addItem('Refresh ADP (FFC)', 'refreshADP')
    .addToUi();
}

// ---- name folding (self-contained; mirrors mark-drafted's _norm) ------------

function _nm(s) {
  return String(s || '')
    .normalize('NFKD').replace(/[\u0300-\u036f]/g, '')  // accents
    .toLowerCase()
    .replace(/[.'`’\-]/g, ' ')                          // punctuation
    .replace(/\b(jr|sr|ii|iii|iv|v)\b/g, ' ')              // suffixes
    .replace(/[^a-z ]/g, ' ')
    .replace(/\s+/g, ' ').trim();
}

// First-initial + last-name key, the fallback when the full string differs
// (e.g. board "D.J. Moore" -> "d j moore" vs a feed's "dj moore"). Mirrors
// mark-drafted.gs's _fiKey. Operates on an already-folded key.
function _fiOf(key) {
  var p = String(key || '').split(' ');
  if (p.length < 2 || !p[0]) return null;
  return p[0].charAt(0) + '|' + p[p.length - 1];
}

// Add a folded key's value under its first-initial+last fallback, marking the
// slot ambiguous (null) if two different players share it — an ambiguous
// initial+last never resolves, which is the safe choice.
function _putFi(fi, key, val) {
  var k = _fiOf(key);
  if (k) fi[k] = (k in fi) ? null : val;
}

// Look a board key up in a feed index {exact, fi}: exact first, then an
// unambiguous initial+last fallback. Returns the value or undefined.
function _lookup(feed, key) {
  if (key in feed.exact) return feed.exact[key];
  var k = _fiOf(key);
  if (k && feed.fi[k]) return feed.fi[k];
  return undefined;
}

// Team defenses ("Seattle DST") are named by city on the board but by full team
// name in the feeds, so they never match by name. Their live status is
// meaningless (a defense has no injury) and their ADP is low-signal, so board
// DST rows are marked with a neutral "—" rather than a noisy "no match".
function _isDst(raw) {
  var s = _nm(raw);
  return s.indexOf('dst') !== -1 || s.indexOf('d st') !== -1 ||
         s.indexOf('defense') !== -1;
}

// The board's player rows as [{row, key, raw}], skipping blanks. Shared by both
// refreshers so they walk the board the same way.
function _boardRows(sh) {
  var n = RB.LAST_ROW - RB.FIRST_ROW + 1;
  var names = sh.getRange(RB.FIRST_ROW, RB.NAME_COL, n, 1).getValues();
  var out = [];
  for (var i = 0; i < n; i++) {
    var raw = names[i][0];
    if (!raw) continue;
    out.push({ row: RB.FIRST_ROW + i, key: _nm(raw), raw: String(raw) });
  }
  return out;
}

function _board() {
  var sh = SpreadsheetApp.getActive().getSheetByName(RB.SHEET);
  if (!sh) throw new Error('sheet "' + RB.SHEET + '" not found');
  return sh;
}

// Style a header cell in the board's dark/white house style.
function _header(sh, col, text) {
  var c = sh.getRange(RB.HEADER_ROW, col);
  c.setValue(text);
  c.setFontColor(RB.WHITE).setFontWeight('bold').setBackground(RB.DARK)
   .setHorizontalAlignment('center');
  sh.setColumnWidth(col, 130);
}

function _toast(msg, title) {
  SpreadsheetApp.getActive().toast(msg, title || 'Draft Board ↻', 8);
}

// ---- Refresh Status (Sleeper) ----------------------------------------------

function refreshStatus() {
  var sh = _board();
  var idx;
  try {
    idx = _sleeperIndex_();
  } catch (err) {
    _toast('Sleeper fetch failed: ' + err, 'Refresh Status');
    return;
  }

  _header(sh, RB.STATUS_COL, 'Live Status');

  var rows = _boardRows(sh);
  var matched = 0, miss = 0, red = 0, amber = 0;
  for (var i = 0; i < rows.length; i++) {
    var cell = sh.getRange(rows[i].row, RB.STATUS_COL);
    cell.setBackground(null).setHorizontalAlignment('center');
    if (_isDst(rows[i].raw)) { cell.setValue('—'); continue; }
    var rec = _lookup(idx, rows[i].key);
    if (!rec) { cell.setValue('— no match —'); miss++; continue; }
    cell.setValue(_statusText_(rec));
    var sev = _severity_(rec);
    if (sev === 'red')   { cell.setBackground(RB.RED);   red++; }
    else if (sev === 'amber') { cell.setBackground(RB.AMBER); amber++; }
    matched++;
  }
  _toast('Status: ' + matched + ' matched, ' + red + ' OUT-type, ' + amber +
         ' quest., ' + miss + ' unmatched.', 'Refresh Status');
}

// normalized full name -> Sleeper record, preferring fantasy-relevant entries.
function _sleeperIndex_() {
  var resp = UrlFetchApp.fetch(RB.SLEEPER_URL, {
    muteHttpExceptions: true, headers: { 'User-Agent': 'ffl-draft-board' }
  });
  if (resp.getResponseCode() !== 200) {
    throw new Error('HTTP ' + resp.getResponseCode());
  }
  var players = JSON.parse(resp.getContentText());
  var exact = {}, fi = {};
  for (var id in players) {
    var p = players[id];
    var full = p.full_name ||
      [p.first_name, p.last_name].filter(function (x) { return x; }).join(' ');
    var key = _nm(full);
    if (!key) continue;
    var prev = exact[key];
    // keep the most fantasy-relevant record when names collide
    if (!prev || (p.fantasy_positions && !prev.fantasy_positions)) {
      exact[key] = p;
      _putFi(fi, key, p);
    }
  }
  return { exact: exact, fi: fi };
}

function _statusText_(p) {
  var inj = String(p.injury_status || '').trim();
  var team = p.team || 'FA';
  var st = String(p.status || '').trim();          // Active / Inactive / ...
  var parts = [];
  if (inj) parts.push(inj);
  if (st && st.toLowerCase() !== 'active' && st.toLowerCase() !== inj.toLowerCase()) {
    parts.push(st);
  }
  return (parts.length ? parts.join(' / ') : 'Active') + ' (' + team + ')';
}

function _severity_(p) {
  var blob = (String(p.injury_status || '') + ' ' + String(p.status || '')).toLowerCase();
  for (var i = 0; i < RB_OUT_LIKE.length; i++) {
    if (blob.indexOf(RB_OUT_LIKE[i]) !== -1) return 'red';
  }
  if (blob.indexOf('questionable') !== -1) return 'amber';
  return 'none';
}

// ---- Refresh ADP (FFC) + 7-day trend ---------------------------------------

function refreshADP() {
  var sh = _board();
  var adp;
  try {
    adp = _ffcADP_();
  } catch (err) {
    _toast('FFC fetch failed: ' + err, 'Refresh ADP');
    return;
  }

  _header(sh, RB.ADP_COL, 'Live ADP');
  _header(sh, RB.TREND_COL, 'Trend');

  var tz = Session.getScriptTimeZone();
  var today = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');

  // Append today's snapshot first, so the history reflects this run.
  _appendSnapshot_(adp.exact, today);

  // Pick a reference column ~7 days old (else the oldest we have) to diff against.
  var ref = _referenceSnapshot_(today);
  _header(sh, RB.DELTA_COL,
          ref ? ('ADP Δ (' + ref.gapDays + 'd)') : 'ADP Δ (7d)');

  var rows = _boardRows(sh);
  var matched = 0, miss = 0;
  for (var i = 0; i < rows.length; i++) {
    var key = rows[i].key;
    var adpCell = sh.getRange(rows[i].row, RB.ADP_COL);
    var dCell = sh.getRange(rows[i].row, RB.DELTA_COL);
    var tCell = sh.getRange(rows[i].row, RB.TREND_COL);
    adpCell.setHorizontalAlignment('center');
    dCell.setHorizontalAlignment('center');
    tCell.setHorizontalAlignment('center');

    if (_isDst(rows[i].raw)) {
      adpCell.setValue('—'); dCell.setValue(''); tCell.setValue('');
      continue;
    }
    var cur = _lookup(adp, key);
    if (cur == null) {
      adpCell.setValue('— no match —');
      dCell.setValue(''); tCell.setValue('');
      miss++;
      continue;
    }
    adpCell.setValue(round1_(cur.adp));
    matched++;

    // Diff against the SAME feed entity's prior ADP. History is keyed by the
    // feed's own folded name, so use that (not the board key, which may have
    // matched via the initial+last fallback under a different spelling).
    var prior = ref ? ref.map[_nm(cur.name)] : null;
    if (prior == null) { dCell.setValue('—'); tCell.setValue(''); continue; }
    // ADP is average draft position: lower = drafted earlier. A player "rising"
    // has a FALLING ADP number, so delta = prior - current is positive when the
    // player is climbing draft boards.
    var delta = prior - cur.adp;
    dCell.setValue((delta > 0 ? '+' : '') + round1_(delta));
    if (delta >= RB.MOVE_MIN)      tCell.setValue('🔼');
    else if (delta <= -RB.MOVE_MIN) tCell.setValue('🔽');
    else tCell.setValue('');
  }
  _toast('ADP: ' + matched + ' matched, ' + miss + ' unmatched. ' +
         (ref ? ('Δ vs ' + ref.date + ' (' + ref.gapDays + 'd ago).')
              : 'No prior snapshot yet — run again over coming days for a trend.'),
         'Refresh ADP');
}

// FFC full-PPR ADP -> {exact: {normKey: {adp, name, pos, team}}, fi: {...}}.
function _ffcADP_() {
  var resp = UrlFetchApp.fetch(RB.FFC_URL, { muteHttpExceptions: true });
  if (resp.getResponseCode() !== 200) throw new Error('HTTP ' + resp.getResponseCode());
  var data = JSON.parse(resp.getContentText());
  var list = (data && data.players) || [];
  var exact = {}, fi = {};
  for (var i = 0; i < list.length; i++) {
    var p = list[i];
    var key = _nm(p.name);
    if (!key || p.adp == null) continue;
    // FFC is sorted by adp; first (best) entry wins on a name collision.
    if (!(key in exact)) {
      var v = { adp: Number(p.adp), name: p.name, pos: p.position, team: p.team };
      exact[key] = v;
      _putFi(fi, key, v);
    }
  }
  return { exact: exact, fi: fi };
}

// ---- ADPHistory (hidden snapshot store) ------------------------------------

// Layout: A1 = 'player_key', B1.. = snapshot dates (yyyy-MM-dd), newest to the
// right. Column A rows 2.. = normalized player keys; each dated column holds
// that player's ADP on that date. A same-day re-run overwrites that day's column.
function _historySheet_() {
  var ss = SpreadsheetApp.getActive();
  var sh = ss.getSheetByName(RB.HISTORY_SHEET);
  if (!sh) {
    sh = ss.insertSheet(RB.HISTORY_SHEET);
    sh.getRange(1, 1).setValue('player_key');
    sh.hideSheet();
  }
  return sh;
}

function _appendSnapshot_(adpByKey, dateStr) {
  var sh = _historySheet_();
  var lastRow = Math.max(sh.getLastRow(), 1);
  var lastCol = Math.max(sh.getLastColumn(), 1);

  // Existing key -> row (column A), building the row map once.
  var keyRow = {};
  if (lastRow >= 2) {
    var keys = sh.getRange(2, 1, lastRow - 1, 1).getValues();
    for (var i = 0; i < keys.length; i++) {
      if (keys[i][0]) keyRow[keys[i][0]] = 2 + i;
    }
  }

  // Reuse today's column if this is a same-day re-run, else add a new one.
  var dates = lastCol >= 2 ? sh.getRange(1, 2, 1, lastCol - 1).getValues()[0] : [];
  var col = -1;
  for (var c = 0; c < dates.length; c++) {
    if (Utilities.formatDate(new Date(dates[c] || 0), Session.getScriptTimeZone(),
        'yyyy-MM-dd') === dateStr || dates[c] === dateStr) { col = 2 + c; break; }
  }
  if (col === -1) { col = lastCol + 1; sh.getRange(1, col).setValue(dateStr); }

  // Add any players new to the history at the bottom of column A.
  var nextRow = lastRow + 1;
  for (var key in adpByKey) {
    if (!(key in keyRow)) { keyRow[key] = nextRow; sh.getRange(nextRow, 1).setValue(key); nextRow++; }
  }

  // Write the whole column in one shot (rows aligned to column A).
  var height = Math.max(nextRow - 1, sh.getLastRow());
  if (height >= 2) {
    var colVals = sh.getRange(2, col, height - 1, 1).getValues();
    var aKeys = sh.getRange(2, 1, height - 1, 1).getValues();
    for (var r = 0; r < aKeys.length; r++) {
      var k = aKeys[r][0];
      colVals[r][0] = (k && adpByKey[k]) ? adpByKey[k].adp : colVals[r][0];
    }
    sh.getRange(2, col, height - 1, 1).setValues(colVals);
  }
}

// Newest snapshot column whose date is ≥ TREND_DAYS old; else the oldest
// available; null if today's is the only column. Returns {date, gapDays, map}.
function _referenceSnapshot_(todayStr) {
  var sh = _historySheet_();
  var lastRow = sh.getLastRow(), lastCol = sh.getLastColumn();
  if (lastCol < 2 || lastRow < 2) return null;

  var dates = sh.getRange(1, 2, 1, lastCol - 1).getValues()[0];
  var tz = Session.getScriptTimeZone();
  var today = _asDate_(todayStr);

  // Candidate columns excluding today, with their age in days.
  var cands = [];
  for (var c = 0; c < dates.length; c++) {
    var ds = (dates[c] instanceof Date)
      ? Utilities.formatDate(dates[c], tz, 'yyyy-MM-dd') : String(dates[c]);
    if (!ds || ds === todayStr) continue;
    var gap = Math.round((today - _asDate_(ds)) / 86400000);
    cands.push({ col: 2 + c, date: ds, gapDays: gap });
  }
  if (!cands.length) return null;

  cands.sort(function (a, b) { return a.gapDays - b.gapDays; });   // youngest first
  var pick = null;
  for (var i = 0; i < cands.length; i++) {
    if (cands[i].gapDays >= RB.TREND_DAYS) { pick = cands[i]; break; }  // newest ≥7d
  }
  if (!pick) pick = cands[cands.length - 1];   // none ≥7d old -> the oldest we have

  // Build key -> adp for the chosen column.
  var keys = sh.getRange(2, 1, lastRow - 1, 1).getValues();
  var vals = sh.getRange(2, pick.col, lastRow - 1, 1).getValues();
  var map = {};
  for (var r = 0; r < keys.length; r++) {
    if (keys[r][0] && vals[r][0] !== '' && vals[r][0] != null) {
      map[keys[r][0]] = Number(vals[r][0]);
    }
  }
  return { date: pick.date, gapDays: pick.gapDays, map: map };
}

function _asDate_(yyyyMmDd) {
  var p = String(yyyyMmDd).split('-');
  return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
}

function round1_(x) { return Math.round(Number(x) * 10) / 10; }
