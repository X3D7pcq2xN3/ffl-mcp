"""Fetch actual weekly stats from Sleeper and compute recent usage.

A projection says how good a player is expected to be. Actual usage says what
role he is actually getting -- snap share, target share, carries -- and that
is the thing a projection lags. A backup who took 70% of the snaps last week
carries a role his season-long projection has not caught up to yet.

The digest prompt used to disclaim these outright ("you are NOT given snap
counts, target share, recent form"). This module supplies them as computed
facts so the model can reason from usage instead of being told to ignore it.

Same undocumented-endpoint caveat as projections.py: the stat keys here
(off_snp, tm_off_snp, rec_tgt, rush_att) come from convention, not from
Sleeper documentation. validate_usage_keys() checks them against live data so
a silently-missing key surfaces instead of quietly zeroing every share.

Endpoint mirrors the projections one and needs no authentication:
  /stats/nfl/{season}/{week}?season_type=regular&position[]=RB
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

STATS_URL = "https://api.sleeper.app/stats/nfl/{season}/{week}"
CACHE_DIR = Path.home() / ".cache" / "ffl-mcp"
# A completed week's box score is final (bar the occasional late stat
# correction), so cached stats need only survive those corrections.
CACHE_TTL_SECONDS = 24 * 60 * 60

FANTASY_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")

# Stat keys this module reads. Named here so validate_usage_keys() can report
# any that live data stops sending.
USAGE_KEYS = ("off_snp", "tm_off_snp", "rec_tgt", "rush_att")


def fetch_stat_records(
    season: int | str,
    week: int,
    positions: tuple[str, ...] = FANTASY_POSITIONS,
    force: bool = False,
) -> list[dict]:
    """Return normalized actual-stat records for a completed week.

    Each record is {player_id, team, opponent, position, stats}. Mirrors
    projections.fetch_projections in shape: one position per request, merged,
    cached on disk. Keeping team and opponent -- which the /stats record
    carries -- is what lets defense.py attribute the points a position scored
    to the defense that allowed them. Position is the one we queried, so it
    needs no guessing from the record's player subobject.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"statrecs_{season}_{week}.json"

    if not force and cache.exists():
        if time.time() - cache.stat().st_mtime < CACHE_TTL_SECONDS:
            return json.loads(cache.read_text())

    records: list[dict] = []
    url = STATS_URL.format(season=season, week=week)

    for pos in positions:
        resp = requests.get(
            url,
            params={"season_type": "regular", "position[]": pos},
            timeout=60,
        )
        if resp.status_code != 200:
            print(f"  warn: {pos} week {week} returned HTTP {resp.status_code}")
            continue

        payload = resp.json()
        # Sleeper has returned both a list of records and a dict keyed by
        # player id from the sibling projections endpoint; handle both here
        # too rather than assume the shape.
        items = payload.values() if isinstance(payload, dict) else payload
        for rec in items:
            if not isinstance(rec, dict):
                continue
            pid = str(rec.get("player_id") or rec.get("id") or "")
            stat_line = rec.get("stats") or {}
            if not pid or not stat_line:
                continue
            records.append({
                "player_id": pid,
                "team": rec.get("team"),
                "opponent": rec.get("opponent"),
                "position": pos,
                "stats": stat_line,
            })

    if records:
        cache.write_text(json.dumps(records))
    return records


def fetch_stats(
    season: int | str,
    week: int,
    positions: tuple[str, ...] = FANTASY_POSITIONS,
    force: bool = False,
) -> dict[str, dict]:
    """Return {sleeper_player_id: stat_line} of actuals for a completed week.

    A thin projection over fetch_stat_records for callers that only need the
    stat lines keyed by id (usage()); a week with no games yet is an empty map.
    """
    return {r["player_id"]: r["stats"]
            for r in fetch_stat_records(season, week, positions, force)}


def _team_targets(week_stats: dict[str, dict],
                  sleeper_players: dict) -> dict[str, int]:
    """Sum targets by team for one week -- the denominator of target share.

    A player's stat line carries his targets but not his team's total, so the
    share can only be computed by aggregating across the whole position pull.
    Players whose team can't be resolved are left out of both sides.
    """
    totals: dict[str, int] = {}
    for pid, line in week_stats.items():
        tgt = line.get("rec_tgt")
        if not tgt:
            continue
        team = (sleeper_players.get(pid) or {}).get("team")
        if not team:
            continue
        totals[team] = totals.get(team, 0) + int(tgt)
    return totals


