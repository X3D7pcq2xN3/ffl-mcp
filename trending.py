"""Trending add/drop volume from Sleeper's public API.

A projection says how good a player is expected to be. It does not say that
something changed. A backup promoted after a Sunday injury carries the same
mediocre projection on Tuesday morning that he carried on Sunday morning --
the projection has not caught up, but 40,000 managers have.

That gap is the signal. Ownership moving sharply means the league-wide
consensus is repricing someone; it does not say why, and it is not a
recommendation on its own. It is a reason to look.

Endpoint is public and unauthenticated:
  /v1/players/nfl/trending/add?lookback_hours=24&limit=25
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

TRENDING_URL = "https://api.sleeper.app/v1/players/nfl/trending/{kind}"
CACHE_DIR = Path.home() / ".cache" / "ffl-mcp"
CACHE_TTL_SECONDS = 60 * 60  # trends move fast; an hour is already stale-ish

# A player has to be moving meaningfully to be worth mentioning. Sleeper's
# raw counts are league-wide across millions of leagues, so small numbers are
# background noise.
MIN_ADD_COUNT = 25000


def fetch_trending(kind: str = "add", lookback_hours: int = 24,
                   limit: int = 50, force: bool = False) -> dict[str, int]:
    """Return {sleeper_player_id: count} for the lookback window."""
    if kind not in ("add", "drop"):
        raise ValueError("kind must be 'add' or 'drop'")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"trending_{kind}_{lookback_hours}h.json"

    if not force and cache.exists():
        if time.time() - cache.stat().st_mtime < CACHE_TTL_SECONDS:
            return json.loads(cache.read_text())

    resp = requests.get(
        TRENDING_URL.format(kind=kind),
        params={"lookback_hours": lookback_hours, "limit": limit},
        timeout=30,
    )
    resp.raise_for_status()

    # Returns [{"player_id": "1234", "count": 41234}, ...]
    data = {str(r["player_id"]): int(r["count"])
            for r in resp.json() if r.get("player_id")}
    cache.write_text(json.dumps(data))
    return data


def annotate(candidates: list[dict], crosswalk, adds: dict[str, int],
             drops: dict[str, int] | None = None,
             min_count: int = MIN_ADD_COUNT) -> list[dict]:
    """Attach trend counts to already-scored free-agent candidates.

    Deliberately annotates rather than re-ranks. Trend volume is not a
    projection and must not be treated as one -- a player everyone is adding
    can still be a bad fit for your roster, and the point gap already
    computed is the better ordering. This adds a "why now" flag, not a score.
    """
    drops = drops or {}
    yahoo_to_sleeper = crosswalk.by_id if crosswalk else {}

    for c in candidates:
        yid = str(c.get("yahoo_id") or c["player"].get("yahoo_id", ""))
        sid = yahoo_to_sleeper.get(yid)
        if not sid:
            continue

        add_count = adds.get(sid, 0)
        drop_count = drops.get(sid, 0)

        if add_count >= min_count:
            c["trending"] = {
                "added_24h": add_count,
                "note": "rising -- something changed, projection may lag",
            }
        # Being added AND dropped heavily usually means a committee backfield
        # or a one-week injury fill; worth flagging as unsettled.
        if add_count >= min_count and drop_count >= min_count:
            c["trending"]["note"] = "churning -- adds and drops both high"

    return candidates


def unrostered_risers(adds: dict[str, int], sleeper_players: dict,
                      rostered_sleeper_ids: set[str],
                      limit: int = 5,
                      min_count: int = MIN_ADD_COUNT) -> list[dict]:
    """Top trending players you don't already have.

    Separate from the candidate list on purpose: these have NOT been scored
    against your league or checked for a roster hole. They are 'the league is
    moving on this' and nothing more. Keep them visually separate from
    recommendations so they never read as one.
    """
    out = []
    for sid, count in sorted(adds.items(), key=lambda kv: kv[1], reverse=True):
        if count < min_count or sid in rostered_sleeper_ids:
            continue
        p = sleeper_players.get(sid) or {}
        name = (p.get("full_name")
                or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
                or sid)
        out.append({
            "name": name,
            "pos": p.get("position", "?"),
            "team": p.get("team") or "FA",
            "added_24h": count,
        })
        if len(out) >= limit:
            break
    return out


if __name__ == "__main__":
    adds = fetch_trending("add", lookback_hours=24, limit=25)
    drops = fetch_trending("drop", lookback_hours=24, limit=25)
    print(f"trending adds:  {len(adds)}")
    print(f"trending drops: {len(drops)}\n")

    import players as pl
    sl = pl.fetch_sleeper_players()

    print("top adds (24h):")
    for sid, count in list(sorted(adds.items(), key=lambda kv: kv[1],
                                  reverse=True))[:10]:
        p = sl.get(sid, {})
        name = (p.get("full_name")
                or f"{p.get('first_name','')} {p.get('last_name','')}".strip()
                or sid)
        churn = " (also dropping)" if drops.get(sid, 0) >= MIN_ADD_COUNT else ""
        print(f"  {count:>7}  {name:24} {p.get('position','?'):4}"
              f"{p.get('team') or 'FA':4}{churn}")
