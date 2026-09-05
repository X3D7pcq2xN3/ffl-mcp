/**
 * Draft Board — live fuzzy search + "hide drafted" toggle (Google Sheets, browser).
 *
 * Setup: open the workbook as a native Google Sheet -> Extensions > Apps Script,
 * paste this, Save. Two features share one onEdit trigger (Apps Script allows only
 * one onEdit per project, so both live here):
 *
 *   A1  — fuzzy search box. Type any part of a player name and non-matching rows
 *          hide; clear the box to reset.
 *   O1  — "hide drafted" toggle checkbox. Check it to hide every drafted row
 *          (☑ or ★) at once; uncheck to show all players again. Run
 *          setupDraftedToggle() once from the editor to place the checkbox.
 *
 * Simple onEdit trigger — no permissions popup, runs entirely in the browser.
 * (The mark-drafted web app hides rows one at a time as picks arrive; this O1
 * toggle is the manual bulk switch for the same idea.)
 */

var DB = { SHEET: 'Draft Board', FIRST: 3, LAST: 252 };  // player rows 3-252
var SEARCH_CELL = { row: 1, col: 1 };   // A1
var TOGGLE_CELL = { row: 1, col: 15 };  // O1
var DRAFTED_COL = 1;                     // column A = Drafted (☐/☑/★)
var UNDRAFTED = '☐';

function onEdit(e) {
  var sh = e.range.getSheet();
  if (sh.getName() !== DB.SHEET) return;                 // only the Draft Board tab
  var r = e.range.getRow(), c = e.range.getColumn();
  if (r === TOGGLE_CELL.row && c === TOGGLE_CELL.col) return toggleDrafted(sh);  // O1
  if (r === SEARCH_CELL.row && c === SEARCH_CELL.col) return searchFilter(sh, e); // A1
}

// A1 fuzzy search: hide players whose name (col D) doesn't contain the box text.
function searchFilter(sh, e) {
  var N = DB.LAST - DB.FIRST + 1;
  var srch = String(e.value == null ? '' : e.value).toLowerCase().trim();
  sh.showRows(DB.FIRST, N);                               // reset: show all players
  if (srch === '') return;                                // empty box = everything visible
  var names = sh.getRange(DB.FIRST, 4, N, 1).getValues(); // column D = Player
  hideWhere(sh, N, function (i) {
    return String(names[i][0]).toLowerCase().indexOf(srch) === -1;
  });
}

// O1 toggle: checked -> hide every drafted row (☑ or ★); unchecked -> show all.
function toggleDrafted(sh) {
  var N = DB.LAST - DB.FIRST + 1;
  sh.showRows(DB.FIRST, N);                               // always start from all-visible
  var on = sh.getRange(TOGGLE_CELL.row, TOGGLE_CELL.col).getValue() === true;
  if (!on) return;                                        // unchecked = show everything
  var marks = sh.getRange(DB.FIRST, DRAFTED_COL, N, 1).getValues();
  hideWhere(sh, N, function (i) {
    return marks[i][0] && marks[i][0] !== UNDRAFTED;      // drafted by anyone
  });
}

// Hide rows FIRST..LAST for which want(i) is true, in contiguous blocks (fast).
function hideWhere(sh, N, want) {
  var runStart = -1, runLen = 0;
  for (var i = 0; i <= N; i++) {
    var hide = (i < N) && want(i);
    if (hide) {
      if (runStart === -1) { runStart = DB.FIRST + i; runLen = 1; } else { runLen++; }
    } else if (runStart !== -1) {
      sh.hideRows(runStart, runLen);
      runStart = -1; runLen = 0;
    }
  }
}

// One-time: drop a checkbox in O1 and label it. Run from the Apps Script editor.
function setupDraftedToggle() {
  var sh = SpreadsheetApp.getActive().getSheetByName(DB.SHEET);
  if (!sh) throw new Error('sheet "' + DB.SHEET + '" not found');
  var cell = sh.getRange(TOGGLE_CELL.row, TOGGLE_CELL.col);          // O1
  cell.setDataValidation(SpreadsheetApp.newDataValidation().requireCheckbox().build());
  cell.setValue(false);
  cell.setNote('Hide drafted: check to hide every drafted row (☑ or ★), uncheck to show all.');
}
