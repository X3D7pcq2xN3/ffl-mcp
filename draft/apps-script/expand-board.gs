/**
 * fflDraft — expandBoard(): one-time board expansion.
 *
 * Appends 72 players (to 250 total) to the Draft Board and extends every range
 * keyed to row 180 out to row 252: the column-A dropdown, the strike/shade
 * conditional formatting, the My Team + Byes roster filter, its player count,
 * and the bye-week COUNTIFS. Run ONCE from the Apps Script editor (pick
 * expandBoard in the function dropdown -> Run). It refuses to run twice.
 *
 * AFTER running: set CFG.LAST_ROW = 252 in mark-drafted.gs and redeploy the web
 * app (Manage deployments -> New version) so the marker scans the new rows.
 *
 * New rows carry Player / Pos / Team / Bye and a live injury Flag; Value /
 * Verdict / Notes are left blank (no ADP/ECR source to rate deep players).
 */

var EXP_LAST = 252, EXP_START = 181, BOARD = 'Draft Board', MYTEAM = 'My Team + Byes';

// [Player, Pos, TeamCode, Bye, InjuryFlag] -- ranked by Sleeper relevance
var EXP_ROWS = [
  ['Brian Robinson','RB','ATL',11,''],
  ['Oronde Gadsden','TE','LAC',7,''],
  ['Tyler Allgeier','RB','ARI',14,''],
  ['James Conner','RB','ARI',14,'IR - Foot'],
  ['Hunter Henry','TE','NE',11,''],
  ['Fernando Mendoza','QB','LV',13,''],
  ['Dalton Schultz','TE','HOU',8,''],
  ['C.J. Stroud','QB','HOU',8,''],
  ['Juwan Johnson','TE','NO',8,''],
  ['Brenton Strange','TE','JAX',7,''],
  ['Cam Ward','QB','TEN',9,''],
  ['Travis Hunter','WR','JAX',7,''],
  ['Kenyon Sadiq','TE','NYJ',13,'Questionable - Abdomen'],
  ['Tyrone Tracy','RB','NYG',8,'Questionable - Neck'],
  ['Emmett Johnson','RB','KC',5,''],
  ['Trey Benson','RB','ARI',14,'IR - Knee'],
  ['Jonah Coleman','RB','DEN',10,''],
  ['Malik Willis','QB','MIA',6,''],
  ['Chris Rodriguez','RB','JAX',7,''],
  ['AJ Barner','TE','SEA',11,''],
  ['T.J. Hockenson','TE','MIN',6,''],
  ['Bryce Young','QB','CAR',5,''],
  ['Dylan Sampson','RB','CLE',11,''],
  ['Daniel Jones','QB','IND',13,''],
  ['David Njoku','TE','LAC',7,''],
  ['Colby Parkinson','TE','LAR',11,''],
  ['Chig Okonkwo','TE','WAS',7,''],
  ['Mason Taylor','TE','NYJ',13,''],
  ['Eli Stowers','TE','PHI',10,'Questionable - Hamstring'],
  ['Kimani Vidal','RB','LAC',7,''],
  ['Terrance Ferguson','TE','LAR',11,'Questionable - Undisclosed'],
  ['Ja\'Kobi Lane','WR','BAL',13,''],
  ['Theo Johnson','TE','NYG',8,'Questionable - Undisclosed'],
  ['Chris Boswell','K','PIT',9,''],
  ['Cade Otton','TE','TB',10,''],
  ['Keaton Mitchell','RB','LAC',7,'Questionable - Undisclosed'],
  ['Evan McPherson','K','CIN',6,''],
  ['Omar Cooper','WR','NYJ',13,''],
  ['Gunnar Helm','TE','TEN',9,''],
  ['Harrison Butker','K','KC',5,''],
  ['Sean Tucker','RB','TB',10,'Questionable - Undisclosed'],
  ['Antonio Williams','WR','WAS',7,''],
  ['Kaytron Allen','RB','WAS',7,''],
  ['Andy Borregales','K','NE',11,''],
  ['Kaelon Black','RB','SF',8,''],
  ['Emanuel Wilson','RB','SEA',11,'Questionable - Hamstring'],
  ['Adonai Mitchell','WR','NYJ',13,''],
  ['Kayshon Boutte','WR','HOU',8,''],
  ['Will Reichard','K','MIN',6,''],
  ['Nicholas Singleton','RB','TEN',9,''],
  ['Ray Davis','RB','BUF',7,''],
  ['Najee Harris','RB','NYG',8,''],
  ['Troy Franklin','WR','DEN',10,''],
  ['Pat Bryant','WR','DEN',10,''],
  ['Kaleb Johnson','RB','GB',11,''],
  ['Eddy Pineiro','K','SF',8,''],
  ['Jaylen Wright','RB','MIA',6,''],
  ['Chimere Dike','WR','TEN',9,''],
  ['Demond Claiborne','RB','MIN',6,''],
  ['Ben Roethlisberger','QB','PIT',9,''],
  ['Brandon Aiyuk','WR','SF',8,'DNR - Knee - ACL + MCL'],
  ['Jake Tonges','TE','SF',8,''],
  ['Cyrus Allen','WR','KC',5,''],
  ['Tre\' Harris','WR','LAC',7,'Questionable - Undisclosed'],
  ['Jacoby Brissett','QB','ARI',14,''],
  ['Kendre Miller','RB','NO',8,'Questionable - Undisclosed'],
  ['Brashard Smith','RB','KC',5,''],
  ['Isaac TeSlaa','WR','DET',6,''],
  ['Elic Ayomanor','WR','TEN',9,''],
  ['Zachariah Branch','WR','ATL',11,''],
  ['Aaron Rodgers','QB','PIT',9,''],
  ['Jaydon Blue','RB','PHI',10,'']
];

