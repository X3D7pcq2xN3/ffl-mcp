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
 * How it marks: it sets the board's OWN "Drafted" dropdown (column A) --
 * ★ for a pick of yours, ☑ for a player another team took -- and the sheet's
 * conditional formatting strikes the row. ★ is what the My Team + Byes tab
 * filters on, so only your picks land there. This is the board's native
 * mechanism, so an extension mark looks identical to a manual one, and reset
 * puts the dropdowns back to ☐. Run resetDrafted() from
 * the editor (or POST {action:"reset"}) to clear the board before a mock.
 */

var CFG = {
  SHEET: 'Draft Board',
  FIRST_ROW: 3,          // first player row
  LAST_ROW: 180,         // last player row
  NAME_COL: 4,           // column D = Player (used to find the row)
  DRAFTED_COL: 1,        // column A = the board's Drafted dropdown
  MINE: '★',             // my pick  -> flows to the My Team + Byes tab
  TAKEN: '☑',            // drafted by another team (unavailable, not mine)
  UNDRAFTED: '☐',        // still available
  TOKEN: 'CHANGE_ME'     // must equal the extension's token
};

function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);
    if (CFG.TOKEN && body.token !== CFG.TOKEN) return _json({ ok: false, error: 'bad token' });
    if (body.action === 'ping')  return _json({ ok: true, service: 'fflDraft', rows: [CFG.FIRST_ROW, CFG.LAST_ROW] });
    if (body.action === 'reset') return _json({ ok: true, reset: resetDrafted() });
    return _json(markDrafted(body.name, body.mine));
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

// Team defenses are named by city on the board ("Seattle DST") but by nickname
// in ESPN's draft ("Seahawks D/ST"), so neither exact nor initial+last match.
// Map every distinctive city/nickname token to a team code and match a defense
// on that code instead. Ambiguous bare tokens (la, new, york) are left out --
// the nickname (rams/chargers/giants/jets) disambiguates and is always present.
var TEAM = {
  arizona:'ARI', cardinals:'ARI', atlanta:'ATL', falcons:'ATL',
  baltimore:'BAL', ravens:'BAL', buffalo:'BUF', bills:'BUF',
  carolina:'CAR', panthers:'CAR', chicago:'CHI', bears:'CHI',
  cincinnati:'CIN', bengals:'CIN', cleveland:'CLE', browns:'CLE',
  dallas:'DAL', cowboys:'DAL', denver:'DEN', broncos:'DEN',
  detroit:'DET', lions:'DET', packers:'GB', houston:'HOU', texans:'HOU',
  indianapolis:'IND', colts:'IND', jacksonville:'JAX', jaguars:'JAX', jags:'JAX',
  chiefs:'KC', raiders:'LV', vegas:'LV', chargers:'LAC', rams:'LAR',
  miami:'MIA', dolphins:'MIA', minnesota:'MIN', vikings:'MIN',
  england:'NE', patriots:'NE', pats:'NE', orleans:'NO', saints:'NO',
  giants:'NYG', jets:'NYJ', philadelphia:'PHI', eagles:'PHI',
  pittsburgh:'PIT', steelers:'PIT', francisco:'SF', niners:'SF',
  seattle:'SEA', seahawks:'SEA', tampa:'TB', buccaneers:'TB', bucs:'TB',
  tennessee:'TEN', titans:'TEN', washington:'WAS', commanders:'WAS'
};

// A defense key ("dst|<code>") when the name looks like a team defense, else null.
function _dstKey(name) {
  var s = _norm(name);
  if (s.indexOf('dst') === -1 && s.indexOf('d st') === -1 && s.indexOf('defense') === -1) return null;
  var toks = s.split(' '), code = null;
  for (var i = 0; i < toks.length; i++) { if (TEAM[toks[i]]) { code = TEAM[toks[i]]; break; } }
  return code ? 'dst|' + code : null;
}

function _index() {
  var sh = SpreadsheetApp.getActive().getSheetByName(CFG.SHEET);
  if (!sh) throw new Error('sheet "' + CFG.SHEET + '" not found');
  var n = CFG.LAST_ROW - CFG.FIRST_ROW + 1;
  var names = sh.getRange(CFG.FIRST_ROW, CFG.NAME_COL, n, 1).getValues();
  var exact = {}, fi = {}, dst = {};
  for (var i = 0; i < n; i++) {
    var raw = names[i][0];
    if (!raw) continue;
    var row = CFG.FIRST_ROW + i;
    exact[_norm(raw)] = row;
    var k = _fiKey(raw);
    if (k) fi[k] = (k in fi) ? -1 : row;   // -1 marks an ambiguous initial+last
    var d = _dstKey(raw);
    if (d) dst[d] = row;
  }
  return { sh: sh, exact: exact, fi: fi, dst: dst };
}

function markDrafted(name, mine) {
  if (!name) return { ok: false, error: 'no name' };
  var ix = _index();
  var row = ix.exact[_norm(name)];
  var how = 'exact';
  if (!row) {
    var k = _fiKey(name);
    if (k && ix.fi[k] && ix.fi[k] !== -1) { row = ix.fi[k]; how = 'initial+last'; }
  }
  if (!row) {                                // team defense (city vs nickname)
    var d = _dstKey(name);
    if (d && ix.dst[d]) { row = ix.dst[d]; how = 'dst-team'; }
  }
  if (!row) return { ok: false, error: 'no match', name: name };

  // Set the board's own Drafted dropdown: ★ for my pick, ☑ for taken-by-another.
  // The sheet's conditional formatting strikes the row and the My Team + Byes
  // tab filters on ★. Never downgrade an existing ★ to ☑ (my pick also shows as
  // taken in ESPN's table, and the mark order isn't guaranteed).
  var cell = ix.sh.getRange(row, CFG.DRAFTED_COL);
  var mark = mine ? CFG.MINE : CFG.TAKEN;
  if (!(mark === CFG.TAKEN && cell.getValue() === CFG.MINE)) cell.setValue(mark);
  return { ok: true, row: row, match: how, name: name, mark: mark };
}

function resetDrafted() {
  var sh = SpreadsheetApp.getActive().getSheetByName(CFG.SHEET);
  var n = CFG.LAST_ROW - CFG.FIRST_ROW + 1;
  sh.getRange(CFG.FIRST_ROW, CFG.DRAFTED_COL, n, 1).setValue(CFG.UNDRAFTED);
  return n;
}
