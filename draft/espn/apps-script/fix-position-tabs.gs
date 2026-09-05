/**
 * fflDraft -- relink the position tabs (RB/WR/QB/TE) to the FULL Draft Board.
 *
 * Each position tab's column A shows a player's drafted mark by looking the
 * player up on the Draft Board:
 *   =IFERROR(INDEX('Draft Board'!$A$2:$A$179, MATCH($D2,'Draft Board'!$D$2:$D$179,0)), "☐")
 * The range stopped at row 179, but the board now runs to row 252 (expandBoard),
 * so a player drafted in rows 180-252 wasn't found and the tab showed ☐ -- the
 * "missing ☑" bug. This rewrites those formulas to reference the WHOLE Draft
 * Board columns ($A:$A / $D:$D) so the lookup can never fall off the end again,
 * whatever the board's length.
 *
 * Run once from the Apps Script editor (Run > fixPositionTabs), then the tabs
 * update live off the Draft Board like the rest of the board. Idempotent --
 * safe to run again. Only cells that already hold the Draft Board lookup are
 * touched; nothing else on the tab changes.
 */
function fixPositionTabs() {
  var TABS = ['RB', 'WR', 'QB', 'TE'];   // K & DST is built differently; not touched
  var ss = SpreadsheetApp.getActive();
  var out = [];
  TABS.forEach(function (name) {
    var sh = ss.getSheetByName(name);
    if (!sh) { out.push(name + ': not found'); return; }
    var last = sh.getLastRow();
    if (last < 2) { out.push(name + ': empty'); return; }
    var formulas = sh.getRange(2, 1, last - 1, 1).getFormulas();  // column A, rows 2..last
    var changed = 0;
    for (var i = 0; i < formulas.length; i++) {
      var f = formulas[i][0];
      if (f && f.indexOf('Draft Board') !== -1) {   // only the existing lookup cells
        var row = 2 + i;
        sh.getRange(row, 1).setFormula(
          "=IFERROR(INDEX('Draft Board'!$A:$A,MATCH($D" + row +
          ",'Draft Board'!$D:$D,0)),\"☐\")");
        changed++;
      }
    }
    out.push(name + ': ' + changed);
  });
  SpreadsheetApp.getUi().alert('Position tabs relinked to the full Draft Board (rows updated):\n' + out.join('\n'));
  return out.join(', ');
}

/**
 * fixStrikethrough -- make the drafted-row strikethrough correct everywhere.
 *
 *   Draft Board: the strike rule (=OR($A3="★",$A3="☑")) only covered rows
 *     3-180; extend it down to 252 so the expanded players strike through too.
 *   Position tabs (RB/WR/QB/TE): the strike rule only fired on ★ (your picks);
 *     change it to fire on ☑ or ★ so opponents' picks strike through as well,
 *     matching the board.
 *
 * Edits the EXISTING rules in place via ConditionalFormatRule.copy(), so the
 * strike styling itself is preserved untouched -- only the range (board) and
 * the formula (position tabs) change. Run once from the editor. Idempotent.
 */
function fixStrikethrough() {
  var ss = SpreadsheetApp.getActive();
  var out = [];

  var db = ss.getSheetByName('Draft Board');
  if (db) {
    var rules = db.getConditionalFormatRules(), changed = 0;
    for (var i = 0; i < rules.length; i++) {
      var f = _ruleFormula(rules[i]);
      if (f && f.indexOf('★') !== -1) {              // ★ -> a strike rule
        var newRanges = rules[i].getRanges().map(function (rg) {
          return db.getRange(rg.getRow(), rg.getColumn(), 252 - rg.getRow() + 1, rg.getNumColumns());
        });
        rules[i] = rules[i].copy().setRanges(newRanges).build();
        changed++;
      }
    }
    db.setConditionalFormatRules(rules);
    out.push('Draft Board: ' + changed + ' strike rule(s) extended to row 252');
  }

  ['RB', 'WR', 'QB', 'TE'].forEach(function (name) {
    var sh = ss.getSheetByName(name);
    if (!sh) { out.push(name + ': not found'); return; }
    var rules = sh.getConditionalFormatRules(), changed = 0;
    for (var i = 0; i < rules.length; i++) {
      var f = _ruleFormula(rules[i]);
      if (f && f.indexOf('★') !== -1 && f.indexOf('☑') === -1) {  // ★-only rule
        var row = rules[i].getRanges()[0].getRow();
        rules[i] = rules[i].copy()
          .whenFormulaSatisfied('=OR($A' + row + '="★",$A' + row + '="☑")')
          .build();
        changed++;
      }
    }
    sh.setConditionalFormatRules(rules);
    out.push(name + ': ' + changed + ' strike rule(s) now fire on ☑ too');
  });

  SpreadsheetApp.getUi().alert('Strikethrough updated:\n' + out.join('\n'));
  return out.join(', ');
}

// The custom formula of a conditional-format rule, or '' if it isn't one.
function _ruleFormula(rule) {
  var bc = rule.getBooleanCondition();
  if (!bc) return '';
  var vals = bc.getCriteriaValues();
  return (vals && vals.length) ? String(vals[0]) : '';
}
