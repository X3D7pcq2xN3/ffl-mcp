/**
 * fflDraft — auto-fit Draft Board row heights.
 *
 * After an import (or once cells wrap), a fixed row height clips content. This
 * resizes each player row to fit what's in it, so nothing is cut off. It runs
 * automatically when the sheet is opened and adds a "Draft Board > Auto-fit
 * rows" menu item to re-run it on demand.
 *
 * Paste this into the same Apps Script project as the other files (it shares
 * the project with mark-drafted.gs and the fuzzy-search onEdit). It defines
 * onOpen -- if you already have an onOpen elsewhere, merge the menu line into
 * that one rather than declaring a second onOpen, since only one will run.
 *
 * Row heights are a display property, independent of the fuzzy search (which
 * hides/shows rows) and of the Drafted dropdown, so this never interferes with
 * either.
 */

var AUTOFIT = { SHEET: 'Draft Board', FIRST_ROW: 3, LAST_ROW: 180 };

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Draft Board')
    .addItem('Auto-fit rows', 'autoFitRows')
    .addToUi();
  autoFitRows();   // fit on open so the board is right the moment it loads
}

function autoFitRows() {
  var sh = SpreadsheetApp.getActive().getSheetByName(AUTOFIT.SHEET);
  if (!sh) return;
  sh.autoResizeRows(AUTOFIT.FIRST_ROW, AUTOFIT.LAST_ROW - AUTOFIT.FIRST_ROW + 1);
}