def usage(
    season: int | str,
    week: int,
    sleeper_players: dict,
    lookback: int = 3,
    positions: tuple[str, ...] = FANTASY_POSITIONS,
    force: bool = False,
) -> dict[str, dict]:
    """Recent usage per player over the weeks *before* `week`.

    Returns {sleeper_player_id: {weeks, snap_pct, snap_trend, target_share,
    targets_pg, carries_pg}} -- only the keys a player actually has data for.
    Uses completed weeks only (week-lookback .. week-1); the current week is
    excluded because a game in progress is not recent form yet.

    Shares are fractions in [0, 1]. snap_trend is per-week snap share, oldest
    first, so a rising or falling role is visible and not just its average.
    """
    weeks = list(range(max(1, int(week) - lookback), int(week)))
    if not weeks:
        return {}

    per_week = {w: fetch_stats(season, w, positions, force) for w in weeks}
    team_tgt = {w: _team_targets(per_week[w], sleeper_players) for w in weeks}

    pids: set[str] = set()
    for w in weeks:
        pids.update(per_week[w].keys())

    out: dict[str, dict] = {}
    for pid in pids:
        snaps: list[float] = []
        tgts: list[int] = []
        shares: list[float] = []
        carries: list[int] = []
        games = 0
        team = (sleeper_players.get(pid) or {}).get("team")

        for w in weeks:
            line = per_week[w].get(pid)
            if not line:
                continue
            games += 1

            off, tm = line.get("off_snp"), line.get("tm_off_snp")
            if off is not None and tm:
                snaps.append(off / tm)

            tgt = line.get("rec_tgt")
            if tgt is not None:
                tgts.append(int(tgt))
                team_total = team_tgt[w].get(team) if team else None
                if team_total:
                    shares.append(int(tgt) / team_total)

            att = line.get("rush_att")
            if att is not None:
                carries.append(int(att))

        if games == 0:
            continue

        u: dict = {"weeks": games}
        if snaps:
            u["snap_pct"] = round(sum(snaps) / len(snaps), 2)
            u["snap_trend"] = [round(s, 2) for s in snaps]
        if tgts:
            u["targets_pg"] = round(sum(tgts) / len(tgts), 1)
        if shares:
            u["target_share"] = round(sum(shares) / len(shares), 2)
        if carries:
            u["carries_pg"] = round(sum(carries) / len(carries), 1)
        out[pid] = u

    return out


def validate_usage_keys(week_stats: dict[str, dict]) -> dict:
    """Check that the usage stat keys still appear in live data.

    Returns which of USAGE_KEYS are present and which are missing. A missing
    key does not raise -- usage() simply omits whatever it can't compute --
    but a missing key means a whole dimension (snap share, say) silently
    vanishes, which is exactly the kind of quiet failure worth surfacing.
    """
    seen: set[str] = set()
    for line in week_stats.values():
        seen.update(line.keys())
    expected = set(USAGE_KEYS)
    return {
        "players": len(week_stats),
        "present": sorted(expected & seen),
        "missing": sorted(expected - seen),
    }


if __name__ == "__main__":
    import projections
    import players as pl

    state = projections.current_state()
    season = state.get("season")
    week = state.get("week") or state.get("display_week") or 1
    print(f"season {season}, week {week} ({state.get('season_type')})")

    if int(week) <= 1:
        print("no completed weeks yet; usage needs at least one prior week")
        raise SystemExit(0)

    prev = int(week) - 1
    wk = fetch_stats(season, prev)
    print(f"week {prev} stat lines: {len(wk)}")
    report = validate_usage_keys(wk)
    print(f"usage keys present: {report['present']}")
    if report["missing"]:
        print(f"MISSING usage keys: {report['missing']}")

    sl = pl.fetch_sleeper_players()
    use = usage(season, week, sl, lookback=3)
    print(f"\nplayers with recent usage: {len(use)}")

    top = sorted(use.items(),
                 key=lambda kv: kv[1].get("snap_pct", 0), reverse=True)
    print("\ntop 10 by recent snap share:")
    for pid, u in top[:10]:
        p = sl.get(pid, {})
        name = (p.get("full_name")
                or f"{p.get('first_name','')} {p.get('last_name','')}".strip()
                or pid)
        print(f"  {name:24} {p.get('position','?'):4}{p.get('team') or 'FA':4} {u}")
