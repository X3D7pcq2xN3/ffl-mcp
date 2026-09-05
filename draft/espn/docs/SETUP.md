# Setup

Two halves: the **Apps Script** that marks the sheet, and the **Firefox/Zen
extension** that watches ESPN. Do them in that order — the extension needs the
web app URL.

## 1. Apps Script (the sheet marks itself)

1. Open `draft-board/2026_ESPN_FullPPR_Draft_Board.xlsx` as a **native Google
   Sheet** (upload to Drive → Open with Google Sheets, or File → Save as Google
   Sheets). The tab must be named **Draft Board** with players in **rows 3–180**
   and the name in **column D** — that's how the export is already shaped.
2. **Extensions → Apps Script**. Paste `apps-script/mark-drafted.gs`. Add
   `apps-script/autofit-rows.gs` too (auto-fits row heights on open + a
   "Draft Board → Auto-fit rows" menu). If you use the fuzzy-search box, keep
   `draft-board/draft_board_fuzzy_search.gs` as well. To pull live injury status
   and market ADP into the board, also paste `apps-script/refresh-board.gs` (see
   [§4](#4-live-status--adp-optional)) — all of them coexist in one project.
   (Only paste one `onOpen`: `autofit-rows.gs` is the one that defines it, and it
   already calls `refresh-board.gs`'s menu via a guarded `addRefreshMenu()`. If
   another file defines its own `onOpen`, move the menu/auto-fit lines into a
   single one instead of declaring a second.)
3. In `CFG`, set `TOKEN` to any random string. Remember it for step 2 below.
4. **Deploy → New deployment → Web app**
   - *Execute as*: **Me**
   - *Who has access*: **Anyone with the link** (the token is the guard)
   - Authorize when prompted. Copy the **/exec** URL.
5. Sanity check: open that URL in a browser — you should see
   `{"ok":true,"service":"fflDraft mark-drafted"}`.

> Editing the script later? **Manage deployments → edit → New version**, or the
> old code keeps serving.

## 2. Extension (Firefox / Zen)

1. Go to `about:debugging` → **This Firefox** → **Load Temporary Add-on** →
   pick `extension/manifest.json`. (Temporary add-ons unload when the browser
   closes — fine for draft day. For a permanent install you'd sign it via AMO.)
2. Open the extension's **options** (about:addons → fflDraft → Preferences, or
   click the toolbar entry). Paste the **/exec** URL and the **same token**.
   Save.
3. Open your ESPN draft (a **mock draft** to test). A small **fflDraft** panel
   appears bottom-right. It should say **connected**.

## 3. Auto-detection (already wired to ESPN)

Auto-marking reads two things from ESPN's draft room, so the board can tell your
team from everyone else's:

- **Taken by anyone** → the player's draft button flips to the disabled
  **"Drafted"** state. The board marks these **☑** (struck, unavailable).
- **Your own picks** → ESPN tags them with its own `my-pick` class (in the
  draft log / pick feed and on the drafted row). The board marks these **★**,
  which is what the *My Team + Byes* tab filters on — instantly, with no
  roster-tab switching.

No setup — it works while the draft is open, and marks your ★ picks separately
from opponents' ☑ picks.

**One thing to keep set:** leave the player list on **"All"**, not "Available
only" — filtered-out drafted rows leave the page and can't be read as taken.

**Your own picks (★)** are read from the **Roster sidebar** (your team panel),
not just the pool table. That's what makes ★ reliable even for a player you had
to **search** for — searching filters the pool and the drafted row scrolls out
of the page before its "mine" marker can be read, but the roster panel always
lists your full team. **Keep the roster panel's team dropdown on your own team**
(the default); if you switch it to view an opponent, their players would be read
as yours.

If ESPN changes its markup in a future season and auto goes quiet, re-inspect
and update the selectors in `extension/content.js → SEL`.

The manual panel is always there as a fallback — **type/paste a name** + Enter,
or **select a name** on the page + **Alt+D** — so you're never blocked.

## 4. Live Status + ADP (optional)

`apps-script/refresh-board.gs` adds two **menu buttons** that pull from free
public APIs and write live columns to the **right** of the board (columns P–S),
so nothing re-uploads the file and no existing column, ranking, or format is
touched. Both are **manual** — nothing runs on a timer.

Paste `refresh-board.gs` into the same Apps Script project, Save, and reload the
Sheet. A **Draft Board ↻** menu appears (built by the shared `onOpen`):

- **Refresh Status (Sleeper)** → writes **Live Status** (col P): injury
  designation + team, shaded **red** for OUT/IR/PUP/SUS/DOUBTFUL and **amber**
  for QUESTIONABLE. This is the live version of `draft-board/sleeper_status_refresh.py`
  — but it edits the Sheet **in place** instead of writing a downloaded `.xlsx`
  copy, so the board you're reading stays current.
- **Refresh ADP (FFC)** → writes **Live ADP** (col Q) from Fantasy Football
  Calculator's full-PPR market ADP, plus **ADP Δ** (col R) and a **Trend** arrow
  (col S, 🔼/🔽 when a player moves ≥3 spots). Each run also appends a dated
  snapshot to a hidden **ADPHistory** tab.

First run of each button authorizes external fetch + edit once.

**About the 7-day trend.** The Δ diffs today's ADP against the snapshot closest
to 7 days old. History only accumulates on the days you click **Refresh ADP**, so
**run it a few times in the week before the draft** and the trend fills in. Until
there's a snapshot ≥7 days old, the Δ header shows the real gap it found (e.g.
`ADP Δ (3d)`) and unmatched-in-history players show `—`.

**Scope, honestly.** Live columns cover offensive players/kickers only —
**team defenses (DST)** show `—` (a defense has no injury, and its market ADP is
low-signal). There is **no live ECR/rankings feed** here: Sleeper gives status
not ranks, FFC gives ADP not ECR, and no free expert-consensus source is worth
depending on — so your **Exp Rk (col J)** stays the ranking. The ADP Δ is an
**annotation** ("the market moved"), never a re-sort of the board.

## Hiding drafted players

Two ways, both optional:

- **Automatic (per pick).** `mark-drafted.gs` hides each player's row the moment
  it's drafted (`CFG.HIDE_ON_MARK`, on by default), so the board shows only who's
  still on the clock. `reset` un-hides everything.
- **Manual toggle (O1).** Paste `draft-board/draft_board_fuzzy_search.gs`, then run
  `setupDraftedToggle()` once from the Apps Script editor to drop a checkbox in
  **cell O1** of the Draft Board. **Check it to hide every drafted row (☑ or ★)
  at once; uncheck to show them all again.** (It shares the same one-time
  `onEdit` as the A1 fuzzy-search box.)

## Resetting between mocks

Click **reset board** in the panel (or run `resetDrafted()` from the Apps Script
editor). It clears the strikethroughs and un-hides every row.

## Notes

- The panel is a **passive sidecar** — it never touches ESPN's pick button, so
  if it breaks you lose auto-marking, never a pick.
- The **sheet is the source of truth**. Refreshing the ESPN tab re-injects the
  script; players already struck through stay struck through.
- Marking sets the board's own **Drafted dropdown (column A)**: **★** for your
  picks (these flow to the My Team + Byes tab), **☑** for players another team
  took. Conditional formatting strikes both ★ and ☑ rows as unavailable; the
  My Team tab filters on ★ so only your team shows there. **reset** sets the
  dropdowns back to
  ☐. (This relies on the conditional-formatting rule reading its own row —
  `=$A3="★"`, not `$A2` — so a stale off-by-one rule strikes the wrong row.)
