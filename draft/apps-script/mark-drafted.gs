/**
 * fflDraft — mark-drafted endpoint (Google Sheets Apps Script web app).
 *
 * The spreadsheet marks itself. The browser extension watches the ESPN draft
 * and POSTs one player name per pick to this web app; this code finds the
 * player's row on the Draft Board and strikes it through. Because the edit
 * happens inside the sheet, the board updates live in whatever tab or window
 * you have it open in -- no cell-scripting from the extension, which is the
 * one thing that does NOT work reliably (Sheets renders its grid on a canvas).
 *
 * SETUP
 *   1. Open the workbook as a native Google Sheet.
 *   2. Extensions > Apps Script. Paste this file (alongside the fuzzy-search
 *      onEdit if you use it -- they coexist).
 *   3. Set CFG.TOKEN below to any random string; put the SAME string in the
 *      extension's options.
 *   4. Deploy > New deployment > type "Web app":
 *        - Execute as: Me
 *        - Who has access: Anyone with the link   (the token is the guard)
 *      Copy the /exec URL into the extension's options.
 *   5. Re-deploy (Manage deployments > edit > new version) whenever you edit
 *      this file, or the old code keeps serving.
 *
 * The mark is strikethrough on the name cell -- fully reversible. Run
 * resetDrafted() from the editor (or POST {action:"reset"}) to clear the
 * board before your next mock. Optional fill / stamp-column are OFF by
 * default because they would overwrite your round banding.
 */

var CFG = {
  SHEET: 'Draft Board',
  FIRST_ROW: 3,        // first player row
  LAST_ROW: 180,       // last player row
  NAME_COL: 4,         // column D = Player
  STAMP_COL: 0,        // set to a FREE column number to stamp "R.P"; 0 = off
  MARK_FILL: '',       // e.g. '#d9d9d9' to gray drafted rows; '' = off (keeps banding)
  TOKEN: 'CHANGE_ME'   // must equal the extension's token
};

function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);
    if (CFG.TOKEN && body.token !== CFG.TOKEN) return _json({ ok: false, error: 'bad token' });
    if (body.action === 'ping')  return _json({ ok: true, service: 'fflDraft', rows: [CFG.FIRST_ROW, CFG.LAST_ROW] });
    if (body.action === 'reset') return _json({ ok: true, reset: resetDrafted() });
    return _json(markDrafted(body.name, body.info || ''));
  } catch (err) {
    return _json({ ok: false, error: String(err) });
  }
}

// A browser GET is handy to confirm the deployment is live.
function doGet() { return _json({ ok: true, service: 'fflDraft mark-drafted' }); }

function _json(o) {
  return ContentService.createTextOutput(JSON.stringify(o))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * Name folding, mirroring ffl-mcp's players.normalize_name: strip accents,
 * punctuation and Jr/Sr/III suffixes, lowercase, collapse spaces. This is what
 * lets ESPN's "D.J. Moore" / "Marvin Harrison Jr." match the board's spelling.
 */
function _norm(s) {
  return String(s || '')
    .normalize('NFKD').replace(/[\u0300-\u036f]/g, '')  // accents
    .toLowerCase()
    .replace(/[.'`’\-]/g, ' ')                        // punctuation
    .replace(/\b(jr|sr|ii|iii|iv|v)\b/g, ' ')             // suffixes
    .replace(/[^a-z ]/g, ' ')
    .replace(/\s+/g, ' ').trim();
}

// First-initial + last-name key, the fallback when the full string differs.
function _fiKey(name) {
  var p = _norm(name).split(' ');
  if (p.length < 2 || !p[0]) return null;
  return p[0].charAt(0) + '|' + p[p.length - 1];
}

function _index() {
  var sh = SpreadsheetApp.getActive().getSheetByName(CFG.SHEET);
  if (!sh) throw new Error('sheet "' + CFG.SHEET + '" not found');
  var n = CFG.LAST_ROW - CFG.FIRST_ROW + 1;
  var names = sh.getRange(CFG.FIRST_ROW, CFG.NAME_COL, n, 1).getValues();
  var exact = {}, fi = {};
  for (var i = 0; i < n; i++) {
    var raw = names[i][0];
    if (!raw) continue;
    var row = CFG.FIRST_ROW + i;
    exact[_norm(raw)] = row;
    var k = _fiKey(raw);
    if (k) fi[k] = (k in fi) ? -1 : row;   // -1 marks an ambiguous initial+last
  }
  return { sh: sh, exact: exact, fi: fi };
}

function markDrafted(name, info) {
  if (!name) return { ok: false, error: 'no name' };
  var ix = _index();
  var row = ix.exact[_norm(name)];
  var how = 'exact';
  if (!row) {
    var k = _fiKey(name);
    if (k && ix.fi[k] && ix.fi[k] !== -1) { row = ix.fi[k]; how = 'initial+last'; }
  }
  if (!row) return { ok: false, error: 'no match', name: name };

  var cell = ix.sh.getRange(row, CFG.NAME_COL);
  cell.setFontLine('line-through');
  if (CFG.MARK_FILL) cell.setBackground(CFG.MARK_FILL);
  if (CFG.STAMP_COL) ix.sh.getRange(row, CFG.STAMP_COL).setValue(info || '✓');
  return { ok: true, row: row, match: how, name: name };
}

function resetDrafted() {
  var sh = SpreadsheetApp.getActive().getSheetByName(CFG.SHEET);
  var n = CFG.LAST_ROW - CFG.FIRST_ROW + 1;
  sh.getRange(CFG.FIRST_ROW, CFG.NAME_COL, n, 1).setFontLine('none');
  if (CFG.MARK_FILL) sh.getRange(CFG.FIRST_ROW, CFG.NAME_COL, n, 1).setBackground(null);
  if (CFG.STAMP_COL) sh.getRange(CFG.FIRST_ROW, CFG.STAMP_COL, n, 1).clearContent();
  return n;
}
