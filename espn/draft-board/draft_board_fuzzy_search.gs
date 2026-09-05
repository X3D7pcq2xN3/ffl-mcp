/**
 * Draft Board — live fuzzy search (Google Sheets, browser).
 * Setup: open the workbook as a native Google Sheet -> Extensions > Apps Script,
 * paste this, Save. Then type any part of a player name in the A1 search box on the
 * "Draft Board" tab and press Enter; non-matching players hide. Clear the box to reset.
 * Simple onEdit trigger — no permissions popup, runs entirely in the browser.
 */
function onEdit(e) {
  var sh = e.range.getSheet();
  if (sh.getName() !== "Draft Board") return;           // only the Draft Board tab
  if (e.range.getRow() !== 1 || e.range.getColumn() !== 1) return;  // only the A1 box

  var FIRST = 3, LAST = 180, N = LAST - FIRST + 1;       // player rows 3-180
  var srch = String(e.value == null ? "" : e.value).toLowerCase().trim();

  sh.showRows(FIRST, N);                                 // reset: show all players
  if (srch === "") return;                               // empty box = everything visible

  var names = sh.getRange(FIRST, 4, N, 1).getValues();   // column D = Player
  var runStart = -1, runLen = 0;
  for (var i = 0; i <= N; i++) {
    var hide = (i < N) && String(names[i][0]).toLowerCase().indexOf(srch) === -1;
    if (hide) {
      if (runStart === -1) { runStart = FIRST + i; runLen = 1; } else { runLen++; }
    } else if (runStart !== -1) {
      sh.hideRows(runStart, runLen);                     // hide non-matching rows in blocks
      runStart = -1; runLen = 0;
    }
  }
}