function expandBoard() {
  var ss = SpreadsheetApp.getActive(), bd = ss.getSheetByName(BOARD);
  if (!bd) throw new Error('sheet "' + BOARD + '" not found');
  if (bd.getRange(EXP_START, 4).getValue()) {
    SpreadsheetApp.getUi().alert('Already expanded (row ' + EXP_START + ' has a player). Nothing done.');
    return;
  }
  for (var i = 0; i < EXP_ROWS.length; i++) {
    var r = EXP_START + i, p = EXP_ROWS[i];
    bd.getRange(r, 1).setValue('☐');
    bd.getRange(r, 2).setValue(179 + i);
    bd.getRange(r, 4).setValue(p[0]);
    bd.getRange(r, 5).setValue(p[1]);
    bd.getRange(r, 7).setValue(p[2]);
    if (p[3] !== '') bd.getRange(r, 8).setValue(p[3]);
    if (p[4]) bd.getRange(r, 13).setValue(p[4]);
  }
  var dv = SpreadsheetApp.newDataValidation().requireValueInList(['☐','☑','★'], true)
    .setAllowInvalid(true).build();
  bd.getRange(EXP_START, 1, EXP_LAST - EXP_START + 1, 1).setDataValidation(dv);
  var rules = bd.getConditionalFormatRules(), out = [];
  for (var j = 0; j < rules.length; j++) {
    var ranges = rules[j].getRanges(), nr = [];
    for (var k = 0; k < ranges.length; k++) {
      var rg = ranges[k];
      if (rg.getRow() === 3 && rg.getLastRow() === 180)
        nr.push(bd.getRange(3, rg.getColumn(), EXP_LAST - 2, rg.getNumColumns()));
      else nr.push(rg);
    }
    out.push(rules[j].copy().setRanges(nr).build());
  }
  bd.setConditionalFormatRules(out);
  var mt = ss.getSheetByName(MYTEAM);
  if (mt) {
    var L = EXP_LAST, q = String.fromCharCode(34);
    mt.getRange('B3').setFormula("=COUNTIF('"+BOARD+"'!$A$3:$A$"+L+","+q+"★"+q+")");
    mt.getRange('A5').setFormula(
      "=IFERROR(SORT(FILTER({'"+BOARD+"'!D3:D"+L+",'"+BOARD+"'!E3:E"+L+",'"+BOARD+"'!G3:G"+L
      +",'"+BOARD+"'!H3:H"+L+",'"+BOARD+"'!M3:M"+L+"},'"+BOARD+"'!A3:A"+L+"="+q+"★"+q
      +"),2,TRUE),"+q+"— no players set to ★ yet —"+q+")");
    var poscols = {9:'QB',10:'RB',11:'WR',12:'TE'};
    for (var row = 5; row <= 14; row++) {
      for (var col in poscols) {
        mt.getRange(row, Number(col)).setFormula(
          "=COUNTIFS('"+BOARD+"'!$A$3:$A$"+L+","+q+"★"+q+",'"+BOARD+"'!$E$3:$E$"+L+","
          +q+poscols[col]+q+",'"+BOARD+"'!$H$3:$H$"+L+",$H"+row+")");
      }
    }
  }
  SpreadsheetApp.getUi().alert('Expanded to ' + EXP_LAST + ' rows (' + EXP_ROWS.length +
    ' added). Now set CFG.LAST_ROW = ' + EXP_LAST + ' in mark-drafted.gs and redeploy.');
}
