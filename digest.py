"""Assemble the weekly digest: scored data in, prose recommendation out.

Division of labor: this module does every calculation. Projections, start/sit
comparisons, bye-week holes, and free-agent ranking are all computed here from
validated code. The model receives finished numbers and reasons about them --
whether a 3-point edge justifies a waiver claim, whether an injury designation
changes the call -- but never recomputes a projection.

That split is deliberate. Arithmetic in code can be validated (see
validate_scoring.py); judgment cannot. Keep the arithmetic here.
"""

from __future__ import annotations

import json
import re
import os
from dataclasses import dataclass

import requests

import notify
from players import is_unavailable

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"

# How many free agents to send. The pool is hundreds deep; the model only
# needs the plausible adds, and a long list buries the real signal.
CANDIDATES_PER_POSITION = 6

# Noise floors. A projection is an estimate, and a sub-2-point gap between
# two players is well inside the error of that estimate -- acting on it is
# coin-flipping with extra steps.
#
# These exist here rather than in the prompt because a filter is testable and
# a judgment instruction is not: handed a list of positive-delta findings, a
# model reads it as a to-do list and reports the marginal ones while arguing
# against them. Filter first, then ask for judgment on what survives.
#
# Tune from real results. If a week produces nothing and you later wish it
# had flagged something, lower these. If the digest feels noisy, raise them.
MIN_SWAP_GAIN = 2.0        # points a bench player must beat a starter by
MIN_CANDIDATE_GAIN = 2.0   # points a free agent must beat your worst by

# Exception: a starter who cannot play (bye, out, IR) is not a marginal
# comparison -- any legal replacement beats zero. Swaps into a slot flagged
# as a hole bypass MIN_SWAP_GAIN.

