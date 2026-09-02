"""Fetch weekly projections from Sleeper and validate them against our scoring map.

Yahoo does not expose projections through its API, so the numbers come from
Sleeper's public projections endpoint. It needs no authentication.

The load-bearing assumption in this project is that Sleeper's stat keys are
spelled the way STAT_ID_MAP expects. That assumption is unverified -- it comes
from convention, not from Sleeper documentation. validate_stat_keys() is here
to check it against live data rather than discovering a silent zero later.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from players import is_shelved
from scoring import STAT_ID_MAP, ScoringRules

PROJECTIONS_URL = "https://api.sleeper.app/projections/nfl/{season}/{week}"
STATE_URL = "https://api.sleeper.app/v1/state/nfl"
CACHE_DIR = Path.home() / ".cache" / "ffl-mcp"
CACHE_TTL_SECONDS = 6 * 60 * 60

FANTASY_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")

# Last week of the NFL regular season. A rest-of-season outlook runs from the
# current week through here; fantasy playoffs sit inside this range.
SEASON_LAST_WEEK = 18


def current_state() -> dict:
    """Sleeper's own view of season and week -- avoids hardcoding either."""
    resp = requests.get(STATE_URL, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_projections(
    season: int | str,
    week: int,
    positions: tuple[str, ...] = FANTASY_POSITIONS,
    force: bool = False,
) -> dict[str, dict]:
    """Return {sleeper_player_id: stat_line} for the given week.

    Sleeper wants one position per request; results are merged. Cached for a
    few hours since projections move during the week but not by the minute.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"proj_{season}_{week}.json"

    if not force and cache.exists():
        if time.time() - cache.stat().st_mtime < CACHE_TTL_SECONDS:
            return json.loads(cache.read_text())

    merged: dict[str, dict] = {}
    url = PROJECTIONS_URL.format(season=season, week=week)

    for pos in positions:
        resp = requests.get(
            url,
            params={"season_type": "regular", "position[]": pos},
            timeout=60,
        )
        if resp.status_code != 200:
            print(f"  warn: {pos} returned HTTP {resp.status_code}")
            continue

        payload = resp.json()
        # Sleeper has returned both a list of records and a dict keyed by
        # player id from this endpoint. Handle both rather than assuming.
        if isinstance(payload, dict):
            items = payload.values()
        else:
            items = payload

        for rec in items:
            if not isinstance(rec, dict):
                continue
            pid = str(rec.get("player_id") or rec.get("id") or "")
            stats = rec.get("stats") or {}
            if pid and stats:
                merged[pid] = stats

    if merged:
        cache.write_text(json.dumps(merged))
    return merged


def rest_of_season(
    season: int | str,
    from_week: int,
    scoring_rules: ScoringRules,
    positions: tuple[str, ...] = FANTASY_POSITIONS,
    last_week: int = SEASON_LAST_WEEK,
    force: bool = False,
    sleeper_players: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """Each player's remaining-season outlook, scored under league rules.

    Sums the scored weekly projections from `from_week` through the season's
    last week. This is the datum a single week cannot give: whether a player
    is worth keeping. One bye or one soft week barely moves a season total, so
    a rest-of-season number separates a temporary dip from a lost job in a way
    a lone weekly projection never can.

    Returns {sleeper_player_id: {ros_points, weeks, ros_ppg}} -- ros_ppg is
    the per-week average over weeks the player is actually projected to play,
    so a bye ahead does not drag the rate down. Weeks are summed from the same
    Sleeper projections and scoring map the weekly digest already uses, so the
    outlook is consistent with the weekly numbers rather than a second source.

    Pass `sleeper_players` (the /players/nfl dump) to gate the sum on injury
    status. Sleeper keeps projecting players it has shelved -- a PUP or IR
    player recovering from surgery still carries a full slate of weekly
    projections -- so summing them yields a rest-of-season number the player
    cannot possibly earn. When the dump is supplied, a shelved player's outlook
    is returned zeroed and flagged {ros_points: 0.0, weeks: 0, shelved: <status>}
    instead of the fictitious total, so a keep-or-drop call is not made on a
    number the injury report already contradicts.
    """
    weeks = range(int(from_week), int(last_week) + 1)
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}

    for w in weeks:
        proj = fetch_projections(season, w, positions, force)
        for pid, stats in proj.items():
            pts = scoring_rules.score(stats)
            totals[pid] = totals.get(pid, 0.0) + pts
            if pts > 0:
                counts[pid] = counts.get(pid, 0) + 1

    # Sleeper ids the injury report has shelved -- their projected weeks are
    # stale and must not be trusted in a season sum. Looked up once here.
    shelved: dict[str, str] = {}
    if sleeper_players:
        for pid in totals:
            status = (sleeper_players.get(str(pid)) or {}).get("injury_status")
            if is_shelved(status):
                shelved[pid] = status

    out: dict[str, dict] = {}
    for pid, pts in totals.items():
        if pid in shelved:
            out[pid] = {"ros_points": 0.0, "weeks": 0, "shelved": shelved[pid]}
            continue
        games = counts.get(pid, 0)
        rec: dict = {"ros_points": round(pts, 1), "weeks": games}
        if games:
            rec["ros_ppg"] = round(pts / games, 1)
        out[pid] = rec
    return out


def validate_stat_keys(projections: dict[str, dict]) -> dict:
    """Compare live Sleeper stat keys against what STAT_ID_MAP expects.

    Returns:
        expected_present -- keys we score AND Sleeper sends (good)
        expected_missing -- keys we score but Sleeper never sends (these
                            silently contribute zero to every projection)
        unused_keys      -- keys Sleeper sends that we don't score (mostly
                            fine; scan for anything a league might score)
    """
    seen: set[str] = set()
    for stats in projections.values():
        seen.update(stats.keys())

    expected = set(STAT_ID_MAP.values())
    return {
        "players": len(projections),
        "expected_present": sorted(expected & seen),
        "expected_missing": sorted(expected - seen),
        "unused_keys": sorted(seen - expected),
    }


if __name__ == "__main__":
    state = current_state()
    season = state.get("season")
    week = state.get("week") or state.get("display_week") or 1
    print(f"season {season}, week {week} ({state.get('season_type')})")

    proj = fetch_projections(season, week)
    print(f"projections fetched: {len(proj)} players\n")

    report = validate_stat_keys(proj)
    print(f"scored keys present ({len(report['expected_present'])}): "
          f"{report['expected_present']}")
    print(f"\nMISSING -- we score these, Sleeper never sends them "
          f"({len(report['expected_missing'])}):")
    print(f"  {report['expected_missing']}")
    print(f"\nunused Sleeper keys ({len(report['unused_keys'])}):")
    print(f"  {report['unused_keys']}")

    # Sanity check: score a few real lines under half PPR.
    rules = ScoringRules(per_unit={
        "pass_yd": 0.04, "pass_td": 4, "pass_int": -1,
        "rush_yd": 0.1, "rush_td": 6,
        "rec": 0.5, "rec_yd": 0.1, "rec_td": 6, "fum_lost": -2,
    })
    top = sorted(proj.items(), key=lambda kv: rules.score(kv[1]), reverse=True)
    print("\ntop 5 projected (half PPR):")
    for pid, stats in top[:5]:
        print(f"  {pid:>8}  {rules.score(stats):6}  "
              f"{ {k: v for k, v in list(stats.items())[:4]} }")
