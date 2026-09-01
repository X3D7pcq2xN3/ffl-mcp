# ffl-mcp

A local [MCP](https://modelcontextprotocol.io) server that exposes my own Yahoo
Fantasy Football league data to an LLM client for weekly lineup and waiver-wire
analysis.

Personal project. Single private league. One user. Not deployed publicly and
not distributed as a product.

## What it does

Yahoo's API returns fantasy data; it does not return advice. This server does
the retrieval and normalization, and leaves the reasoning to the model on the
other end of the MCP connection. The value is in having roster state, league
scoring rules, and the available player pool in one context at the same time,
so questions like "who do I start at FLEX given my scoring settings and this
week's byes" can be answered without hand-assembling the data.

## Scope of access

Read-only. The server issues GET requests against the Yahoo Fantasy Sports API
for a single league that my Yahoo account is a member of. It does not write
lineups, submit transactions, or modify league state. Roster moves are made by
hand in the Yahoo app.

No Yahoo data is cached beyond a short-lived local file cache for league
settings and player identifiers, and none of it is republished or shared.

## Tools

| Tool | Description |
| --- | --- |
| `get_roster` | Current roster with eligible positions, bye weeks, injury status |
| `get_league_scoring` | League scoring and roster settings |
| `get_available_players` | Free agents and waiver-wire players by position |
| `get_transactions` | Recent league-wide adds, drops, and trades |
| `get_matchup` | Current-week matchup and scoreboard |

## Architecture

- Python, [FastMCP](https://github.com/PrefectHQ/fastmcp), stdio transport
- Runs locally on my own machine; no network listener, no hosted component
- OAuth2 authorization code flow against Yahoo; refresh token stored locally
  and never committed
- Weekly projections sourced from a public third-party API and joined to Yahoo
  player IDs, since Yahoo does not expose projections through its API

## Status

Early development.

## License

MIT
