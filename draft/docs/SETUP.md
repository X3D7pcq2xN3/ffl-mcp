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
   `draft-board/draft_board_fuzzy_search.gs` as well — all three coexist in one
   project. (Only paste one `onOpen`: if another file already defines one, move
   the menu/auto-fit lines into it instead of declaring a second.)
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

## 3. Auto-detection (already wired to ESPN's table)

Auto-marking reads ESPN's own player table: when a player is taken, their row's
draft button flips to the disabled **"Drafted"** state, and the extension reads
that. No setup — it just works while the draft is open.

**One thing to keep set:** leave ESPN's player list on **"All"**, not
**"Available only."** If drafted players are filtered out of the table, their
rows leave the page and there's nothing for the extension to read.

If ESPN changes its markup in a future season and auto goes quiet, re-inspect a
drafted row and update the three selectors in `extension/content.js → SEL`
(`DRAFTED_BTN`, `ROW`, `NAME`).

The manual panel is always there as a fallback — **type/paste a name** + Enter,
or **select a name** on the page + **Alt+D** — so you're never blocked.

## Resetting between mocks

Click **reset board** in the panel (or run `resetDrafted()` from the Apps Script
editor). It clears the strikethroughs.

## Notes

- The panel is a **passive sidecar** — it never touches ESPN's pick button, so
  if it breaks you lose auto-marking, never a pick.
- The **sheet is the source of truth**. Refreshing the ESPN tab re-injects the
  script; players already struck through stay struck through.
- Marking sets the board's own **Drafted dropdown (column A) to ★**; your
  sheet's conditional formatting strikes the row from there. So an auto-mark
  looks identical to a manual one, and **reset** just sets the dropdowns back to
  ☐. (This relies on the conditional-formatting rule reading its own row —
  `=$A3="★"`, not `$A2` — so a stale off-by-one rule strikes the wrong row.)