SYSTEM_PROMPT = """You advise on one fantasy football roster.

Every projection you are given was computed under this league's own scoring
rules. Treat them as accurate. Do not recompute, re-rank by your own
estimates, or substitute general player knowledge for the numbers provided.

Reason ONLY from the data in the payload. You are given projections, roster
slots, injury designations, injury detail (body part and practice
participation), depth-chart order, recent usage (snap share, target share,
targets and carries per game over the last few weeks), a rest-of-season
outlook (projected points through season's end), an opponent defense-vs-
position matchup (points the opponent allows to the player's position, with a
rank), bye weeks, and ownership percentages. You are NOT given weather, Vegas
point totals or spreads, or game pace. Do not invent them. Judge a matchup
ONLY from the defense-vs-position data provided -- an opponent abbreviation is
otherwise just identification, and your own memory of how good a team is does
not count as evidence. If a recommendation would need information you do not
have, say what would settle it instead of guessing.

Depth-chart order ("depth") is a player's rank at their position on their own
team; 1 is the starter. It is role context, not a projection: a player who
has risen to 1 often beats a projection that has not caught up to the change,
and a player sitting at 3 behind healthy starters is a bench body however
tempting his number. Use it to weigh a claim or a start, never to override a
projection you were given.

Practice participation ("practice": DNP, Limited, Full) is the best available
read on whether a Questionable player suits up: Full through the week points
toward playing, DNP on the last days points toward sitting. Use it to set the
Check block and the fallback, not to invent a projection for a player who
sits.

Recent usage ("usage") is what a player actually did over the last few
completed weeks: snap_pct and target_share are fractions of his team's total;
snap_trend lists per-week snap share oldest-first, so a rising or falling role
is visible; targets_pg and carries_pg are per game. It is backward-looking
fact, not a forecast. Use it to judge whether a projection or a trending add
reflects a real role: a rising snap_trend behind a good projection is
confirmation; a strong projection on a player whose snap share is low and
falling is a reason for caution. Never treat usage as a projection or add it
to one -- the projection already accounts for expected volume.

Rest-of-season outlook ("ros") is projected points from this week through
season's end (ros_points), with a per-week rate (ros_ppg) over the weeks the
player is projected to play. It is the keep-or-drop datum the weekly
projection is not: one bye or one soft week barely moves a season total, so a
low ros_ppg is a lasting problem where a low weekly number may be noise. Use
ros to compare who to keep; use the weekly projection to decide who starts.
Do not mix them -- a strong ros does not make a benched player a start this
week, and a weak week does not make a high-ros player a drop. An ros marked
"shelved" (e.g. shelved: PUP) is a deliberate zero: the player is on IR or PUP
and his weekly projections are stale, so his outlook is set to zero rather than
a total he cannot earn. Read it as "unavailable, hold only for later," never as
a player who has collapsed in value.

Matchup ("matchup") is the opponent's defense-vs-position: pa_pg is the points
that opponent allows to this player's position per game, and rank is where
that sits among defenses -- rank 1 of "of" allows the most, so a low rank is a
soft matchup and a high rank a tough one. It is computed from past weeks under
this league's scoring; the "weeks" count on it says how many, and a small
count early in the season is weak signal, not proof. Use it to break a close
start/sit or to pick between streamers, never to override a projection gap that
already clears the noise. It is not a projection and is never added to one.

Do not assume a player's gender. Use the player's name or "they".

The payload lists the league's starting slots. Every lineup change you
recommend must be legal under those slots: name the slot a player moves into,
and confirm the vacated slot still gets filled. Never suggest a bench player
for a slot their position cannot occupy.

Your job is judgment on top of the numbers:
- Is a projected edge large enough to act on, or is it noise?
- Does an injury designation or bye change the call?
- Is a waiver claim worth spending when the upgrade is marginal?

A weekly projection decides who starts; it does not decide who to cut, because
a low week may be a bye, an injury, or one bad matchup for a player worth
keeping. The rest-of-season outlook is what decides keep-or-drop. Recommend a
DROP only when the payload gives a reason beyond a single week's number, and
name that reason: a low rest-of-season outlook, or a snap or target share that
is both low and falling -- a lost role rather than one bad week. Even then,
when an add requires a corresponding drop, name the weakest keeps by their
season outlook but leave the final cut to me.

Report every item you would act on yourself. There is no minimum and no
maximum. Some weeks the right answer is one line saying the lineup is set;
some weeks there are five real problems. Never pad, and never omit a real
recommendation to stay short.

The test for including an item: would you make this move? If your own answer
is "probably not" or "it's marginal," leave it out entirely. Do not report a
move and then argue against it -- that costs the reader attention and gives
them nothing. A difference inside projection noise is not a finding.

OUTPUT FORMAT

Read on a phone, in a plain-text chat. No markdown is rendered: asterisks,
pound signs, and pipe tables show up as literal characters and make it worse.

Match this shape exactly:

Lineup
  RB     Runner C   was Runner B, bye
  W/R/T  Catcher C  was Runner C   +3.9

Claim
  FA Back  RB 10.4  31% owned, waivers close tonight

Check
  Catcher B is Q. If out, Catcher C to WR, Runner C to W/R/T.

Rules for that shape:
- Three blocks: Lineup, Claim, Check. Omit any block with nothing in it.
- Block name alone on its line. Two spaces indent for entries.
- No #, *, |, or table syntax anywhere. Ever.
- Lineup lists only slots that CHANGE, as final state. Never explain the
  sequence or add a sentence after the table -- the final state is the whole
  instruction. One table even when several findings share one fix.
- Give +X.X when a projection gap drove it, or the reason when it was forced.
- Claim: name, position, projection, and ONE fact that decides it. If a claim
  needs a drop, add "needs a roster spot" -- do not pick who to cut.
- Check: what might change, and the fallback, in one line.
- Every line under 15 words. No line wraps to a third phone line.

If nothing needs doing, the entire response is: Lineup is set, nothing worth
claiming.

Be direct about uncertainty. "Projections disagree here" is more useful than
false confidence."""


