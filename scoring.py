"""Score projected stat lines under a league's own Yahoo scoring rules.

Sleeper's projections endpoint returns raw stat categories (rushing yards,
receptions, interceptions). Yahoo's /league/{key}/settings returns the point
value the league assigns to each. Neither is useful alone: a 90-yard, 8-catch
game is worth 17.0 in full PPR and 9.0 in standard, and only the league's own
settings say which.

Yahoo identifies stat categories by numeric stat_id. Sleeper uses string keys.
STAT_ID_MAP is the bridge. It covers the categories that appear in ordinary
football leagues; anything Yahoo sends that isn't in the map is reported by
unmapped_stats() rather than silently scored as zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Yahoo stat_id -> Sleeper projection key.
# Yahoo's stat_id values are stable across seasons for football.
STAT_ID_MAP: dict[int, str] = {
    # Passing
    4: "pass_yd",
    5: "pass_td",
    6: "pass_int",
    # Rushing
    9: "rush_yd",
    10: "rush_td",
    # Receiving
    11: "rec",
    12: "rec_yd",
    13: "rec_td",
    # Misc offense
    15: "fum_lost",
    16: "pass_2pt",
    17: "rush_2pt",
    18: "rec_2pt",
    # Kicking
    19: "fgm_0_19",
    20: "fgm_20_29",
    21: "fgm_30_39",
    22: "fgm_40_49",
    23: "fgm_50p",
    29: "xpm",
    # Team defense / special teams
    31: "def_td",
    32: "sack",
    33: "int",
    34: "fum_rec",
    35: "def_td",
    36: "safe",
    37: "blk_kick",
    50: "pts_allow",
    57: "yds_allow",
}

# Yahoo expresses some categories as a bracket with a single point value
# (e.g. "points allowed 0" is worth 10). Those arrive as separate stat_ids
# and are handled by the caller supplying pts_allow directly.


@dataclass
class ScoringRules:
    """A league's scoring, reduced to Sleeper-key -> points-per-unit."""

    per_unit: dict[str, float] = field(default_factory=dict)
    unmapped: list[dict] = field(default_factory=list)

    def score(self, stats: dict[str, float]) -> float:
        """Apply the rules to one projected stat line."""
        total = 0.0
        for key, value in stats.items():
            weight = self.per_unit.get(key)
            if weight and value:
                total += float(value) * weight
        return round(total, 2)

    def breakdown(self, stats: dict[str, float]) -> list[tuple[str, float, float, float]]:
        """(stat, value, weight, points) for every scoring contribution.

        Use this when explaining a recommendation -- "start X over Y" is a
        weak claim without showing which categories drive the gap.
        """
        rows = []
        for key, value in stats.items():
            weight = self.per_unit.get(key)
            if weight and value:
                rows.append((key, float(value), weight,
                             round(float(value) * weight, 2)))
        rows.sort(key=lambda r: abs(r[3]), reverse=True)
        return rows

    def unmapped_stats(self) -> list[dict]:
        """Yahoo categories this league scores that we can't translate.

        Non-empty means projected totals will be systematically off for the
        positions those categories affect. Check it before trusting output.
        """
        return self.unmapped

    @property
    def is_ppr(self) -> float:
        return self.per_unit.get("rec", 0.0)


def parse_league_settings(settings: dict) -> ScoringRules:
    """Build ScoringRules from a Yahoo /league/{key}/settings response.

    Accepts the stat_modifiers block in the shape Yahoo returns it:
        {"stat_modifiers": {"stats": [{"stat": {"stat_id": 12, "value": "0.1"}}]}}
    or a pre-flattened [{"stat_id": ..., "value": ...}] list.
    """
    rules = ScoringRules()

    raw = settings
    if "stat_modifiers" in settings:
        raw = settings["stat_modifiers"]
    if isinstance(raw, dict) and "stats" in raw:
        raw = raw["stats"]

    for entry in raw:
        stat = entry.get("stat", entry) if isinstance(entry, dict) else {}
        try:
            stat_id = int(stat.get("stat_id"))
            value = float(stat.get("value"))
        except (TypeError, ValueError):
            continue

        if value == 0:
            continue  # league scores this category at zero; skip it

        key = STAT_ID_MAP.get(stat_id)
        if key is None:
            rules.unmapped.append({"stat_id": stat_id, "value": value})
            continue

        # Two Yahoo ids map to def_td; sum rather than overwrite.
        rules.per_unit[key] = rules.per_unit.get(key, 0.0) + value

    return rules


def score_players(
    projections: dict[str, dict],
    rules: ScoringRules,
    crosswalk=None,
) -> dict[str, float]:
    """Score a {sleeper_id: stat_line} map into {sleeper_id: points}.

    Pass a Crosswalk to key the result by Yahoo player_id instead.
    """
    scored = {sid: rules.score(stats) for sid, stats in projections.items()}
    if crosswalk is None:
        return scored

    by_yahoo = {}
    for yahoo_id, sleeper_id in crosswalk.by_id.items():
        if sleeper_id in scored:
            by_yahoo[yahoo_id] = scored[sleeper_id]
    return by_yahoo


if __name__ == "__main__":
    # Half-PPR settings in Yahoo's own response shape.
    half_ppr = {
        "stat_modifiers": {"stats": [
            {"stat": {"stat_id": 4, "value": "0.04"}},
            {"stat": {"stat_id": 5, "value": "4"}},
            {"stat": {"stat_id": 6, "value": "-1"}},
            {"stat": {"stat_id": 9, "value": "0.1"}},
            {"stat": {"stat_id": 10, "value": "6"}},
            {"stat": {"stat_id": 11, "value": "0.5"}},
            {"stat": {"stat_id": 12, "value": "0.1"}},
            {"stat": {"stat_id": 13, "value": "6"}},
            {"stat": {"stat_id": 15, "value": "-2"}},
            {"stat": {"stat_id": 999, "value": "1"}},  # unknown category
        ]}
    }

    rules = parse_league_settings(half_ppr)
    print(f"ppr value:  {rules.is_ppr}")
    print(f"unmapped:   {rules.unmapped_stats()}")

    wr = {"rec": 8, "rec_yd": 90, "rec_td": 1}
    print(f"\nWR line {wr}")
    print(f"  points: {rules.score(wr)}")
    for row in rules.breakdown(wr):
        print(f"  {row[0]:10} {row[1]:6} x {row[2]:5} = {row[3]}")

    # Same line under full PPR and standard, to confirm scoring actually moves.
    for ppr, label in ((1.0, "full PPR"), (0.0, "standard")):
        r = ScoringRules(per_unit={**rules.per_unit, "rec": ppr})
        print(f"  {label:10} {r.score(wr)}")
