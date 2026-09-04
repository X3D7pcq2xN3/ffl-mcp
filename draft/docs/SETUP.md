# Setup

Two halves: the **Apps Script** that marks the sheet, and the **Firefox/Zen
extension** that watches ESPN. Do them in that order — the extension needs the
web app URL.

## 1. Apps Script (the sheet marks itself)

1. Open `draft-board/2026_ESPN_FullPPR_Draft_Board.xlsx` as a **native Google
   Sheet** (upload to Drive → Open with Google Sheets, or File → Save as Google
   Sheets). The tab must be named **Draft Board** with players in **rows 3–180**
   and the name in **column D** — that's how the export is already shaped.
2. **Extensions → Apps Script**. Paste `apps-script/mark-drafted.gs`. (If you
   use the fuzzy-search box, keep `draft-board/draft_board_fuzzy_search.gs` too;
   they don't conflict.)
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

## 3. Confirm the ESPN selector (once, on a mock)

Auto-detection ships with broad guesses. To make it reliable:

1. Start an ESPN **mock draft**. Let a pick or two happen.
2. Right-click a completed pick in the pick feed → **Inspect**.
3. Find the element holding the player's **name**; note a stable class or an
   `a[href*="/player/"]`.
4. Put that selector in `extension/content.js` → `SEL.PICK_NAME`. Reload the
   temporary add-on.

Until then — and any time auto misbehaves — the panel still works:
- **type/paste a name** + Enter, or
- **select a name** on the page + **Alt+D**.

Both mark the sheet immediately, so you're never blocked.

## Resetting between mocks

Click **reset board** in the panel (or run `resetDrafted()` from the Apps Script
editor). It clears the strikethroughs.

## Notes

- The panel is a **passive sidecar** — it never touches ESPN's pick button, so
  if it breaks you lose auto-marking, never a pick.
- The **sheet is the source of truth**. Refreshing the ESPN tab re-injects the
  script; players already struck through stay struck through.
- The mark is **strikethrough only** by default (fully reversible). To also gray
  the row or stamp a column, set `MARK_FILL` / `STAMP_COL` in the script — note
  a fill overwrites your round banding on that cell.