@dataclass
class Player:
    name: str
    position: str
    slot: str | None      # roster slot, or None if on bench
    projection: float
    team: str = ""
    opponent: str = ""
    status: str = ""      # injury designation: Q/D/O/IR/PUP/... (Sleeper or
                          # Yahoo spelling); players.is_unavailable classifies it
    on_bye: bool = False
    owned_pct: float | None = None
    on_waivers: bool = False
    # Role and injury detail from Sleeper's player dump (players.player_details).
    # A projection lags a role change by days; depth-chart order does not.
    # Injury detail turns a bare "Q" into a decidable call.
    depth_chart_order: int | None = None  # rank at position on own team; 1 = starter
    depth_chart_position: str = ""        # e.g. "RB", "LWR"
    injury_body_part: str = ""            # e.g. "Hamstring"
    practice: str = ""                    # DNP / Limited / Full
    injury_notes: str = ""                # free text from the report
    # Recent actual usage from Sleeper box scores (stats.usage): snap share,
    # target share, targets and carries per game over the last few weeks.
    # Backward-looking fact, not a projection -- it confirms a role the
    # projection may still lag. Held as the dict stats.usage() returns so this
    # module stays decoupled from its exact keys.
    usage: dict | None = None
    # Rest-of-season outlook from projections.rest_of_season: summed weekly
    # projections through season's end, scored under league rules. The datum a
    # single week can't give -- the basis for a keep-or-drop call.
    ros: dict | None = None
    # Opponent defense-vs-position from defense.matchup: points the opponent
    # allows to this position per game and its rank among defenses. The one
    # honest matchup signal from public data; context, not a projection.
    matchup: dict | None = None

    def to_dict(self) -> dict:
        d = {"name": self.name, "pos": self.position,
             "proj": round(self.projection, 1)}
        if self.slot:
            d["slot"] = self.slot
        if self.opponent:
            d["opp"] = self.opponent
        if self.status:
            d["status"] = self.status
        if self.on_bye:
            d["bye"] = True
        if self.owned_pct is not None:
            d["owned_pct"] = round(self.owned_pct)
        if self.on_waivers:
            d["waivers"] = True
        if self.depth_chart_order is not None:
            d["depth"] = self.depth_chart_order
        if self.depth_chart_position:
            d["depth_pos"] = self.depth_chart_position
        if self.injury_body_part:
            d["injury"] = self.injury_body_part
        if self.practice:
            d["practice"] = self.practice
        if self.injury_notes:
            d["injury_notes"] = self.injury_notes
        if self.usage:
            d["usage"] = self.usage
        if self.ros:
            d["ros"] = self.ros
        if self.matchup:
            d["matchup"] = self.matchup
        return d


# Roster slots that accept more than one position. A slot name is matched
# case-insensitively against these keys; anything else is treated as a
# dedicated slot that only its own position can fill.
FLEX_SLOTS = {
    "W/R": {"WR", "RB"},
    "W/T": {"WR", "TE"},
    "W/R/T": {"WR", "RB", "TE"},
    "FLEX": {"WR", "RB", "TE"},
    "Q/W/R/T": {"QB", "WR", "RB", "TE"},
    "SUPERFLEX": {"QB", "WR", "RB", "TE"},
    "OP": {"QB", "WR", "RB", "TE"},
}


def slot_accepts(slot: str | None, position: str) -> bool:
    """Can `position` legally occupy `slot`?

    Yahoo rejects an illegal lineup outright, so a suggestion that can't be
    executed is worse than no suggestion -- it costs a trip to the app to
    discover it doesn't work.
    """
    if not slot:
        return False
    key = slot.strip().upper()
    if key in FLEX_SLOTS:
        return position in FLEX_SLOTS[key]
    return key == position.upper()


