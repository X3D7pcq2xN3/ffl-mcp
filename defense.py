"""Opponent defense-vs-position from Sleeper box scores.

Points-allowed-by-position: how many fantasy points, under this league's own
scoring, each defense gives up to each offensive position per game. It is the
one honest matchup signal buildable from public data -- a WR facing the
defense that allows the most WR points is in a soft spot, and the digest can
say so instead of the model guessing from a team abbreviation.

Built by attributing every player's scored week to the defense they faced:
the /stats record carries both the player's team and his opponent. The number
is backward-looking and small early in the season, so it is context to break a
close call or pick a streamer -- never a projection, and never added to one.

Team defense (DST) is deliberately excluded. Yahoo scores points-allowed in
tiers (0 allowed is worth one flat amount, 1-6 another), which ScoringRules
models as a flat per-point weight; a DST's scored line -- and any
defense-vs-DST number built from it -- would therefore be systematically
wrong. Skill positions and kickers score cleanly from their stat lines, so
those are what this computes.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from players import normalize_team
from scoring import ScoringRules
import stats as st

# Positions whose stat lines ScoringRules scores cleanly (see DST note above).
DVP_POSITIONS = ("QB", "RB", "WR", "TE", "K")


def defense_vs_position(
    season: int | str,
    weeks: Iterable[int],
    scoring_rules: ScoringRules,
    positions: tuple[str, ...] = DVP_POSITIONS,
    force: bool = False,
) -> dict[str, dict]:
    """Points each defense allows per game to each position, with a rank.

    Returns {team: {pos: {pa_pg, weeks, rank, of}}}. A week's points for a
    (defense, position) pair are the sum of all opposing players of that
    position, so pa_pg is the whole position's output against that defense per
    game -- the standard defense-vs-position measure. rank 1 is the softest
    matchup (allows the most); "of" is how many defenses were ranked.
    """
    weekly: dict[tuple, float] = defaultdict(float)  # (def, pos, week) -> pts
    seen: dict[tuple, set] = defaultdict(set)        # (def, pos) -> weeks

    for w in weeks:
        for r in st.fetch_stat_records(season, w, positions, force):
            defense = normalize_team(r.get("opponent"))
            pos = r.get("position")
            if not defense or pos not in positions:
                continue
            weekly[(defense, pos, w)] += scoring_rules.score(r["stats"])
            seen[(defense, pos)].add(w)

    agg: dict[str, dict] = {}
    for (defense, pos), wks in seen.items():
        n = len(wks)
        total = sum(weekly[(defense, pos, w)] for w in wks)
        agg.setdefault(defense, {})[pos] = {"pa_pg": round(total / n, 1),
                                            "weeks": n}

    # Rank per position across defenses: 1 = softest (allows the most).
    by_pos: dict[str, list] = defaultdict(list)
    for defense, posmap in agg.items():
        for pos, entry in posmap.items():
            by_pos[pos].append(entry)
    for pos, entries in by_pos.items():
        entries.sort(key=lambda e: e["pa_pg"], reverse=True)
        for rank, entry in enumerate(entries, 1):
            entry["rank"] = rank
            entry["of"] = len(entries)

    return agg


def _opponent_team(opponent: str) -> str:
    """The team abbreviation from a Yahoo-style opponent string.

    Yahoo prefixes the opponent with home/away ("@GB", "vs NYJ"); the abbr is
    the trailing token. Normalized so a Yahoo spelling (JAC, WAS) matches the
    Sleeper key (JAX, WAS) the table is built on.
    """
    if not opponent:
        return ""
    token = opponent.replace("@", " ").replace("vs", " ").split()
    return normalize_team(token[-1]) if token else ""


def matchup(dvp: dict, opponent: str, position: str) -> dict | None:
    """One player's matchup as a compact dict for the digest payload, or None.

    None when the opponent or position was not ranked (e.g. a position with no
    data yet, or a defense the window never saw), so the caller can simply omit
    the field rather than carry a placeholder.
    """
    team = _opponent_team(opponent)
    entry = (dvp.get(team) or {}).get(position)
    if not entry or "rank" not in entry:
        return None
    return {"vs": team, "pos": position, "pa_pg": entry["pa_pg"],
            "rank": entry["rank"], "of": entry["of"]}


if __name__ == "__main__":
    # Smoke test on a completed season -- proves the attribution and ranking
    # against real data without needing the current week to have been played.
    rules = ScoringRules(per_unit={
        "pass_yd": 0.04, "pass_td": 4, "pass_int": -1,
        "rush_yd": 0.1, "rush_td": 6,
        "rec": 0.5, "rec_yd": 0.1, "rec_td": 6, "fum_lost": -2,
        "fgm_0_19": 3, "fgm_20_29": 3, "fgm_30_39": 3,
        "fgm_40_49": 4, "fgm_50p": 5, "xpm": 1,
    })
    season, weeks = 2024, range(1, 6)
    dvp = defense_vs_position(season, weeks, rules)
    print(f"defenses ranked: {len(dvp)} (weeks {weeks.start}-{weeks.stop - 1}, "
          f"half PPR)\n")

    for pos in DVP_POSITIONS:
        ranked = sorted(
            ((team, d[pos]) for team, d in dvp.items() if pos in d),
            key=lambda x: x[1]["rank"])
        if not ranked:
            continue
        soft, tough = ranked[0], ranked[-1]
        print(f"{pos:3} softest: {soft[0]:4} {soft[1]['pa_pg']:6} pa/g   "
              f"toughest: {tough[0]:4} {tough[1]['pa_pg']:6} pa/g")
