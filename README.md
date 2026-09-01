# ffl-mcp

A local tool that assembles my own Yahoo Fantasy Football league data, scores it
under my league's rules, and produces a weekly lineup and waiver-wire summary.

Personal project. Single private league. One user. Not deployed publicly and
not distributed as a product.

## What it does

Yahoo's API returns fantasy data; it does not return advice. This tool does the
retrieval, joining, and scoring, then hands the assembled picture to an LLM for
the reasoning. The value is in having roster state, league scoring rules, and
the available player pool in one place at the same time, so questions like
"who do I start at FLEX given my scoring settings and this week's byes" can be
answered without hand-assembling the data.

Output is a summary I read on my phone. Roster moves are made by hand in the
Yahoo Fantasy mobile app.

## Scope of access

Read-only. The tool issues GET requests against the Yahoo Fantasy Sports API for
a single league that my Yahoo account is a member of. It does not write lineups,
submit transactions, or modify league state.

No Yahoo data is redistributed or republished. A short-lived local file cache
holds league settings and player identifiers.

## Modules

| Module | Purpose |
| --- | --- |
| `players.py` | Yahoo ↔ Sleeper player ID crosswalk with name/team normalization |
| `scoring.py` | Translates Yahoo league scoring settings into a scoring function |
| `projections.py` | Fetches weekly projections from Sleeper's public API |
| `validate_scoring.py` | Verifies the scoring map against Sleeper's own computed point totals |

## Yahoo endpoints used

- `/league/{league_key}/settings` — scoring and roster rules
- `/team/{team_key}/roster` — current roster, eligible positions, injury status
- `/league/{league_key}/players` — free agents and waiver-wire players
- `/league/{league_key}/transactions` — recent league adds, drops, trades
- `/league/{league_key}/scoreboard` — current-week matchup

## Architecture

- Python, running locally under Termux on my own phone
- No network listener, no hosted component, no public deployment
- OAuth2 authorization code flow against Yahoo; refresh token stored locally
  and never committed
- Weekly projections sourced from Sleeper's public API and joined to Yahoo
  player IDs, since Yahoo does not expose projections through its API

## Status

Early development. Analysis layer built and validated; Yahoo client pending API
access approval.

## License

MIT