def find_start_sit(starters: list[Player], bench: list[Player],
                   flex_eligible: set[str] | None = None,
                   min_gain: float = MIN_SWAP_GAIN) -> list[dict]:
    """Bench players outprojecting a starter at a slot they can legally fill.

    Swaps below min_gain are dropped as noise -- unless the starter cannot
    play, in which case any legal replacement is worth naming.
    """
    findings = []
    for benched in bench:
        if benched.on_bye or is_unavailable(benched.status):
            continue
        for starter in starters:
            if starter.projection >= benched.projection:
                continue
            slot = starter.slot or ""
            if not slot_accepts(slot, benched.position):
                continue

            gain = benched.projection - starter.projection
            unavailable = starter.on_bye or is_unavailable(starter.status)
            if gain < min_gain and not unavailable:
                continue

            findings.append({
                "type": "start_sit",
                "slot": slot,
                "start": benched.to_dict(),
                "over": starter.to_dict(),
                "gain": round(gain, 1),
                "forced": unavailable,
            })
    findings.sort(key=lambda f: (f["forced"], f["gain"]), reverse=True)
    return findings


def find_holes(starters: list[Player]) -> list[dict]:
    """Starting slots filled by someone on bye, out, or projecting near zero."""
    holes = []
    for p in starters:
        reason = None
        if p.on_bye:
            reason = "bye"
        elif is_unavailable(p.status):
            reason = f"out ({p.status})"
        elif p.projection < 1.0:
            reason = "no projection"
        if reason:
            holes.append({"type": "hole", "slot": p.slot,
                          "player": p.to_dict(), "reason": reason})
    return holes


def rank_candidates(free_agents: list[Player],
                    roster: list[Player],
                    per_position: int = CANDIDATES_PER_POSITION,
                    min_gain: float = MIN_CANDIDATE_GAIN) -> list[dict]:
    """Free agents who beat your worst rostered player at their position.

    Beating your worst bench player by a point is not a reason to spend a
    waiver claim, so anything under min_gain is dropped before the model
    sees it.

    A free agent who cannot play -- out, on IR, or on PUP -- is never a
    candidate, however high his stale weekly projection reads: recommending a
    claim on a player the injury report has shelved is exactly the mistake a
    projection-only ranker makes (a PUP running back still projected for points
    outranking a healthy bench player). Unavailable free agents are dropped
    before ranking, and unavailable roster players are left out of the floor so
    the bar is set by a player you can actually start.
    """
    worst_by_pos: dict[str, float] = {}
    for p in roster:
        if p.on_bye or is_unavailable(p.status):
            continue
        cur = worst_by_pos.get(p.position)
        if cur is None or p.projection < cur:
            worst_by_pos[p.position] = p.projection

    by_pos: dict[str, list[Player]] = {}
    for fa in free_agents:
        if is_unavailable(fa.status):
            continue
        floor = worst_by_pos.get(fa.position)
        if floor is None or fa.projection - floor < min_gain:
            continue
        by_pos.setdefault(fa.position, []).append(fa)

    out = []
    for pos, players in by_pos.items():
        players.sort(key=lambda p: p.projection, reverse=True)
        for p in players[:per_position]:
            out.append({
                "type": "candidate",
                "player": p.to_dict(),
                "beats_worst_rostered": round(
                    p.projection - worst_by_pos[pos], 1),
            })
    out.sort(key=lambda c: c["beats_worst_rostered"], reverse=True)
    return out


def roster_slots(starters: list[Player]) -> list[dict]:
    """The league's starting slots and what each accepts.

    Without this the model can only infer lineup structure from which slots
    happen to be occupied, which is how it ends up suggesting a starter be
    moved to "his bench spot" -- a place that does not exist.
    """
    slots = []
    for p in starters:
        key = (p.slot or "").strip().upper()
        slots.append({
            "slot": p.slot,
            "accepts": sorted(FLEX_SLOTS[key]) if key in FLEX_SLOTS else [key],
            "current": p.name,
        })
    return slots


