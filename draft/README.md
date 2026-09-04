# fflDraft-mcp

A draft-day companion for my ESPN fantasy football league. During a live draft
it watches the picks in the browser and strikes each drafted player off my
Google Sheets draft board automatically, so the board I'm reading is always
current without me marking players by hand.

The draft-day half of `ffl-mcp` (the rest of the repo is the in-season
lineup/waiver tool). This part is draft-only and deliberately small: no server,
no projections engine — it reuses the Google Sheet I already build each year and
just keeps it in sync with the live draft. It shares no code with the Python at
the repo root, only the name-normalization idea.

## How it works

```
ESPN draft tab                          Google Sheet (any other tab/window)
┌────────────────────┐                  ┌──────────────────────────────┐
│ content script      │  pick name       │  Draft Board                 │
│ • watches pick feed │ ───────────────▶ │  rows 3–180, col D = Player  │
│ • passive panel     │                  │  drafted rows struck through │
└─────────┬──────────┘                  └──────────────▲───────────────┘
          │ message                                     │ edits itself
          ▼                                             │
   ┌─ background.js ─┐   POST {name, token}   ┌─ Apps Script web app ─┐
   │ does the network │ ────────────────────▶ │ fuzzy-match col D →   │
   └──────────────────┘                       │ strikethrough the row │
                                              └───────────────────────┘
```

The key design choice: the extension **never edits the spreadsheet's cells
directly** (Google Sheets renders its grid on a canvas, so that path is
hopeless). Instead it POSTs the drafted player's name to a small Apps Script
**web app**, and the sheet edits *itself* — which also means the board updates
live in whatever tab or window it's open in.

## Layout

| Path | What it is |
| --- | --- |
| `extension/` | The Firefox/Zen WebExtension (manifest, background, content script, options) |
| `apps-script/mark-drafted.gs` | The Google Sheets web app that finds a player by name and strikes the row |
| `draft-board/` | The Draft Board workbook and the earlier prep scripts (fuzzy search, Sleeper status refresh, chat transcript) |
| `docs/SETUP.md` | Step-by-step install: deploy the web app, load the extension, confirm the ESPN selector on a mock |

## Status

Early. The Apps Script marker and the extension plumbing are complete and the
name matcher mirrors `ffl-mcp`'s (accents/punctuation/suffix folding, then
first-initial + last-name fallback). The one field to confirm against a live
**mock draft** is ESPN's pick-feed selector (`SEL.PICK_NAME` in
`extension/content.js`) — until it's set, the panel's manual entry and the
**Alt+D** hotkey mark the board reliably, so the tool is usable day one.

## Design principles

- **Passive sidecar** — never touches ESPN's own draft controls. If the script
  breaks, you lose auto-marking, never a pick.
- **Sheet is the source of truth** — a page refresh re-injects the script and
  already-drafted players stay marked.
- **Reversible marks** — strikethrough by default; a one-click *reset board*
  between mocks.
- **Read-only on ESPN** — observes picks, recommends nothing, automates no
  picks.

See `docs/SETUP.md` to install.
