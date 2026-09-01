"""Validate STAT_ID_MAP against Sleeper's own computed fantasy points.

Sleeper ships pts_std, pts_half_ppr, and pts_ppr alongside the raw stat lines.
Those are the same projections scored under known, standard rules. If we build
matching ScoringRules and our number disagrees with theirs, the disagreement is
in our stat mapping -- not in the projection.

This is the strongest check available without Yahoo access: it exercises every
category Sleeper actually projects, across thousands of players, against a
ground truth we didn't compute.

Caveat: Sleeper's own totals may include bonus categories (bonus_rec_te,
rec_fd) that standard scoring doesn't. Positions where those apply will show a
consistent offset rather than a random one -- read the sign and the pattern,
not just the magnitude.
"""

from __future__ import annotations

from collections import defaultdict

from projections import current_state, fetch_projections
from scoring import ScoringRules

# Standard scoring, as Sleeper's pts_* columns compute it.
BASE = {
    "pass_yd": 0.04, "pass_td": 4, "pass_int": -1, "pass_2pt": 2,
    "rush_yd": 0.1, "rush_td": 6, "rush_2pt": 2,
    "rec_yd": 0.1, "rec_td": 6, "rec_2pt": 2,
    "fum_lost": -2,
    "xpm": 1, "fgm_0_19": 3, "fgm_20_29": 3, "fgm_30_39": 3,
    "fgm_40_49": 4, "fgm_50p": 5,
    "sack": 1, "int": 2, "fum_rec": 2, "safe": 2, "def_td": 6, "blk_kick": 2,
}

VARIANTS = {
    "pts_std": 0.0,
    "pts_half_ppr": 0.5,
    "pts_ppr": 1.0,
}

TOLERANCE = 0.5  # points; anything larger is a mapping problem, not rounding


def compare(projections: dict[str, dict], column: str, ppr: float) -> dict:
    rules = ScoringRules(per_unit={**BASE, "rec": ppr})

    diffs = []
    for pid, stats in projections.items():
        truth = stats.get(column)
        if truth is None:
            continue
        ours = rules.score(stats)
        diffs.append((pid, ours, float(truth), round(ours - float(truth), 2)))

    if not diffs:
        return {"column": column, "compared": 0}

    off = [d for d in diffs if abs(d[3]) > TOLERANCE]
    off.sort(key=lambda d: abs(d[3]), reverse=True)

    return {
        "column": column,
        "compared": len(diffs),
        "within_tolerance": len(diffs) - len(off),
        "off": off,
        "mean_abs_diff": round(sum(abs(d[3]) for d in diffs) / len(diffs), 3),
    }


def attribute(off: list, projections: dict[str, dict], limit: int = 12) -> None:
    """For mismatched players, show which unused stat keys they have.

    A key that shows up on almost every mismatch and almost no match is very
    likely the category we failed to map.
    """
    mismatch_keys = defaultdict(int)
    for pid, _, _, _ in off:
        for k, v in projections[pid].items():
            if v:
                mismatch_keys[k] += 1

    total = len(off) or 1
    ranked = sorted(mismatch_keys.items(), key=lambda kv: kv[1], reverse=True)
    print(f"\n  stat keys present on mismatched players (of {total}):")
    for key, count in ranked[:limit]:
        if key in BASE or key.startswith("pts_"):
            continue
        print(f"    {key:22} {count:5}  ({count / total:.0%})")


if __name__ == "__main__":
    state = current_state()
    season, week = state.get("season"), state.get("week") or 1
    proj = fetch_projections(season, week)
    print(f"season {season} week {week} -- {len(proj)} players\n")

    for column, ppr in VARIANTS.items():
        r = compare(proj, column, ppr)
        if not r["compared"]:
            print(f"{column}: not present in payload")
            continue

        print(f"{column}  (rec={ppr})")
        print(f"  compared:  {r['compared']}")
        print(f"  matching:  {r['within_tolerance']} "
              f"({r['within_tolerance'] / r['compared']:.1%})")
        print(f"  mean |diff|: {r['mean_abs_diff']}")

        if r["off"]:
            print(f"  worst offenders:")
            for pid, ours, truth, diff in r["off"][:8]:
                print(f"    {pid:>8}  ours={ours:7}  sleeper={truth:7}  "
                      f"diff={diff:+7}")
            if column == "pts_ppr":
                attribute(r["off"], proj)
        print()