def build_payload(week: int, starters: list[Player], bench: list[Player],
                  free_agents: list[Player], scoring: dict,
                  flex_eligible: set[str] | None = None) -> dict:
    roster = starters + bench

    return {
        "week": week,
        "scoring_notes": {
            "ppr": scoring.get("rec", 0),
            "te_premium": scoring.get("bonus_rec_te", 0) or None,
        },
        "roster_slots": roster_slots(starters),
        "data_provided": [
            "projections (computed under this league's scoring)",
            "roster slots and eligibility",
            "injury status", "injury detail (body part, practice participation)",
            "depth-chart order and position",
            "recent usage: snap share, target share, targets/game, "
            "carries/game (last few completed weeks)",
            "rest-of-season outlook: projected points through season's end "
            "(ros_points) and per-week rate (ros_ppg)",
            "opponent defense-vs-position: points the opponent allows to this "
            "position per game (pa_pg) and its rank among defenses (rank 1 "
            "of 'of' allows the most)",
            "bye weeks", "ownership percentage",
        ],
        "data_NOT_provided": [
            "weather", "Vegas point totals or spreads", "game pace or script",
        ],
        "lineup": [p.to_dict() for p in starters],
        "bench": [p.to_dict() for p in bench],
        "findings": (find_holes(starters)
                     + find_start_sit(starters, bench)[:5]),
        "available": rank_candidates(free_agents, roster),
    }


def ask_model(payload: dict, api_key: str | None = None) -> str:
    notify.load_env()  # explicit, not a side effect of importing notify
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env or environment")

    resp = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 900,
            "system": SYSTEM_PROMPT,
            "messages": [{
                "role": "user",
                "content": (
                    "Week " + str(payload["week"]) + " roster review.\n\n"
                    + json.dumps(payload, indent=1)
                ),
            }],
        },
        timeout=120,
    )
    resp.raise_for_status()
    body = resp.json()
    return "".join(b.get("text", "") for b in body.get("content", [])
                   if b.get("type") == "text").strip()


def strip_markdown(text: str) -> str:
    """Remove markdown the model emitted despite being told not to.

    A prompt rule is a request; this is the guarantee. Pipes and pound signs
    render as literal noise in a plain-text chat, which is exactly the thing
    that makes a digest not worth reading.
    """
    out = []
    for line in text.splitlines():
        s = line.strip()
        # Drop table separator rows: |---|---|
        if s.startswith("|") and set(s) <= set("|-: "):
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)          # headers
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)    # bold
        line = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", line)
        line = re.sub(r"^\s*[-*+]\s+", "  ", line)      # bullets -> indent
        if "|" in line:                                  # table row -> spaces
            line = "  " + "  ".join(
                c.strip() for c in line.strip().strip("|").split("|")
                if c.strip())
        out.append(line.rstrip())

    # Collapse runs of blank lines
    cleaned, blank = [], False
    for line in out:
        if not line.strip():
            if blank:
                continue
            blank = True
        else:
            blank = False
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def run(week: int, starters, bench, free_agents, scoring) -> str:
    """Assemble, ask, deliver. Reports its own failure rather than dying quiet."""
    try:
        payload = build_payload(week, starters, bench, free_agents, scoring)
        text = strip_markdown(ask_model(payload))
        notify.send(f"Week {week}\n\n{text}", markdown=False)
        return text
    except Exception as exc:
        notify.send_failure(f"week {week} digest", exc)
        raise


