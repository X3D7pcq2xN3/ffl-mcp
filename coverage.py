"""Report what a league's scoring does and does not cover.

The recurring question behind every projection is "am I counting everything my
league counts?". This answers it against live Sleeper projections: which of the
league's scored categories actually appear in the data, and -- the other
direction -- which real, scorable categories the league leaves uncounted, so a
genuine gap (a return-TD category you score but never mapped) stands out from
the long tail of things a league simply does not score.

It also settles a confusion that recurs when eyeballing a single player: our
score rarely equals Sleeper's pts_std / pts_half_ppr / pts_ppr, and that is
expected, not a bug. Those columns are Sleeper's OWN standard scoring, which
bakes in categories many leagues do not use -- passing first downs and
completion bonuses inflate quarterbacks, yards- and points-allowed bonuses
inflate defenses. Measured against the league's own rules (the only rules the
digest uses) those keys are correctly unscored. Judge coverage from this
report, not from the pts_* delta.

Note on aggregates: Sleeper's def_td already sums a defense's pick-sixes
(pass_int_td) and fumble-return TDs (def_fum_td), and st_td sums its kick- and
punt-return TDs. Score the aggregate, not the components, or a defensive score
double-counts. The catalog below flags these so a league mapping does not add
both.

Note on "scored but absent": a league can score a category Sleeper never
projects, which surfaces here rather than silently doing nothing. The known
case is fgm_50p -- Sleeper projects fgm (total) and buckets only through 40-49,
never a 50+ bucket, and its own pts_std confirms it does not score the missing
makes (bucket-only scoring matches pts_std; crediting fgm minus the buckets as
50+ makes overshoots pts_std by ~2 points a kicker). So a 50+ field-goal rule
correctly triggers on nothing from projections. That is a Sleeper limitation to
know about, not a mapping bug to fix.
"""

from __future__ import annotations

from collections import defaultdict

# Real, commonly-scored fantasy categories, as Sleeper keys. The point of a
# fixed catalog is signal: the projection payload carries dozens of volume and
# metadata keys (pass_att, cmp_pct, snap counts) no league scores, and ranking
# raw magnitude would bury a missed return TD under passing attempts. So the
# report speaks only about categories a league plausibly scores.
#
# (aggregate) marks a key that already sums finer keys -- score it alone.
CATALOG: dict[str, str] = {
    "pass_yd": "passing yards", "pass_td": "passing TD",
    "pass_int": "interception thrown", "pass_2pt": "2-pt pass",
    "rush_yd": "rushing yards", "rush_td": "rushing TD", "rush_2pt": "2-pt rush",
    "rec": "reception", "rec_yd": "receiving yards", "rec_td": "receiving TD",
    "rec_2pt": "2-pt reception", "fum_lost": "fumble lost",
    "bonus_rec_te": "TE reception bonus", "rec_fd": "reception first down",
    "fgm_0_19": "FG 0-19", "fgm_20_29": "FG 20-29", "fgm_30_39": "FG 30-39",
    "fgm_40_49": "FG 40-49", "fgm_50p": "FG 50+", "xpm": "extra point made",
    "sack": "sack", "int": "defensive interception", "fum_rec": "fumble recovery",
    "def_td": "defensive TD (aggregate)", "safe": "safety",
    "blk_kick": "blocked kick", "pts_allow": "points allowed (bracketed)",
    "yds_allow": "yards allowed",
    # Special teams / returns -- the categories this report was built to surface.
    "kr_td": "kick-return TD", "pr_td": "punt-return TD",
    "st_td": "special-teams return TD (aggregate)",
    "pass_int_td": "defensive pick-six (in def_td)",
    "def_fum_td": "defensive fumble-return TD (in def_td)",
}


def coverage(rules, projections: dict[str, dict]) -> dict:
    """Categorize CATALOG keys for one league's rules against projection data.

    Returns three lists of (key, label): scored_present (league scores it and
    it appears in the data -- working), scored_absent (league scores it but the
    data never carries it -- worth a look, often a stat_id that mapped to the
    wrong key), and gaps (a real category present in the data that the league's
    rules do not score). Each carries the players-seen count so a gap worth
    chasing (a return TD half the field is projected for) is distinct from
    noise (one player at 0.06).
    """
    scored = set(rules.per_unit)
    if getattr(rules, "pts_allow_tiers", None):
        scored.add("pts_allow")

    seen_count: dict[str, int] = defaultdict(int)
    for stats in projections.values():
        for key, value in stats.items():
            if key in CATALOG and value:
                seen_count[key] += 1

    scored_present, scored_absent, gaps = [], [], []
    for key, label in CATALOG.items():
        row = (key, label, seen_count.get(key, 0))
        if key in scored:
            (scored_present if seen_count.get(key) else scored_absent).append(row)
        elif seen_count.get(key):
            gaps.append(row)
    gaps.sort(key=lambda r: r[2], reverse=True)
    return {"scored_present": scored_present,
            "scored_absent": scored_absent, "gaps": gaps}


if __name__ == "__main__":
    import projections as pj
    from scoring import parse_league_settings

    # The Bastos 2 League, in Yahoo's settings shape -- doubles as a record of
    # the league's scoring. 0.5 PPR, tiered points-allowed, ST/return TDs.
    def stat(sid, val):
        return {"stat": {"stat_id": sid, "value": str(val)}}

    settings = {"stat_modifiers": {"stats": [
        stat(4, 0.04), stat(5, 4), stat(6, -1), stat(9, 0.1), stat(10, 6),
        stat(11, 0.5), stat(12, 0.1), stat(13, 6), stat(15, -2),
        stat(16, 2), stat(17, 2), stat(18, 2),  # 2-pt pass / rush / rec
        stat(19, 3), stat(20, 3), stat(21, 3), stat(22, 4), stat(23, 5), stat(29, 1),
        stat(32, 1), stat(33, 2), stat(34, 2), stat(31, 6), stat(36, 2), stat(37, 2),
        stat(50, 10), stat(51, 7), stat(52, 4), stat(53, 1),
        stat(54, 0), stat(55, -1), stat(56, -4),
    ]}}
    rules = parse_league_settings(settings)

    state = pj.current_state()
    season, week = state.get("season"), state.get("week") or 1
    proj = pj.fetch_projections(season, week)
    rep = coverage(rules, proj)

    print(f"season {season} week {week} -- {len(proj)} players, "
          f"{len(rules.pts_allow_tiers)} pts-allowed tiers\n")
    print("SCORED and present in data:")
    for k, label, n in rep["scored_present"]:
        print(f"  {label:34} ({k}, seen {n})")
    if rep["scored_absent"]:
        print("\nSCORED but ABSENT from data (verify the mapping):")
        for k, label, n in rep["scored_absent"]:
            print(f"  {label:34} ({k})")
    print("\nGAPS -- scorable category in the data the league does not count:")
    for k, label, n in rep["gaps"]:
        note = "  <- noise" if n < 20 else ""
        print(f"  {label:34} ({k}, seen {n}){note}")