def demo() -> tuple:
    """Fixture roster for testing without Yahoo access.

    Deliberately includes: a bye-week starter, a Q-tagged starter, a bench
    player who beats a starter at a legal slot, a bench player who beats a
    starter at an ILLEGAL slot (TE vs a dedicated RB slot), and a free agent
    below every rostered player.
    """
    starters = [
        Player("Passer A", "QB", "QB", 18.4, opponent="@SF"),
        Player("Runner A", "RB", "RB", 14.1, opponent="vs DAL",
               usage={"weeks": 3, "snap_pct": 0.78, "snap_trend": [0.75, 0.79, 0.8],
                      "carries_pg": 16.3, "target_share": 0.11, "targets_pg": 3.7}),
        Player("Runner B", "RB", "RB", 6.1, on_bye=True),
        # Tough matchup but a projection that clears the noise anyway -- the
        # matchup should not talk the model out of an easy start.
        Player("Catcher A", "WR", "WR", 15.8, opponent="@GB",
               usage={"weeks": 3, "snap_pct": 0.9, "snap_trend": [0.88, 0.91, 0.91],
                      "target_share": 0.28, "targets_pg": 9.7},
               matchup={"vs": "GB", "pos": "WR", "pa_pg": 22.0, "rank": 30, "of": 32}),
        Player("Catcher B", "WR", "WR", 9.2, status="Q", opponent="vs NYJ",
               injury_body_part="Hamstring", practice="DNP"),
        Player("Tight A", "TE", "TE", 7.7, opponent="@MIA"),
        # Strong weekly projection but a role that is slipping -- usage is the
        # caution, and the season outlook confirms it is fading, not dipping.
        Player("Runner C", "RB", "W/R/T", 8.0, opponent="vs LAR",
               usage={"weeks": 3, "snap_pct": 0.34, "snap_trend": [0.52, 0.33, 0.17],
                      "carries_pg": 5.0},
               ros={"ros_points": 61.0, "weeks": 12, "ros_ppg": 5.1}),
    ]
    bench = [
        # A one-week dip on a clear keeper, into a soft matchup: weak
        # projection this week, strong outlook, opponent generous to WRs.
        Player("Catcher C", "WR", None, 11.9, opponent="vs CHI",
               ros={"ros_points": 186.0, "weeks": 12, "ros_ppg": 15.5},
               matchup={"vs": "CHI", "pos": "WR", "pa_pg": 41.0, "rank": 3, "of": 32}),
        Player("Runner D", "RB", None, 4.2, opponent="@BUF", depth_chart_order=3,
               ros={"ros_points": 33.0, "weeks": 11, "ros_ppg": 3.0}),
        Player("Tight B", "TE", None, 8.9, opponent="vs DEN"),
    ]
    free_agents = [
        # A backup just promoted to RB1 -- projection lags the role, usage
        # already shows the snap share climbing.
        Player("FA Back", "RB", None, 10.4, owned_pct=31, on_waivers=True,
               depth_chart_order=1, depth_chart_position="RB",
               usage={"weeks": 3, "snap_pct": 0.41, "snap_trend": [0.18, 0.35, 0.7],
                      "carries_pg": 9.0}),
        Player("FA Wide", "WR", None, 8.1, owned_pct=12, opponent="vs CAR",
               matchup={"vs": "CAR", "pos": "WR", "pa_pg": 38.0, "rank": 5, "of": 32}),
        Player("FA End", "TE", None, 9.6, owned_pct=44, on_waivers=True),
        Player("FA Scrub", "RB", None, 2.0, owned_pct=1),
        # On PUP with a high, STALE weekly projection -- Sleeper never zeroed
        # him. Without the injury gate this outranks every healthy RB above and
        # gets recommended as a claim; with it he is dropped from candidates and
        # his rest-of-season sum is flagged shelved rather than trusted.
        Player("FA Shelf", "RB", None, 12.5, owned_pct=53, status="PUP",
               injury_body_part="Knee - ACL", injury_notes="Surgery",
               depth_chart_order=4,
               ros={"ros_points": 0.0, "weeks": 0, "shelved": "PUP"}),
    ]
    scoring = {"rec": 0.5, "rec_yd": 0.1, "rush_yd": 0.1}
    return starters, bench, free_agents, scoring


if __name__ == "__main__":
    import sys

    starters, bench, free_agents, scoring = demo()

    if "--send" in sys.argv:
        # Full path: assemble -> Anthropic -> Telegram.
        print(run(3, starters, bench, free_agents, scoring))
    elif "--ask" in sys.argv:
        # Model call only, printed locally. No Telegram, no cost surprise.
        payload = build_payload(3, starters, bench, free_agents, scoring)
        print(ask_model(payload))
    else:
        # Default: assembly only. No network, no API key needed.
        payload = build_payload(3, starters, bench, free_agents, scoring)
        print(json.dumps(payload, indent=2))
